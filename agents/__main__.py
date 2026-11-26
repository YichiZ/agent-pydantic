"""Run one of the agents in this repo: `python -m agents <agent> [args...]`.

An agent is a package `agents/<name>/` with a `cli.py` whose `main(argv) -> int` gets the rest of the arguments.
"""

import importlib
import importlib.util
import pkgutil
import sys
from collections.abc import Sequence

import agents

USAGE = 'usage: python -m agents <agent> [args...]'


def available() -> list[str]:
    """The packages under agents/ that have a `cli` module. Finding it imports only the package, not its cli."""
    return sorted(info.name for info in pkgutil.iter_modules(agents.__path__)
                  if info.ispkg and importlib.util.find_spec(f'agents.{info.name}.cli') is not None)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    names = available()
    if not args or args[0] in ('-h', '--help'):
        print('\n'.join([USAGE, '', 'agents:', *(f'  {name}' for name in names)]))
        return 0
    if args[0] not in names:
        print(f'error: unknown agent {args[0]!r}; available: {", ".join(names)}', file=sys.stderr)
        return 2
    return importlib.import_module(f'agents.{args[0]}.cli').main(args[1:])


if __name__ == '__main__':
    sys.exit(main())
