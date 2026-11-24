# AR database

`db.json` is a synthetic accounts receivable database for one tenant, Harborline Industrial Supply.
Every company, person and amount in it is invented. It was written for this repo; tau2-bench has no
receivables domain to copy from.

It uses the table format of tau2-bench's `banking_knowledge` domain: each table is
`{"data": {id: row}, "notes": "..."}`, and the notes explain the fields.

| Table | Rows | What it holds |
|---|---|---|
| `tenants` | 1 | "today" (`as_of_date`, 2026-11-16), the credit limit that needs approval, reminder spacing |
| `customers` | 13 | one parent and child pair (Delmar Foods), autonomy per channel |
| `contacts` | 14 | one is do-not-contact |
| `invoices` | 20 | 2 paid, 18 open; one line each, so `amount = quantity × unit_price` |
| `payments` | 6 | 2 applied, 4 landed today and unapplied |
| `remittances` | 3 | one exact, one across three invoices and two entities, one short-pay with a deduction code |
| `applications` | 2 | payment to invoice |
| `credits` | 1 | applied the day before "today" |
| `disputes` | 4 | 3 open, 1 resolved |
| `promises` | 0 | filled by the agent |
| `messages` | 6 | 2 outbound reminders, 4 inbound claims |
| `approvals` | 0 | filled by the agent |
| `customer_notes` | 6 | long-term memory; one note is deliberately stale |
| `action_log` | 9 | every earlier write, with its reason |

Rules the data obeys:

- An invoice's balance is not stored. It is `amount − applications − applied credits`.
- An invoice is `paid` only when its balance is zero.
- `collections_paused` is true exactly when the invoice has an open dispute.
- A remittance's lines add up to its payment.
- Money is a string with two decimals; dates are `YYYY-MM-DD`.

Each account holds one piece of actionable work, for one eval task, plus distractors that are
plainly not actionable, such as an invoice that is not yet due. An agent run acts on one event,
so a second piece of real work on the same account would make a correct run look wrong. The one
exception is Fennick, whose dispute is used at three moments by three tasks. The task list is in
`docs/ar-coworker-implementation.md`.
