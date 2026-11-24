"""The --trace view, built from real pydantic-ai histories: the real agent driven by a scripted `FunctionModel`, offline."""
import asyncio
import json
import re
from dataclasses import replace
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from scripted_agents import noop_agent, replay_agent
from test_agent import DB_DIR, Script, load, reference_calls, run

from ar.agent import MAX_REQUESTS, OUTPUT_TOOL, agent, run_turn
from ar.environment import call_tool, fresh_store
from ar.run_types import AgentFn, AgentTurn
from evals import trace
from evals.ar_projection import TableDiff, diff_text
from evals.ar_runner import STOP, run_trial
from evals.ar_tasks import load_tasks
from evals.scoreboard import TraceTurn, TrialTrace
from evals.trace_color import CYAN, GREEN, GREY, MAGENTA, RED, RESET, YELLOW, use_color

TASKS = {task.id: task for task in load_tasks()}
JUNIPER_DENIED = {'contact_id': 'con_810', 'channel': 'email', 'invoice_ids': ['INV-1702'],
                  'body': 'INV-1702 for $4,800.00 was due on November 6, 2026.'}
FENNICK_CREDIT = {'dispute_id': 'dsp_3002', 'amount': '3120.00', 'reason': 'Carrier damage report confirms 40 cases.'}
ANSI = re.compile(r'\x1b\[[0-9;]*m')
TRIAL_INDENT = 4  # a trial's trace sits under its header line


def said(*parts: ModelResponsePart) -> ModelResponse:
    return ModelResponse(parts=list(parts))


def turn_of(script: Script, customer_id: str, prompt: str = 'Event: aging_check.') -> TraceTurn:
    store = fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents')
    done = run(script, store, customer_id, prompt)
    return TraceTurn(prompt, done.history, done.text)


def traced(script: Script, customer_id: str, prompt: str = 'Event: aging_check.') -> list[str]:
    return trace.trace_lines(TrialTrace(turns=(turn_of(script, customer_id, prompt),)))


def scripted(script: Script) -> AgentFn:
    """The real agent on a scripted model, as an `AgentFn` the runner can drive."""

    async def agent_fn(store, customer_id, prompt, **options: Any) -> AgentTurn:
        with agent.override(model=FunctionModel(script)):
            return await run_turn(store, customer_id, prompt, **options)

    return agent_fn


def blocks(lines: list[str], indent: int = 0) -> list[tuple[str, list[str]]]:
    """The trace as (label, body) pairs: a label sits at `indent`, its body two spaces further in."""
    rows = [line[indent:] for line in lines]
    starts = [i for i, row in enumerate(rows) if row and not row.startswith(' ')]
    return [(rows[s], [row[2:] for row in rows[s + 1:end]]) for s, end in zip(starts, [*starts[1:], len(rows)])]


def labels(lines: list[str], indent: int = 0) -> list[str]:
    return [label for label, _ in blocks(lines, indent)]


def bodies(lines: list[str], label: str, indent: int = 0) -> list[list[str]]:
    return [body for found, body in blocks(lines, indent) if found == label]


def body(lines: list[str], label: str, indent: int = 0) -> list[str]:
    (only,) = bodies(lines, label, indent)
    return only


def as_json(rows: list[str]) -> Any:
    return json.loads('\n'.join(rows))


def test_the_user_message_comes_first_then_each_call_and_its_result_then_the_reply():
    script = Script(('get_account_state', {}), load('collections'), ('amount_due', {'invoice_ids': ['INV-1001']}),
                    *reference_calls('task_01'), output={'summary': 'Reminded Priya on INV-1001.', 'actions': []})
    lines = traced(script, 'cus_brightwell')
    assert labels(lines) == [
        'USER', 'TOOL CALL get_account_state', 'TOOL RESULT get_account_state', 'TOOL CALL load_capability',
        'TOOL RESULT load_capability', 'TOOL CALL amount_due', 'TOOL RESULT amount_due', 'TOOL CALL send_message',
        'TOOL RESULT send_message', 'ASSISTANT', 'WROTE']
    assert lines[:2] == ['USER', '  Event: aging_check.']
    assert body(lines, 'TOOL CALL get_account_state') == ['{}']
    assert as_json(body(lines, 'TOOL CALL load_capability')) == {'id': 'collections'}
    assert as_json(body(lines, 'TOOL RESULT amount_due')) == {'invoice_ids': ['INV-1001'], 'amount_due': '12400.00'}
    sent = as_json(body(lines, 'TOOL RESULT send_message'))
    assert sent['status'] == 'done' and re.fullmatch(r'msg_\d+', sent['target_id'])
    assert lines[-4:] == ['ASSISTANT', '  Reminded Priya on INV-1001.', 'WROTE', '  nothing']


def test_reasoning_comes_before_the_call_it_leads_to_and_empty_thinking_is_left_out():
    thought = 'Priya is the contact on file.\nCheck the amount due before writing.'
    due = ToolCallPart('amount_due', {'invoice_ids': ['INV-1001']})
    script = Script(said(ThinkingPart(''), ThinkingPart(f'{thought}\n\n'), due),  # the model ends its thinking with blank lines
                    said(ThinkingPart(''), ToolCallPart('get_account_state', {})))
    lines = traced(script, 'cus_brightwell')
    assert labels(lines) == ['USER', 'REASONING', 'TOOL CALL amount_due', 'TOOL RESULT amount_due',
                             'TOOL CALL get_account_state', 'TOOL RESULT get_account_state', 'ASSISTANT', 'WROTE']
    assert body(lines, 'REASONING') == thought.splitlines()


def test_assistant_text_alongside_a_tool_call_is_shown_and_empty_text_is_not():
    script = Script(said(TextPart('Looking at the account first.'), ToolCallPart('get_account_state', {})),
                    said(TextPart(''), ToolCallPart('list_open_invoices', {})))
    lines = traced(script, 'cus_brightwell')
    assert labels(lines) == ['USER', 'ASSISTANT', 'TOOL CALL get_account_state', 'TOOL RESULT get_account_state',
                             'TOOL CALL list_open_invoices', 'TOOL RESULT list_open_invoices', 'ASSISTANT', 'WROTE']
    assert bodies(lines, 'ASSISTANT') == [['Looking at the account first.'], ['Done.']]


def test_text_with_no_tool_call_is_shown_then_the_retry_the_model_was_sent():
    lines = traced(Script(said(TextPart('Nothing is overdue.'))), 'cus_brightwell')
    assert labels(lines) == ['USER', 'ASSISTANT', 'RETRY', 'ASSISTANT', 'WROTE']
    assert bodies(lines, 'ASSISTANT')[0] == ['Nothing is overdue.']
    assert 'tool call' in ' '.join(body(lines, 'RETRY'))  # pydantic-ai asks for the output tool


def test_arguments_and_results_are_shown_in_full():
    message = reference_calls('task_01')[0][1]
    assert '\n\n' in message['body'] and len(message['body']) > 200
    many = {'invoice_ids': [f'INV-{n}' for n in range(1201, 1231)]}
    script = Script(('get_account_state', {}), ('amount_due', many), load('collections'), ('send_message', message))
    lines = traced(script, 'cus_brightwell')
    assert as_json(body(lines, 'TOOL CALL send_message')) == message
    assert as_json(body(lines, 'TOOL CALL amount_due')) == many
    account = call_tool(fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents'), 'cus_brightwell', 'get_account_state')
    assert as_json(body(lines, 'TOOL RESULT get_account_state')) == account
    assert body(lines, 'TOOL RESULT amount_due')[0].startswith('DENIED P11: Invoice INV-1201 belongs to cus_corvid')


def test_a_policy_denial_then_a_corrected_call():
    script = Script(load('collections'), ('send_message', JUNIPER_DENIED), *reference_calls('task_12'))
    lines = traced(script, 'cus_juniper')
    denied, sent = bodies(lines, 'TOOL RESULT send_message')
    assert len(denied) == 1 and denied[0].startswith('DENIED P1: Collections are paused on INV-1702')
    assert as_json(sent)['status'] == 'done'
    corrected = reference_calls('task_12')[0][1]
    assert [as_json(b) for b in bodies(lines, 'TOOL CALL send_message')] == [JUNIPER_DENIED, corrected]


def test_a_write_held_for_a_person_names_the_rule_and_the_approval_then_the_whole_result():
    lines = traced(Script(load('disputes'), ('propose_credit', FENNICK_CREDIT)), 'cus_fennick')
    assert as_json(body(lines, 'TOOL CALL propose_credit')) == FENNICK_CREDIT
    held = body(lines, 'TOOL RESULT propose_credit')
    assert held[0] == 'HELD P10: approval apr_8001'
    result = as_json(held[1:])
    assert (result['status'], result['rule'], result['approval_id']) == ('held_for_approval', 'P10', 'apr_8001')
    assert result['row']['payload']['amount'] == '3120.00'


def test_a_refusal_that_is_not_a_policy_rule_is_a_retry_and_a_refused_final_result_is_shown():
    script = Script(('get_invoice', {'invoice_id': 'INV-9999'}), (OUTPUT_TOOL, {'summary': 3}))
    lines = traced(script, 'cus_corvid')
    assert labels(lines) == ['USER', 'TOOL CALL get_invoice', 'TOOL RESULT get_invoice', f'TOOL CALL {OUTPUT_TOOL}',
                             f'TOOL RESULT {OUTPUT_TOOL}', 'ASSISTANT', 'WROTE']
    assert body(lines, 'TOOL RESULT get_invoice') == ["RETRY: No invoice with id 'INV-9999'."]
    refused = '\n'.join(body(lines, f'TOOL RESULT {OUTPUT_TOOL}'))
    assert refused.startswith('RETRY: [') and {e['loc'][0] for e in json.loads(refused.removeprefix('RETRY: '))} == {
        'summary', 'actions'}


def test_a_call_that_failed_or_never_returned_says_so_after_the_rest_of_the_turn():
    history = [ModelRequest(parts=[UserPromptPart('Event.')]),
               ModelResponse(parts=[ToolCallPart('get_invoice', {'invoice_id': 'INV-1301'}, tool_call_id='c1'),
                                    ToolCallPart('get_payment', {'payment_id': 'pay_2001'}, tool_call_id='c2')]),
               ModelRequest(parts=[ToolReturnPart('get_invoice', 'boom', tool_call_id='c1', outcome='failed')])]
    lines = trace.trace_lines(TrialTrace(turns=(TraceTurn('Event.', history, reply=None),)), error='KeyError: boom')
    assert lines == [
        'USER', '  Event.',
        'TOOL CALL get_invoice', '  {', '    "invoice_id": "INV-1301"', '  }',
        'TOOL CALL get_payment', '  {', '    "payment_id": "pay_2001"', '  }',
        'TOOL RESULT get_invoice', '  FAILED: boom',
        'TOOL RESULT get_payment', '  no result: the run stopped first',
        'ERROR', '  KeyError: boom',
        'WROTE', '  nothing',
    ]


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
    assert lines == ['USER', '  Event.', 'no trace available for this turn', 'ASSISTANT', '  Nothing to do.',
                     'WROTE', '  nothing']


def test_wrote_lists_added_and_changed_rows_per_table_and_counts_the_action_log():
    wrote = (TableDiff('action_log', added=('act_9001', 'act_9002')), TableDiff('invoices', changed=('INV-1301 (status)',)),
             TableDiff('messages', added=('msg_6011',)))
    lines = trace.trace_lines(TrialTrace(wrote=wrote))
    assert lines == ['WROTE', '  invoices ~INV-1301 (status)', '  messages +msg_6011', '  action_log +2 rows']


def test_the_runner_records_what_the_agent_wrote():
    result = asyncio.run(run_trial(TASKS['task_04'], replay_agent(TASKS['task_04'])))
    tables = {d.table: d for d in result.trace.wrote}
    assert tables['applications'].added and tables['action_log'].added
    assert any(c.startswith('INV-1301 (') and 'status' in c for c in tables['invoices'].changed)
    assert result.trace.chat is False and [t.prompt for t in result.trace.turns] == [TASKS['task_04'].ticket]


def test_a_chat_shows_each_clerk_message_as_the_user_and_does_not_repeat_the_first_turns_calls():
    lines_said = ['Hi, INV-1101 will be paid Friday.', 'Can you confirm?']

    async def clerk(scenario, transcript):
        return lines_said[len(transcript) // 2] if len(transcript) < 4 else STOP

    script = Script(('get_account_state', {}), output={'summary': 'Noted, thank you.', 'actions': []})
    result = asyncio.run(run_trial(TASKS['task_02'], scripted(script), clerk=clerk))
    lines = trace.trial_lines(1, result)[1:]
    assert labels(lines, TRIAL_INDENT) == ['USER', 'TOOL CALL get_account_state', 'TOOL RESULT get_account_state',
                                           'ASSISTANT', 'USER', 'ASSISTANT', 'WROTE', 'FAILED', 'DIFF']
    assert bodies(lines, 'USER', TRIAL_INDENT) == [[line] for line in lines_said]
    assert bodies(lines, 'ASSISTANT', TRIAL_INDENT) == [['Noted, thank you.']] * 2
    assert result.trace.chat is True and [t.prompt for t in result.trace.turns] == lines_said


def test_a_crash_shows_the_calls_up_to_it_and_the_error():
    script = Script(*[('list_open_invoices', {})] * (MAX_REQUESTS + 5))
    result = asyncio.run(run_trial(TASKS['task_13'], scripted(script)))
    lines = trace.trial_lines(1, result)
    assert lines[0].startswith('  trial 1  FAIL  0 tool calls  $0.0000  ')
    found = labels(lines[1:], TRIAL_INDENT)
    assert found.count('TOOL CALL list_open_invoices') == MAX_REQUESTS
    assert found[-2:] == ['ERROR', 'WROTE'] and 'ASSISTANT' not in found
    assert 'UsageLimitExceeded' in body(lines[1:], 'ERROR', TRIAL_INDENT)[0]


def test_a_failed_trial_shows_its_failed_assertions_and_diff_after_its_trace():
    result = asyncio.run(run_trial(TASKS['task_04'], noop_agent))
    lines = trace.trial_lines(2, result)
    assert lines[0].startswith('  trial 2  FAIL  0 tool calls  $0.0000  ')
    assert labels(lines[1:], TRIAL_INDENT) == ['USER', 'no trace available for this turn', 'ASSISTANT', 'WROTE',
                                               'FAILED', 'DIFF']
    assert body(lines[1:], 'FAILED', TRIAL_INDENT) == list(result.failed_assertions)
    assert 'assert_balance(invoice_id=INV-1301, expected=0.00)' in result.failed_assertions
    diff = body(lines[1:], 'DIFF', TRIAL_INDENT)
    assert diff == [diff_text(d) for d in result.diff] and diff[0].startswith('applications -')


def test_a_passing_trial_has_a_one_line_header_and_no_failure_blocks():
    result = replace(asyncio.run(run_trial(TASKS['task_13'], noop_agent)), tool_calls=1, cost_usd=0.0971, seconds=7.04)
    lines = trace.trial_lines(1, result)
    assert lines[0] == '  trial 1  PASS  1 tool call  $0.0971  7.0s'
    assert not {'FAILED', 'DIFF', 'ERROR'} & set(labels(lines[1:], TRIAL_INDENT))


# Colour.

def test_colour_marks_each_kind_of_block_and_strips_back_to_the_plain_trace():
    denied = turn_of(Script(load('collections'), said(
        ThinkingPart('INV-1702 may be paused.'), TextPart('Sending a reminder.'),
        ToolCallPart('send_message', JUNIPER_DENIED))), 'cus_juniper')
    held = turn_of(Script(load('disputes'), ('propose_credit', FENNICK_CREDIT)), 'cus_fennick')
    both = TrialTrace(turns=(denied, held))
    plain, coloured = trace.trace_lines(both), trace.trace_lines(both, color=True)
    assert [ANSI.sub('', line) for line in coloured] == plain
    shown = dict(zip(plain, coloured))
    assert shown['USER'] == f'{CYAN}USER{RESET}'
    assert shown['  Event: aging_check.'] == f'  {CYAN}Event: aging_check.{RESET}'  # the indent is not coloured
    assert shown['REASONING'] == f'{GREY}REASONING{RESET}'
    assert shown['  INV-1702 may be paused.'] == f'  {GREY}INV-1702 may be paused.{RESET}'
    assert shown['ASSISTANT'] == f'{GREEN}ASSISTANT{RESET}'
    assert shown['  Sending a reminder.'] == '  Sending a reminder.'  # the agent's text is not coloured
    assert shown['TOOL CALL send_message'] == f'{YELLOW}TOOL CALL send_message{RESET}'
    assert shown['TOOL RESULT send_message'] == 'TOOL RESULT send_message'
    denial = next(line for line in plain if line.startswith('  DENIED P1: '))
    assert shown[denial] == f'  {RED}{denial.strip()}{RESET}'
    assert shown['  HELD P10: approval apr_8001'] == f'  {MAGENTA}HELD P10: approval apr_8001{RESET}'
    assert shown['WROTE'] == 'WROTE'
    users = {i for i, line in enumerate(plain) if line in ('USER', '  Event: aging_check.')}
    assert all(CYAN not in line for i, line in enumerate(coloured) if i not in users)  # only the user is cyan


def test_a_coloured_trial_keeps_its_header_and_indent():
    result = asyncio.run(run_trial(TASKS['task_13'], noop_agent))
    plain, coloured = trace.trial_lines(1, result), trace.trial_lines(1, result, color=True)
    assert [ANSI.sub('', line) for line in coloured] == plain
    assert coloured[0] == plain[0] and coloured[1] == f'    {CYAN}USER{RESET}'


@pytest.mark.parametrize(('mode', 'isatty', 'environ', 'expected'), [
    ('always', False, {'NO_COLOR': '1'}, True),
    ('never', True, {}, False),
    ('auto', True, {}, True),
    ('auto', True, {'NO_COLOR': ''}, True),  # NO_COLOR counts only when it is set to something
    ('auto', True, {'NO_COLOR': '1'}, False),
    ('auto', False, {}, False),
])
def test_use_color(mode, isatty, environ, expected):
    assert use_color(mode, isatty=isatty, environ=environ) is expected
