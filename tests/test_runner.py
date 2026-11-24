"""One trial of one task, the chat loop, and many tasks at once; all with scripted agents and no model."""
import asyncio
from typing import Any

import pytest
from scripted_agents import escalate_agent, noop_agent, one_line_clerk, raising_agent, replay_agent

from ar.errors import PolicyDenied
from ar.run_types import AgentTurn
from evals.ar_runner import STOP, HarnessError, run_tasks, run_trial
from evals.ar_tasks import Assertion, load_tasks

TASKS = {task.id: task for task in load_tasks()}
NEEDS_HUMAN = {'task_03', 'task_07', 'task_10', 'task_18'}


def trial(task_id, agent, **options):
    return asyncio.run(run_trial(TASKS[task_id], agent, clerk=options.pop('clerk', one_line_clerk), **options))


@pytest.mark.parametrize('task_id', TASKS)
def test_replaying_the_reference_passes_every_task(task_id):
    result = trial(task_id, replay_agent(TASKS[task_id]))
    assert (result.passed, result.db_match, result.assertions_ok) == (True, True, True)
    assert result.failed_assertions == () and result.diff == () and result.error is None
    assert result.brought_in_person == (task_id in NEEDS_HUMAN)
    assert result.tool_calls == len(TASKS[task_id].evaluation_criteria.actions)
    assert result.cost_usd == pytest.approx(0.01)
    assert result.seconds >= 0


@pytest.mark.parametrize('task_id', TASKS)
def test_doing_nothing_passes_only_the_do_nothing_tasks(task_id):
    result = trial(task_id, noop_agent)
    assert result.passed == (task_id in {'task_13', 'task_16', 'task_17'})
    assert result.brought_in_person is False  # tasks 19 and 20 start with a decided approval: not counted


def test_a_failed_trial_says_why():
    result = trial('task_04', noop_agent)
    assert result.db_match is False and result.assertions_ok is False
    assert 'assert_balance(invoice_id=INV-1301, expected=0.00)' in result.failed_assertions
    assert {d.table for d in result.diff} >= {'applications', 'invoices', 'payments'}


def test_task_three_is_scored_on_assertions_when_the_state_matches():
    result = trial('task_03', noop_agent)
    assert result.db_match is True and result.assertions_ok is False and result.passed is False


def test_escalating_on_every_task_brings_in_a_person_every_time():
    results = [trial(task_id, escalate_agent) for task_id in TASKS]
    assert all(r.brought_in_person for r in results)
    assert {r.task_id for r in results if r.passed} == {'task_03'}


def test_a_crashing_agent_is_a_failed_trial_not_a_crashed_run():
    result = trial('task_04', raising_agent)
    assert result.passed is False and result.error == 'RuntimeError: model unavailable'
    results = asyncio.run(run_tasks([TASKS['task_04'], TASKS['task_13']], raising_agent, clerk=one_line_clerk))
    assert [(r.task_id, r.error is not None, r.passed) for r in results] == [
        ('task_04', True, False), ('task_13', True, False)]  # task 13's state still matches; the crash fails it


def test_an_assertion_on_a_row_that_was_never_written_fails_instead_of_crashing():
    task = TASKS['task_04']
    missing = Assertion(env_type='assistant', func_name='assert_dispute_status',
                        arguments={'dispute_id': 'dsp_9999', 'expected': 'open'}, assert_value=True)
    broken = task.model_copy(update={'evaluation_criteria': task.evaluation_criteria.model_copy(
        update={'env_assertions': (missing,)})})
    result = asyncio.run(run_trial(broken, replay_agent(task)))
    assert result.assertions_ok is False
    assert result.failed_assertions == ('assert_dispute_status(dispute_id=dsp_9999, expected=open)',)


def broken_reference():
    task = TASKS['task_04']
    wrong = task.evaluation_criteria.actions[0].model_copy(update={'arguments': {
        'payment_id': 'pay_2001', 'invoice_id': 'INV-1001', 'amount': '15000.00'}})
    return task.model_copy(update={'evaluation_criteria': task.evaluation_criteria.model_copy(
        update={'actions': (wrong,)})})


def test_a_reference_path_that_policy_denies_is_a_harness_error():
    with pytest.raises(PolicyDenied):
        asyncio.run(run_trial(broken_reference(), noop_agent))
    with pytest.raises(HarnessError, match='task_04'):
        asyncio.run(run_tasks([broken_reference()], noop_agent))


def test_a_ticket_task_is_one_solo_turn_on_the_ticket():
    calls = []

    async def agent(store, customer_id, prompt, **options: Any) -> AgentTurn:
        calls.append((customer_id, prompt, options))
        return AgentTurn(text='ok', cost_usd=0.5, tool_calls=2, history=None)

    result = trial('task_06', agent, retrieval='golden')
    assert calls == [('cus_elmstead', TASKS['task_06'].ticket,
                      {'policy': 'solo', 'retrieval': 'golden', 'golden_documents': ('doc_deduction_reason_codes',)})]
    assert (result.cost_usd, result.tool_calls) == (0.5, 2)
    trial('task_06', agent, retrieval='search')
    assert calls[-1][2]['golden_documents'] == ()


class Recorder:
    """A chat agent that records what it was given and hands back a numbered history."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, store, customer_id, prompt, **options: Any) -> AgentTurn:
        self.calls.append({'prompt': prompt, **options})
        return AgentTurn(text=f'reply {len(self.calls)}', cost_usd=0.25, tool_calls=1, history=f'h{len(self.calls)}')


def test_chat_stops_when_the_clerk_says_stop():
    agent, seen = Recorder(), []

    async def clerk(scenario, transcript):
        seen.append(tuple(transcript))
        return 'Hi, INV-1101 will be paid Friday.' if len(transcript) < 4 else f'Thanks! {STOP}'

    result = trial('task_02', agent, clerk=clerk)
    assert [c['prompt'] for c in agent.calls] == ['Hi, INV-1101 will be paid Friday.'] * 2
    assert all(c['policy'] == 'chat' for c in agent.calls)
    assert seen[-1] == (('clerk', 'Hi, INV-1101 will be paid Friday.'), ('agent', 'reply 1'),
                        ('clerk', 'Hi, INV-1101 will be paid Friday.'), ('agent', 'reply 2'))
    assert (result.cost_usd, result.tool_calls) == (0.5, 2)


def test_chat_passes_history_from_one_turn_to_the_next_and_stops_at_the_turn_limit():
    agent = Recorder()

    async def chatty(scenario, transcript):
        return 'And another thing.'

    trial('task_08', agent, clerk=chatty)
    assert len(agent.calls) == 8
    assert [c['history'] for c in agent.calls] == [None, 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7']
    agent = Recorder()
    trial('task_08', agent, clerk=chatty, max_turns=3)
    assert len(agent.calls) == 3


def test_chat_needs_a_clerk():
    with pytest.raises(ValueError, match='clerk'):
        asyncio.run(run_trial(TASKS['task_02'], noop_agent))


def test_many_tasks_times_k_trials_each_on_its_own_store():
    tasks = [TASKS['task_04'], TASKS['task_05'], TASKS['task_13']]
    results = asyncio.run(run_tasks(tasks, noop_agent, trials=3, concurrency=2, clerk=one_line_clerk))
    assert sorted(r.task_id for r in results) == ['task_04'] * 3 + ['task_05'] * 3 + ['task_13'] * 3
    assert [r.passed for r in results if r.task_id == 'task_13'] == [True] * 3
    assert results[0].labels.skill == 'cash_application'


def test_run_tasks_rejects_bad_counts():
    with pytest.raises(ValueError):
        asyncio.run(run_tasks([TASKS['task_04']], noop_agent, trials=0))
    with pytest.raises(ValueError):
        asyncio.run(run_tasks([TASKS['task_04']], noop_agent, concurrency=0))


def test_the_judge_scores_new_outreach_and_never_changes_passed():
    judged = []

    async def judge(text, facts):
        judged.append((text, facts))
        return 0.75

    result = trial('task_01', replay_agent(TASKS['task_01']), judge=judge)
    assert result.tone == 0.75 and result.passed
    text, facts = judged[0]
    assert text == TASKS['task_01'].evaluation_criteria.actions[0].arguments['body']
    assert 'INV-1001' in facts and '12400.00' in facts and '2026-11-06' in facts
    draft = trial('task_18', replay_agent(TASKS['task_18']), judge=judge)
    assert draft.tone == 0.75 and judged[-1][0] == TASKS['task_18'].evaluation_criteria.actions[0].arguments['body']
    assert trial('task_04', replay_agent(TASKS['task_04']), judge=judge).tone is None
    assert trial('task_01', noop_agent, judge=judge).tone is None  # nothing new to judge
    assert len(judged) == 2


def test_a_failing_judge_is_recorded_and_the_trial_still_counts():
    async def judge(text, facts):
        raise TimeoutError('judge timed out')

    result = trial('task_01', replay_agent(TASKS['task_01']), judge=judge)
    assert result.passed and result.tone is None and result.tone_error == 'TimeoutError: judge timed out'
