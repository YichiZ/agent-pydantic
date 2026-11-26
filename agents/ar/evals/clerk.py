"""The default simulated AP clerk for chat tasks: Haiku playing the task's persona. It only talks; no tools.

The agent is built with `defer_model_check`, so importing this module needs no API key; the model
is resolved on the first real call. Tests swap it with `clerk_agent.override(model=...)`.
"""

from pydantic_ai import Agent

from agents.ar.evals.runner import STOP, Transcript
from agents.ar.evals.tasks import UserScenario

CLERK_MODEL = 'anthropic:claude-haiku-5-5'
SPEAKERS = {'clerk': 'You', 'agent': 'Harborline'}

clerk_agent = Agent(CLERK_MODEL, output_type=str, name='ap_clerk', defer_model_check=True)


def instructions(scenario: UserScenario) -> str:
    return (f'{scenario.persona}\n\n{scenario.instructions}\n\n'
            'You are the customer, writing to the accounts receivable team at your supplier, Harborline. '
            f'Write only your next message, in plain text. To end the conversation, reply with only {STOP}.')


def render(transcript: Transcript) -> str:
    if not transcript:
        return 'Write your first message to Harborline.'
    lines = [f'{SPEAKERS[speaker]}: {text}' for speaker, text in transcript]
    return '\n'.join(['The conversation so far:', *lines, '', 'Write your next message.'])


async def haiku_clerk(scenario: UserScenario, transcript: Transcript) -> str:
    result = await clerk_agent.run(render(transcript), instructions=instructions(scenario))
    return result.output
