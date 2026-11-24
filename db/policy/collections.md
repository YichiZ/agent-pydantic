## Collections

- Reminders go out only on an aging check: at most one per run, to one contact, on that contact's
  preferred channel, covering every invoice on the account that may be chased.
- An invoice may be chased only if it is open and past due, its collections are not paused (an
  open dispute pauses them), and its open promises to pay whose dates are still to come do not
  add up to its balance.
- Never contact a do-not-contact contact, on any channel. If no contact may be reached, escalate.
- Leave at least the tenant's minimum days (seven) between reminders to a customer. Exactly the
  seventh day is allowed; any earlier, send nothing.
- The body states the amount due as a number equal to what `amount_due` returns for exactly the
  invoices covered. Name each invoice and its due date, ask when payment can be expected, and stay
  polite and factual: no threats, no claim the ledger does not support.
- When a customer promises to pay, log the promise against the invoice with its date, at most 30
  days ahead (a later one is for a person), and amount; do not ask them for money again in that run.
