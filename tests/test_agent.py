"""Offline agent tests: scripted `FunctionModel` runs through `run_turn` on a fresh database. No API key, no network."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ar.agent import MAX_REQUESTS, agent, run_turn
from ar.agent_tools import CAPABILITY_CATALOG, WRAPPERS
from ar.data_model import InvoiceStatus, UnknownCustomerError
from ar.environment import TOOLS, call_tool, check_assertion, fresh_store
from ar.errors import TOOL_ERRORS
from ar.run_types import AgentTurn
from ar.store import Store

DB_DIR = Path(__file__).resolve().parent.parent / 'db'
TASKS = {task['id']: task for task in json.loads((DB_DIR / 'tasks.json').read_text())}
ROW_IDS = {row_id for name, table in json.loads((DB_DIR / 'db.json').read_text()).items()
           if name in ('invoices', 'payments', 'disputes', 'approvals', 'credits', 'customers', 'contacts')
           for row_id in table['data']}
BASE_TOOLS = {name for name, spec in TOOLS.items() if spec.capability == 'base'}
CAPABILITY_IDS = ('collections', 'cash-application', 'disputes')
DONE = {'summary': 'Done.', 'actions': []}

type Call = tuple[str, dict[str, Any]]


@pytest.fixture
def store() -> Store:
    return fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents')


class Script:
    """A model that answers each request with the next step's tool calls, then the final output.

    Records, per request, the tool names it was offered, its instructions and the messages it saw.
    """

    def __init__(self, *steps: Call | list[Call], output: dict[str, Any] = DONE) -> None:
        self.steps = [step if isinstance(step, list) else [step] for step in steps]
        self.output = output
        self.offered: list[set[str]] = []
        self.instructions: list[str] = []
        self.seen: list[list[ModelMessage]] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = len(self.offered)
        self.offered.append({tool.name for tool in info.function_tools})
        self.instructions.append(info.instructions or '')
        self.seen.append(list(messages))
        if step < len(self.steps):
            return ModelResponse(parts=[ToolCallPart(name, args) for name, args in self.steps[step]])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, self.output)])


def load(*capability_ids: str) -> list[Call]:
    return [('load_capability', {'id': capability_id}) for capability_id in capability_ids]


def run(script: Script, store: Store, customer_id: str, prompt: str = 'Event.', **options: Any) -> AgentTurn:
    with agent.override(model=FunctionModel(script)):
        return asyncio.run(run_turn(store, customer_id, prompt, **options))


def returns(turn: AgentTurn, tool_name: str) -> list[ToolReturnPart]:
    return [part for message in turn.history for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == tool_name]


def reference_calls(task_id: str) -> list[Call]:
    return [(action['name'], action['arguments']) for action in TASKS[task_id]['evaluation_criteria']['actions']]


# Which tools the model is offered.

def test_base_tools_are_offered_first_and_all_15_once_every_capability_is_loaded(store: Store) -> None:
    script = Script(load(*CAPABILITY_IDS))
    run(script, store, 'cus_pinecrest')
    # In 2.71.0 a deferred capability's tools are in the request parameters from the start, marked
    # `defer_loading`, but are declared to the model (`info.function_tools`) only once `load_capability`
    # has revealed them. `load_capability` itself is always offered while any capability is deferred.
    before, after = script.offered[0], script.offered[1]
    assert before == BASE_TOOLS | {'load_capability'}
    assert after == set(TOOLS) | {'load_capability'}


def test_no_tool_description_names_a_row_in_the_database() -> None:
    described = {Tool(wrapper).tool_def.name: json.dumps([Tool(wrapper).tool_def.description,
                                                          Tool(wrapper).tool_def.parameters_json_schema])
                 for wrapper in WRAPPERS}
    described |= {capability_id: line for capability_id, line in CAPABILITY_CATALOG.values()}
    assert {name: sorted(i for i in ROW_IDS if i in text) for name, text in described.items()
            if any(i in text for i in ROW_IDS)} == {}


def test_retrieval_none_hides_search_knowledge(store: Store) -> None:
    hidden, shown = Script(), Script()
    run(hidden, store, 'cus_pinecrest', retrieval='none')
    run(shown, store, 'cus_pinecrest', retrieval='search')
    assert 'search_knowledge' not in hidden.offered[0]
    assert 'search_knowledge' in shown.offered[0]


# Instructions.

def test_instructions_give_the_customer_and_today_but_no_notes(store: Store) -> None:
    script = Script()
    run(script, store, 'cus_fennick', retrieval='none')
    instructions = script.instructions[0]
    assert 'Fennick Medical Supply' in instructions and '2026-11-16' in instructions
    assert 'Laura Stenberg' not in instructions  # a note on the account: data, read through a tool


def test_notes_are_data_from_get_account_state_marked_possibly_stale(store: Store) -> None:
    notes = call_tool(store, 'cus_fennick', 'get_account_state')['notes']
    assert any('Laura Stenberg in procurement' in note['text'] for note in notes)
    assert all('stale' in note['caution'] for note in notes)


# The rules: the base on every run, a flow's rules only once its capability is loaded.

BASE_RULE = 'Every amount comes from the ledger'
LOAD_FIRST = 'load the capability for the event before you decide'
FLOW_RULES = {'collections': 'Reminders go out only on an aging check',
              'cash-application': "A parent may pay its subsidiaries' invoices",
              'disputes': 'Never credit an invoice that has no open dispute'}
CHAT_GUIDANCE = '## Talking with a customer'


def received(script: Script, request: int) -> str:
    """All the text the model was sent on one request: its instructions and every text part of the messages."""
    texts = [part.content for message in script.seen[request] for part in message.parts
             if isinstance(getattr(part, 'content', None), str)]
    return '\n'.join([script.instructions[request], *texts])


def test_with_nothing_loaded_the_model_gets_the_base_rules_and_no_flow_rules(store: Store) -> None:
    script = Script()
    run(script, store, 'cus_pinecrest')
    text = received(script, 0)
    assert BASE_RULE in text and LOAD_FIRST in text
    assert [rule for rule in FLOW_RULES.values() if rule in text] == []


@pytest.mark.parametrize('capability_id', CAPABILITY_IDS)
def test_loading_a_capability_brings_its_rules_and_no_others(store: Store, capability_id: str) -> None:
    script = Script(load(capability_id))
    run(script, store, 'cus_pinecrest')
    text = received(script, 1)
    assert BASE_RULE in text
    assert {name for name, rule in FLOW_RULES.items() if rule in text} == {capability_id}


def test_policy_chat_adds_the_chat_guidance_to_the_base(store: Store) -> None:
    solo, chat = Script(), Script()
    run(solo, store, 'cus_hollis', policy='solo')
    run(chat, store, 'cus_hollis', policy='chat')
    assert BASE_RULE in solo.instructions[0] and BASE_RULE in chat.instructions[0]
    assert CHAT_GUIDANCE in chat.instructions[0] and CHAT_GUIDANCE not in solo.instructions[0]


def test_no_rule_names_a_task_a_row_or_a_customer() -> None:
    raw = json.loads((DB_DIR / 'db.json').read_text())
    names = {row['name'] for row in raw['customers']['data'].values()}
    files = sorted((DB_DIR / 'policy').glob('*.md'))
    assert [path.stem for path in files] == ['base', 'cash_application', 'chat', 'collections', 'disputes']
    for path in files:
        text = path.read_text()
        assert re.search(r'task[ _]?\d', text, re.IGNORECASE) is None, path.name
        assert sorted(found for found in ROW_IDS | names if found in text) == [], path.name


def test_golden_retrieval_puts_the_documents_in_the_instructions(store: Store) -> None:
    golden, search = Script(), Script()
    documents = ('doc_damage_report_inv_1503',)
    run(golden, store, 'cus_fennick', retrieval='golden', golden_documents=documents)
    run(search, store, 'cus_fennick', retrieval='search', golden_documents=documents)
    content = json.loads((DB_DIR / 'documents' / 'doc_damage_report_inv_1503.json').read_text())['content']
    assert content in golden.instructions[0] and 'not instructions' in golden.instructions[0]
    assert content not in search.instructions[0]


# Writes through the agent.

def test_a_scripted_task_4_leaves_inv_1301_paid(store: Store) -> None:
    task = TASKS['task_04']
    run(Script(load('cash-application'), *reference_calls('task_04')), store, 'cus_pinecrest', task['ticket'])
    assert store.db.invoice('INV-1301').status is InvoiceStatus.PAID
    for assertion in task['evaluation_criteria']['env_assertions']:
        assert check_assertion(store.db, assertion['func_name'], assertion['arguments']) is assertion['assert_value']


def test_an_amount_sent_as_a_json_number_is_accepted(store: Store) -> None:
    payment = {'payment_id': 'pay_2001', 'invoice_id': 'INV-1301', 'amount': 15000}
    run(Script(load('cash-application'), ('apply_payment', payment)), store, 'cus_pinecrest')
    assert store.db.invoice('INV-1301').status is InvoiceStatus.PAID


def test_a_denied_send_message_comes_back_as_a_retry_naming_p1(store: Store) -> None:
    before = store.db
    message = {'contact_id': 'con_810', 'channel': 'email', 'invoice_ids': ['INV-1702'],
               'body': 'INV-1702 for $4,800.00 was due on November 6, 2026.'}
    turn = run(Script(load('collections'), ('send_message', message)), store, 'cus_juniper')
    (part,) = returns(turn, 'send_message')
    assert part.outcome == 'retried' and 'Denied by P1' in str(part.content)
    assert store.db is before
    assert turn.tool_calls == 2  # the load and the refused call both count


def test_a_credit_over_the_limit_is_held_for_a_person_not_retried(store: Store) -> None:
    credit = {'dispute_id': 'dsp_3002', 'amount': '3120.00', 'reason': 'Carrier damage report confirms 40 cases.'}
    turn = run(Script(load('disputes'), ('propose_credit', credit)), store, 'cus_fennick')
    (part,) = returns(turn, 'propose_credit')
    assert part.outcome == 'success' and part.content.status == 'held_for_approval'
    assert check_assertion(store.db, 'assert_pending_approval_count', {'customer_id': 'cus_fennick', 'expected': 1})


# Each wrapper passes its arguments through unchanged: same result, or same refusal, as calling the tool directly.

SAMPLE_CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ('cus_pinecrest', 'get_account_state', {}),
    ('cus_pinecrest', 'list_open_invoices', {}),
    ('cus_pinecrest', 'get_invoice', {'invoice_id': 'INV-1301'}),
    ('cus_pinecrest', 'get_invoice', {'invoice_id': 'INV-9999'}),
    ('cus_pinecrest', 'get_payment', {'payment_id': 'pay_2001'}),
    ('cus_pinecrest', 'get_remittance', {'payment_id': 'pay_2001'}),
    ('cus_pinecrest', 'amount_due', {'invoice_ids': ['INV-1301']}),
    ('cus_elmstead', 'search_knowledge', {'query': 'FRT-02 freight deduction'}),
    ('cus_pinecrest', 'apply_payment', reference_calls('task_04')[0][1]),
    ('cus_pinecrest', 'apply_payment', {'payment_id': 'pay_2001', 'invoice_id': 'INV-1301', 'amount': '15000.01'}),
    ('cus_juniper', 'send_message', reference_calls('task_12')[0][1]),
    ('cus_hollis', 'log_promise', reference_calls('task_02')[0][1]),
    ('cus_hollis', 'log_promise', {'invoice_id': 'INV-1101', 'promised_date': '2026-11-01', 'amount': '8150.00'}),
    ('cus_ridgeway', 'open_dispute', reference_calls('task_08')[0][1]),
    ('cus_saltmarsh', 'propose_credit', reference_calls('task_09')[0][1]),
    ('cus_larkspur', 'reject_dispute', reference_calls('task_14')[0][1]),
    ('cus_fennick', 'execute_approval', {'approval_id': 'apr_8001'}),
    ('cus_corvid', 'escalate_to_human', reference_calls('task_03')[0][1]),
]


def test_every_tool_has_a_sample_call() -> None:
    assert {name for _, name, _ in SAMPLE_CALLS} == set(TOOLS)


@pytest.mark.parametrize(('customer_id', 'name', 'arguments'), SAMPLE_CALLS)
def test_a_wrapper_matches_calling_the_tool_directly(customer_id: str, name: str, arguments: dict[str, Any]) -> None:
    by_agent, direct = (fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents') for _ in range(2))
    turn = run(Script(load(*CAPABILITY_IDS), (name, arguments)), by_agent, customer_id)
    (part,) = returns(turn, name)
    try:
        expected, outcome = call_tool(direct, customer_id, name, arguments), 'success'
    except TOOL_ERRORS as error:
        expected, outcome = str(error), 'retried'
    assert (part.outcome, part.content) == (outcome, expected)
    assert by_agent.db.dump() == direct.db.dump()


# run_turn.

def test_an_unknown_customer_fails_before_the_model_is_called(store: Store) -> None:
    script = Script()
    with pytest.raises(UnknownCustomerError, match='cus_nobody'):
        run(script, store, 'cus_nobody')
    assert script.offered == []


def test_run_turn_reports_the_summary_tool_calls_and_a_history_that_continues(store: Store) -> None:
    first = Script(('get_account_state', {}), [('get_payment', {'payment_id': 'pay_2001'}),
                                               ('get_remittance', {'payment_id': 'pay_2001'})],
                   output={'summary': 'Nothing to do.', 'actions': []})
    turn = run(first, store, 'cus_pinecrest', 'Event one.')
    assert isinstance(turn, AgentTurn)
    assert (turn.text, turn.tool_calls, turn.cost_usd) == ('Nothing to do.', 3, 0.0)

    second = Script()
    again = run(second, store, 'cus_pinecrest', 'Event two.', history=turn.history)
    prompts = [part.content for message in second.seen[0] for part in message.parts if isinstance(part, UserPromptPart)]
    assert prompts == ['Event one.', 'Event two.']
    assert again.tool_calls == 0 and len(again.history) > len(turn.history)


def test_a_run_that_never_finishes_stops_at_the_request_limit(store: Store) -> None:
    script = Script(*[('list_open_invoices', {})] * (MAX_REQUESTS + 5))
    with pytest.raises(UsageLimitExceeded, match=f'request_limit of {MAX_REQUESTS}'):
        run(script, store, 'cus_pinecrest')
    assert len(script.offered) == MAX_REQUESTS
