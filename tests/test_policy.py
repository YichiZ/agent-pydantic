"""Policy rules P1-P13: at least one allowed and one failing case each, on rows from db/db.json."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ar.data_model import Application, ApprovalStatus, ArDb, AutonomyLevel, Channel
from ar.environment import call_env_function, call_tool, fresh_store
from ar.policy import (
    Decision,
    Outcome,
    amounts_in,
    check_apply_payment,
    check_execute_approval,
    check_log_promise,
    check_open_dispute,
    check_pause_collections,
    check_propose_credit,
    check_reject_dispute,
    check_scope,
    check_send_message,
    payment_candidates,
)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'db' / 'db.json'
DOCUMENTS = ROOT / 'db' / 'documents'


@pytest.fixture(scope='module')
def db() -> ArDb:
    return ArDb.load(DB_PATH)


def send(db: ArDb, customer_id: str, contact_id: str, invoice_ids: list[str], body: str,
         channel: Channel = Channel.EMAIL) -> Decision:
    return check_send_message(
        db, customer_id, contact_id=contact_id, channel=channel, invoice_ids=invoice_ids, body=body,
    )


def apply(db: ArDb, customer_id: str, payment_id: str, invoice_id: str, amount: str) -> Decision:
    return check_apply_payment(db, customer_id, payment_id=payment_id, invoice_id=invoice_id, amount=Decimal(amount))


def credit(db: ArDb, customer_id: str, dispute_id: str, amount: str) -> Decision:
    return check_propose_credit(db, customer_id, dispute_id=dispute_id, amount=Decimal(amount))


def assert_allowed(decision: Decision) -> None:
    assert decision.outcome is Outcome.ALLOW, decision


def assert_denied(decision: Decision, rule: str) -> None:
    assert (decision.outcome, decision.rule) == (Outcome.DENY, rule), decision
    assert decision.reason


def assert_held(decision: Decision, rule: str) -> None:
    assert (decision.outcome, decision.rule) == (Outcome.NEEDS_APPROVAL, rule), decision
    assert decision.reason


def test_p1_a_paused_invoice_may_not_be_chased(db):
    assert_denied(send(db, 'cus_juniper', 'con_810', ['INV-1702'], 'INV-1702: $4,800.00 is due.'), 'P1')
    assert_denied(send(db, 'cus_juniper', 'con_810', ['INV-1701', 'INV-1702'], 'Due: $12,050.00.'), 'P1')
    assert_allowed(send(db, 'cus_juniper', 'con_810', ['INV-1701'], 'INV-1701 for $7,250.00 is due.'))


def test_p2_a_do_not_contact_contact_is_never_messaged(db):
    assert_denied(send(db, 'cus_corvid', 'con_803', ['INV-1201'], 'INV-1201: $3,975.50 is due.'), 'P2')
    assert_denied(send(db, 'cus_corvid', 'con_803', ['INV-1201'], '$3,975.50', Channel.SMS), 'P2')
    assert_allowed(send(db, 'cus_brightwell', 'con_801', ['INV-1001'], 'INV-1001: $12,400.00 is due.'))


@pytest.mark.parametrize('stated', ['$9,400', '9,400.00', '9400', '$9,400.00.', 'USD 9400.0'])
def test_p3_accepts_the_amount_due_written_any_way(db, stated):
    assert_allowed(send(db, 'cus_garnet', 'con_809', ['INV-1601'], f'INV-1601: the balance due is {stated}'))


@pytest.mark.parametrize('stated', ['$10,000.00', '9,400.01', '$94.00', 'nine thousand four hundred dollars'])
def test_p3_denies_a_body_without_the_amount_due(db, stated):
    assert_denied(send(db, 'cus_garnet', 'con_809', ['INV-1601'], f'INV-1601: the balance due is {stated}'), 'P3')


def test_amounts_in_parses_values_not_text():
    found = amounts_in('INV-1601 for $9,400 or 9,400.00 was due November 2, 2026. Total 1,234,567.5!')
    assert found == (Decimal(1601), Decimal(9400), Decimal('9400.00'), Decimal(2), Decimal(2026), Decimal('1234567.5'))


def test_p4_nolan_was_reminded_three_days_ago(db):
    assert_denied(send(db, 'cus_nolan', 'con_818', ['INV-2101'], 'INV-2101: $7,800.00 is due.'), 'P4')


def test_p4_hollis_was_reminded_exactly_seven_days_ago(db):
    assert (db.today - db.messages['msg_6001'].sent_at).days == 7
    assert_allowed(send(db, 'cus_hollis', 'con_802', ['INV-1101'], 'INV-1101: $8,150.00 is due.'))


@pytest.mark.parametrize(('days_ago', 'allowed'), [(6, False), (7, True), (8, True)])
def test_p4_allows_a_reminder_from_the_seventh_day(db, days_ago, allowed):
    moved = db.messages['msg_6010'].model_copy(update={'sent_at': db.today - timedelta(days=days_ago)})
    decision = send(db.with_rows('messages', {'msg_6010': moved}), 'cus_nolan', 'con_818', ['INV-2101'], '$7,800.00')
    assert (decision.outcome is Outcome.ALLOW) == allowed, decision
    if not allowed:
        assert decision.rule == 'P4'


def test_p5_a_channel_on_review_needs_approval(db):
    assert_held(send(db, 'cus_orchard', 'con_819', ['INV-2201'], 'INV-2201: $5,760.00 is due.'), 'P5')
    assert_held(send(db, 'cus_brightwell', 'con_801', ['INV-1001'], '$12,400.00', Channel.SMS), 'P5')
    assert_allowed(send(db, 'cus_brightwell', 'con_801', ['INV-1001'], '$12,400.00', Channel.EMAIL))


def test_p5_a_channel_that_is_off_is_denied(db):
    orchard = db.customer('cus_orchard')
    off = orchard.model_copy(update={'autonomy': {Channel.EMAIL: AutonomyLevel.OFF, Channel.SMS: AutonomyLevel.OFF}})
    db_off = db.with_rows('customers', {'cus_orchard': off})
    assert_denied(send(db_off, 'cus_orchard', 'con_819', ['INV-2201'], 'INV-2201: $5,760.00 is due.'), 'P5')


def test_p5_an_approved_draft_is_allowed(db):
    decision = check_send_message(
        db, 'cus_orchard', contact_id='con_819', channel=Channel.EMAIL, invoice_ids=['INV-2201'],
        body='$5,760.00', approved=True,
    )
    assert_allowed(decision)


def test_p6_an_application_fits_the_payment_and_the_invoice(db):
    assert_allowed(apply(db, 'cus_pinecrest', 'pay_2001', 'INV-1301', '15000.00'))
    assert_denied(apply(db, 'cus_pinecrest', 'pay_2001', 'INV-1301', '15000.01'), 'P6')
    assert_denied(apply(db, 'cus_pinecrest', 'pay_2001', 'INV-1301', '0.00'), 'P6')
    assert_denied(apply(db, 'cus_delmar', 'pay_2002', 'INV-1305', '7000.00'), 'P6')  # balance 6,640.00


def test_p7_only_invoices_in_the_payers_family(db):
    assert_denied(apply(db, 'cus_pinecrest', 'pay_2001', 'INV-1302', '100.00'), 'P7')
    assert_allowed(apply(db, 'cus_delmar', 'pay_2002', 'INV-1303', '9780.00'))


def test_p8_no_remittance_and_two_matching_invoices_needs_approval(db):
    assert payment_candidates(db, 'pay_2004') == ('INV-1402', 'INV-1403')
    assert_held(apply(db, 'cus_quarry', 'pay_2004', 'INV-1402', '6300.00'), 'P8')
    assert_held(apply(db, 'cus_quarry', 'pay_2004', 'INV-1403', '6300.00'), 'P8')


def test_p8_one_matching_invoice_or_a_remittance_is_allowed(db):
    assert payment_candidates(db, 'pay_2001') == ()
    bigger = db.invoice('INV-1403').model_copy(update={'amount': Decimal('6400.00')})
    one_match = db.with_rows('invoices', {'INV-1403': bigger})
    assert payment_candidates(one_match, 'pay_2004') == ('INV-1402',)
    assert_allowed(apply(one_match, 'cus_quarry', 'pay_2004', 'INV-1402', '6300.00'))


def test_p9_a_credit_needs_an_open_dispute_and_fits_it(db):
    assert_allowed(credit(db, 'cus_saltmarsh', 'dsp_3001', '378.00'))
    assert_denied(credit(db, 'cus_saltmarsh', 'dsp_3001', '378.01'), 'P9')
    assert_denied(credit(db, 'cus_saltmarsh', 'dsp_3001', '0.00'), 'P9')
    assert_denied(credit(db, 'cus_garnet', 'dsp_3003', '100.00'), 'P9')  # resolved


def test_p9_a_credit_never_exceeds_the_invoice_balance(db):
    paid_down = Application(application_id='app_9999', payment_id='pay_2001', invoice_id='INV-1502',
                            amount=Decimal('9350.00'), applied_at=db.today, idempotency_key='pay_2001:INV-1502')
    assert_denied(credit(db.with_rows('applications', {'app_9999': paid_down}), 'cus_saltmarsh', 'dsp_3001', '378.00'),
                  'P9')


def test_p10_a_credit_above_the_limit_needs_approval(db):
    assert db.tenant.credit_auto_approve_limit == Decimal('500.00')
    assert_held(credit(db, 'cus_fennick', 'dsp_3002', '3120.00'), 'P10')
    assert_held(credit(db, 'cus_fennick', 'dsp_3002', '500.01'), 'P10')
    assert_allowed(credit(db, 'cus_fennick', 'dsp_3002', '500.00'))


def test_p11_nothing_outside_the_account_and_its_children(db):
    assert_allowed(check_scope(db, 'cus_delmar', 'cus_delmar_west', 'invoice INV-1303'))
    assert_denied(check_scope(db, 'cus_delmar_west', 'cus_delmar', 'invoice INV-1302'), 'P11')
    assert_denied(send(db, 'cus_corvid', 'con_801', ['INV-1001'], '$12,400.00'), 'P11')
    assert_denied(send(db, 'cus_brightwell', 'con_801', ['INV-1201'], '$3,975.50'), 'P11')
    assert_denied(apply(db, 'cus_brightwell', 'pay_2001', 'INV-1301', '15000.00'), 'P11')
    assert_denied(credit(db, 'cus_brightwell', 'dsp_3001', '378.00'), 'P11')
    assert_denied(check_open_dispute(db, 'cus_brightwell', invoice_id='INV-1501'), 'P11')
    assert_denied(check_reject_dispute(db, 'cus_brightwell', dispute_id='dsp_3005'), 'P11')
    assert_denied(check_log_promise(db, 'cus_brightwell', invoice_id='INV-1101'), 'P11')
    assert_denied(check_pause_collections(db, 'cus_brightwell', invoice_id='INV-1101'), 'P11')
    assert_denied(check_execute_approval(db, 'cus_brightwell', approval_id='apr_8000'), 'P11')
    assert_allowed(check_open_dispute(db, 'cus_ridgeway', invoice_id='INV-1501'))
    assert_allowed(check_reject_dispute(db, 'cus_larkspur', dispute_id='dsp_3005'))
    assert_allowed(check_log_promise(db, 'cus_hollis', invoice_id='INV-1101'))
    assert_allowed(check_pause_collections(db, 'cus_hollis', invoice_id='INV-1101'))


def test_p12_no_reminder_while_a_promise_is_not_yet_due(db):
    assert_denied(send(db, 'cus_kestrel', 'con_815', ['INV-1801'], 'INV-1801: $5,400.00 is due.'), 'P12')
    due_today = db.promises['prm_8501'].model_copy(update={'promised_date': db.today})
    assert_denied(send(db.with_rows('promises', {'prm_8501': due_today}), 'cus_kestrel', 'con_815', ['INV-1801'],
                       '$5,400.00'), 'P12')
    lapsed = db.promises['prm_8501'].model_copy(update={'promised_date': db.today - timedelta(days=1)})
    assert_allowed(send(db.with_rows('promises', {'prm_8501': lapsed}), 'cus_kestrel', 'con_815', ['INV-1801'],
                        '$5,400.00'))


def test_p13_only_an_approved_approval_is_carried_out_once(db):
    assert_denied(check_execute_approval(db, 'cus_garnet', approval_id='apr_8000'), 'P13')  # already executed
    store = fresh_store(DB_PATH, DOCUMENTS)
    call_tool(store, 'cus_fennick', 'propose_credit', {'dispute_id': 'dsp_3002', 'amount': '3120.00', 'reason': 'r'})
    assert_denied(check_execute_approval(store.db, 'cus_fennick', approval_id='apr_8001'), 'P13')  # pending
    decided = {'approval_id': 'apr_8001', 'decided_by': 'ar_lead', 'note': None}
    approved = fresh_store(DB_PATH, DOCUMENTS)
    call_tool(approved, 'cus_fennick', 'propose_credit', {'dispute_id': 'dsp_3002', 'amount': '3120.00', 'reason': 'r'})
    call_env_function(approved, 'decide_approval', {**decided, 'decision': 'approved'})
    assert_allowed(check_execute_approval(approved.db, 'cus_fennick', approval_id='apr_8001'))
    approved_alone = store.db.approval('apr_8001').model_copy(update={'status': ApprovalStatus.APPROVED})
    unlinked = store.db.with_rows('approvals', {'apr_8001': approved_alone})  # credit still only proposed
    assert_denied(check_execute_approval(unlinked, 'cus_fennick', approval_id='apr_8001'), 'P13')
    call_env_function(store, 'decide_approval', {**decided, 'decision': 'rejected'})
    assert_denied(check_execute_approval(store.db, 'cus_fennick', approval_id='apr_8001'), 'P13')  # rejected
