# agent-pydantic

A bank support agent built with [Pydantic AI](https://pydantic.dev/docs/ai/overview/), after the
docs' bank support example. Its data is the `banking_knowledge` domain of
[tau2-bench](https://github.com/sierra-research/tau2-bench), read through a read-only
[local workspace](https://pydantic.dev/docs/ai/core-concepts/workspace/).

## Setup

`.env` needs:

- `ANTHROPIC_API_KEY`
- `TAU2_DATA_DIR` — the `data` directory of a tau2-bench checkout

## Run

```bash
uv run python bank_support.py           # demo questions, live model
uv run pytest                           # offline: fixture data, scripted models
uv run python -m evals.support_evals    # evals: live model, real tau2 data
```

## Layout

- `bank_db.py` — typed read-only view of tau2's `db.json`
- `bank_support.py` — the agent and its tools
- `tests/` — unit tests with a small fixture database
- `evals/` — behaviour evals (see `evals/README.md`)
