"""The browser agent's commands: `python -m agents browser demo`."""

import asyncio
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from agents.browser.agent import Quotes, extract

USAGE = 'usage: python -m agents browser demo'
DEMO_URL = 'https://quotes.toscrape.com/js/'  # renders quotes with JavaScript, so it needs a real browser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ('-h', '--help'):
        print(f'{USAGE}\n\ncommands:\n  demo  extract every quote on the first page of {DEMO_URL}')
        return 0
    if args != ['demo']:
        print(f'error: unknown command {" ".join(args)!r}; {USAGE}', file=sys.stderr)
        return 2
    load_dotenv()  # ANTHROPIC_API_KEY from .env; real env vars win
    try:
        found = asyncio.run(extract(DEMO_URL, 'every quote on the first page', Quotes))
    except RuntimeError as error:  # the agent reported the page unreadable
        print(f'error: {error}', file=sys.stderr)
        return 1
    print(found.model_dump_json(indent=2))
    return 0
