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
