"""Ledger arithmetic over db/db.json, and the data rules in db/README.md checked through it."""
from decimal import Decimal
from pathlib import Path

import pytest

from ar.data_model import (
    ArDb,
    Credit,
    CreditStatus,
    DisputeStatus,
    InvoiceStatus,
    PaymentStatus,
    UnknownCustomerError,
    UnknownInvoiceError,
    UnknownPaymentError,
    next_id,
)
from ar.ledger import amount_due, balance, is_overdue, open_invoices, payer_family, unapplied

DB_PATH = Path(__file__).resolve().parent.parent / 'db' / 'db.json'


@pytest.fixture(scope='module')
def db() -> ArDb:
    return ArDb.load(DB_PATH)


# Rules the data obeys (db/README.md), checked through the ledger.

def test_invoice_is_paid_exactly_when_its_balance_is_zero(db):
    for invoice in db.invoices.values():
        assert (invoice.status is InvoiceStatus.PAID) == (balance(db, invoice.invoice_id) == 0), invoice.invoice_id


def test_collections_paused_exactly_when_an_open_dispute_exists(db):
    disputed = {d.invoice_id for d in db.disputes.values() if d.status is DisputeStatus.OPEN}
    for invoice in db.invoices.values():
        assert invoice.collections_paused == (invoice.invoice_id in disputed), invoice.invoice_id


def test_remittance_lines_add_up_to_their_payment(db):
    for remittance in db.remittances.values():
        total = sum((line.amount for line in remittance.lines), Decimal(0))
        assert total == db.payment(remittance.payment_id).amount, remittance.remittance_id


def test_payment_is_applied_exactly_when_nothing_is_unapplied(db):
    for payment in db.payments.values():
        assert (payment.status is PaymentStatus.APPLIED) == (unapplied(db, payment.payment_id) == 0), payment.payment_id


def test_invoice_amount_is_its_lines(db):
    for invoice in db.invoices.values():
        assert invoice.amount == sum(line.quantity * line.unit_price for line in invoice.lines), invoice.invoice_id


# Ledger functions on known rows.

def test_balance(db):
    assert balance(db, 'INV-1601') == Decimal('9400.00')
    assert balance(db, 'INV-1000') == 0
    assert balance(db, 'INV-1503') == Decimal('31200.00')


def test_only_applied_credits_reduce_a_balance(db):
    credit_id = next_id(db, 'credits')
    proposed = Credit(
        credit_id=credit_id, invoice_id='INV-1503', dispute_id='dsp_3002', amount=Decimal('3120.00'),
        reason='damage', status=CreditStatus.PROPOSED, created_at=db.today, applied_at=None, approval_id=None,
    )
    with_proposed = db.with_rows('credits', {credit_id: proposed})
    assert balance(with_proposed, 'INV-1503') == Decimal('31200.00')
    applied = proposed.model_copy(update={'status': CreditStatus.APPLIED, 'applied_at': db.today})
    assert balance(db.with_rows('credits', {credit_id: applied}), 'INV-1503') == Decimal('28080.00')


def test_amount_due(db):
    assert amount_due(db, ['INV-1701', 'INV-1702']) == Decimal('12050.00')
    assert amount_due(db, ['INV-1701', 'INV-1701']) == Decimal('7250.00')
    assert amount_due(db, []) == 0


def test_payer_family(db):
    assert payer_family(db, 'cus_delmar') == ('cus_delmar', 'cus_delmar_west')
    assert payer_family(db, 'cus_delmar_west') == ('cus_delmar_west',)
    assert payer_family(db, 'cus_brightwell') == ('cus_brightwell',)


def test_open_invoices_cover_the_family_sorted_by_due_date_then_id(db):
    ids = [invoice.invoice_id for invoice in open_invoices(db, 'cus_delmar')]
    assert ids == ['INV-1302', 'INV-1303', 'INV-1304', 'INV-1305']
    assert [invoice.invoice_id for invoice in open_invoices(db, 'cus_brightwell')] == ['INV-1001', 'INV-1003']


def test_is_overdue(db):
    assert is_overdue(db, 'INV-1001') is True
    assert is_overdue(db, 'INV-1003') is False
    due_today = db.invoice('INV-1001').model_copy(update={'due_date': db.today})
    assert is_overdue(db.with_rows('invoices', {'INV-1001': due_today}), 'INV-1001') is False


def test_unapplied(db):
    assert unapplied(db, 'pay_2002') == Decimal('27480.00')
    assert unapplied(db, 'pay_1900') == 0


def test_unknown_ids_raise_named_errors(db):
    with pytest.raises(UnknownInvoiceError):
        balance(db, 'INV-0000')
    with pytest.raises(UnknownInvoiceError):
        amount_due(db, ['INV-1701', 'INV-0000'])
    with pytest.raises(UnknownInvoiceError):
        is_overdue(db, 'INV-0000')
    with pytest.raises(UnknownPaymentError):
        unapplied(db, 'pay_0000')
    with pytest.raises(UnknownCustomerError):
        payer_family(db, 'cus_nobody')
    with pytest.raises(UnknownCustomerError):
        open_invoices(db, 'cus_nobody')
