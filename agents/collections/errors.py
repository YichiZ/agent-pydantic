"""Errors a tool call raises. Each message says what to change, so the agent can retry."""

from agents.collections.data_model import UnknownIdError


class ToolError(Exception):
    """A tool call that was refused. Nothing was written."""


class PolicyDenied(ToolError):
    """A write (or read) a policy rule forbids. `rule` is "P1".."P15"; `reason` is one sentence to act on."""

    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(f'Denied by {rule}: {reason}')
        self.rule = rule
        self.reason = reason


class InvalidArgumentError(ToolError):
    """An argument that is malformed, or that does not fit the row it names."""


class UnknownToolError(ToolError):
    """A tool, environment function or assertion name that does not exist."""


# What a caller (the agent wrapper) should turn into a retry: refusals and unknown ids.
TOOL_ERRORS: tuple[type[Exception], ...] = (ToolError, UnknownIdError)
