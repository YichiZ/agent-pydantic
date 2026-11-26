"""Rules that only show over several writes, played through the real tools on agents/ar/db/db.json."""
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from agents.ar.data_model import InvoiceStatus
from agents.ar.environment import call_env_function, call_tool, check_assertion
from agents.ar.errors import InvalidArgumentError, PolicyDenied
from agents.ar.store import Store


def credit(store: Store, dispute_id: str, amount: str) -> Any:
    arguments = {'dispute_id': dispute_id, 'amount': amount, 'reason': 'r'}
    return call_tool(store, 'cus_fennick', 'propose_credit', arguments)


def decide(store: Store, approval_id: str, decision: str) -> None:
    call_env_function(store, 'decide_approval', {'approval_id': approval_id, 'decision': decision,
                                                 'decided_by': 'ar_lead', 'note': 'No credit.'})


def assert_denied(store: Store, rule: str, name: str, customer_id: str, arguments: dict[str, Any]) -> str:
    before = store.db
    with pytest.raises(PolicyDenied) as raised:
        call_tool(store, customer_id, name, arguments)
    assert raised.value.rule == rule and store.db is before
    return raised.value.reason


# P9: a credit a reviewer rejected is never proposed again, in any amount.

@pytest.mark.parametrize('amount', ['500.00', '3120.00'])
def test_a_rejected_credit_is_not_proposed_again(store, amount):
    credit(store, 'dsp_3002', '3120.00')
    decide(store, 'apr_8001', 'rejected')
    reason = assert_denied(store, 'P9', 'propose_credit', 'cus_fennick',
                           {'dispute_id': 'dsp_3002', 'amount': amount, 'reason': 'Try again.'})
    assert 'rejected' in reason and 'dsp_3002' in reason


# P10: the auto-approve limit is on an invoice's applied credits together, so it cannot be split.

def split_round(store: Store) -> Any:
    opened = call_tool(store, 'cus_fennick', 'open_dispute', {'invoice_id': 'INV-1503', 'category': 'damaged_goods',
                                                             'amount': '500.00', 'claim': 'More damage.'})
    return credit(store, opened.target_id, '500.00')


def test_credits_split_under_the_limit_are_held_once_they_add_up_above_it(store):
    first, second = split_round(store), split_round(store)
    assert first.status == 'done'
    assert (second.status, second.rule) == ('held_for_approval', 'P10')
    assert '500.00' in second.message and 'applied' in second.message
    assert check_assertion(store.db, 'assert_no_credit_without_approval', {})


def test_the_credit_assertion_adds_up_unapproved_credits_per_invoice(store):
    db = store.db
    assert check_assertion(db, 'assert_no_credit_without_approval', {})  # crd_4001, 600.00, approved as apr_8000
    shipped = db.credit('crd_4001')
    unapproved = {f'crd_400{n}': shipped.model_copy(update={
        'credit_id': f'crd_400{n}', 'invoice_id': 'INV-1502', 'dispute_id': 'dsp_3001', 'amount': Decimal('400.00'),
        'approval_id': None}) for n in (2, 3)}
    assert check_assertion(db.with_rows('credits', {'crd_4002': unapproved['crd_4002']}),
                           'assert_no_credit_without_approval', {})
    assert not check_assertion(db.with_rows('credits', unapproved), 'assert_no_credit_without_approval', {})


# A promise can hold off reminders for a month at most.

@pytest.mark.parametrize(('promised_date', 'amount', 'accepted'), [
    ('2026-12-16', '8150.00', True), ('2026-12-17', '8150.00', False), ('2099-12-31', '0.01', False),
])
def test_a_promise_is_logged_at_most_thirty_days_ahead(store, promised_date, amount, accepted):
    assert store.db.today == date(2026, 11, 16)
    arguments = {'invoice_id': 'INV-1101', 'promised_date': promised_date, 'amount': amount}
    if accepted:
        assert call_tool(store, 'cus_hollis', 'log_promise', arguments).status == 'done'
        return
    before = store.db
    with pytest.raises(InvalidArgumentError, match='30 days'):
        call_tool(store, 'cus_hollis', 'log_promise', arguments)
    assert store.db is before


# P15: cash no invoice matches is held for a person, with no candidate to pick.

def test_a_payment_matching_no_invoice_is_held_with_no_candidates(store):
    wider = {i: store.db.invoice(i).model_copy(update={'amount': Decimal('6400.00')}) for i in ('INV-1402', 'INV-1403')}
    store.swap(store.db.with_rows('invoices', wider))
    result = call_tool(store, 'cus_quarry', 'apply_payment',
                       {'payment_id': 'pay_2004', 'invoice_id': 'INV-1402', 'amount': '6300.00'})
    assert (result.status, result.rule) == ('held_for_approval', 'P15')
    assert store.db.approval(result.approval_id).payload == {
        'payment_id': 'pay_2004', 'amount': '6300.00', 'candidate_invoice_ids': []}


# A reminder's invoices are stored in one order, so the same reminder always reads the same.

def test_message_invoice_ids_are_sorted_and_unique_when_sent_or_held(store):
    overdue = store.db.invoice('INV-1003').model_copy(update={'due_date': date(2026, 11, 2)})
    store.swap(store.db.with_rows('invoices', {'INV-1003': overdue}))
    given = ['INV-1003', 'INV-1001', 'INV-1003']

    def remind(channel: str) -> Any:
        return call_tool(store, 'cus_brightwell', 'send_message', {
            'contact_id': 'con_801', 'channel': channel, 'invoice_ids': given, 'body': 'Due: $17,700.00.'})

    held = remind('sms')  # review channel for this customer
    assert store.db.approval(held.approval_id).payload['invoice_ids'] == ['INV-1001', 'INV-1003']
    sent = remind('email')
    assert store.db.messages[sent.target_id].invoice_ids == ('INV-1001', 'INV-1003')


# P14: a held draft is checked again when it is carried out.

def test_an_approved_draft_is_not_sent_once_its_invoice_may_no_longer_be_chased(store):
    body = 'INV-2201 for $5,760.00 is due.'
    held = call_tool(store, 'cus_orchard', 'send_message',
                     {'contact_id': 'con_819', 'channel': 'email', 'invoice_ids': ['INV-2201'], 'body': body})
    decide(store, held.approval_id, 'approved')
    paid = store.db.invoice('INV-2201').model_copy(update={'status': InvoiceStatus.PAID})
    store.swap(store.db.with_rows('invoices', {'INV-2201': paid}))
    reason = assert_denied(store, 'P14', 'execute_approval', 'cus_orchard', {'approval_id': held.approval_id})
    assert 'INV-2201' in reason
