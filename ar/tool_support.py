"""What every tool shares: argument parsing at the boundary, the write result, and committing a write.

A write builds a new `ArDb`, appends one action log row and swaps it into the store in one step,
so a refused write never leaves anything behind.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from ar.data_model import (
    ActionLogEntry,
    Approval,
    ApprovalStatus,
    ArDb,
    InvoiceStatus,
    Row,
    next_id,
)
from ar.errors import InvalidArgumentError, PolicyDenied
from ar.ledger import balance
from ar.policy import Decision, Outcome, has_open_dispute
from ar.store import Store

COWORKER = 'coworker'
_CENT = Decimal('0.01')
_MAX_MONEY = Decimal('1e12')
_MONEY = re.compile(r'\d{1,12}(\.\d{1,2})?')
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
_PAYLOAD = TypeAdapter(dict[str, JsonValue])


# Arguments.

def parse_money(value: object, name: str) -> Decimal:
    """A two-decimal string such as "1234.50" (or a `Decimal`), as a non-negative `Decimal` with two places."""
    if isinstance(value, str) and _MONEY.fullmatch(value):
        value = Decimal(value)
    if isinstance(value, Decimal) and value.is_finite() and 0 <= value < _MAX_MONEY and value.as_tuple().exponent >= -2:
        return value.quantize(_CENT)
    raise InvalidArgumentError(f'{name} must be an amount with at most two decimals and no commas, like "1234.50"; '
                               f'got {value!r}.')


def parse_date(value: object, name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and _DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise InvalidArgumentError(f'{name} {value!r} is not a real date.') from error
    raise InvalidArgumentError(f'{name} must be a date written YYYY-MM-DD; got {value!r}.')


def parse_text(value: object, name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise InvalidArgumentError(f'{name} must be a non-empty string; got {value!r}.')


def parse_ids(value: object, name: str) -> tuple[str, ...]:
    """A non-empty list of ids, duplicates dropped, order kept."""
    if isinstance(value, list | tuple) and value and all(isinstance(i, str) and i.strip() for i in value):
        return tuple(dict.fromkeys(value))
    raise InvalidArgumentError(f'{name} must be a non-empty list of ids, like ["INV-0000"]; got {value!r}.')


def parse_choice[E: StrEnum](enum: type[E], value: object, name: str) -> E:
    try:
        return enum(value)
    except (ValueError, TypeError) as error:
        raise InvalidArgumentError(f'{name} must be one of {", ".join(enum)}; got {value!r}.') from error


def parse_payload(value: object, name: str) -> dict[str, JsonValue]:
    try:
        return _PAYLOAD.validate_python(value)
    except ValidationError as error:
        raise InvalidArgumentError(f'{name} must be a JSON object; got {value!r}.') from error


def require_amount(amount: Decimal, limit: Decimal, name: str, what: str) -> None:
    if not 0 < amount <= limit:
        raise InvalidArgumentError(f'{name} must be positive and at most {what}, {limit}; got {amount}.')


def require(decision: Decision) -> None:
    """Raise `PolicyDenied` for a deny; allow and needs-approval pass through to the tool."""
    if decision.outcome is Outcome.DENY:
        raise PolicyDenied(str(decision.rule), decision.reason)


# Results.

class WriteResult(BaseModel):
    """What a write tool returns.

    `done`: the write was made. `held_for_approval`: only a pending approval was written; the write waits
    for a person. `unchanged`: the write was already in place, so nothing was written or logged.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal['done', 'held_for_approval', 'unchanged']
    message: str
    target_id: str
    rule: str | None = None
    approval_id: str | None = None
    row: dict[str, Any]


def log_entry(db: ArDb, action: str, target_id: str, reason: str, actor: str = COWORKER) -> ActionLogEntry:
    return ActionLogEntry(action_id=next_id(db, 'action_log'), at=db.today, actor=actor, action=action,
                          target_id=target_id, reason=reason)


def commit(store: Store, db: ArDb, action: str, row: Row, reason: str, message: str,
           actor: str = COWORKER) -> WriteResult:
    """Append one action log row to `db`, swap it in, and report `row` as the write's main row."""
    entry = log_entry(db, action, row.row_id, reason, actor)
    store.swap(db.with_rows('action_log', {entry.action_id: entry}))
    return WriteResult(status='done', message=message, target_id=row.row_id, row=row.model_dump(mode='json'))


def unchanged(row: Row, message: str) -> WriteResult:
    return WriteResult(status='unchanged', message=message, target_id=row.row_id, row=row.model_dump(mode='json'))


def hold(store: Store, db: ArDb, customer_id: str, action: str, payload: Mapping[str, JsonValue], rule: str | None,
         reason: str, target_id: str | None = None) -> WriteResult:
    """Write one pending approval (and its log row) instead of the write itself."""
    approval = Approval(
        approval_id=next_id(db, 'approvals'), customer_id=customer_id, action=action, payload=payload, reason=reason,
        status=ApprovalStatus.PENDING, decided_by=None, decided_at=None, note=None, executed_at=None,
    )
    db = db.with_rows('approvals', {approval.approval_id: approval})
    target = target_id or approval.approval_id
    entry = log_entry(db, action, target, f'Held for approval {approval.approval_id}: {reason}')
    store.swap(db.with_rows('action_log', {entry.action_id: entry}))
    return held(approval, rule, target)


def held(approval: Approval, rule: str | None, target_id: str | None = None, repeat: bool = False) -> WriteResult:
    lead = 'Already held for a person' if repeat else 'Held for a person, not done'
    return WriteResult(
        status='unchanged' if repeat else 'held_for_approval',
        message=f'{lead}: {approval.reason} Pending approval {approval.approval_id}'
                f'{f" ({rule})" if rule else ""} records it. Nothing else was written; stop and let the reviewer decide.',
        target_id=target_id or approval.approval_id, rule=rule, approval_id=approval.approval_id,
        row=approval.model_dump(mode='json'),
    )


# Invoice state that follows from the ledger.

def mark_paid_if_settled(db: ArDb, invoice_id: str) -> ArDb:
    invoice = db.invoice(invoice_id)
    if invoice.status is InvoiceStatus.PAID or balance(db, invoice_id) != 0:
        return db
    return db.with_rows('invoices', {invoice_id: invoice.model_copy(update={'status': InvoiceStatus.PAID})})


def resume_if_undisputed(db: ArDb, invoice_id: str) -> ArDb:
    """Unpause collections once the invoice has no open dispute left."""
    invoice = db.invoice(invoice_id)
    if not invoice.collections_paused or has_open_dispute(db, invoice_id):
        return db
    return db.with_rows('invoices', {invoice_id: invoice.model_copy(update={'collections_paused': False})})
