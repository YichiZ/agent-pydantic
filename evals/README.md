# Evals

`support_evals.py` is a runnable skeleton with one example case. The rest is yours to write.

```bash
uv run python -m evals.support_evals
```

## What the agent can do today

- Greets the customer by name.
- `list_accounts` — bank accounts with balances.
- `recent_transactions` — newest first, one account at a time.
- `credit_card_accounts` — balance owed and reward points (loaded on demand).
- Returns `support_advice` (text), `block_card` (bool) and `risk` (0-10).

## Customers worth using

Ground truth is in `db/db.json`.

| Customer id | Name | Has |
|---|---|---|
| `lj82d4f1a9` | Liang Jinhai | 2 checking accounts, 1 credit card, 58 transactions |
| `kj93a7b2e1` | Kim Junho | 3 checking accounts, 87 transactions |
| `123` | Mia Smith | 1 checking (zero balance), 1 savings |
| `6680a37184` | Kenji Tanaka | 1 credit card, no bank accounts |

## Things to decide

- Which behaviours matter enough that a change to them must not go unnoticed?
- For each, what is the cheapest check that would fail if it broke? Options, cheapest first:
  a field comparison on the output, a substring in `support_advice`, a custom `Evaluator`,
  an `LLMJudge` rubric.
- The model is not deterministic. `dataset.evaluate_sync(ask, repeat=3)` shows whether a case is stable.

Docs: https://pydantic.dev/docs/ai/evals/
