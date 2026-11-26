# Browser agent

An agent you chat with in the terminal that browses the web in a real browser. It is a
[Pydantic AI](https://pydantic.dev/docs/ai/overview/) `Agent` with the Playwright browser capability from
`pydantic-ai-harness`, and nothing else: see `agent.py`.

It can open any public page; private and loopback addresses are blocked. The browser closes after each
turn, so the conversation carries between turns but logins and open pages do not.

```bash
uv run python -m agents browser                            # chat; needs ANTHROPIC_API_KEY in .env
uv run pytest agents/browser                                # offline test, no API key, no browser
uv run --env-file .env pytest -m e2e agents/browser         # live test against quotes.toscrape.com
```

## Eval

Task `bu2-052` of [BU Bench V2.1](https://github.com/browser-use/benchmark), scored by the benchmark's own judge:
see `evals/run.py` and [docs/eval-plan.md](docs/eval-plan.md). A trial costs about $4 for the agent plus one OpenAI
judge call; the report shows both as `agent_cost_usd` and `judge_cost_usd`. It needs `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in `.env`.

```bash
git clone https://github.com/browser-use/benchmark agents/browser/evals/.benchmark   # once; gitignored
git -C agents/browser/evals/.benchmark checkout 77b4df339fe8fc293fb48896cfa1c73dd743af42
uv run --env-file .env python -m agents.browser.evals.run 3                          # three trials, one at a time
```

Baseline (2026-11-26, 3 trials): mean score 0.72 (0.70, 0.86, 0.60). The parameters and the result per rubric item
are in [evals/runs/README.md](evals/runs/README.md). Save a run's full report to `evals/.reports/` (gitignored): it
paraphrases the benchmark's rubric, so only scores and per-item results are committed.

## Traces

Chat and eval runs can be sent to [Logfire](https://pydantic.dev/docs/logfire/), so you can see where a run went
wrong. It is off until this checkout has Logfire credentials; without them nothing is sent and nothing is printed.

Set it up once, from the repo root, with a free Logfire account and a project in it:

```bash
uvx logfire-cli --region us auth                        # sign in through the browser; --region eu for an EU account
uvx logfire-cli --region us init use --name <project>   # writes .logfire/logfire_credentials.json (gitignored)
```

Instead of the CLI, you can create a write token in the project's settings and put it in `.env` as `LOGFIRE_TOKEN`.
Either one turns tracing on; the token wins if both are set. The credentials file is only found when you run from
the repo root.

Each run then shows up in the project's Live view under the service `browser`, as one trace:

- `invoke_agent agent`: the whole run, with the final output and token usage.
- `chat claude-sonnet-5-5`: one per model request, with the messages sent and the reply. The HTTP call to Anthropic
  is the `anthropic.messages.create` span under it.
- `execute_tool <tool>`: one per tool call, with its arguments and result. A failed call is not marked as an error:
  the error text is the result the model got back.
- `browser <action>`: the browser operation under each tool call, with `browser.outcome` set to `ok` or `error`.
  What the page did during it is attached as events: console messages, page errors, responses (4xx and 5xx marked
  as errors), and failed or blocked requests.

The eval is a Pydantic Evals experiment, so its trace starts with an `evaluate run` span for the dataset
`bu_bench_v2`, with each trial's agent run under it. No eval has been run with tracing on yet.

Logfire's default scrubbing can redact text that contains words like "session" or "cookie"; the Playwright
capability's README shows how to keep it. The setup is `trace_to_logfire()` in `agent.py`.
