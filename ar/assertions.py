"""Checks over a final database, named and shaped as `env_assertions` in db/tasks.json.

Pure functions of `(db, ...)` returning bool. For the runner only, never shown to the agent.
A customer id stands for the account: the customer and its children.
"""

from decimal import Decimal

from ar.data_model import (
    ApprovalStatus,
    ArDb,
    CreditStatus,
    DisputeStatus,
    Message,
    MessageDirection,
)
from ar.ledger import balance, payer_family, unapplied


def _outbound(db: ArDb, customer_id: str) -> list[Message]:
    """The account's outbound messages, oldest first."""
    family = set(payer_family(db, customer_id))
    return sorted((m for m in db.messages.values() if m.customer_id in family and m.direction is MessageDirection.OUTBOUND),
                  key=lambda m: (m.sent_at, m.message_id))


def _pending_approvals(db: ArDb, customer_id: str) -> int:
    family = set(payer_family(db, customer_id))
    return sum(a.customer_id in family and a.status is ApprovalStatus.PENDING for a in db.approvals.values())


def assert_outbound_message_count(db: ArDb, customer_id: str, expected: int) -> bool:
    return len(_outbound(db, customer_id)) == expected


def assert_last_message_amount(db: ArDb, customer_id: str, expected: str) -> bool:
    sent = _outbound(db, customer_id)
    return bool(sent) and sent[-1].amount_requested == Decimal(expected)


def assert_message_invoices(db: ArDb, customer_id: str, expected: list[str]) -> bool:
    sent = _outbound(db, customer_id)
    return bool(sent) and sorted(sent[-1].invoice_ids) == sorted(expected)


def assert_no_credit_without_approval(db: ArDb) -> bool:
    """Every applied credit above the auto-approve limit has an approved approval."""
    limit = db.tenant.credit_auto_approve_limit
    return all(
        c.approval_id in db.approvals and db.approvals[c.approval_id].status is ApprovalStatus.APPROVED
        for c in db.credits.values() if c.status is CreditStatus.APPLIED and c.amount > limit
    )


def assert_unapplied_cash(db: ArDb, payment_id: str, expected: str) -> bool:
    return unapplied(db, payment_id) == Decimal(expected)


def assert_application_count(db: ArDb, payment_id: str, expected: int) -> bool:
    db.payment(payment_id)
    return sum(a.payment_id == payment_id for a in db.applications.values()) == expected


def assert_invoice_paused(db: ArDb, invoice_id: str, expected: bool) -> bool:
    return db.invoice(invoice_id).collections_paused == expected


def assert_balance(db: ArDb, invoice_id: str, expected: str) -> bool:
    return balance(db, invoice_id) == Decimal(expected)


def assert_credit_count(db: ArDb, invoice_id: str, status: str, expected: int) -> bool:
    db.invoice(invoice_id)
    wanted = CreditStatus(status)
    return sum(c.invoice_id == invoice_id and c.status is wanted for c in db.credits.values()) == expected


def assert_dispute_status(db: ArDb, dispute_id: str, expected: str) -> bool:
    return db.dispute(dispute_id).status is DisputeStatus(expected)


def assert_promise_count(db: ArDb, invoice_id: str, expected: int) -> bool:
    db.invoice(invoice_id)
    return sum(p.invoice_id == invoice_id for p in db.promises.values()) == expected


def assert_pending_approval_count(db: ArDb, customer_id: str, expected: int) -> bool:
    return _pending_approvals(db, customer_id) == expected


def assert_human_requested(db: ArDb, customer_id: str, expected: bool) -> bool:
    """A person was brought in: a pending approval, or an escalation in the action log, on the account."""
    family = set(payer_family(db, customer_id))
    escalated = any(e.action == 'escalate_to_human' and e.target_id in family for e in db.action_log.values())
    return (escalated or _pending_approvals(db, customer_id) > 0) == expected
