"""Typed, immutable view of the AR database in `agents/ar/db/db.json`.

Every row and the database itself are frozen. A write builds a new `ArDb` with `with_rows`.
Money is a non-negative `Decimal` with at most two places, dumped back as a two-decimal string.
"""

import json
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PlainSerializer, model_validator

Money = Annotated[
    Decimal,
    Field(ge=0, decimal_places=2),
    PlainSerializer(lambda value: f'{value:.2f}', return_type=str, when_used='json'),
]


class InvoiceStatus(StrEnum):
    OPEN = 'open'
    PAID = 'paid'


class PaymentStatus(StrEnum):
    UNAPPLIED = 'unapplied'
    APPLIED = 'applied'


class CreditStatus(StrEnum):
    PROPOSED = 'proposed'
    APPROVED = 'approved'
    APPLIED = 'applied'
    REJECTED = 'rejected'


class DisputeStatus(StrEnum):
    OPEN = 'open'
    RESOLVED_VALID = 'resolved_valid'
    RESOLVED_INVALID = 'resolved_invalid'


class DisputeCategory(StrEnum):
    TRADE_PROMOTION = 'trade_promotion'
    PRICING_VARIANCE = 'pricing_variance'
    FREIGHT = 'freight'
    SHORTAGE = 'shortage'
    DAMAGED_GOODS = 'damaged_goods'
    QUALITY = 'quality'
    DELIVERY = 'delivery'
    DUPLICATE_CHARGE = 'duplicate_charge'


class PromiseStatus(StrEnum):
    OPEN = 'open'
    KEPT = 'kept'
    BROKEN = 'broken'


class ApprovalStatus(StrEnum):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class MessageDirection(StrEnum):
    INBOUND = 'inbound'
    OUTBOUND = 'outbound'


class Channel(StrEnum):
    EMAIL = 'email'
    SMS = 'sms'


class AutonomyLevel(StrEnum):
    AUTONOMOUS = 'autonomous'
    REVIEW = 'review'
    OFF = 'off'


class UnknownIdError(LookupError):
    """An id that is not in its table. Subclasses name the table."""

    kind: ClassVar[str] = 'row'

    def __init__(self, row_id: str) -> None:
        super().__init__(f'No {self.kind} with id {row_id!r}.')
        self.row_id = row_id


class UnknownTableError(UnknownIdError):
    kind = 'table'


class UnknownInvoiceError(UnknownIdError):
    kind = 'invoice'


class UnknownPaymentError(UnknownIdError):
    kind = 'payment'


class UnknownCustomerError(UnknownIdError):
    kind = 'customer'


class UnknownContactError(UnknownIdError):
    kind = 'contact'


class UnknownDisputeError(UnknownIdError):
    kind = 'dispute'


class UnknownCreditError(UnknownIdError):
    kind = 'credit'


class UnknownApprovalError(UnknownIdError):
    kind = 'approval'


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class Row(_Frozen):
    """A frozen table row. Revalidated whenever it is put into an `ArDb`, so `model_copy` edits are checked."""

    model_config = ConfigDict(revalidate_instances='always')
    id_field: ClassVar[str]

    @property
    def row_id(self) -> str:
        return getattr(self, self.id_field)


class Tenant(Row):
    id_field = 'tenant_id'
    tenant_id: str
    name: str
    currency: str
    as_of_date: date
    credit_auto_approve_limit: Money
    min_days_between_reminders: int
    default_payment_terms_days: int


class Customer(Row):
    id_field = 'customer_id'
    customer_id: str
    tenant_id: str
    name: str
    parent_id: str | None
    currency: str
    segment: str
    payment_terms_days: int
    autonomy: Mapping[Channel, AutonomyLevel]


class Contact(Row):
    id_field = 'contact_id'
    contact_id: str
    customer_id: str
    name: str
    role: str
    email: str
    phone: str
    preferred_channel: Channel
    do_not_contact: bool
    note: str | None


class InvoiceLine(_Frozen):
    sku: str
    description: str
    quantity: int
    unit_price: Money


class Invoice(Row):
    id_field = 'invoice_id'
    invoice_id: str
    customer_id: str
    po_number: str
    issue_date: date
    due_date: date
    amount: Money
    status: InvoiceStatus
    collections_paused: bool
    lines: tuple[InvoiceLine, ...]


class Payment(Row):
    id_field = 'payment_id'
    payment_id: str
    customer_id: str
    received_date: date
    amount: Money
    method: str
    payer_reference: str
    status: PaymentStatus


class RemittanceLine(_Frozen):
    invoice_ref: str
    amount: Money
    deduction_amount: Money | None
    deduction_code: str | None


class Remittance(Row):
    id_field = 'remittance_id'
    remittance_id: str
    payment_id: str
    source: str
    lines: tuple[RemittanceLine, ...]
    raw_text: str


class Application(Row):
    id_field = 'application_id'
    application_id: str
    payment_id: str
    invoice_id: str
    amount: Money
    applied_at: date
    idempotency_key: str


class Credit(Row):
    id_field = 'credit_id'
    credit_id: str
    invoice_id: str
    dispute_id: str
    amount: Money
    reason: str
    status: CreditStatus
    created_at: date
    applied_at: date | None
    approval_id: str | None


class Dispute(Row):
    id_field = 'dispute_id'
    dispute_id: str
    invoice_id: str
    customer_id: str
    category: DisputeCategory
    amount: Money
    status: DisputeStatus
    opened_at: date
    claim: str
    evidence_document_ids: tuple[str, ...]
    resolution: str | None


class Promise(Row):
    id_field = 'promise_id'
    promise_id: str
    invoice_id: str
    promised_date: date
    amount: Money
    status: PromiseStatus
    source_message_id: str | None


class Message(Row):
    id_field = 'message_id'
    message_id: str
    customer_id: str
    contact_id: str
    direction: MessageDirection
    channel: Channel
    sent_at: date
    invoice_ids: tuple[str, ...]
    amount_requested: Money | None
    body: str


class Approval(Row):
    id_field = 'approval_id'
    approval_id: str
    customer_id: str
    action: str
    payload: Mapping[str, JsonValue]  # shape depends on `action`; built by the tool that writes it
    reason: str
    status: ApprovalStatus
    decided_by: str | None
    decided_at: date | None
    note: str | None
    executed_at: date | None


# What an approval's payload holds, per action: built by the tool that holds the write, read back to carry it out.

class MessageDraft(_Frozen):
    """send_message held under P5."""

    contact_id: str
    channel: Channel
    invoice_ids: tuple[str, ...]
    amount: Money
    body: str


class CreditApproval(_Frozen):
    """propose_credit held under P10; the credit row exists with status proposed."""

    credit_id: str
    dispute_id: str
    invoice_id: str
    amount: Money


class PaymentApproval(_Frozen):
    """apply_payment held under P8 (the reviewer picks one of the candidates) or P15 (no candidate matches)."""

    payment_id: str
    amount: Money
    candidate_invoice_ids: tuple[str, ...]


class CustomerNote(Row):
    id_field = 'note_id'
    note_id: str
    customer_id: str
    kind: str
    text: str
    source: str
    created_at: date


class ActionLogEntry(Row):
    id_field = 'action_id'
    action_id: str
    at: date
    actor: str
    action: str
    target_id: str
    reason: str


class ArDb(_Frozen):
    """The whole database: one `{id: row}` mapping per table, named as in db.json."""

    tenants: Mapping[str, Tenant]
    customers: Mapping[str, Customer]
    contacts: Mapping[str, Contact]
    invoices: Mapping[str, Invoice]
    payments: Mapping[str, Payment]
    remittances: Mapping[str, Remittance]
    applications: Mapping[str, Application]
    credits: Mapping[str, Credit]
    disputes: Mapping[str, Dispute]
    promises: Mapping[str, Promise]
    messages: Mapping[str, Message]
    approvals: Mapping[str, Approval]
    customer_notes: Mapping[str, CustomerNote]
    action_log: Mapping[str, ActionLogEntry]

    @model_validator(mode='after')
    def _check_keys_and_tenant(self) -> Self:
        for name in type(self).model_fields:
            for key, row in self.table(name).items():
                if key != row.row_id:
                    raise ValueError(f'{name}: row stored under {key!r} has id {row.row_id!r}.')
        if len(self.tenants) != 1:
            raise ValueError(f'Expected exactly one tenant, found {len(self.tenants)}.')
        return self

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Read db.json, unwrapping each `{"data": {...}, "notes": "..."}` table."""
        raw = json.loads(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(f'{path} must hold a JSON object of tables.')
        return cls.model_validate({name: _unwrap(name, table) for name, table in raw.items()})

    def dump(self) -> dict[str, dict[str, Any]]:
        """Plain JSON-able rows, `{table: {id: row}}`, in db.json's format without the notes."""
        return self.model_dump(mode='json')

    def table(self, name: str) -> Mapping[str, Row]:
        if name not in type(self).model_fields:
            raise UnknownTableError(name)
        return getattr(self, name)

    def with_rows(self, table_name: str, rows: Mapping[str, Row]) -> Self:
        """A new database with `rows` added to or replacing rows in one table. `self` is unchanged."""
        tables = {name: self.table(name) for name in type(self).model_fields}
        return self.model_validate({**tables, table_name: {**self.table(table_name), **rows}})

    @property
    def tenant(self) -> Tenant:
        return next(iter(self.tenants.values()))

    @property
    def today(self) -> date:
        return self.tenant.as_of_date

    def invoice(self, invoice_id: str) -> Invoice:
        return _lookup(self.invoices, invoice_id, UnknownInvoiceError)

    def payment(self, payment_id: str) -> Payment:
        return _lookup(self.payments, payment_id, UnknownPaymentError)

    def customer(self, customer_id: str) -> Customer:
        return _lookup(self.customers, customer_id, UnknownCustomerError)

    def contact(self, contact_id: str) -> Contact:
        return _lookup(self.contacts, contact_id, UnknownContactError)

    def dispute(self, dispute_id: str) -> Dispute:
        return _lookup(self.disputes, dispute_id, UnknownDisputeError)

    def credit(self, credit_id: str) -> Credit:
        return _lookup(self.credits, credit_id, UnknownCreditError)

    def approval(self, approval_id: str) -> Approval:
        return _lookup(self.approvals, approval_id, UnknownApprovalError)


def _unwrap(name: str, table: Any) -> Any:
    if not (isinstance(table, dict) and isinstance(table.get('data'), dict) and set(table) <= {'data', 'notes'}):
        raise ValueError(f'Table {name!r} must look like {{"data": {{id: row}}, "notes": "..."}}.')
    return table['data']


def _lookup[R: Row](table: Mapping[str, R], row_id: str, error: type[UnknownIdError]) -> R:
    if row_id not in table:
        raise error(row_id)
    return table[row_id]


# The tables the tools add rows to: each one's id prefix and the number its first row takes.
ID_SEQUENCES: Mapping[str, tuple[str, int]] = MappingProxyType({
    'action_log': ('act_', 7001), 'applications': ('app_', 5000), 'approvals': ('apr_', 8000),
    'credits': ('crd_', 4001), 'disputes': ('dsp_', 3001), 'messages': ('msg_', 6001), 'promises': ('prm_', 8501),
})


def next_id(db: ArDb, table_name: str) -> str:
    """The table's id prefix plus its largest number plus one, e.g. `apr_8000` -> `apr_8001`; an empty table starts
    at its first number. A table with no id sequence raises `UnknownTableError`."""
    if table_name not in ID_SEQUENCES:
        raise UnknownTableError(table_name)
    prefix, first = ID_SEQUENCES[table_name]
    numbers = [int(found[1]) for row_id in db.table(table_name)
               if (found := re.fullmatch(rf'{re.escape(prefix)}(\d+)', row_id))]
    return f'{prefix}{max(numbers, default=first - 1) + 1}'
