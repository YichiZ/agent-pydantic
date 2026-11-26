"""The lines of a --trace view, and how they are drawn: plain, or with ANSI colours for a terminal.

`agents.ar.evals.trace` builds `Line`s and knows nothing of colour; `render` is the one place colour is applied.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

type ColorMode = Literal['auto', 'always', 'never']
COLOR_MODES: tuple[ColorMode, ...] = ('auto', 'always', 'never')

RESET = '\033[0m'
CYAN = '\033[36m'
GREY = '\033[2;37m'  # dim grey
GREEN = '\033[32m'
YELLOW = '\033[33m'
RED = '\033[31m'
MAGENTA = '\033[35m'
NO_COLOR = 'NO_COLOR'  # https://no-color.org: set to anything, it turns colour off


class Kind(StrEnum):
    """What a line shows: the block it belongs to, or, inside a tool result, a denial or a hold."""

    USER = 'user'
    REASONING = 'reasoning'
    ASSISTANT = 'assistant'
    TOOL_CALL = 'tool_call'
    TOOL_RESULT = 'tool_result'
    DENIED = 'denied'
    HELD = 'held'
    PLAIN = 'plain'  # headers, retries, errors, failures, diffs and what the agent wrote


@dataclass(frozen=True)
class Line:
    kind: Kind
    text: str
    indent: int = 0
    label: bool = False  # the block's label line, not its body


# (kind, label) -> colour; anything not here is drawn plain.
COLORS: Mapping[tuple[Kind, bool], str] = {
    (Kind.USER, True): CYAN, (Kind.USER, False): CYAN,
    (Kind.REASONING, True): GREY, (Kind.REASONING, False): GREY,
    (Kind.ASSISTANT, True): GREEN,
    (Kind.TOOL_CALL, True): YELLOW,
    (Kind.DENIED, False): RED,
    (Kind.HELD, False): MAGENTA,
}


def render(lines: Iterable[Line], color: bool) -> list[str]:
    """Each line as text, indented; with `color`, its text (not its indent) in its kind's colour."""
    return [f'{" " * line.indent}{_paint(line, color)}' if line.text else '' for line in lines]


def _paint(line: Line, color: bool) -> str:
    code = COLORS.get((line.kind, line.label)) if color else None
    return f'{code}{line.text}{RESET}' if code else line.text


def use_color(mode: ColorMode, *, isatty: bool, environ: Mapping[str, str]) -> bool:
    """'always' and 'never' decide; 'auto' colours a terminal unless NO_COLOR is set to something."""
    if mode == 'auto':
        return isatty and not environ.get(NO_COLOR)
    return mode == 'always'
