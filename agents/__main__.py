"""Run one of the agents in this repo: `python -m agents <agent> [args...]`.

An agent is a package `agents/<name>/` with a `cli.py`, or failing that an `agent.py`, whose `main(argv) -> int`
gets the rest of the arguments.
"""

import importlib
import importlib.util
import pkgutil
import sys
from collections.abc import Sequence

import agents

USAGE = 'usage: python -m agents <agent> [args...]'


def entry(name: str) -> str | None:
    """The module holding the agent's `main`: its `cli`, else its `agent`. Finding it imports only the package."""
    return next((module for module in (f'agents.{name}.cli', f'agents.{name}.agent')
                 if importlib.util.find_spec(module) is not None), None)


def available() -> list[str]:
    """The packages under agents/ that have an entry module."""
    return sorted(info.name for info in pkgutil.iter_modules(agents.__path__) if info.ispkg and entry(info.name))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    names = available()
    if not args or args[0] in ('-h', '--help'):
        print('\n'.join([USAGE, '', 'agents:', *(f'  {name}' for name in names)]))
        return 0
    if args[0] not in names:
        print(f'error: unknown agent {args[0]!r}; available: {", ".join(names)}', file=sys.stderr)
        return 2
    return importlib.import_module(entry(args[0])).main(args[1:])


if __name__ == '__main__':
    sys.exit(main())
