"""Ledger arithmetic over an `CollectionsDb`. Pure functions: no I/O, no clock, no writes.

Unknown ids raise the `Unknown*Error` lookups from `agents.collections.data_model`, never `KeyError`.
"""

from collections.abc import Iterable
from decimal import Decimal

from agents.collections.data_model import CollectionsDb, CreditStatus, Invoice, InvoiceStatus

ZERO = Decimal('0.00')


def balance(db: CollectionsDb, invoice_id: str) -> Decimal:
    """Amount minus applications to the invoice minus its applied credits."""
    invoice = db.invoice(invoice_id)
    applied = sum((a.amount for a in db.applications.values() if a.invoice_id == invoice_id), ZERO)
    return invoice.amount - applied - applied_credits(db, invoice_id)


def applied_credits(db: CollectionsDb, invoice_id: str) -> Decimal:
    """Sum of the credits applied to the invoice."""
    return sum((c.amount for c in db.credits.values()
                if c.invoice_id == invoice_id and c.status is CreditStatus.APPLIED), ZERO)


def amount_due(db: CollectionsDb, invoice_ids: Iterable[str]) -> Decimal:
    """Sum of the balances of the distinct invoices named."""
    return sum((balance(db, invoice_id) for invoice_id in dict.fromkeys(invoice_ids)), ZERO)


def payer_family(db: CollectionsDb, customer_id: str) -> tuple[str, ...]:
    """The customer's id, then the ids of customers whose parent it is."""
    db.customer(customer_id)
    children = sorted(c.customer_id for c in db.customers.values() if c.parent_id == customer_id)
    return (customer_id, *children)


def open_invoices(db: CollectionsDb, customer_id: str) -> tuple[Invoice, ...]:
    """Open invoices of the customer and its children, by due date then id."""
    family = set(payer_family(db, customer_id))
    found = (i for i in db.invoices.values() if i.customer_id in family and i.status is InvoiceStatus.OPEN)
    return tuple(sorted(found, key=lambda invoice: (invoice.due_date, invoice.invoice_id)))


def is_overdue(db: CollectionsDb, invoice_id: str) -> bool:
    """Due date strictly before the tenant's `as_of_date`."""
    return db.invoice(invoice_id).due_date < db.today


def unapplied(db: CollectionsDb, payment_id: str) -> Decimal:
    """Payment amount minus everything applied from it."""
    payment = db.payment(payment_id)
    return payment.amount - sum((a.amount for a in db.applications.values() if a.payment_id == payment_id), ZERO)
