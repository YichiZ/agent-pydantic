"""Offline checks on the collections eval set in agents/collections/db/: tasks, splits, documents and the ids they name."""
import json
import re
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parent.parent / 'db'

# Tool name -> argument names, from the Piece D table in agents/collections/docs/collections-agent-implementation.md.
TOOLS = {
    'get_account_state': set(),
    'list_open_invoices': set(),
    'get_invoice': {'invoice_id'},
    'get_payment': {'payment_id'},
    'get_remittance': {'payment_id'},
    'amount_due': {'invoice_ids'},
    'search_knowledge': {'query'},
    'apply_payment': {'payment_id', 'invoice_id', 'amount'},
    'send_message': {'contact_id', 'channel', 'invoice_ids', 'body'},
    'open_dispute': {'invoice_id', 'category', 'amount', 'claim'},
    'propose_credit': {'dispute_id', 'amount', 'reason'},
    'reject_dispute': {'dispute_id', 'reason'},
    'log_promise': {'invoice_id', 'promised_date', 'amount'},
    'execute_approval': {'approval_id'},
    'escalate_to_human': {'reason'},
}
ENV_FUNCTIONS = {'decide_approval': {'approval_id', 'decision', 'decided_by', 'note'}}
ASSERTIONS = {
    'assert_outbound_message_count': {'customer_id', 'expected'},
    'assert_last_message_amount': {'customer_id', 'expected'},
    'assert_message_invoices': {'customer_id', 'expected'},
    'assert_no_credit_without_approval': set(),
    'assert_unapplied_cash': {'payment_id', 'expected'},
    'assert_application_count': {'payment_id', 'expected'},
    'assert_invoice_paused': {'invoice_id', 'expected'},
    'assert_balance': {'invoice_id', 'expected'},
    'assert_credit_count': {'invoice_id', 'status', 'expected'},
    'assert_dispute_status': {'dispute_id', 'expected'},
    'assert_promise_count': {'invoice_id', 'expected'},
    'assert_pending_approval_count': {'customer_id', 'expected'},
    'assert_human_requested': {'customer_id', 'expected'},
}
MONEY_ASSERTIONS = {'assert_last_message_amount', 'assert_unapplied_cash', 'assert_balance'}
ANNOTATIONS = {
    'flow': {'collections', 'cash_application', 'disputes', 'cross_flow'},
    'trigger': {'ticket', 'chat'},
    'disposition': {'act', 'ask', 'escalate', 'do_nothing', 'refuse'},
    'needs_human': {True, False},
    'data_condition': {'clean', 'short_pay', 'no_remittance', 'multi_entity', 'stale_memory', 'open_dispute'},
    'adversarial': {True, False},
}
ID_PATTERNS = {
    'invoices': r'INV-\d+',
    'payments': r'pay_\d+',
    'disputes': r'dsp_\d+',
    'customers': r'cus_[a-z_]+',
    'contacts': r'con_\d+',
}
MONEY = re.compile(r'^\d+\.\d{2}$')


def task_id(n):
    return f'task_{n:02d}'


@pytest.fixture(scope='module')
def tasks():
    return json.loads((DB / 'tasks.json').read_text())


@pytest.fixture(scope='module')
def db():
    return {name: table['data'] for name, table in json.loads((DB / 'db.json').read_text()).items()}


def test_twenty_one_tasks_with_unique_ids(tasks):
    assert [t['id'] for t in tasks] == [task_id(n) for n in range(1, 22)]


def test_each_task_has_exactly_one_trigger(tasks):
    for t in tasks:
        assert (t['ticket'] is None) != (t['user_scenario'] is None), t['id']
        assert t['annotations']['trigger'] == ('ticket' if t['ticket'] else 'chat'), t['id']
        if t['user_scenario']:
            assert t['user_scenario']['persona'] and t['user_scenario']['instructions'], t['id']


def test_annotations_use_allowed_values(tasks):
    for t in tasks:
        a = t['annotations']
        assert set(a) == set(ANNOTATIONS) | {'customer_id'}, t['id']
        for key, allowed in ANNOTATIONS.items():
            assert a[key] in allowed, (t['id'], key, a[key])
        assert t['evaluation_criteria']['reward_basis'] == ['DB', 'ENV_ASSERTION'], t['id']


def test_splits(tasks):
    splits = json.loads((DB / 'split_tasks.json').read_text())
    assert splits == {
        'base': [task_id(n) for n in range(1, 22)],
        'never_events': [task_id(n) for n in (3, 7, 10, 11, 12, 14, 15, 16, 20, 21)],
        'cross_flow': [task_id(n) for n in (6, 11, 12)],
    }
    assert [task_id(n) for n in (6, 11, 12)] == [t['id'] for t in tasks if t['annotations']['flow'] == 'cross_flow']


def test_needs_human_exactly_for_3_7_10_18(tasks):
    assert [t['id'] for t in tasks if t['annotations']['needs_human']] == [task_id(n) for n in (3, 7, 10, 18)]


def test_every_task_asserts_human_requested_to_match_its_label(tasks):
    for t in tasks:
        checks = [e['arguments'] for e in t['evaluation_criteria']['env_assertions']
                  if e['func_name'] == 'assert_human_requested']
        a = t['annotations']
        assert checks == [{'customer_id': a['customer_id'], 'expected': a['needs_human']}], t['id']


def test_actions_name_tools_with_their_arguments(tasks):
    for t in tasks:
        actions = t['evaluation_criteria']['actions']
        for i, action in enumerate(actions):
            assert action['action_id'] == f"{t['id'][-2:]}_{i}", t['id']
            assert action['requestor'] == 'assistant', t['id']
            assert set(action['arguments']) == TOOLS[action['name']], (t['id'], action['name'])
            if 'amount' in action['arguments']:
                assert MONEY.match(action['arguments']['amount']), t['id']
        if t['annotations']['disposition'] == 'do_nothing':
            assert actions == [], t['id']


def test_initial_state_replays_tools_or_env_functions(tasks):
    for t in tasks:
        for step in (t['initial_state'] or {}).get('initialization_actions') or []:
            known = TOOLS if step['env_type'] == 'assistant' else ENV_FUNCTIONS
            assert step['env_type'] in ('assistant', 'env'), t['id']
            assert set(step['arguments']) == known[step['func_name']], (t['id'], step['func_name'])


def test_assertions_use_known_functions(tasks):
    for t in tasks:
        assert t['evaluation_criteria']['env_assertions'], t['id']
        for e in t['evaluation_criteria']['env_assertions']:
            assert e['env_type'] == 'assistant' and e['assert_value'] is True, t['id']
            assert set(e['arguments']) == ASSERTIONS[e['func_name']], (t['id'], e['func_name'])
            if e['func_name'] in MONEY_ASSERTIONS:
                assert MONEY.match(e['arguments']['expected']), (t['id'], e)


def test_named_ids_exist_in_db(tasks, db):
    for t in tasks:
        text = json.dumps([t['initial_state'], t['evaluation_criteria'], t['annotations']])
        for table, pattern in ID_PATTERNS.items():
            for found in re.findall(pattern, text):
                assert found in db[table], (t['id'], found)
        if t['ticket']:
            assert f"({t['annotations']['customer_id']})" in t['ticket'], t['id']


def test_no_ticket_names_a_tool(tasks):
    for t in tasks:
        for tool in TOOLS:
            assert tool not in (t['ticket'] or ''), (t['id'], tool)


def test_documents_exist_for_tasks_and_evidence(tasks, db):
    docs = {p.stem: json.loads(p.read_text()) for p in (DB / 'documents').glob('*.json')}
    for stem, doc in docs.items():
        assert doc['id'] == stem and doc['title'] and doc['content'], stem
    needed = {d for t in tasks for d in t['required_documents']}
    needed |= {d for dispute in db['disputes'].values() for d in dispute['evidence_document_ids']}
    assert needed <= set(docs), needed - set(docs)
