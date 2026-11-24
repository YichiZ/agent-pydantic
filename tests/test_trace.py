"""The --trace view, built from real pydantic-ai histories: the real agent driven by a scripted `FunctionModel`, offline."""
import asyncio
import re
from dataclasses import replace
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from scripted_agents import noop_agent, replay_agent
from test_agent import DB_DIR, Script, load, reference_calls, run

from ar.agent import MAX_REQUESTS, agent, run_turn
from ar.environment import fresh_store
from ar.run_types import AgentFn, AgentTurn
from evals import trace
from evals.ar_projection import TableDiff
from evals.ar_runner import STOP, run_trial
from evals.ar_tasks import load_tasks
from evals.scoreboard import TraceTurn, TrialTrace

TASKS = {task.id: task for task in load_tasks()}
JUNIPER_DENIED = {'contact_id': 'con_810', 'channel': 'email', 'invoice_ids': ['INV-1702'],
                  'body': 'INV-1702 for $4,800.00 was due on November 6, 2026.'}
FENNICK_CREDIT = {'dispute_id': 'dsp_3002', 'amount': '3120.00', 'reason': 'Carrier damage report confirms 40 cases.'}


def traced(script: Script, customer_id: str, prompt: str = 'Event: aging_check.') -> list[str]:
    store = fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents')
    turn = run(script, store, customer_id, prompt)
    return trace.trace_lines(TrialTrace(turns=(TraceTurn(prompt, turn.history, turn.text),)))


def scripted(script: Script) -> AgentFn:
    """The real agent on a scripted model, as an `AgentFn` the runner can drive."""

    async def agent_fn(store, customer_id, prompt, **options: Any) -> AgentTurn:
        with agent.override(model=FunctionModel(script)):
            return await run_turn(store, customer_id, prompt, **options)

    return agent_fn


def numbered(lines: list[str]) -> list[str]:
    return [line for line in lines if re.match(r'\d+ ', line)]


def test_an_allowed_write_shows_each_call_with_its_arguments_and_result_in_order():
    script = Script(('get_account_state', {}), load('collections'), ('amount_due', {'invoice_ids': ['INV-1001']}),
                    *reference_calls('task_01'), output={'summary': 'Reminded Priya on INV-1001.', 'actions': []})
    lines = traced(script, 'cus_brightwell')
    assert lines[0] == 'event   Event: aging_check.'
    assert numbered(lines) == [
        '1  get_account_state()',
        '2  load_capability(collections)',
        '3  amount_due(invoice_ids=["INV-1001"])',
        '4  send_message(contact_id="con_801", channel="email", invoice_ids=["INV-1001"], body="Hi Priya, a remi...")',
    ]
    assert lines[lines.index('3  amount_due(invoice_ids=["INV-1001"])') + 1] == (
        '     -> invoice_ids INV-1001; amount_due 12400.00')
    assert re.fullmatch(r'     -> done: msg_\d+', lines[-3])
    assert lines[-2:] == ['final   Reminded Priya on INV-1001.', 'wrote   nothing']


def test_a_message_body_is_shown_in_full_on_its_own_lines():
    body = reference_calls('task_01')[0][1]['body']
    lines = traced(Script(load('collections'), *reference_calls('task_01')), 'cus_brightwell')
    start = next(i for i, line in enumerate(lines) if line.startswith('     body: Hi Priya, a reminder'))
    end = next(i for i, line in enumerate(lines) if line.startswith('     -> '))
    block = lines[start:end]
    assert all(line == '' or line.startswith('           ') for line in block[1:])  # aligned under the text
    assert '' in block  # the paragraph break is kept
    assert ' '.join(' '.join(block).removeprefix('     body: ').split()) == ' '.join(body.split())
    assert all(len(line) <= trace.WIDTH for line in block)


def test_a_policy_denial_then_a_corrected_call():
    script = Script(load('collections'), ('send_message', JUNIPER_DENIED), *reference_calls('task_12'))
    lines = traced(script, 'cus_juniper')
    calls = numbered(lines)
    assert [c.split('(')[0] for c in calls] == ['1  load_capability', '2  send_message', '3  send_message']
    denied = lines[lines.index(calls[1]) + 2]  # after the body's one line
    assert denied.startswith('     -> DENIED P1: Collections are paused on INV-1702')
    assert re.fullmatch(r'     -> done: msg_\d+', lines[-3])


def test_a_write_held_for_a_person_names_the_rule_and_the_approval():
    lines = traced(Script(load('disputes'), ('propose_credit', FENNICK_CREDIT)), 'cus_fennick')
    assert numbered(lines) == [
        '1  load_capability(disputes)',
        '2  propose_credit(dispute_id="dsp_3002", amount="3120.00", reason="Carrier damage r...")',
    ]
    assert '     reason: Carrier damage report confirms 40 cases.' in lines
    assert '     -> HELD P10: approval apr_8001' in lines


def test_a_refusal_that_is_not_a_policy_rule_is_a_retry_and_a_request_for_a_person_is_held():
    approval = {'action': 'write_off', 'payload': {'invoice_id': 'INV-1201', 'note': 'x' * 200},
                'reason': 'With outside counsel.'}
    script = Script(('get_invoice', {'invoice_id': 'INV-9999'}), ('request_approval', approval),
                    ('list_open_invoices', {}))
    lines = traced(script, 'cus_corvid')
    assert lines[2].startswith('     -> RETRY: ') and 'INV-9999' in lines[2]
    call = numbered(lines)[1]
    assert call.startswith('2  request_approval(action="write_off", payload={"invoice_id": "INV-1201", "note": ')
    assert '...' in call and 'x' * 200 not in call  # a long value that is not text is cut
    assert re.fullmatch(r'     -> HELD: approval apr_\d+', lines[lines.index(call) + 1])
    assert lines[lines.index(numbered(lines)[2]) + 1].startswith('     -> INV-1201')  # a list of rows: their ids


def test_a_call_the_run_stopped_before_answering_says_so():
    history = [ModelRequest(parts=[UserPromptPart('Event.')]),
               ModelResponse(parts=[ToolCallPart('get_invoice', {'invoice_id': 'INV-1301'})])]
    lines = trace.trace_lines(TrialTrace(turns=(TraceTurn('Event.', history, reply=None),)), error='KeyError: boom')
    assert lines == ['event   Event.', '1  get_invoice(invoice_id="INV-1301")', '     -> no result: the run stopped first',
                     'error   KeyError: boom', 'wrote   nothing']


def test_a_long_text_that_starts_with_line_breaks_keeps_the_call_on_one_line():
    body = 'Hi Wen,\n\nA reminder that INV-1601 has 9,400.00 due.'
    history = [ModelRequest(parts=[UserPromptPart('Event.')]),
               ModelResponse(parts=[ToolCallPart('send_message', {'contact_id': 'con_809', 'body': body})])]
    lines = trace.trace_lines(TrialTrace(turns=(TraceTurn('Event.', history, reply=None),)))
    assert lines[1:5] == ['1  send_message(contact_id="con_809", body="Hi Wen, A remind...")', '     body: Hi Wen,', '',
                          '           A reminder that INV-1601 has 9,400.00 due.']


def test_a_clerk_that_raises_fails_the_trial_and_keeps_the_turns_before_it():
    async def clerk(scenario, transcript):
        if transcript:
            raise TimeoutError('clerk timed out')
        return 'Hi, INV-1101 will be paid Friday.'

    result = asyncio.run(run_trial(TASKS['task_02'], noop_agent, clerk=clerk))
    assert result.passed is False and result.error == 'TimeoutError: clerk timed out'
    assert [(t.prompt, t.reply) for t in result.trace.turns] == [('Hi, INV-1101 will be paid Friday.', 'Nothing to do.')]


@pytest.mark.parametrize('history', [None, 'h1', 3, ['not', 'messages']])
def test_an_opaque_history_says_no_trace_is_available(history):
    lines = trace.trace_lines(TrialTrace(turns=(TraceTurn('Event.', history, 'Nothing to do.'),)))
    assert lines == ['event   Event.', 'no trace available for this turn', 'final   Nothing to do.', 'wrote   nothing']


def test_wrote_lists_added_and_changed_rows_per_table_and_counts_the_action_log():
    wrote = (TableDiff('action_log', added=('act_9001', 'act_9002')), TableDiff('invoices', changed=('INV-1301 (status)',)),
             TableDiff('messages', added=('msg_6011',)))
    lines = trace.trace_lines(TrialTrace(wrote=wrote))
    assert lines == ['wrote   invoices ~INV-1301 (status)', '        messages +msg_6011', '        action_log +2 rows']


def test_the_runner_records_what_the_agent_wrote():
    result = asyncio.run(run_trial(TASKS['task_04'], replay_agent(TASKS['task_04'])))
    tables = {d.table: d for d in result.trace.wrote}
    assert tables['applications'].added and tables['action_log'].added
    assert any(c.startswith('INV-1301 (') and 'status' in c for c in tables['invoices'].changed)
    assert result.trace.chat is False and [t.prompt for t in result.trace.turns] == [TASKS['task_04'].ticket]


def test_a_chat_shows_each_clerk_message_then_the_calls_then_the_reply_in_order():
    lines_said = ['Hi, INV-1101 will be paid Friday.', 'Can you confirm?']

    async def clerk(scenario, transcript):
        return lines_said[len(transcript) // 2] if len(transcript) < 4 else STOP

    script = Script(('get_account_state', {}), output={'summary': 'Noted, thank you.', 'actions': []})
    result = asyncio.run(run_trial(TASKS['task_02'], scripted(script), clerk=clerk))
    body = [line.removeprefix('    ') for line in trace.trial_lines(1, result)[1:]]
    order = ['clerk   Hi, INV-1101 will be paid Friday.', '1  get_account_state()', 'agent   Noted, thank you.',
             'clerk   Can you confirm?', 'agent   Noted, thank you.', 'wrote   nothing']
    rest = iter(body)
    assert all(line in rest for line in order)  # each found after the one before
    assert len(numbered(body)) == 1  # the second turn made no calls; the first turn's are not repeated
    assert result.trace.chat is True and [t.prompt for t in result.trace.turns] == lines_said


def test_a_crash_shows_the_calls_up_to_it_and_the_error():
    script = Script(*[('list_open_invoices', {})] * (MAX_REQUESTS + 5))
    result = asyncio.run(run_trial(TASKS['task_13'], scripted(script)))
    lines = trace.trial_lines(1, result)
    assert lines[0].startswith('  trial 1  FAIL  0 tool calls  $0.0000  ')
    assert len(numbered([line.removeprefix('    ') for line in lines])) == MAX_REQUESTS
    error = next(line for line in lines if line.startswith('    error   '))
    assert 'UsageLimitExceeded' in error and lines.index(error) < lines.index('    wrote   nothing')


def test_a_failed_trial_shows_its_failed_assertions_and_diff_with_its_trace():
    result = asyncio.run(run_trial(TASKS['task_04'], noop_agent))
    lines = trace.trial_lines(2, result)
    assert lines[0].startswith('  trial 2  FAIL  0 tool calls  $0.0000  ')
    assert '    no trace available for this turn' in lines
    failed = [line[12:] for line in lines if line.startswith(('    failed  ', '            assert_'))]
    assert failed == list(result.failed_assertions)
    assert 'assert_balance(invoice_id=INV-1301, expected=0.00)' in failed
    diff = lines.index(next(line for line in lines if line.startswith('    diff    ')))
    assert lines[diff].startswith('    diff    applications -') and lines[diff - 1].endswith(failed[-1])
    assert any(line.startswith('            invoices ~INV-1301 (') for line in lines[diff:])


def test_a_passing_trial_has_a_one_line_header_and_no_failure_lines():
    result = replace(asyncio.run(run_trial(TASKS['task_13'], noop_agent)), tool_calls=1, cost_usd=0.0971, seconds=7.04)
    lines = trace.trial_lines(1, result)
    assert lines[0] == '  trial 1  PASS  1 tool call  $0.0971  7.0s'
    assert not any(line.startswith(('    failed', '    diff', '    error')) for line in lines)
