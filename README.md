# agent-pydantic

Independent AI agents built with [Pydantic AI](https://pydantic.dev/docs/ai/overview/), one package each
under `agents/`. Each agent keeps its own data, evals, tests and docs in its package.

Every agent in this repo uses the Pydantic AI framework. An agent built on another framework does not
belong here.

## Agents

- [`ar`](agents/ar/README.md): an accounts receivable agent (collections reminders, cash
  application, disputes and deductions), with its eval set and baseline.
- [`browser`](agents/browser/README.md): an interactive agent you chat with in the terminal; it browses the web in a real browser.

## Run

Needs [uv](https://docs.astral.sh/uv/) and Python 3.13. Live runs need `ANTHROPIC_API_KEY` in a `.env`
at the repo root (`cp .env.example .env`, then fill it in); the tests do not call a model.

```bash
uv run python -m agents                      # list the agents
uv run python -m agents ar -h                # an agent's commands
uv run python -m agents ar run --list        # e.g. the AR agent's events
uv run python -m agents ar eval --trials 4   # e.g. the AR eval set, pass^4
uv run python -m agents browser              # e.g. chat with the browser agent
uv run pytest                                # every agent's offline tests
```

## Add an agent

1. Create `agents/<name>/` with an `__init__.py`; keep its data, evals, tests and docs inside it. Build
   the agent with Pydantic AI.
2. Add `agents/<name>/cli.py` (or, for a one-file agent, `agent.py`) with
   `main(argv: Sequence[str] | None = None) -> int`. It gets the arguments after `python -m agents <name>`,
   and `python -m agents` lists it from then on.
3. Put its tests in `agents/<name>/tests/` with an `__init__.py`, so their module names do not collide with
   another agent's; `uv run pytest` collects them.
