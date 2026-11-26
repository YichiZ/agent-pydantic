# Accounts receivable database

`db.json` is a synthetic accounts receivable database for one tenant, Harborline Industrial Supply.
Every company, person and amount in it is invented. It was written for this repo; tau2-bench has no
receivables domain to copy from.

It uses the table format of tau2-bench's `banking_knowledge` domain: each table is
`{"data": {id: row}, "notes": "..."}`, and the notes explain the fields.

| Table | Rows | What it holds |
|---|---|---|
| `tenants` | 1 | "today" (`as_of_date`, 2026-11-16), the credit limit that needs approval, reminder spacing |
| `customers` | 18 | one parent and child pair (Delmar Foods), autonomy per channel; one has email on review |
| `contacts` | 19 | one is do-not-contact |
| `invoices` | 26 | 2 paid, 24 open; one line each, so `amount = quantity × unit_price` |
| `payments` | 7 | 2 applied, 5 landed today and unapplied |
| `remittances` | 4 | one exact, one across three invoices and two entities, one short-pay with a deduction code, one with an instruction aimed at an AI system hidden in its text |
| `applications` | 2 | payment to invoice |
| `credits` | 1 | applied the day before "today" |
| `disputes` | 5 | 4 open, 1 resolved |
| `promises` | 1 | one open promise, not yet due; more are filled by the agent |
| `messages` | 10 | 4 outbound reminders, 5 inbound claims, 1 inbound promise to pay |
| `approvals` | 1 | one historical approval, already carried out; the agent adds more |
| `customer_notes` | 6 | long-term memory; one note is deliberately stale |
| `action_log` | 13 | every earlier write, with its reason |

Rules the data obeys:

- An invoice's balance is not stored. It is `amount − applications − applied credits`.
- An invoice is `paid` only when its balance is zero.
- `collections_paused` is true exactly when the invoice has an open dispute.
- A remittance's lines add up to its payment.
- Money is a string with two decimals; dates are `YYYY-MM-DD`.

Each account holds one piece of actionable work, for one eval task, plus distractors that are
plainly not actionable, such as an invoice that is not yet due. An agent run acts on one event,
so a second piece of real work on the same account would make a correct run look wrong. Two disputes
are used at more than one moment: Fennick's by three tasks, and Juniper's by two, open and then
rejected. The task list is in `docs/collections-agent-implementation.md`.

## The eval set

| File | What it holds |
|---|---|
| `tasks.json` | 21 tasks in tau2-bench's task schema, one reference path and env assertions each |
| `split_tasks.json` | `base` (all 21), `never_events`, `cross_flow` |
| `policy/base.md` | the rules the agent reads on every run |
| `policy/chat.md` | how to talk to a customer, added to the base for the two chat tasks |
| `policy/collections.md`, `policy/cash_application.md`, `policy/disputes.md` | each flow's rules, which come with its capability when the agent loads it |
| `documents/` | nine knowledge documents: evidence, agreements, policies and one distractor |

A new row's id is its table prefix plus the largest numeric suffix in that table plus one, so a
run on a fresh copy of the database creates `apr_8001`, `crd_4002`, `dsp_3006`, `msg_6011`,
`prm_8502` and `app_5002` first. `tests/test_eval_set.py` checks the set offline.

`assert_no_credit_without_approval` holds on the untouched database: the one historical credit
above the limit, `crd_4001` (600.00), has an approved approval, `apr_8000`.
