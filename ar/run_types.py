"""The contract between the agent and whatever drives it (the eval runner, a CLI, a test).

`ar.agent.run_turn` implements `AgentFn`. The eval runner takes any `AgentFn`, so its tests can
pass a scripted stand-in and never import the real agent.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ar.store import Store

PolicyKind = Literal['solo', 'chat']  # which rulebook: db/policy_solo.md or db/policy.md
Retrieval = Literal['none', 'golden', 'search']


@dataclass(frozen=True)
class AgentTurn:
    """What one agent turn produced. Writes have already happened, through the store."""

    text: str  # what the agent said: its summary, or its reply to the customer in a chat
    cost_usd: float
    tool_calls: int
    history: Any  # opaque; pass it back as `history` to continue the same conversation


class AgentFn(Protocol):
    async def __call__(
        self,
        store: Store,
        customer_id: str,
        prompt: str,
        *,
        policy: PolicyKind = 'solo',
        retrieval: Retrieval = 'search',
        golden_documents: Sequence[str] = (),
        history: Any | None = None,
    ) -> AgentTurn:
        """Run one turn for `customer_id`. `prompt` is the event text, or the customer's message.

        `golden_documents` are document ids to hand to the agent when `retrieval` is 'golden'.
        """
        ...
