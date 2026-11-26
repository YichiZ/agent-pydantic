"""Policy rules P1-P15 as pure functions over an `ArDb`. No I/O, no clock, no writes.

Each `check_*` takes the database, the run's customer id and the proposed write, and returns a
`Decision`: allow, needs approval or deny, with the rule id and a sentence the model can act on.
Rules are checked in order and the first that does not allow decides; denials come before the
holds (P5, P8, P10, P15), so a write is only ever held for a person when nothing forbids it outright.
"""

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from agents.collections.data_model import (
    Approval,
    ApprovalStatus,
    ArDb,
    AutonomyLevel,
    Channel,
    Contact,
    CreditApproval,
    CreditStatus,
    Dispute,
    DisputeStatus,
    InvoiceStatus,
    MessageDirection,
    MessageDraft,
    PromiseStatus,
    Remittance,
)
from agents.collections.ledger import ZERO, amount_due, applied_credits, balance, is_overdue, open_invoices, payer_family, unapplied


class Outcome(StrEnum):
    ALLOW = 'allow'
    NEEDS_APPROVAL = 'needs_approval'
    DENY = 'deny'


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    rule: str | None = None
    reason: str = ''


ALLOW = Decision(Outcome.ALLOW)


def deny(rule: str, reason: str) -> Decision:
    return Decision(Outcome.DENY, rule, reason)


def needs_approval(rule: str, reason: str) -> Decision:
    return Decision(Outcome.NEEDS_APPROVAL, rule, reason)


def first_failure(decisions: Iterable[Decision]) -> Decision:
    """The first decision that does not allow, else ALLOW. Generators are consumed lazily."""
    return next((d for d in decisions if d.outcome is not Outcome.ALLOW), ALLOW)


# Shared reads.

def remittance_for(db: ArDb, payment_id: str) -> Remittance | None:
    return next((r for r in db.remittances.values() if r.payment_id == payment_id), None)


def last_outbound_date(db: ArDb, customer_id: str) -> date | None:
    family = set(payer_family(db, customer_id))
    sent = [m.sent_at for m in db.messages.values() if m.customer_id in family and m.direction is MessageDirection.OUTBOUND]
    return max(sent, default=None)


_NUMBER = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?')


def amounts_in(text: str) -> tuple[Decimal, ...]:
    """Every number written in the text, as a value: "$9,400", "9,400.00" and "9400" all give 9400."""
    return tuple(Decimal(found.replace(',', '')) for found in _NUMBER.findall(text))


def payment_candidates(db: ArDb, payment_id: str) -> tuple[str, ...]:
    """For a payment with no remittance: open invoices in the payer's family whose balance equals what is left."""
    if remittance_for(db, payment_id) is not None:
        return ()
    left = unapplied(db, payment_id)
    family_open = open_invoices(db, db.payment(payment_id).customer_id)
    return tuple(sorted(i.invoice_id for i in family_open if balance(db, i.invoice_id) == left))


# P11: scope.

def check_scope(db: ArDb, customer_id: str, owner_id: str, what: str) -> Decision:
    """P11: `what`, owned by `owner_id`, must belong to the run's customer or one of its children."""
    family = payer_family(db, customer_id)
    if owner_id in family:
        return ALLOW
    return deny('P11', f"{what} belongs to {owner_id}, outside this run's account ({', '.join(family)}); leave it alone.")


def check_invoice_scope(db: ArDb, customer_id: str, *, invoice_id: str) -> Decision:
    """P11 for one invoice; the whole check on opening a dispute on it or logging a promise against it."""
    return check_scope(db, customer_id, db.invoice(invoice_id).customer_id, f'Invoice {invoice_id}')


# Messages: P11, P2, P1, P14, P12, P4, P3, P5.

def check_send_message(db: ArDb, customer_id: str, *, contact_id: str, channel: Channel, invoice_ids: Sequence[str],
                       body: str, approved: bool = False) -> Decision:
    """`approved` is True when carrying out a draft a person approved, which satisfies P5's review."""
    contact = db.contact(contact_id)
    return first_failure(_message_rules(db, customer_id, contact, channel, invoice_ids, body, approved))


def _message_rules(db: ArDb, customer_id: str, contact: Contact, channel: Channel, invoice_ids: Sequence[str],
                   body: str, approved: bool) -> Iterator[Decision]:
    yield check_scope(db, customer_id, contact.customer_id, f'Contact {contact.contact_id}')
    yield from (check_invoice_scope(db, customer_id, invoice_id=invoice_id) for invoice_id in invoice_ids)
    yield _p2_do_not_contact(contact)
    yield _p1_not_paused(db, invoice_ids)
    yield _p14_open_and_overdue(db, invoice_ids)
    yield _p12_no_promise_pending(db, invoice_ids)
    yield _p4_spacing(db, customer_id)
    yield _p3_amount_stated(db, invoice_ids, body)
    yield _p5_autonomy(db, contact, channel, approved)


def _p2_do_not_contact(contact: Contact) -> Decision:
    if not contact.do_not_contact:
        return ALLOW
    return deny('P2', f'{contact.name} ({contact.contact_id}) is do-not-contact on every channel. '
                      'If no contact on the account may be reached, escalate to a person.')


def _p1_not_paused(db: ArDb, invoice_ids: Sequence[str]) -> Decision:
    paused = [i for i in invoice_ids if db.invoice(i).collections_paused]
    if not paused:
        return ALLOW
    return deny('P1', f'Collections are paused on {", ".join(paused)} (an open dispute); leave paused invoices out '
                      'of any reminder.')


def _not_chaseable(db: ArDb, invoice_id: str) -> str | None:
    invoice = db.invoice(invoice_id)
    if invoice.status is not InvoiceStatus.OPEN:
        return f'{invoice_id} is {invoice.status}'
    if not is_overdue(db, invoice_id):
        return f'{invoice_id} is not past due (due {invoice.due_date})'
    return None


def _p14_open_and_overdue(db: ArDb, invoice_ids: Sequence[str]) -> Decision:
    blocked = [why for i in invoice_ids if (why := _not_chaseable(db, i)) is not None]
    if not blocked:
        return ALLOW
    return deny('P14', f'A reminder may cover only open invoices past their due date (today is {db.today}): '
                       f'{"; ".join(blocked)}. Leave them out of any reminder.')


def _p12_no_promise_pending(db: ArDb, invoice_ids: Sequence[str]) -> Decision:
    """A promise holds off reminders only while the open, not-yet-due promises cover the invoice's balance."""
    for invoice_id in invoice_ids:
        pending = [p for p in db.promises.values() if p.invoice_id == invoice_id
                   and p.status is PromiseStatus.OPEN and p.promised_date >= db.today]
        promised, owed = sum((p.amount for p in pending), ZERO), balance(db, invoice_id)
        if pending and promised >= owed:
            last = max(p.promised_date for p in pending)
            return deny('P12', f'{invoice_id} has open promises to pay {promised} by {last}, covering its balance of '
                               f'{owed}; send no reminder on it until the promised date has passed.')
    return ALLOW


def _p4_spacing(db: ArDb, customer_id: str) -> Decision:
    last, minimum = last_outbound_date(db, customer_id), db.tenant.min_days_between_reminders
    if last is None or (db.today - last).days >= minimum:
        return ALLOW
    return deny('P4', f'The last reminder to this customer went on {last}, {(db.today - last).days} days ago; '
                      f'reminders need {minimum} days between them, so send nothing before {last + timedelta(minimum)}.')


def _p3_amount_stated(db: ArDb, invoice_ids: Sequence[str], body: str) -> Decision:
    # Checks only that the amount due appears; other figures may too, and unsupported claims are the tone judge's job.
    due = amount_due(db, invoice_ids)
    if due in amounts_in(body):
        return ALLOW
    return deny('P3', f'The body must state the amount due for {", ".join(invoice_ids)}, which the ledger gives as '
                      f'{due:,.2f}; no number in the body equals it.')


def _p5_autonomy(db: ArDb, contact: Contact, channel: Channel, approved: bool) -> Decision:
    customer = db.customer(contact.customer_id)
    level = customer.autonomy.get(channel, AutonomyLevel.OFF)
    if level is AutonomyLevel.OFF:
        return deny('P5', f'Outreach on {channel} is turned off for {customer.name}; do not use this channel.')
    if level is AutonomyLevel.REVIEW and not approved:
        return needs_approval('P5', f'{channel} messages to {customer.name} are reviewed by a person before they go.')
    return ALLOW


# Cash application: P11, P7, P6, P15, P8.

def check_apply_payment(db: ArDb, customer_id: str, *, payment_id: str, invoice_id: str, amount: Decimal) -> Decision:
    return first_failure(_payment_rules(db, customer_id, payment_id, invoice_id, amount))


def _payment_rules(db: ArDb, customer_id: str, payment_id: str, invoice_id: str, amount: Decimal) -> Iterator[Decision]:
    payment, invoice = db.payment(payment_id), db.invoice(invoice_id)
    yield check_scope(db, customer_id, payment.customer_id, f'Payment {payment_id}')
    if invoice.customer_id not in payer_family(db, payment.customer_id):
        yield deny('P7', f'{invoice_id} belongs to {invoice.customer_id}, outside the family of the payer '
                         f'{payment.customer_id}; apply the payment only to the payer\'s own invoices.')
    yield check_invoice_scope(db, customer_id, invoice_id=invoice_id)
    yield _p6_fits(db, payment_id, invoice_id, amount)
    yield _p15_follows_remittance(db, payment_id, invoice_id, amount)
    yield _p8_one_candidate(db, payment_id)


def _p6_fits(db: ArDb, payment_id: str, invoice_id: str, amount: Decimal) -> Decision:
    left, owed = unapplied(db, payment_id), balance(db, invoice_id)
    if amount <= 0:
        return deny('P6', f'An application must be a positive amount; got {amount}.')
    if amount > left:
        return deny('P6', f'{payment_id} has {left} left to apply; {amount} is more than that.')
    if amount > owed:
        return deny('P6', f'{invoice_id} has a balance of {owed}; apply no more than that.')
    return ALLOW


def _p15_follows_remittance(db: ArDb, payment_id: str, invoice_id: str, amount: Decimal) -> Decision:
    """P15: cash goes where its remittance says, up to the amount it gives; with none, `_p15_no_remittance` decides."""
    remittance = remittance_for(db, payment_id)
    if remittance is None:
        return _p15_no_remittance(db, payment_id, invoice_id)
    lines = [line for line in remittance.lines if line.invoice_ref == invoice_id]
    if not lines:
        named = ', '.join(dict.fromkeys(line.invoice_ref for line in remittance.lines))
        return deny('P15', f'Remittance {remittance.remittance_id} with {payment_id} names {named}, not {invoice_id}; '
                           'apply the payment only to the invoices its remittance names.')
    given = sum((line.amount for line in lines), ZERO)
    already = sum((a.amount for a in db.applications.values()
                   if (a.payment_id, a.invoice_id) == (payment_id, invoice_id)), ZERO)
    if already + amount <= given:
        return ALLOW
    return deny('P15', f'Remittance {remittance.remittance_id} gives {given} for {invoice_id} and {already} of '
                       f'{payment_id} is already applied to it; apply no more than {given - already}.')


def _p15_no_remittance(db: ArDb, payment_id: str, invoice_id: str) -> Decision:
    """One matching invoice: only that one. Several: P8 holds them for a person. None: unidentified cash, held too."""
    candidates, left = payment_candidates(db, payment_id), unapplied(db, payment_id)
    if not candidates:
        return needs_approval('P15', f'{payment_id} has no remittance and no open invoice matches its {left}; '
                                     'unidentified cash goes to a person.')
    if len(candidates) == 1 and invoice_id not in candidates:
        return deny('P15', f'{payment_id} has no remittance and its {left} matches only {candidates[0]}; apply it '
                           f'there, never to {invoice_id}.')
    return ALLOW


def _p8_one_candidate(db: ArDb, payment_id: str) -> Decision:
    candidates = payment_candidates(db, payment_id)
    if len(candidates) <= 1:
        return ALLOW
    return needs_approval('P8', f'{payment_id} has no remittance and its {unapplied(db, payment_id)} matches '
                                f'{len(candidates)} open invoices ({", ".join(candidates)}); a person must choose.')


# Disputes and credits: P11, P9, P10.


def has_open_dispute(db: ArDb, invoice_id: str) -> bool:
    return any(d.invoice_id == invoice_id and d.status is DisputeStatus.OPEN for d in db.disputes.values())


def _dispute_scope(db: ArDb, customer_id: str, dispute: Dispute) -> Decision:
    return check_scope(db, customer_id, db.invoice(dispute.invoice_id).customer_id, f'Dispute {dispute.dispute_id}')


def check_reject_dispute(db: ArDb, customer_id: str, *, dispute_id: str) -> Decision:
    return _dispute_scope(db, customer_id, db.dispute(dispute_id))


def check_propose_credit(db: ArDb, customer_id: str, *, dispute_id: str, amount: Decimal) -> Decision:
    dispute = db.dispute(dispute_id)
    return first_failure((
        _dispute_scope(db, customer_id, dispute),
        _p9_never_rejected(db, dispute),
        _p9_fits_dispute(db, dispute, amount),
        _p10_limit(db, dispute.invoice_id, amount),
    ))


def _p9_never_rejected(db: ArDb, dispute: Dispute) -> Decision:
    rejected = sorted(c.credit_id for c in db.credits.values()
                      if c.dispute_id == dispute.dispute_id and c.status is CreditStatus.REJECTED)
    if not rejected:
        return ALLOW
    return deny('P9', f'A reviewer rejected a credit on {dispute.dispute_id} ({", ".join(rejected)}); a credit on this '
                      'dispute must not be proposed again in any amount. Read the reviewer\'s note: if it settles the '
                      'matter, reject the dispute with the note as the reason.')


def _p9_fits_dispute(db: ArDb, dispute: Dispute, amount: Decimal) -> Decision:
    if dispute.status is not DisputeStatus.OPEN:
        return deny('P9', f'{dispute.dispute_id} is {dispute.status}, not open; a credit needs an open dispute.')
    if amount <= 0:
        return deny('P9', f'A credit must be a positive amount; got {amount}.')
    if amount > dispute.amount:
        return deny('P9', f'{amount} is more than the {dispute.amount} disputed in {dispute.dispute_id}; '
                          'credit no more than the dispute amount.')
    owed = balance(db, dispute.invoice_id)
    if amount > owed:
        return deny('P9', f'{dispute.invoice_id} has a balance of {owed}; a credit may not exceed it.')
    return ALLOW


def _p10_limit(db: ArDb, invoice_id: str, amount: Decimal) -> Decision:
    """The limit is on the invoice's credits together, so a large credit cannot be split into small ones."""
    limit, already = db.tenant.credit_auto_approve_limit, applied_credits(db, invoice_id)
    if already + amount <= limit:
        return ALLOW
    return needs_approval('P10', f'{invoice_id} already has {already} in applied credits; with {amount} more that is '
                                 f'{already + amount}, above the {limit} auto-approve limit; a person must approve it.')


# Approvals: P11, P13, then the rules of the action being carried out.

def check_execute_approval(db: ArDb, customer_id: str, *, approval_id: str) -> Decision:
    approval = db.approval(approval_id)
    return first_failure(_execute_rules(db, customer_id, approval))


def _execute_rules(db: ArDb, customer_id: str, approval: Approval) -> Iterator[Decision]:
    yield check_scope(db, customer_id, approval.customer_id, f'Approval {approval.approval_id}')
    yield _p13_approved_once(approval)
    yield _ready_to_carry_out(db, customer_id, approval)


def _p13_approved_once(approval: Approval) -> Decision:
    name = approval.approval_id
    if approval.status is ApprovalStatus.PENDING:
        return deny('P13', f'{name} is still pending: no person has decided it yet. Wait for the decision.')
    if approval.status is ApprovalStatus.REJECTED:
        return deny('P13', f'{name} was rejected by {approval.decided_by} (note: {approval.note!r}); never carry it '
                           'out or propose it again.')
    if approval.executed_at is not None:
        return deny('P13', f'{name} was already carried out on {approval.executed_at}; nothing is carried out twice.')
    return ALLOW


def _ready_to_carry_out(db: ArDb, customer_id: str, approval: Approval) -> Decision:
    match approval.action:
        case 'propose_credit':
            credit = db.credit(CreditApproval.model_validate(approval.payload).credit_id)
            if credit.approval_id != approval.approval_id or credit.status is not CreditStatus.APPROVED:
                return deny('P13', f'Credit {credit.credit_id} is {credit.status} and not approved under '
                                   f'{approval.approval_id}; it cannot be applied.')
            return _p9_fits_dispute(db, db.dispute(credit.dispute_id), credit.amount)
        case 'send_message':
            draft = MessageDraft.model_validate(approval.payload)
            return check_send_message(db, customer_id, contact_id=draft.contact_id, channel=draft.channel,
                                      invoice_ids=draft.invoice_ids, body=draft.body, approved=True)
        case 'apply_payment':
            return deny('P13', 'Carrying out a payment approval is not supported yet: it needs the reviewer\'s choice '
                               'of invoice, so a person applies the payment.')
        case _:
            return deny('P13', f'The coworker cannot carry out a {approval.action!r} approval; a person must do it.')
