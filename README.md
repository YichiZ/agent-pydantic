# agent-pydantic

An AI coworker for accounts receivable, built with [Pydantic AI](https://pydantic.dev/docs/ai/overview/).
It handles collections reminders, cash application, and disputes and deductions for one tenant.
The eval set is built first and is the specification for the agent that follows.

![AR coworker architecture](docs/ar-coworker-design.svg)

## Status

The eval set, the data layer, the policy rules and the tools exist. There is no agent to run yet.

- Done: [design](docs/ar-coworker-design.md), [implementation plan](docs/ar-coworker-implementation.md),
  synthetic AR database, eval set of 20 tasks, data model and ledger, 13 policy rules, 17 tools,
  and an offline replay of every task's reference actions through the real tools.
- Not built yet: the eval runner and the agent.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and Python 3.13. `uv run` creates the environment on first use.

A `.env` with `ANTHROPIC_API_KEY` is only needed later, for live agent runs. Nothing today calls a model.

## Run

```bash
uv run pytest             # offline tests
uv run pytest --cov=ar    # with coverage of the ar/ package
```

## The eval set

- 20 tasks in [tau2-bench](https://github.com/sierra-research/tau2-bench)'s task schema. The format
  is tau2's; the tasks and data are written for this repo and are synthetic.
- A `never_events` split (9 tasks) of forbidden actions, plus `base` (all 20) and `cross_skill`.
- Each task is labelled with its skill, expected disposition and whether a person must be involved.

Details are in [`db/README.md`](db/README.md) and section 2 of the
[implementation plan](docs/ar-coworker-implementation.md). The design is in
[`docs/ar-coworker-design.md`](docs/ar-coworker-design.md).

## Flows

Each event starts one run for one account: an aging check, a payment received, a dispute to
review, a decision on an approval, or a chat with someone at the customer. The agent proposes
writes and policy code decides whether each one happens; runs hand work to each other only
through the database. [`docs/ar-flows.md`](docs/ar-flows.md) has a diagram for every flow and its
endings, each tied to an eval task. They describe what the tasks specify; the agent is not built yet.

![How the flows connect](docs/ar-flow-overview.svg)

## Layout

- `docs/`: design, its diagram, the implementation plan, the flows of every event with their
  diagrams, and a walk-through of one event
- `db/`: database, tasks, splits, policy text and knowledge documents
- `ar/`: data model, ledger, policy rules, tools, and the assertions the evals use
- `evals/scoreboard.py`: pass rate, cost and latency against a baseline
- `tests/`: offline tests
