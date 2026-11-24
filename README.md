# agent-pydantic

An AI coworker for accounts receivable, built with [Pydantic AI](https://pydantic.dev/docs/ai/overview/).
It is at the design stage: see the [design](docs/ar-coworker-design.md) and the
[implementation plan](docs/ar-coworker-implementation.md).

## Setup

`.env` needs `ANTHROPIC_API_KEY`.

## Run

```bash
uv run pytest    # offline unit tests
```

## Layout

- `db/` — the synthetic AR database (see `db/README.md`)
- `docs/` — the design, its diagram and the implementation plan
- `evals/scoreboard.py` — pass rate, cost and latency against a baseline
- `tests/` — unit tests
