"""Run the AR eval set: one trial of one task, and many tasks times k trials (plan, Piece E).

A trial starts two fresh stores and replays the task's initial state on both. TARGET then replays
the reference actions; ACTUAL runs the agent (one solo turn on the ticket, or a chat with the
simulated clerk). The score compares the two projections and checks the task's assertions on
ACTUAL. No model is involved in scoring.

Many trials run through a pydantic-evals `Dataset`: each case is one task, `repeat` gives k trials,
`max_concurrency` bounds them, and every trial builds its own stores inside the case's task.
"""

import time
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelMessage
from pydantic_evals import Case, Dataset
from pydantic_evals.dataset import increment_eval_metric
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from ar.data_model import ApprovalStatus, ArDb, UnknownIdError
from ar.environment import call_env_function, call_tool, check_assertion, fresh_store
from ar.errors import TOOL_ERRORS
from ar.ledger import payer_family
from ar.run_types import AgentFn, AgentTurn, Retrieval
from ar.store import Store
from evals.ar_projection import diff, project
from evals.ar_tasks import DB_PATH, DOCUMENTS_DIR, Assertion, Task, UserScenario
from evals.judge import JudgeFn, score_tone
from evals.scoreboard import COST_METRIC, TaskLabels, TraceTurn, TrialResult, TrialTrace

STOP = '###STOP###'  # the clerk ends the conversation by saying this
DEFAULT_MAX_TURNS = 8  # agent turns in a chat
DEFAULT_CONCURRENCY = 4

type Transcript = Sequence[tuple[Literal['clerk', 'agent'], str]]


class ClerkFn(Protocol):
    """The simulated AP clerk: given its scenario and the conversation so far, its next message. No tools."""

    async def __call__(self, scenario: UserScenario, transcript: Transcript) -> str: ...


class HarnessError(RuntimeError):
    """The eval itself is broken (a reference path or initial state that fails), not the agent."""


def initialize(task: Task) -> Store:
    """A fresh store with the task's initial state replayed."""
    store = fresh_store(DB_PATH, DOCUMENTS_DIR)
    for step in task.setup:
        if step.env_type == 'assistant':
            call_tool(store, task.annotations.customer_id, step.func_name, step.arguments)
        else:
            call_env_function(store, step.func_name, step.arguments)
    return store


def replay(store: Store, task: Task) -> None:
    """Play the task's reference actions on `store`."""
    for action in task.evaluation_criteria.actions:
        call_tool(store, task.annotations.customer_id, action.name, action.arguments)


def check_reference(task: Task) -> None:
    """Raise `HarnessError` naming the task if its initial state or reference path is refused by a tool."""
    try:
        replay(initialize(task), task)
    except TOOL_ERRORS as error:
        raise HarnessError(f'{task.id}: its initial state or reference path fails: {error}') from error


def failed_assertions(db: ArDb, task: Task) -> tuple[str, ...]:
    return tuple(a.label() for a in task.evaluation_criteria.env_assertions if not _holds(db, a))


def _holds(db: ArDb, assertion: Assertion) -> bool:
    try:
        return check_assertion(db, assertion.func_name, assertion.arguments) == assertion.assert_value
    except UnknownIdError:  # the row it checks was never written, so the check fails
        return False


def human_marks(db: ArDb, customer_id: str) -> frozenset[str]:
    """Ids of the account's pending approvals and escalations: the signs that a person was brought in."""
    family = set(payer_family(db, customer_id))
    pending = {a.approval_id for a in db.approvals.values()
               if a.customer_id in family and a.status is ApprovalStatus.PENDING}
    escalated = {e.action_id for e in db.action_log.values()
                 if e.action == 'escalate_to_human' and e.target_id in family}
    return frozenset(pending | escalated)


def labels(task: Task) -> TaskLabels:
    notes = task.annotations
    return TaskLabels(flow=notes.flow, disposition=notes.disposition, needs_human=notes.needs_human,
                      uses_documents=bool(task.required_documents))


async def run_trial(task: Task, agent_fn: AgentFn, *, clerk: ClerkFn | None = None, retrieval: Retrieval = 'search',
                    max_turns: int = DEFAULT_MAX_TURNS, judge: JudgeFn | None = None) -> TrialResult:
    """One trial: TARGET by replay, ACTUAL by the agent, scored with no model. The agent crashing fails the trial;
    a broken reference path or initial state raises."""
    if task.user_scenario is not None and clerk is None:
        raise ValueError(f'{task.id} is a chat task and needs a clerk.')
    target = initialize(task)
    replay(target, task)
    actual = initialize(task)
    start, customer_id = actual.db, task.annotations.customer_id
    began = time.perf_counter()
    acted = await _act(task, actual, agent_fn, clerk, retrieval, max_turns)
    seconds = time.perf_counter() - began
    tone, tone_error = await score_tone(judge, task.id, customer_id, start, actual.db) if judge else (None, None)
    changes, failed = diff(project(target.db), project(actual.db)), failed_assertions(actual.db, task)
    turns, error = acted.turns, acted.error
    return TrialResult(
        task_id=task.id, labels=labels(task), passed=not changes and not failed and error is None,
        db_match=not changes, assertions_ok=not failed, failed_assertions=failed, diff=changes,
        brought_in_person=bool(human_marks(actual.db, customer_id) - human_marks(start, customer_id)),
        cost_usd=sum(t.cost_usd for t in turns), tool_calls=sum(t.tool_calls for t in turns), seconds=seconds,
        error=error, tone=tone, tone_error=tone_error,
        trace=TrialTrace(chat=task.user_scenario is not None, turns=acted.traced,
                         wrote=diff(start.dump(), actual.db.dump())),
    )


@dataclass(frozen=True)
class _Acted:
    turns: tuple[AgentTurn, ...]  # the turns the agent finished: what is scored
    traced: tuple[TraceTurn, ...]  # those turns, and the one it crashed on if it did: what --trace shows
    error: str | None  # the agent's (or the clerk's) exception


class _AgentCrashed(Exception):
    """The agent raised `error` on `prompt`; `messages` is what its run had exchanged by then."""

    def __init__(self, prompt: str, messages: Sequence[ModelMessage], error: Exception) -> None:
        super().__init__(prompt)
        self.prompt, self.messages, self.error = prompt, list(messages), error


async def _act(task: Task, store: Store, agent_fn: AgentFn, clerk: ClerkFn | None, retrieval: Retrieval,
               max_turns: int) -> _Acted:
    """Run the agent on ACTUAL: the turns it finished, and its error if it (or the clerk) raised."""
    finished: list[tuple[str, AgentTurn]] = []
    try:
        async for prompt, turn in _turns(task, store, agent_fn, clerk, retrieval, max_turns):
            finished.append((prompt, turn))
    except _AgentCrashed as crash:  # whatever the agent under test raises is a failed trial, recorded, not a crashed run
        return _acted(finished, (TraceTurn(crash.prompt, crash.messages, reply=None),), crash.error)
    except Exception as error:  # so is whatever the clerk raises
        return _acted(finished, (), error)
    return _acted(finished, (), None)


def _acted(finished: Sequence[tuple[str, AgentTurn]], crashed: tuple[TraceTurn, ...], error: Exception | None) -> _Acted:
    return _Acted(turns=tuple(turn for _, turn in finished),
                  traced=(*(TraceTurn(prompt, turn.history, turn.text) for prompt, turn in finished), *crashed),
                  error=None if error is None else f'{type(error).__name__}: {error}')


async def _turns(task: Task, store: Store, agent_fn: AgentFn, clerk: ClerkFn | None, retrieval: Retrieval,
                 max_turns: int) -> AsyncIterator[tuple[str, AgentTurn]]:
    """Each prompt the agent was given (the ticket, or the clerk's message) and the turn it took on it."""
    customer_id = task.annotations.customer_id
    golden = task.required_documents if retrieval == 'golden' else ()
    if task.ticket is not None:
        yield task.ticket, await _agent_turn(agent_fn, store, customer_id, task.ticket, policy='solo',
                                             retrieval=retrieval, golden_documents=golden)
        return
    assert clerk is not None and task.user_scenario is not None  # checked in run_trial and by Task
    transcript: Transcript = ()
    history = None
    for _ in range(max_turns):
        said = await clerk(task.user_scenario, transcript)
        transcript = (*transcript, ('clerk', said))
        if STOP in said:
            return
        turn = await _agent_turn(agent_fn, store, customer_id, said, policy='chat', retrieval=retrieval,
                                 golden_documents=golden, history=history)
        history, transcript = turn.history, (*transcript, ('agent', turn.text))
        yield said, turn


async def _agent_turn(agent_fn: AgentFn, store: Store, customer_id: str, prompt: str, **options: Any) -> AgentTurn:
    """`agent_fn` on `prompt`. If it raises, `_AgentCrashed` keeps the messages a pydantic-ai run had exchanged by
    then (none from a scripted agent), so the trace can show the calls up to the crash."""
    with capture_run_messages() as messages:
        try:
            return await agent_fn(store, customer_id, prompt, **options)
        except Exception as error:
            raise _AgentCrashed(prompt, messages, error) from error


@dataclass
class StateAndAssertions(Evaluator[Task, TrialResult, None]):
    """The trial's pass, split into its parts, as pydantic-evals assertions."""

    def evaluate(self, ctx: EvaluatorContext[Task, TrialResult, None]) -> dict[str, bool]:
        return {'db_match': ctx.output.db_match, 'assertions_ok': ctx.output.assertions_ok,
                'agent_finished': ctx.output.error is None}


async def run_tasks(tasks: Iterable[Task], agent_fn: AgentFn, *, trials: int = 1,
                    concurrency: int = DEFAULT_CONCURRENCY, clerk: ClerkFn | None = None,
                    retrieval: Retrieval = 'search', judge: JudgeFn | None = None,
                    progress: bool = False) -> tuple[TrialResult, ...]:
    """Every task `trials` times, at most `concurrency` at once, each trial on its own stores. Every task's initial
    state and reference path is replayed first, offline, so a broken one raises before any paid trial runs."""
    tasks = tuple(tasks)
    for task in tasks:
        check_reference(task)

    async def trial(task: Task) -> TrialResult:
        result = await run_trial(task, agent_fn, clerk=clerk, retrieval=retrieval, judge=judge)
        increment_eval_metric(COST_METRIC, result.cost_usd)
        return result

    dataset = Dataset[Task, TrialResult, None](
        name='ar_coworker', cases=[Case(name=task.id, inputs=task) for task in tasks],
        evaluators=[StateAndAssertions()])
    report = await dataset.evaluate(trial, task_name='ar_trial', max_concurrency=concurrency, repeat=trials,
                                    progress=progress)
    if report.failures:
        raise HarnessError('; '.join(f'{failure.name}: {failure.error_message}' for failure in report.failures))
    return tuple(case.output for case in report.cases)
