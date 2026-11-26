"""The data model loads agents/collections/db/db.json, round-trips it, and refuses bad rows."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.collections.data_model import (
    CollectionsDb,
    AutonomyLevel,
    Channel,
    CreditStatus,
    Dispute,
    DisputeCategory,
    Invoice,
    InvoiceStatus,
    UnknownApprovalError,
    UnknownContactError,
    UnknownCreditError,
    UnknownCustomerError,
    UnknownDisputeError,
    UnknownIdError,
    UnknownInvoiceError,
    UnknownPaymentError,
    UnknownTableError,
    next_id,
)
from agents.collections.evals.tasks import DB_PATH


@pytest.fixture(scope='module')
def raw() -> dict:
    return json.loads(DB_PATH.read_text())


def test_loads_every_table_with_typed_rows(db, raw):
    assert set(db.dump()) == set(raw)
    assert len(db.customers) == 18 and len(db.invoices) == 26
    invoice = db.invoice('INV-1601')
    assert invoice.amount == Decimal('10000.00')
    assert invoice.due_date == date(2026, 11, 2)
    assert invoice.status is InvoiceStatus.OPEN
    assert db.customer('cus_orchard').autonomy[Channel.EMAIL] is AutonomyLevel.REVIEW
    assert db.dispute('dsp_3001').category is DisputeCategory.SHORTAGE
    assert db.credit('crd_4001').status is CreditStatus.APPLIED


def test_dump_round_trips_db_json_exactly(db, raw):
    assert db.dump() == {name: table['data'] for name, table in raw.items()}


def test_tenant_and_today(db):
    assert db.tenant.tenant_id == 'tn_harborline'
    assert db.today == date(2026, 11, 16)
    assert db.tenant.credit_auto_approve_limit == Decimal('500.00')


def test_lookups_return_rows(db):
    assert db.payment('pay_2002').amount == Decimal('27480.00')
    assert db.contact('con_803').do_not_contact is True
    assert db.approval('apr_8000').payload['credit_id'] == 'crd_4001'


@pytest.mark.parametrize(('lookup', 'error'), [
    ('invoice', UnknownInvoiceError),
    ('payment', UnknownPaymentError),
    ('customer', UnknownCustomerError),
    ('contact', UnknownContactError),
    ('dispute', UnknownDisputeError),
    ('credit', UnknownCreditError),
    ('approval', UnknownApprovalError),
])
def test_unknown_ids_raise_named_lookup_errors(db, lookup, error):
    with pytest.raises(error, match="'nope'") as caught:
        getattr(db, lookup)('nope')
    assert isinstance(caught.value, UnknownIdError) and isinstance(caught.value, LookupError)
    assert not isinstance(caught.value, KeyError)


def test_next_id_continues_each_tables_numbering(db):
    assert [next_id(db, table) for table in
            ('approvals', 'credits', 'disputes', 'messages', 'promises', 'applications')] == [
        'apr_8001', 'crd_4002', 'dsp_3006', 'msg_6011', 'prm_8502', 'app_5002']
    assert next_id(db, 'action_log') == 'act_7014'


def test_next_id_starts_an_empty_table_at_its_first_number(db):
    tables = {name: db.table(name) for name in CollectionsDb.model_fields}
    empty = CollectionsDb.model_validate({**tables, 'approvals': {}, 'credits': {}})
    assert (next_id(empty, 'approvals'), next_id(empty, 'credits')) == ('apr_8000', 'crd_4001')


def test_next_id_refuses_unnumbered_ids_and_unknown_tables(db):
    with pytest.raises(UnknownTableError, match='customers'):  # no tool adds customers, so it has no sequence
        next_id(db, 'customers')
    with pytest.raises(UnknownTableError, match='nope'):
        next_id(db, 'nope')


def test_with_rows_returns_new_db_and_leaves_original_alone(db, raw):
    paid = db.invoice('INV-1001').model_copy(update={'status': InvoiceStatus.PAID})
    updated = db.with_rows('invoices', {'INV-1001': paid})
    assert updated is not db and updated != db
    assert updated.invoice('INV-1001').status is InvoiceStatus.PAID
    assert db.invoice('INV-1001').status is InvoiceStatus.OPEN
    assert db.dump() == {name: table['data'] for name, table in raw.items()}


def test_with_rows_adds_a_row_under_its_own_id(db):
    new_id = next_id(db, 'disputes')
    dispute = db.dispute('dsp_3001').model_copy(update={'dispute_id': new_id})
    updated = db.with_rows('disputes', {new_id: dispute})
    assert updated.dispute(new_id) == dispute
    assert next_id(updated, 'disputes') == 'dsp_3007'
    with pytest.raises(UnknownDisputeError):
        db.dispute(new_id)


def test_with_rows_revalidates_what_it_is_given(db):
    invoice = db.invoice('INV-1001')
    with pytest.raises(ValidationError, match='INV-9999'):
        db.with_rows('invoices', {'INV-9999': invoice})
    with pytest.raises(ValidationError):
        db.with_rows('invoices', {'INV-1001': invoice.model_copy(update={'amount': Decimal('-1.00')})})
    with pytest.raises(ValidationError):
        db.with_rows('invoices', {'INV-1001': db.payment('pay_2001')})
    with pytest.raises(UnknownTableError):
        db.with_rows('nope', {})


def test_rows_and_db_are_frozen(db):
    with pytest.raises(ValidationError):
        db.invoice('INV-1001').amount = Decimal('1.00')
    with pytest.raises(ValidationError):
        db.invoices = {}


def _dispute(**changes) -> dict:
    row = {
        'dispute_id': 'dsp_1', 'invoice_id': 'INV-1', 'customer_id': 'cus_1', 'category': 'freight',
        'amount': '10.00', 'status': 'open', 'opened_at': '2026-11-16', 'claim': 'late',
        'evidence_document_ids': [], 'resolution': None,
    }
    return {**row, **changes}


def test_valid_row_parses_and_dumps_money_as_two_decimals():
    dispute = Dispute.model_validate(_dispute(amount='10'))
    assert dispute.model_dump(mode='json')['amount'] == '10.00'


@pytest.mark.parametrize('changes', [
    {'amount': '-1.00'},
    {'amount': '1.005'},
    {'amount': 'NaN'},
    {'category': 'weather'},
    {'status': 'closed'},
    {'opened_at': '16/11/2026'},
    {'surprise': 'field'},
])
def test_models_reject_bad_values(changes):
    with pytest.raises(ValidationError):
        Dispute.model_validate(_dispute(**changes))


def test_invoice_rejects_unknown_status():
    row = json.loads(DB_PATH.read_text())['invoices']['data']['INV-1001']
    with pytest.raises(ValidationError):
        Invoice.model_validate({**row, 'status': 'void'})


def _write(tmp_path: Path, content: dict) -> Path:
    path = tmp_path / 'db.json'
    path.write_text(json.dumps(content))
    return path


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        CollectionsDb.load(tmp_path / 'missing.json')


def test_load_rejects_unwrapped_table(tmp_path, raw):
    broken = {**raw, 'invoices': raw['invoices']['data']}
    with pytest.raises(ValueError, match="'invoices'"):
        CollectionsDb.load(_write(tmp_path, broken))


def test_load_rejects_non_object_file(tmp_path):
    path = tmp_path / 'db.json'
    path.write_text('[]')
    with pytest.raises(ValueError, match='object'):
        CollectionsDb.load(path)


def test_load_rejects_missing_or_extra_tables(tmp_path, raw):
    without = {name: table for name, table in raw.items() if name != 'credits'}
    with pytest.raises(ValidationError, match='credits'):
        CollectionsDb.load(_write(tmp_path, without))
    with pytest.raises(ValidationError, match='refunds'):
        CollectionsDb.load(_write(tmp_path, {**raw, 'refunds': {'data': {}, 'notes': ''}}))


def test_load_rejects_second_tenant(tmp_path, raw):
    tenant = raw['tenants']['data']['tn_harborline']
    tenants = {'data': {'tn_harborline': tenant, 'tn_other': {**tenant, 'tenant_id': 'tn_other'}}}
    with pytest.raises(ValidationError, match='one tenant'):
        CollectionsDb.load(_write(tmp_path, {**raw, 'tenants': tenants}))
