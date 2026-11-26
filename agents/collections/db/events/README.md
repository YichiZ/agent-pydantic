# Collections events

Twenty events for the collections flow, one JSON file each. They are situations to run the agent
on and look at, not scored tasks: an event says what happened and what is on the account, and has
no reference answer and no assertions. The 21 scored tasks are in `db/tasks.json`.

event_11 was promoted to `task_21` after the agent got it wrong, and stays as the record of how it was
found; none of the others repeats a task. Each uses an account from `db/db.json`, either as it stands or
after a short setup.

## Fields

| Field | Meaning |
|---|---|
| `id` | `event_01` to `event_20` |
| `flow` | `collections` for all of them |
| `type` | `aging_check`, `approval_decided`, or `customer_message` |
| `customer_id` | the account |
| `ticket` | the event text the agent is given; null for a customer message |
| `user_scenario` | for a customer message: the persona and instructions for a simulated clerk, in the same shape as a chat task |
| `initial_state` | steps replayed on a fresh database before the agent starts, in the same shape as a task's; null when the account is used as it stands |
| `situation` | what is on the account that makes the event worth running |
| `open_question` | what the right outcome is, or why it is not obvious |
| `rules_settle_it` | true when the rulebook and policy code already decide the outcome; false when they do not |

## The set

| Events | Type | What they probe |
|---|---|---|
| 01 to 03, 10 | aging check | An invoice is past due, but money for it is sitting unapplied on the account |
| 04 | aging check | A reminder exactly seven days after the last one |
| 05, 07, 08, 09 | aging check | Nothing may be chased: nothing due, or the invoice is in dispute |
| 06 | aging check | The plain case, as a control |
| 11, 12, 15 | aging check | The amount or the set of invoices changed just before: a rejected dispute, a credit, a part-payment |
| 13 | aging check | A promise that covers only part of the balance |
| 14 | aging check | The same event delivered twice |
| 16, 17 | approval decided | A held reminder draft, approved and rejected |
| 18, 19, 20 | customer message | "We already paid", a request for a payment plan, and a do-not-contact contact who writes first |

Eleven are settled by the rules. The other nine are the interesting ones: the agent has to use
judgment, or the system has no good way to do the right thing.

`tests/test_events.py` checks that every event is well formed, names real rows, and that its setup
replays through the real tools.

`evals/run_event.py` runs them against the real model (it needs `ANTHROPIC_API_KEY` in `.env`). Each
event runs on a fresh copy of `db/db.json` with its setup replayed; nothing is written to disk. For
each it prints the situation and open question, the setup steps, and what the agent did: every
tool call with its outcome, full message bodies, its summary and the rows it wrote.

```bash
uv run python -m agents collections run --list                   # ids, types, accounts; runs nothing
uv run python -m agents collections run event_06                 # one event; several ids run in order
uv run python -m agents collections run --all                    # all twenty, in order
uv run python -m agents collections run event_20 --interactive   # type the customer's lines yourself
uv run python -m agents collections run --customer cus_garnet --event "Event: aging_check. Account: Garnet Tooling (cus_garnet)."
```

A chat event is played by the simulated clerk unless `--interactive` is given; an empty line or
`quit` ends it.
