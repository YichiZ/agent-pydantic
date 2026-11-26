# Browser agent

Opens a web page in a real browser and returns typed data from it, built with
[Pydantic AI](https://pydantic.dev/docs/ai/overview/) and the Playwright browser capability from
`pydantic-ai-harness`.

`extract(url, what, output_type)` in `agent.py` opens `url`, finds `what`, and returns it as the Pydantic
model you pass. The browser is confined to the host of the URL it was given, and page content is treated
as data, never as instructions. A page that cannot be read raises `RuntimeError`.

## Run

From the repo root. The demo calls a real model (Sonnet 5.5) and needs `ANTHROPIC_API_KEY` in `.env`.

```bash
uv run python -m agents browser demo            # every quote on quotes.toscrape.com/js/, as JSON
uv run pytest agents/browser                    # offline tests, no API key, no browser
```

Playwright comes from the `browser` dependency group, installed by default; `uv sync --no-group browser`
leaves it out.
