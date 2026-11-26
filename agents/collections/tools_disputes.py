"""Dispute write tools: open_dispute, propose_credit, reject_dispute.

Plain functions of `(store, customer_id, ...)`. Each checks policy, swaps in a new database and
logs once; a denied write raises `PolicyDenied` and leaves the store as it was.
"""

from decimal import Decimal

from agents.collections.data_model import ArDb, Credit, CreditApproval, CreditStatus, Dispute, DisputeCategory, DisputeStatus, next_id
from agents.collections.errors import InvalidArgumentError
from agents.collections.ledger import balance
from agents.collections.policy import (
    Outcome,
    check_invoice_scope,
    check_propose_credit,
    check_reject_dispute,
)
from agents.collections.store import Store
from agents.collections.tool_support import (
    WriteResult,
    commit,
    hold,
    mark_paid_if_settled,
    parse_choice,
    parse_money,
    parse_text,
    require,
    require_amount,
    resume_if_undisputed,
    unchanged,
)


def open_dispute(store: Store, customer_id: str, invoice_id: str, category: str, amount: str | Decimal,
                 claim: str) -> WriteResult:
    """Record a contested amount on an invoice as an open dispute. Collections on the invoice pause."""
    db = store.db
    invoice_id = parse_text(invoice_id, 'invoice_id')
    kind = parse_choice(DisputeCategory, category, 'category')
    contested, claim = parse_money(amount, 'amount'), parse_text(claim, 'claim')
    require(check_invoice_scope(db, customer_id, invoice_id=invoice_id))
    invoice = db.invoice(invoice_id)
    require_amount(contested, balance(db, invoice_id), 'amount', f'the balance of {invoice_id}')
    dispute = Dispute(
        dispute_id=next_id(db, 'disputes'), invoice_id=invoice_id, customer_id=invoice.customer_id, category=kind,
        amount=contested, status=DisputeStatus.OPEN, opened_at=db.today, claim=claim, evidence_document_ids=(),
        resolution=None,
    )
    db = db.with_rows('disputes', {dispute.dispute_id: dispute})
    if not invoice.collections_paused:
        db = db.with_rows('invoices', {invoice_id: invoice.model_copy(update={'collections_paused': True})})
    return commit(store, db, 'open_dispute', dispute, f'Opened {kind} dispute for {contested} on {invoice_id}.',
                  f'Opened {dispute.dispute_id}: {kind}, {contested} on {invoice_id}. Collections on it are paused.')


def propose_credit(store: Store, customer_id: str, dispute_id: str, amount: str | Decimal,
                   reason: str) -> WriteResult:
    """Credit an open dispute. At or under the auto-approve limit the credit is applied and the dispute
    resolved; above it the credit is proposed and held for a person (P10)."""
    db = store.db
    dispute_id, credited, reason = parse_text(dispute_id, 'dispute_id'), parse_money(amount, 'amount'), parse_text(
        reason, 'reason')
    decision = check_propose_credit(db, customer_id, dispute_id=dispute_id, amount=credited)
    require(decision)
    dispute = db.dispute(dispute_id)
    credit = Credit(
        credit_id=next_id(db, 'credits'), invoice_id=dispute.invoice_id, dispute_id=dispute_id, amount=credited,
        reason=reason, status=CreditStatus.PROPOSED, created_at=db.today, applied_at=None, approval_id=None,
    )
    if decision.outcome is Outcome.NEEDS_APPROVAL:
        linked = credit.model_copy(update={'approval_id': next_id(db, 'approvals')})
        payload = CreditApproval(credit_id=credit.credit_id, dispute_id=dispute_id, invoice_id=dispute.invoice_id,
                                 amount=credited)
        return hold(store, db.with_rows('credits', {credit.credit_id: linked}), customer_id, 'propose_credit',
                    payload.model_dump(mode='json'), decision.rule, decision.reason, target_id=credit.credit_id)
    db = apply_credit(db.with_rows('credits', {credit.credit_id: credit}), credit)
    return commit(store, db, 'propose_credit', db.credit(credit.credit_id), reason,
                  f'Applied credit {credit.credit_id} of {credited} to {dispute.invoice_id}; {dispute_id} is resolved '
                  'and collections resume unless another dispute is open.')


def apply_credit(db: ArDb, credit: Credit) -> ArDb:
    """Apply a credit: the credit is applied, its dispute resolved valid, the invoice unpaused or paid as due."""
    applied = credit.model_copy(update={'status': CreditStatus.APPLIED, 'applied_at': db.today})
    dispute = db.dispute(credit.dispute_id)
    resolved = dispute.model_copy(update={
        'status': DisputeStatus.RESOLVED_VALID,
        'resolution': f'Credit {credit.credit_id} of {credit.amount} applied: {credit.reason}',
    })
    db = db.with_rows('credits', {credit.credit_id: applied}).with_rows('disputes', {dispute.dispute_id: resolved})
    return mark_paid_if_settled(resume_if_undisputed(db, credit.invoice_id), credit.invoice_id)


def reject_dispute(store: Store, customer_id: str, dispute_id: str, reason: str) -> WriteResult:
    """Resolve an open dispute as invalid, citing the evidence. Collections resume unless another dispute is open."""
    db = store.db
    dispute_id, reason = parse_text(dispute_id, 'dispute_id'), parse_text(reason, 'reason')
    require(check_reject_dispute(db, customer_id, dispute_id=dispute_id))
    dispute = db.dispute(dispute_id)
    if dispute.status is DisputeStatus.RESOLVED_INVALID:
        return unchanged(dispute, f'{dispute_id} is already rejected; nothing to do.')
    if dispute.status is DisputeStatus.RESOLVED_VALID:
        raise InvalidArgumentError(f"{dispute_id} was already resolved in the customer's favour; it cannot be rejected.")
    rejected = dispute.model_copy(update={'status': DisputeStatus.RESOLVED_INVALID, 'resolution': reason})
    db = resume_if_undisputed(db.with_rows('disputes', {dispute_id: rejected}), dispute.invoice_id)
    return commit(store, db, 'reject_dispute', rejected, reason,
                  f'Rejected {dispute_id}; collections on {dispute.invoice_id} resume unless another dispute is open.')
