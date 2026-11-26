"""Run the AR eval set: one trial of one task, and many tasks times k trials (plan, Piece E).

A trial starts two fresh stores and replays the task's initial state on both. TARGET then replays
the reference actions; ACTUAL runs the agent (one solo turn on the ticket, or a chat with the
simulated clerk). The score compares the two projections and checks the task's assertions on
ACTUAL. No model is involved in scoring.

`run_agent` is the ACTUAL half on its own, unscored: `agents.ar.evals.run_event` uses it to run the agent on an event.

Many trials run through a pydantic-evals `Dataset`: each case is one task, `repeat` gives k trials,
`max_concurrency` bounds them, and every trial builds its own stores inside the case's task.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, Protocol

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelMessage
from pydantic_evals import Case, Dataset
from pydantic_evals.dataset import increment_eval_metric

from agents.ar.assertions import human_marks
from agents.ar.data_model import ArDb, UnknownIdError
from agents.ar.environment import call_env_function, call_tool, check_assertion, fresh_store
from agents.ar.errors import TOOL_ERRORS
from agents.ar.evals.judge import JudgeFn, score_tone
from agents.ar.evals.projection import diff, project
from agents.ar.evals.scoreboard import COST_METRIC, TaskLabels, TraceTurn, TrialResult, TrialTrace
from agents.ar.evals.tasks import DB_PATH, DOCUMENTS_DIR, Assertion, Step, Task, UserScenario
from agents.ar.run_types import AgentFn, AgentTurn, Retrieval
from agents.ar.store import Store

STOP = '###STOP###'  # the clerk ends the conversation by saying this
DEFAULT_MAX_TURNS = 8  # agent turns in a chat
DEFAULT_CONCURRENCY = 4

type Transcript = Sequence[tuple[Literal['clerk', 'agent'], str]]
type Customer = Callable[[Transcript], Awaitable[str]]  # the other side of a chat: its next message, given the chat so far


class ClerkFn(Protocol):
    """The simulated AP clerk: given its scenario and the conversation so far, its next message. No tools."""

    async def __call__(self, scenario: UserScenario, transcript: Transcript) -> str: ...


class HarnessError(RuntimeError):
    """The eval itself is broken (a reference path or initial state that fails), not the agent."""


def initialize(task: Task) -> Store:
    """A fresh store with the task's initial state replayed."""
    return setup_store(task.annotations.customer_id, task.setup)


def setup_store(customer_id: str, steps: Iterable[Step]) -> Store:
    """A fresh store with `steps` replayed: agent tools for `customer_id`, or environment functions. Raises what a
    refused step raises (`agents.ar.errors.TOOL_ERRORS`)."""
    store = fresh_store(DB_PATH, DOCUMENTS_DIR)
    for step in steps:
        if step.env_type == 'assistant':
            call_tool(store, customer_id, step.func_name, step.arguments)
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


def labels(task: Task) -> TaskLabels:
    notes = task.annotations
    return TaskLabels(flow=notes.flow, disposition=notes.disposition, needs_human=notes.needs_human,
                      uses_documents=bool(task.required_documents))


async def run_trial(task: Task, agent_fn: AgentFn, *, clerk: ClerkFn | None = None, retrieval: Retrieval = 'search',
                    max_turns: int = DEFAULT_MAX_TURNS, judge: JudgeFn | None = None,
                    thinking: bool = False) -> TrialResult:
    """One trial: TARGET by replay, ACTUAL by the agent (with `thinking` passed to every turn), scored with no model.
    The agent crashing fails the trial; a broken reference path or initial state raises."""
    customer = _customer(task, clerk)
    target = initialize(task)
    replay(target, task)
    actual = initialize(task)
    start, customer_id = actual.db, task.annotations.customer_id
    ran = await run_agent(actual, customer_id, agent_fn, ticket=task.ticket, customer=customer, max_turns=max_turns,
                          retrieval=retrieval, golden_documents=task.required_documents if retrieval == 'golden' else (),
                          thinking=thinking)
    tone, tone_error = await score_tone(judge, task.id, customer_id, start, actual.db) if judge else (None, None)
    changes, failed = diff(project(target.db), project(actual.db)), failed_assertions(actual.db, task)
    return TrialResult(
        task_id=task.id, labels=labels(task), passed=not changes and not failed and ran.error is None,
        db_match=not changes, assertions_ok=not failed, failed_assertions=failed, diff=changes,
        brought_in_person=bool(human_marks(actual.db, customer_id) - human_marks(start, customer_id)),
        cost_usd=ran.cost_usd, tool_calls=ran.tool_calls, seconds=ran.seconds,
        error=ran.error, tone=tone, tone_error=tone_error, trace=ran.trace,
    )


def _customer(task: Task, clerk: ClerkFn | None) -> Customer | None:
    """The clerk playing a chat task's scenario; None for a ticket task."""
    if task.user_scenario is None:
        return None
    if clerk is None:
        raise ValueError(f'{task.id} is a chat task and needs a clerk.')
    return partial(clerk, task.user_scenario)


@dataclass(frozen=True)
class AgentRun:
    """What the agent did on one store, whether or not it finished."""

    turns: tuple[AgentTurn, ...]  # the turns it finished: what is scored
    trace: TrialTrace  # those turns, the one it crashed on if it did, and the rows it wrote
    error: str | None  # the agent's (or the customer's) exception
    seconds: float

    @property
    def cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.turns)

    @property
    def tool_calls(self) -> int:
        return sum(t.tool_calls for t in self.turns)


async def run_agent(store: Store, customer_id: str, agent_fn: AgentFn, *, ticket: str | None = None,
                    customer: Customer | None = None, max_turns: int = DEFAULT_MAX_TURNS, **options: Any) -> AgentRun:
    """The agent on `store`: one solo turn on `ticket`, or a chat of at most `max_turns` agent turns with `customer`.
    What the agent or the customer raises is the run's error, not raised. `options` go to every turn."""
    if (ticket is None) == (customer is None):
        raise ValueError('Give the agent exactly one of a ticket and a customer to talk to.')
    start, began = store.db, time.perf_counter()
    acted = await _act(_turns(store, customer_id, agent_fn, ticket, customer, max_turns, options))
    seconds = time.perf_counter() - began
    return AgentRun(turns=acted.turns, error=acted.error, seconds=seconds,
                    trace=TrialTrace(chat=customer is not None, turns=acted.traced,
                                     wrote=diff(start.dump(), store.db.dump())))


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


async def _act(turns: AsyncIterator[tuple[str, AgentTurn]]) -> _Acted:
    """Drive the agent's `turns`: the ones it finished, and its error if it (or the customer) raised."""
    finished: list[tuple[str, AgentTurn]] = []
    try:
        async for prompt, turn in turns:
            finished.append((prompt, turn))
    except _AgentCrashed as crash:  # whatever the agent under test raises is a failed trial, recorded, not a crashed run
        return _acted(finished, (TraceTurn(crash.prompt, crash.messages, reply=None),), crash.error)
    except Exception as error:  # so is whatever the customer (the clerk) raises
        return _acted(finished, (), error)
    return _acted(finished, (), None)


def _acted(finished: Sequence[tuple[str, AgentTurn]], crashed: tuple[TraceTurn, ...], error: Exception | None) -> _Acted:
    return _Acted(turns=tuple(turn for _, turn in finished),
                  traced=(*(TraceTurn(prompt, turn.history, turn.text) for prompt, turn in finished), *crashed),
                  error=None if error is None else f'{type(error).__name__}: {error}')


async def _turns(store: Store, customer_id: str, agent_fn: AgentFn, ticket: str | None, customer: Customer | None,
                 max_turns: int, options: Mapping[str, Any]) -> AsyncIterator[tuple[str, AgentTurn]]:
    """Each prompt the agent was given (the ticket, or the customer's message) and the turn it took on it."""
    if ticket is not None:
        yield ticket, await _agent_turn(agent_fn, store, customer_id, ticket, policy='solo', **options)
        return
    assert customer is not None  # checked in run_agent
    transcript: Transcript = ()
    history = None
    for _ in range(max_turns):
        said = await customer(transcript)
        transcript = (*transcript, ('clerk', said))
        if STOP in said:
            return
        turn = await _agent_turn(agent_fn, store, customer_id, said, policy='chat', history=history, **options)
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


async def run_tasks(tasks: Iterable[Task], agent_fn: AgentFn, *, trials: int = 1,
                    concurrency: int = DEFAULT_CONCURRENCY, clerk: ClerkFn | None = None,
                    retrieval: Retrieval = 'search', judge: JudgeFn | None = None, thinking: bool = False,
                    progress: bool = False) -> tuple[TrialResult, ...]:
    """Every task `trials` times, at most `concurrency` at once, each trial on its own stores. Every task's initial
    state and reference path is replayed first, offline, so a broken one raises before any paid trial runs."""
    tasks = tuple(tasks)
    for task in tasks:
        check_reference(task)

    async def trial(task: Task) -> TrialResult:
        result = await run_trial(task, agent_fn, clerk=clerk, retrieval=retrieval, judge=judge, thinking=thinking)
        increment_eval_metric(COST_METRIC, result.cost_usd)
        return result

    dataset = Dataset[Task, TrialResult, None](
        name='ar_coworker', cases=[Case(name=task.id, inputs=task) for task in tasks])
    report = await dataset.evaluate(trial, task_name='ar_trial', max_concurrency=concurrency, repeat=trials,
                                    progress=progress)
    if report.failures:
        raise HarnessError('; '.join(f'{failure.name}: {failure.error_message}' for failure in report.failures))
    return tuple(case.output for case in report.cases)
