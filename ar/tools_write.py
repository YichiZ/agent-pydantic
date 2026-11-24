"""Write tools for collections, cash application and approvals, plus the reviewer's `decide_approval`.

Plain functions of `(store, customer_id, ...)`. Each checks policy, swaps in a new database and
logs once; a denied write raises `PolicyDenied` and leaves the store as it was. A write a rule
holds for a person writes only a pending approval and says so.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from ar.data_model import (
    Application,
    Approval,
    ApprovalStatus,
    ArDb,
    Channel,
    Credit,
    CreditApproval,
    CreditStatus,
    Message,
    MessageDirection,
    MessageDraft,
    PaymentApproval,
    PaymentStatus,
    Promise,
    PromiseStatus,
    next_id,
)
from ar.errors import InvalidArgumentError
from ar.ledger import amount_due, balance, payer_family, unapplied
from ar.policy import (
    Outcome,
    check_apply_payment,
    check_execute_approval,
    check_log_promise,
    check_scope,
    check_send_message,
    payment_candidates,
)
from ar.store import Store
from ar.tool_support import (
    WriteResult,
    commit,
    held,
    hold,
    log_entry,
    mark_paid_if_settled,
    parse_choice,
    parse_date,
    parse_ids,
    parse_money,
    parse_payload,
    parse_text,
    require,
    require_amount,
    unchanged,
)
from ar.tools_disputes import apply_credit

# Writes a rule already routes to a person; request_approval refuses them so the model never builds their payload.
COVERED_BY_RULES = frozenset({'send_message', 'apply_payment', 'propose_credit'})
DECISIONS = {'approved': ApprovalStatus.APPROVED, 'rejected': ApprovalStatus.REJECTED}
CREDIT_AFTER = {ApprovalStatus.APPROVED: CreditStatus.APPROVED, ApprovalStatus.REJECTED: CreditStatus.REJECTED}
MAX_PROMISE_DAYS = 30  # a promise holds off reminders (P12), so it may not reach further ahead than this


def send_message(store: Store, customer_id: str, contact_id: str, channel: str, invoice_ids: Sequence[str],
                 body: str) -> WriteResult:
    """Send one outbound message. The tool stamps `amount_requested` from the ledger; on a channel set to
    review the draft is held for a person (P5)."""
    db = store.db
    contact_id, body = parse_text(contact_id, 'contact_id'), parse_text(body, 'body')
    # Sorted, so the same reminder is stored the same whatever order the invoices were named in.
    medium, ids = parse_choice(Channel, channel, 'channel'), tuple(sorted(parse_ids(invoice_ids, 'invoice_ids')))
    decision = check_send_message(db, customer_id, contact_id=contact_id, channel=medium, invoice_ids=ids, body=body)
    require(decision)
    draft = MessageDraft(contact_id=contact_id, channel=medium, invoice_ids=ids, amount=amount_due(db, ids), body=body)
    if decision.outcome is Outcome.NEEDS_APPROVAL:
        return hold(store, db, customer_id, 'send_message', draft.model_dump(mode='json'), decision.rule,
                    decision.reason)
    db, message = write_message(db, draft)
    return commit(store, db, 'send_message', message, f'Reminder for {", ".join(ids)}: {draft.amount} due.',
                  f'Sent {message.message_id} to {contact_id} by {medium}, asking for {draft.amount}.')


def write_message(db: ArDb, draft: MessageDraft) -> tuple[ArDb, Message]:
    """The outbound message row for a draft, with the amount due stamped from the ledger now."""
    message = Message(
        message_id=next_id(db, 'messages'), customer_id=db.contact(draft.contact_id).customer_id,
        contact_id=draft.contact_id, direction=MessageDirection.OUTBOUND, channel=draft.channel, sent_at=db.today,
        invoice_ids=draft.invoice_ids, amount_requested=amount_due(db, draft.invoice_ids), body=draft.body,
    )
    return db.with_rows('messages', {message.message_id: message}), message


def apply_payment(store: Store, customer_id: str, payment_id: str, invoice_id: str,
                  amount: str | Decimal) -> WriteResult:
    """Apply part or all of a payment to one invoice, as its remittance says (P15). A repeat returns the existing
    application; a payment with no remittance that matches several invoices (P8), or none (P15), is held for a
    person with every candidate."""
    db = store.db
    payment_id, invoice_id = parse_text(payment_id, 'payment_id'), parse_text(invoice_id, 'invoice_id')
    applied = parse_money(amount, 'amount')
    require(check_scope(db, customer_id, db.payment(payment_id).customer_id, f'Payment {payment_id}'))
    # ponytail: idempotent on (payment, invoice), so one payment cannot be applied to one invoice in two parts;
    # key on an application sequence, or allow a top-up up to the remittance line, if that is ever needed.
    existing = next((a for a in db.applications.values()
                     if (a.payment_id, a.invoice_id) == (payment_id, invoice_id)), None)
    if existing is not None:
        return unchanged(existing, f'{payment_id} is already applied to {invoice_id} as {existing.application_id} '
                                   f'({existing.amount}); nothing to do.')
    decision = check_apply_payment(db, customer_id, payment_id=payment_id, invoice_id=invoice_id, amount=applied)
    require(decision)
    if decision.outcome is Outcome.NEEDS_APPROVAL:
        return _hold_payment(store, db, customer_id, payment_id, str(decision.rule), decision.reason)
    application = Application(
        application_id=next_id(db, 'applications'), payment_id=payment_id, invoice_id=invoice_id, amount=applied,
        applied_at=db.today, idempotency_key=f'{payment_id}:{invoice_id}',
    )
    db = mark_paid_if_settled(db.with_rows('applications', {application.application_id: application}), invoice_id)
    if unapplied(db, payment_id) == 0:
        db = db.with_rows('payments', {payment_id: db.payment(payment_id).model_copy(
            update={'status': PaymentStatus.APPLIED})})
    return commit(store, db, 'apply_payment', application, f'Applied {applied} of {payment_id} to {invoice_id}.',
                  f'Applied {applied} of {payment_id} to {invoice_id} as {application.application_id}; '
                  f'{invoice_id} balance is now {balance(db, invoice_id)}, {unapplied(db, payment_id)} of the '
                  'payment is left.')


def _hold_payment(store: Store, db: ArDb, customer_id: str, payment_id: str, rule: str, reason: str) -> WriteResult:
    """One pending approval per payment, listing every candidate, whichever one the caller named."""
    pending = next((a for a in db.approvals.values() if a.action == 'apply_payment'
                    and a.status is ApprovalStatus.PENDING and a.payload.get('payment_id') == payment_id), None)
    if pending is not None:
        return held(pending, rule, repeat=True)
    payload = PaymentApproval(payment_id=payment_id, amount=unapplied(db, payment_id),
                              candidate_invoice_ids=payment_candidates(db, payment_id))
    return hold(store, db, customer_id, 'apply_payment', payload.model_dump(mode='json'), rule, reason)


def log_promise(store: Store, customer_id: str, invoice_id: str, promised_date: str | date,
                amount: str | Decimal) -> WriteResult:
    """Record a customer's promise to pay an invoice by a date."""
    db = store.db
    invoice_id, when = parse_text(invoice_id, 'invoice_id'), parse_date(promised_date, 'promised_date')
    promised = parse_money(amount, 'amount')
    require(check_log_promise(db, customer_id, invoice_id=invoice_id))
    require_amount(promised, balance(db, invoice_id), 'amount', f'the balance of {invoice_id}')
    if when < db.today:
        raise InvalidArgumentError(f'promised_date {when} is in the past; today is {db.today}.')
    if when > db.today + timedelta(days=MAX_PROMISE_DAYS):
        raise InvalidArgumentError(f'promised_date {when} is more than {MAX_PROMISE_DAYS} days after today '
                                   f'({db.today}); log no promise that far out, and escalate it to a person.')
    promise = Promise(promise_id=next_id(db, 'promises'), invoice_id=invoice_id, promised_date=when, amount=promised,
                      status=PromiseStatus.OPEN, source_message_id=None)
    return commit(store, db.with_rows('promises', {promise.promise_id: promise}), 'log_promise', promise,
                  f'Customer promised {promised} on {invoice_id} by {when}.',
                  f'Logged {promise.promise_id}: {promised} on {invoice_id} by {when}.')


def request_approval(store: Store, customer_id: str, action: str, payload: dict[str, object],
                     reason: str) -> WriteResult:
    """Ask a person to decide something no rule covers. Writes one pending approval."""
    db = store.db
    payer_family(db, customer_id)
    action, reason = parse_text(action, 'action').strip(), parse_text(reason, 'reason')
    if action in COVERED_BY_RULES:
        raise InvalidArgumentError(f'Do not request approval for {action}: call {action} itself. When a rule needs a '
                                   'person, the tool holds the write and records the approval.')
    return hold(store, db, customer_id, action, parse_payload(payload, 'payload'), None, reason)


def escalate_to_human(store: Store, customer_id: str, reason: str) -> WriteResult:
    """Hand the account to a person. Writes an action log entry only."""
    db = store.db
    payer_family(db, customer_id)
    entry = log_entry(db, 'escalate_to_human', customer_id, parse_text(reason, 'reason'))
    store.swap(db.with_rows('action_log', {entry.action_id: entry}))
    return WriteResult(status='done', message=f'Escalated {customer_id} to a person ({entry.action_id}). Stop here.',
                       target_id=customer_id, row=entry.model_dump(mode='json'))


def execute_approval(store: Store, customer_id: str, approval_id: str) -> WriteResult:
    """Carry out an approved approval, once: an approved credit is applied, an approved draft is sent (P13)."""
    db = store.db
    require(check_execute_approval(db, customer_id, approval_id=parse_text(approval_id, 'approval_id')))
    approval = db.approval(approval_id)
    if approval.action == 'propose_credit':
        credit = db.credit(CreditApproval.model_validate(approval.payload).credit_id)
        db, done = apply_credit(db, credit), f'applied credit {credit.credit_id} of {credit.amount} to {credit.invoice_id}'
    else:  # check_execute_approval allows only credits and message drafts
        db, message = write_message(db, MessageDraft.model_validate(approval.payload))
        done = f'sent {message.message_id} asking for {message.amount_requested}'
    executed = approval.model_copy(update={'executed_at': db.today})
    return commit(store, db.with_rows('approvals', {approval_id: executed}), 'execute_approval', executed,
                  f'Carried out {approval_id}: {done}.', f'Carried out {approval_id}: {done}.')


def decide_approval(store: Store, approval_id: str, decision: str, decided_by: str, note: str | None) -> WriteResult:
    """The reviewer's decision on a pending approval (an environment function, never an agent tool)."""
    db = store.db
    approval = db.approval(parse_text(approval_id, 'approval_id'))
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise InvalidArgumentError(f'decision must be one of {", ".join(DECISIONS)}; got {decision!r}.')
    reviewer, status = parse_text(decided_by, 'decided_by'), DECISIONS[decision]
    if note is not None and not isinstance(note, str):
        raise InvalidArgumentError(f'note must be text or null; got {note!r}.')
    if approval.status is not ApprovalStatus.PENDING:
        raise InvalidArgumentError(f'{approval_id} was already {approval.status}; it cannot be decided again.')
    decided = approval.model_copy(update={'status': status, 'decided_by': reviewer, 'decided_at': db.today,
                                          'note': note})
    db = db.with_rows('approvals', {approval_id: decided}).with_rows('credits', _linked_credits(db, decided))
    return commit(store, db, 'decide_approval', decided, note or f'{status} by {reviewer}.',
                  f'{approval_id} {status} by {reviewer}.', actor=reviewer)


def _linked_credits(db: ArDb, approval: Approval) -> dict[str, Credit]:
    status = CREDIT_AFTER[approval.status]
    return {c.credit_id: c.model_copy(update={'status': status}) for c in db.credits.values()
            if c.approval_id == approval.approval_id and c.status is CreditStatus.PROPOSED}
