"""Scripted stand-ins for the agent and the clerk, so the eval runner can be tested with no model."""
from collections.abc import Sequence
from typing import Any

from agents.ar.environment import call_tool
from agents.ar.evals.runner import STOP, Transcript
from agents.ar.evals.tasks import Task, UserScenario
from agents.ar.run_types import AgentFn, AgentTurn, PolicyKind, Retrieval
from agents.ar.store import Store


def replay_agent(task: Task) -> AgentFn:
    """Plays the task's reference actions on its first turn (history None), then does nothing."""

    async def agent(store: Store, customer_id: str, prompt: str, *, policy: PolicyKind = 'solo',
                    retrieval: Retrieval = 'search', golden_documents: Sequence[str] = (),
                    history: Any | None = None, thinking: bool = False) -> AgentTurn:
        actions = task.evaluation_criteria.actions if history is None else ()
        for action in actions:
            call_tool(store, customer_id, action.name, action.arguments)
        return AgentTurn(text='Done.', cost_usd=0.01, tool_calls=len(actions), history=(history or 0) + 1)

    return agent


async def noop_agent(store: Store, customer_id: str, prompt: str, *, policy: PolicyKind = 'solo',
                     retrieval: Retrieval = 'search', golden_documents: Sequence[str] = (),
                     history: Any | None = None, thinking: bool = False) -> AgentTurn:
    return AgentTurn(text='Nothing to do.', cost_usd=0.0, tool_calls=0, history=history)


async def escalate_agent(store: Store, customer_id: str, prompt: str, *, policy: PolicyKind = 'solo',
                         retrieval: Retrieval = 'search', golden_documents: Sequence[str] = (),
                         history: Any | None = None, thinking: bool = False) -> AgentTurn:
    call_tool(store, customer_id, 'escalate_to_human', {'reason': 'Please check this account.'})
    return AgentTurn(text='Escalated.', cost_usd=0.02, tool_calls=1, history=history)


async def raising_agent(store: Store, customer_id: str, prompt: str, *, policy: PolicyKind = 'solo',
                        retrieval: Retrieval = 'search', golden_documents: Sequence[str] = (),
                        history: Any | None = None, thinking: bool = False) -> AgentTurn:
    raise RuntimeError('model unavailable')


async def one_line_clerk(scenario: UserScenario, transcript: Transcript) -> str:
    """Says one line, then ends the conversation."""
    return 'Hello, I am writing about my invoice.' if not transcript else STOP
