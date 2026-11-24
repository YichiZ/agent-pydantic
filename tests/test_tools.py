"""Write tools change exactly the expected rows and log once; denials and no-ops change nothing."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ar.data_model import (
    ApprovalStatus,
    ArDb,
    CreditStatus,
    DisputeStatus,
    InvoiceStatus,
    MessageDirection,
    PaymentStatus,
    PromiseStatus,
    UnknownInvoiceError,
)
from ar.environment import TOOLS, call_env_function, call_tool, check_assertion, fresh_store
from ar.errors import InvalidArgumentError, PolicyDenied, UnknownToolError
from ar.store import Store

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'db' / 'db.json'
DOCUMENTS = ROOT / 'db' / 'documents'


@pytest.fixture
def store() -> Store:
    return fresh_store(DB_PATH, DOCUMENTS)


def run(store: Store, customer_id: str, name: str, **arguments: Any) -> Any:
    """Call a tool, checking that the database value it started from was not mutated."""
    before, snapshot = store.db, store.db.dump()
    result = call_tool(store, customer_id, name, arguments)
    assert before.dump() == snapshot
    return result


def changes(before: ArDb, after: ArDb) -> dict[str, set[str]]:
    """Ids added, changed or removed, per table."""
    found = {}
    for name in ArDb.model_fields:
        old, new = before.table(name), after.table(name)
        ids = {key for key in new if old.get(key) != new[key]} | {key for key in old if key not in new}
        if ids:
            found[name] = ids
    return found


def assert_denied(store: Store, rule: str, customer_id: str, name: str, **arguments: Any) -> None:
    before, snapshot = store.db, store.db.dump()
    with pytest.raises(PolicyDenied) as raised:
        run(store, customer_id, name, **arguments)
    assert raised.value.rule == rule and raised.value.reason
    assert store.db is before and before.dump() == snapshot


def assert_unchanged(store: Store, customer_id: str, name: str, **arguments: Any) -> Any:
    before = store.db
    result = run(store, customer_id, name, **arguments)
    assert result.status == 'unchanged' and store.db is before
    return result


def reminder(contact_id: str, invoice_ids: list[str], body: str, channel: str = 'email') -> dict[str, Any]:
    return {'contact_id': contact_id, 'channel': channel, 'invoice_ids': invoice_ids, 'body': body}


# send_message

def test_send_message_writes_one_message_stamped_from_the_ledger(store):
    before, snapshot = store.db, store.db.dump()
    result = run(store, 'cus_garnet', 'send_message', **reminder('con_809', ['INV-1601'], 'Now due: $9,400.00.'))
    assert (result.status, result.target_id) == ('done', 'msg_6011')
    assert changes(before, store.db) == {'messages': {'msg_6011'}, 'action_log': {'act_7014'}}
    message = store.db.messages['msg_6011']
    assert message.amount_requested == Decimal('9400.00') and message.sent_at == before.today
    assert (message.direction, message.customer_id, message.invoice_ids) == (
        MessageDirection.OUTBOUND, 'cus_garnet', ('INV-1601',))
    log = store.db.action_log['act_7014']
    assert (log.actor, log.action, log.target_id, log.at) == ('coworker', 'send_message', 'msg_6011', before.today)
    assert before.dump() == snapshot


def test_send_message_denied_changes_nothing(store):
    assert_denied(store, 'P1', 'cus_juniper', 'send_message', **reminder('con_810', ['INV-1702'], '$4,800.00'))
    assert_denied(store, 'P3', 'cus_garnet', 'send_message', **reminder('con_809', ['INV-1601'], '$10,000.00'))


def test_send_message_on_review_holds_the_draft_in_one_pending_approval(store):
    before = store.db
    body = 'INV-2201 for $5,760.00 is due.'
    result = run(store, 'cus_orchard', 'send_message', **reminder('con_819', ['INV-2201'], body))
    assert (result.status, result.approval_id, result.rule) == ('held_for_approval', 'apr_8001', 'P5')
    assert 'apr_8001' in result.message
    assert changes(before, store.db) == {'approvals': {'apr_8001'}, 'action_log': {'act_7014'}}
    approval = store.db.approval('apr_8001')
    assert (approval.status, approval.customer_id, approval.action) == (
        ApprovalStatus.PENDING, 'cus_orchard', 'send_message')
    assert approval.payload == {'contact_id': 'con_819', 'channel': 'email', 'invoice_ids': ['INV-2201'],
                                'amount': '5760.00', 'body': body}


# apply_payment

def test_apply_payment_applies_and_settles_invoice_and_payment(store):
    before = store.db
    result = run(store, 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1301',
                 amount='15000.00')
    assert (result.status, result.target_id) == ('done', 'app_5002')
    assert changes(before, store.db) == {'applications': {'app_5002'}, 'invoices': {'INV-1301'},
                                         'payments': {'pay_2001'}, 'action_log': {'act_7014'}}
    assert store.db.applications['app_5002'].idempotency_key == 'pay_2001:INV-1301'
    assert store.db.invoice('INV-1301').status is InvoiceStatus.PAID
    assert store.db.payment('pay_2001').status is PaymentStatus.APPLIED


def test_apply_payment_partial_leaves_the_invoice_open(store):
    before = store.db
    run(store, 'cus_delmar', 'apply_payment', payment_id='pay_2002', invoice_id='INV-1302', amount=Decimal('100'))
    assert changes(before, store.db) == {'applications': {'app_5002'}, 'action_log': {'act_7014'}}


def test_apply_payment_repeat_returns_the_existing_application(store):
    arguments = {'payment_id': 'pay_2001', 'invoice_id': 'INV-1301', 'amount': '15000.00'}
    run(store, 'cus_pinecrest', 'apply_payment', **arguments)
    assert assert_unchanged(store, 'cus_pinecrest', 'apply_payment', **arguments).target_id == 'app_5002'


def test_apply_payment_denied_changes_nothing(store):
    assert_denied(store, 'P6', 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1301',
                  amount='15000.01')
    assert_denied(store, 'P7', 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1302',
                  amount='1.00')


def test_apply_payment_with_two_candidates_holds_one_approval_listing_both(store):
    before = store.db
    result = run(store, 'cus_quarry', 'apply_payment', payment_id='pay_2004', invoice_id='INV-1403', amount='6300.00')
    assert (result.status, result.approval_id, result.rule) == ('held_for_approval', 'apr_8001', 'P8')
    assert changes(before, store.db) == {'approvals': {'apr_8001'}, 'action_log': {'act_7014'}}
    assert store.db.approval('apr_8001').payload == {
        'payment_id': 'pay_2004', 'amount': '6300.00', 'candidate_invoice_ids': ['INV-1402', 'INV-1403']}
    again = assert_unchanged(store, 'cus_quarry', 'apply_payment', payment_id='pay_2004', invoice_id='INV-1402',
                             amount='6300.00')
    assert (again.approval_id, again.rule) == ('apr_8001', 'P8')


# open_dispute

def test_open_dispute_records_the_claim_and_pauses_the_invoice(store):
    before = store.db
    result = run(store, 'cus_ridgeway', 'open_dispute', invoice_id='INV-1501', category='pricing_variance',
                 amount='2000.00', claim='Customer says $40.00 per case.')
    assert (result.status, result.target_id) == ('done', 'dsp_3006')
    assert changes(before, store.db) == {'disputes': {'dsp_3006'}, 'invoices': {'INV-1501'}, 'action_log': {'act_7014'}}
    dispute = store.db.dispute('dsp_3006')
    assert (dispute.status, dispute.customer_id, dispute.opened_at, dispute.evidence_document_ids) == (
        DisputeStatus.OPEN, 'cus_ridgeway', before.today, ())
    assert store.db.invoice('INV-1501').collections_paused is True


@pytest.mark.parametrize(('category', 'amount'), [('freight', '22000.01'), ('freight', '0.00'), ('weather', '10.00')])
def test_open_dispute_refuses_bad_arguments(store, category, amount):
    before = store.db
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_ridgeway', 'open_dispute', invoice_id='INV-1501', category=category, amount=amount, claim='c')
    assert store.db is before


def test_open_dispute_denied_outside_the_account(store):
    assert_denied(store, 'P11', 'cus_brightwell', 'open_dispute', invoice_id='INV-1501', category='freight',
                  amount='10.00', claim='c')


# propose_credit

def test_propose_credit_under_the_limit_applies_and_resolves(store):
    before = store.db
    result = run(store, 'cus_saltmarsh', 'propose_credit', dispute_id='dsp_3001', amount='378.00', reason='POD short.')
    assert (result.status, result.target_id) == ('done', 'crd_4002')
    assert changes(before, store.db) == {'credits': {'crd_4002'}, 'disputes': {'dsp_3001'}, 'invoices': {'INV-1502'},
                                         'action_log': {'act_7014'}}
    assert store.db.credit('crd_4002').status is CreditStatus.APPLIED
    assert store.db.dispute('dsp_3001').status is DisputeStatus.RESOLVED_VALID
    assert store.db.invoice('INV-1502').collections_paused is False


def test_a_credit_that_clears_the_balance_marks_the_invoice_paid(store):
    run(store, 'cus_elmstead', 'apply_payment', payment_id='pay_2003', invoice_id='INV-1401', amount='17850.00')
    run(store, 'cus_elmstead', 'open_dispute', invoice_id='INV-1401', category='freight', amount='750.00', claim='c')
    run(store, 'cus_elmstead', 'propose_credit', dispute_id='dsp_3006', amount='750.00', reason='Late delivery.')
    decide(store, 'apr_8001', 'approved')
    run(store, 'cus_elmstead', 'execute_approval', approval_id='apr_8001')
    invoice = store.db.invoice('INV-1401')
    assert (invoice.status, invoice.collections_paused) == (InvoiceStatus.PAID, False)
    assert_denied(store, 'P9', 'cus_elmstead', 'propose_credit', dispute_id='dsp_3006', amount='1.00', reason='again')


def test_propose_credit_above_the_limit_holds_a_proposed_credit(store):
    before = store.db
    result = run(store, 'cus_fennick', 'propose_credit', dispute_id='dsp_3002', amount='3120.00', reason='Damage.')
    assert (result.status, result.approval_id, result.rule, result.target_id) == (
        'held_for_approval', 'apr_8001', 'P10', 'crd_4002')
    assert changes(before, store.db) == {'credits': {'crd_4002'}, 'approvals': {'apr_8001'}, 'action_log': {'act_7014'}}
    proposed = store.db.credit('crd_4002')
    assert (proposed.status, proposed.approval_id, proposed.applied_at) == (CreditStatus.PROPOSED, 'apr_8001', None)
    assert store.db.approval('apr_8001').payload == {
        'credit_id': 'crd_4002', 'dispute_id': 'dsp_3002', 'invoice_id': 'INV-1503', 'amount': '3120.00'}


def test_propose_credit_denied_changes_nothing(store):
    assert_denied(store, 'P9', 'cus_garnet', 'propose_credit', dispute_id='dsp_3003', amount='10.00', reason='r')


# reject_dispute

def test_reject_dispute_resolves_invalid_and_unpauses(store):
    before = store.db
    result = run(store, 'cus_larkspur', 'reject_dispute', dispute_id='dsp_3005', reason='POD shows 200 cases.')
    assert (result.status, result.target_id) == ('done', 'dsp_3005')
    assert changes(before, store.db) == {'disputes': {'dsp_3005'}, 'invoices': {'INV-1901'}, 'action_log': {'act_7014'}}
    dispute = store.db.dispute('dsp_3005')
    assert (dispute.status, dispute.resolution) == (DisputeStatus.RESOLVED_INVALID, 'POD shows 200 cases.')
    assert store.db.invoice('INV-1901').collections_paused is False
    assert_unchanged(store, 'cus_larkspur', 'reject_dispute', dispute_id='dsp_3005', reason='again')


def test_reject_dispute_keeps_the_pause_while_another_dispute_is_open(store):
    run(store, 'cus_larkspur', 'open_dispute', invoice_id='INV-1901', category='quality', amount='10.00', claim='c')
    run(store, 'cus_larkspur', 'reject_dispute', dispute_id='dsp_3005', reason='POD')
    assert store.db.invoice('INV-1901').collections_paused is True


def test_reject_dispute_refuses_a_dispute_resolved_valid(store):
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_garnet', 'reject_dispute', dispute_id='dsp_3003', reason='r')


# log_promise

def test_log_promise_records_an_open_promise(store):
    before = store.db
    result = run(store, 'cus_hollis', 'log_promise', invoice_id='INV-1101', promised_date='2026-11-20',
                 amount='8150.00')
    assert (result.status, result.target_id) == ('done', 'prm_8502')
    assert changes(before, store.db) == {'promises': {'prm_8502'}, 'action_log': {'act_7014'}}
    promise = store.db.promises['prm_8502']
    assert (promise.status, promise.source_message_id, str(promise.promised_date)) == (
        PromiseStatus.OPEN, None, '2026-11-20')


@pytest.mark.parametrize(('promised_date', 'amount'), [
    ('2026-11-15', '8150.00'), ('20/11/2026', '8150.00'), ('2026-11-20', '8150.01'), ('2026-11-20', '0.00'),
])
def test_log_promise_refuses_bad_arguments(store, promised_date, amount):
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_hollis', 'log_promise', invoice_id='INV-1101', promised_date=promised_date, amount=amount)


# pause_collections

def test_pause_collections_on_a_disputed_invoice_changes_nothing(store):
    assert_denied(store, 'P1', 'cus_brightwell', 'pause_collections', invoice_id='INV-1001', reason='Customer query.')
    assert_unchanged(store, 'cus_juniper', 'pause_collections', invoice_id='INV-1702', reason='already paused')


# request_approval and escalate_to_human

def test_request_approval_writes_one_pending_approval(store):
    before = store.db
    result = run(store, 'cus_brightwell', 'request_approval', action='write_off', payload={'invoice_id': 'INV-1001'},
                 reason='Customer is closing down.')
    assert (result.status, result.approval_id) == ('held_for_approval', 'apr_8001')
    assert changes(before, store.db) == {'approvals': {'apr_8001'}, 'action_log': {'act_7014'}}
    assert store.db.approval('apr_8001').customer_id == 'cus_brightwell'


@pytest.mark.parametrize('action', ['send_message', 'apply_payment', 'propose_credit', ''])
def test_request_approval_refuses_actions_a_rule_already_covers(store, action):
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_brightwell', 'request_approval', action=action, payload={}, reason='r')


def test_escalate_to_human_only_logs(store):
    before = store.db
    result = run(store, 'cus_corvid', 'escalate_to_human', reason='Only contact is do-not-contact.')
    assert changes(before, store.db) == {'action_log': {'act_7014'}}
    assert store.db.action_log['act_7014'].target_id == 'cus_corvid' == result.target_id
    assert check_assertion(store.db, 'assert_human_requested', {'customer_id': 'cus_corvid', 'expected': True})


# decide_approval and execute_approval

def decide(store: Store, approval_id: str, decision: str) -> Any:
    return call_env_function(store, 'decide_approval', {
        'approval_id': approval_id, 'decision': decision, 'decided_by': 'ar_lead', 'note': 'Checked.'})


def test_decide_approval_records_the_decision_and_the_credit(store):
    run(store, 'cus_fennick', 'propose_credit', dispute_id='dsp_3002', amount='3120.00', reason='Damage.')
    before = store.db
    decide(store, 'apr_8001', 'rejected')
    assert changes(before, store.db) == {'approvals': {'apr_8001'}, 'credits': {'crd_4002'}, 'action_log': {'act_7015'}}
    approval = store.db.approval('apr_8001')
    assert (approval.status, approval.decided_by, approval.decided_at, approval.note) == (
        ApprovalStatus.REJECTED, 'ar_lead', before.today, 'Checked.')
    assert store.db.credit('crd_4002').status is CreditStatus.REJECTED
    assert store.db.action_log['act_7015'].actor == 'ar_lead'
    with pytest.raises(InvalidArgumentError):
        decide(store, 'apr_8001', 'approved')


def test_decide_approval_refuses_an_unknown_decision(store):
    run(store, 'cus_fennick', 'propose_credit', dispute_id='dsp_3002', amount='3120.00', reason='Damage.')
    with pytest.raises(InvalidArgumentError):
        decide(store, 'apr_8001', 'maybe')


def test_execute_approval_applies_an_approved_credit_once(store):
    run(store, 'cus_fennick', 'propose_credit', dispute_id='dsp_3002', amount='3120.00', reason='Damage.')
    assert_denied(store, 'P13', 'cus_fennick', 'execute_approval', approval_id='apr_8001')  # still pending
    decide(store, 'apr_8001', 'approved')
    before = store.db
    result = run(store, 'cus_fennick', 'execute_approval', approval_id='apr_8001')
    assert (result.status, result.target_id) == ('done', 'apr_8001')
    assert changes(before, store.db) == {'credits': {'crd_4002'}, 'disputes': {'dsp_3002'}, 'invoices': {'INV-1503'},
                                         'approvals': {'apr_8001'}, 'action_log': {'act_7016'}}
    assert store.db.credit('crd_4002').status is CreditStatus.APPLIED
    assert store.db.approval('apr_8001').executed_at == before.today
    assert_denied(store, 'P13', 'cus_fennick', 'execute_approval', approval_id='apr_8001')


def test_execute_approval_sends_an_approved_draft(store):
    run(store, 'cus_orchard', 'send_message', **reminder('con_819', ['INV-2201'], 'INV-2201: $5,760.00 is due.'))
    decide(store, 'apr_8001', 'approved')
    before = store.db
    run(store, 'cus_orchard', 'execute_approval', approval_id='apr_8001')
    assert changes(before, store.db) == {'messages': {'msg_6011'}, 'approvals': {'apr_8001'}, 'action_log': {'act_7016'}}
    assert store.db.messages['msg_6011'].amount_requested == Decimal('5760.00')


def test_execute_approval_refuses_a_payment_approval_for_now(store):
    run(store, 'cus_quarry', 'apply_payment', payment_id='pay_2004', invoice_id='INV-1402', amount='6300.00')
    decide(store, 'apr_8001', 'approved')
    assert_denied(store, 'P13', 'cus_quarry', 'execute_approval', approval_id='apr_8001')


def test_execute_approval_refuses_an_action_it_cannot_carry_out(store):
    run(store, 'cus_brightwell', 'request_approval', action='write_off', payload={}, reason='r')
    decide(store, 'apr_8001', 'approved')
    assert_denied(store, 'P13', 'cus_brightwell', 'execute_approval', approval_id='apr_8001')


# read tools

def test_reads_refuse_rows_outside_the_account(store):
    for name, arguments in [('get_invoice', {'invoice_id': 'INV-1001'}), ('get_payment', {'payment_id': 'pay_2001'}),
                            ('get_remittance', {'payment_id': 'pay_2001'}), ('amount_due', {'invoice_ids': ['INV-1001']})]:
        with pytest.raises(PolicyDenied) as raised:
            run(store, 'cus_corvid', name, **arguments)
        assert raised.value.rule == 'P11'


def test_get_account_state_covers_the_family(store):
    state = run(store, 'cus_delmar', 'get_account_state')
    assert json.loads(json.dumps(state)) == state
    assert state['today'] == '2026-11-16'
    assert {c['customer_id'] for c in state['customers']} == {'cus_delmar', 'cus_delmar_west'}
    assert set(state) == {'today', 'customers', 'contacts', 'open_invoices', 'open_disputes', 'unapplied_payments',
                          'open_promises', 'approvals', 'recent_messages', 'notes'}
    invoices = {i['invoice_id']: i for i in state['open_invoices']}
    assert set(invoices) == {'INV-1302', 'INV-1303', 'INV-1304', 'INV-1305'}
    assert (invoices['INV-1305']['balance'], invoices['INV-1305']['overdue']) == ('6640.00', False)
    assert [(p['payment_id'], p['unapplied'], p['has_remittance']) for p in state['unapplied_payments']] == [
        ('pay_2002', '27480.00', True)]
    assert [n['note_id'] for n in state['notes']] == ['note_9003']


def test_get_account_state_shows_disputes_promises_approvals_and_messages(store):
    kestrel = run(store, 'cus_kestrel', 'get_account_state')
    assert [p['promise_id'] for p in kestrel['open_promises']] == ['prm_8501']
    assert [m['message_id'] for m in kestrel['recent_messages']] == ['msg_6008', 'msg_6007']
    garnet = run(store, 'cus_garnet', 'get_account_state')
    assert [(a['approval_id'], a['status'], a['note']) for a in garnet['approvals']] == [
        ('apr_8000', 'approved', 'Agreement confirms 37.60.')]
    juniper = run(store, 'cus_juniper', 'get_account_state')
    assert [d['dispute_id'] for d in juniper['open_disputes']] == ['dsp_3004']


def test_list_open_invoices_flags_overdue(store):
    invoices = run(store, 'cus_brightwell', 'list_open_invoices')
    assert [(i['invoice_id'], i['balance'], i['overdue']) for i in invoices] == [
        ('INV-1001', '12400.00', True), ('INV-1003', '5300.00', False)]


def test_get_invoice_payment_and_amount_due(store):
    invoice = run(store, 'cus_garnet', 'get_invoice', invoice_id='INV-1601')
    assert invoice['balance'] == '9400.00' and [c['credit_id'] for c in invoice['credits']] == ['crd_4001']
    assert [d['dispute_id'] for d in invoice['disputes']] == ['dsp_3003']
    assert [m['message_id'] for m in invoice['messages']] == ['msg_6004', 'msg_6005']
    payment = run(store, 'cus_delmar', 'get_payment', payment_id='pay_2002')
    assert (payment['unapplied'], payment['applications']) == ('27480.00', [])
    assert run(store, 'cus_juniper', 'amount_due', invoice_ids=['INV-1701', 'INV-1702']) == {
        'invoice_ids': ['INV-1701', 'INV-1702'], 'amount_due': '12050.00'}


def test_get_remittance_with_and_without_one(store):
    none = run(store, 'cus_quarry', 'get_remittance', payment_id='pay_2004')
    assert none['remittance'] is None and 'No remittance' in none['message']
    found = run(store, 'cus_pinecrest', 'get_remittance', payment_id='pay_2001')
    assert found['remittance']['remittance_id'] == 'rem_2001'


def test_search_knowledge_finds_documents_and_only_this_accounts_notes(store):
    results = run(store, 'cus_elmstead', 'search_knowledge', query='FRT-02')['results']
    assert results[0]['id'] == 'doc_deduction_reason_codes'
    assert {'doc_deduction_reason_codes', 'note_9004'} <= {r['id'] for r in results}
    assert all(set(r) == {'id', 'title', 'content'} for r in results)
    other = run(store, 'cus_elmstead', 'search_knowledge', query='Thursdays')['results']
    assert other == []
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_elmstead', 'search_knowledge', query='  ')


# arguments and dispatch

def test_bad_arguments_raise_typed_errors(store):
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1301', amount='15,000')
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1301', amount=15000.0)
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_pinecrest', 'apply_payment', payment_id='pay_2001', invoice_id='INV-1301')
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_garnet', 'send_message', **reminder('con_809', [], '$9,400.00'))
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_garnet', 'send_message', **reminder('con_809', ['INV-1601'], '$9,400.00', channel='fax'))
    with pytest.raises(UnknownInvoiceError):
        run(store, 'cus_pinecrest', 'get_invoice', invoice_id='INV-0000')
    with pytest.raises(UnknownToolError):
        run(store, 'cus_pinecrest', 'write_off_everything')
    with pytest.raises(UnknownToolError):
        call_env_function(store, 'reset_db', {})
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_hollis', 'log_promise', invoice_id='INV-1101', promised_date='2026-02-30', amount='1.00')
    with pytest.raises(InvalidArgumentError):
        run(store, 'cus_brightwell', 'request_approval', action='write_off', payload='everything', reason='r')


def test_typed_values_are_accepted_too(store):
    result = run(store, 'cus_hollis', 'log_promise', invoice_id='INV-1101', promised_date=date(2026, 11, 20),
                 amount=Decimal('8150'))
    assert store.db.promises[result.target_id].amount == Decimal('8150.00')


def test_decide_approval_refuses_a_note_that_is_not_text(store):
    run(store, 'cus_fennick', 'propose_credit', dispute_id='dsp_3002', amount='3120.00', reason='Damage.')
    with pytest.raises(InvalidArgumentError):
        call_env_function(store, 'decide_approval', {
            'approval_id': 'apr_8001', 'decision': 'approved', 'decided_by': 'ar_lead', 'note': 42})


def test_fresh_store_needs_the_documents_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        fresh_store(DB_PATH, tmp_path / 'missing')


def test_registry_places_each_tool_once():
    assert len(TOOLS) == 17
    assert sum(spec.kind == 'read' for spec in TOOLS.values()) == 7
    by_skill = {skill: {name for name, spec in TOOLS.items() if spec.skill == skill}
                for skill in ('base', 'collections', 'cash_application', 'disputes')}
    assert by_skill['collections'] == {'send_message', 'log_promise'}
    assert by_skill['cash_application'] == {'apply_payment'}
    assert by_skill['disputes'] == {'open_dispute', 'pause_collections', 'propose_credit', 'reject_dispute'}
    assert {'request_approval', 'execute_approval', 'escalate_to_human'} <= by_skill['base']
    assert all(spec.name == name for name, spec in TOOLS.items())
