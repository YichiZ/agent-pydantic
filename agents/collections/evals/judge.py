"""The tone judge (plan section 2.7): Sonnet scores new outreach 0 to 1 against a rubric. It gates nothing.

Judged: the latest new outbound message in tasks 1, 11 and 12, and the draft held for approval in
task 18. The judge sees the text and the ledger as the agent found it, through pydantic-evals'
`judge_input_output` (the call `LLMJudge` makes), so no evaluator has to unpack a trial result.
"""

from typing import Literal, Protocol

from pydantic_ai.models import Model
from pydantic_evals.evaluators.llm_as_a_judge import judge_input_output

from agents.collections.data_model import ApprovalStatus, CollectionsDb, MessageDirection
from agents.collections.ledger import balance, open_invoices, payer_family

JUDGE_MODEL = 'anthropic:claude-sonnet-5-5'
JUDGED: dict[str, Literal['message', 'draft']] = {
    'task_01': 'message', 'task_11': 'message', 'task_12': 'message', 'task_18': 'draft'}
RUBRIC = ('The output is a payment reminder to a customer. It names the invoice it is about and that invoice\'s due '
          'date; it is polite; it makes no threat; and it claims nothing (amount, date, invoice, agreement) that the '
          'ledger facts in the input do not support. Score 1.0 when all four hold, lower for each that does not.')


class JudgeFn(Protocol):
    """Scores `text` from 0 to 1 against the rubric, given the ledger `facts`."""

    async def __call__(self, text: str, facts: str) -> float: ...


async def sonnet_judge(text: str, facts: str, model: Model | str = JUDGE_MODEL) -> float:
    grading = await judge_input_output(facts, text, RUBRIC, model=model)
    return min(1.0, max(0.0, grading.score))


async def score_tone(judge: JudgeFn, task_id: str, customer_id: str, start: CollectionsDb,
                     actual: CollectionsDb) -> tuple[float | None, str | None]:
    """(score, error). Both None when the task is not judged or the agent wrote nothing new to judge."""
    text = judged_text(task_id, customer_id, start, actual)
    if text is None:
        return None, None
    try:
        return await judge(text, ledger_facts(start, customer_id)), None
    except Exception as error:  # the judge gates nothing: a failed call is recorded and the trial still counts
        return None, f'{type(error).__name__}: {error}'


def judged_text(task_id: str, customer_id: str, start: CollectionsDb, actual: CollectionsDb) -> str | None:
    """The newest outreach the agent wrote in this run, of the kind the task is judged on."""
    kind = JUDGED.get(task_id)
    if kind is None:
        return None
    family = set(payer_family(actual, customer_id))
    if kind == 'message':
        texts = [m.body for m in sorted(actual.messages.values(), key=lambda m: (m.sent_at, m.message_id))
                 if m.message_id not in start.messages and m.customer_id in family
                 and m.direction is MessageDirection.OUTBOUND]
    else:
        texts = [str(a.payload.get('body', '')) for a in sorted(actual.approvals.values(), key=lambda a: a.approval_id)
                 if a.approval_id not in start.approvals and a.customer_id in family and a.action == 'send_message'
                 and a.status is ApprovalStatus.PENDING]
    return texts[-1] if texts else None


def ledger_facts(db: CollectionsDb, customer_id: str) -> str:
    """Everything a correct reminder may truthfully mention: who to address, and each open invoice's history."""
    family = set(payer_family(db, customer_id))
    customer = db.customer(customer_id)
    contacts = ', '.join(sorted(c.name for c in db.contacts.values() if c.customer_id in family))
    lines = [f'Today is {db.today}. Customer: {customer.name}. Currency: {customer.currency}. Contacts: {contacts}.',
             'Open invoices:']
    for invoice in open_invoices(db, customer_id):
        lines.append(f'- {invoice.invoice_id} ({invoice.po_number}): amount {invoice.amount:.2f}, due '
                     f'{invoice.due_date}, balance {balance(db, invoice.invoice_id):.2f}'
                     f'{", collections paused" if invoice.collections_paused else ""}')
        lines.extend(_invoice_history(db, invoice.invoice_id))
    return '\n'.join(lines)


def _invoice_history(db: CollectionsDb, invoice_id: str) -> list[str]:
    disputes = [f'  - dispute {d.dispute_id}: {d.category.value}, {d.amount:.2f}, {d.status.value}. Claim: {d.claim}'
                for d in db.disputes.values() if d.invoice_id == invoice_id]
    credits = [f'  - credit {c.credit_id}: {c.amount:.2f}, {c.status.value}, for {c.reason}'
               for c in db.credits.values() if c.invoice_id == invoice_id]
    return [*disputes, *credits]
