"""The AR agent's commands: `python -m agents ar run ...` and `python -m agents ar eval ...`.

Each forwards the rest of the arguments, untouched, to the `main` of the module that parses them.
"""

import sys
from collections.abc import Sequence

from agents.ar.evals import run, run_event

USAGE = 'usage: python -m agents ar {run,eval} [args...]'
COMMANDS = {'run': run_event, 'eval': run}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ('-h', '--help'):
        print('\n'.join([USAGE, '', 'commands:',
                         *(f'  {name:<6}{module.__doc__.splitlines()[0]}' for name, module in COMMANDS.items())]))
        return 0
    if args[0] not in COMMANDS:
        print(f'error: unknown command {args[0]!r}; choose from {", ".join(COMMANDS)}', file=sys.stderr)
        return 2
    return COMMANDS[args[0]].main(args[1:])
