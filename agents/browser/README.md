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
see `eval.py` and [docs/eval-plan.md](docs/eval-plan.md). A trial costs about $4 for the agent plus one OpenAI
judge call, and needs `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in `.env`.

```bash
git clone https://github.com/browser-use/benchmark agents/browser/.benchmark   # once; gitignored
git -C agents/browser/.benchmark checkout 77b4df339fe8fc293fb48896cfa1c73dd743af42
uv run --env-file .env python -m agents.browser.eval 3                          # three trials, one at a time
```

Baseline: not run yet.
