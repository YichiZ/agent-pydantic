"""The default clerk and judge, run against pydantic-ai test models: no API key, no network."""
import asyncio

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from agents.collections.evals import clerk, judge
from agents.collections.evals.runner import initialize
from agents.collections.evals.tasks import load_tasks

TASKS = {task.id: task for task in load_tasks()}


def test_the_clerk_plays_the_scenario_from_the_transcript():
    seen = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen['instructions'] = info.instructions
        seen['prompt'] = messages[-1].parts[-1].content
        return ModelResponse(parts=[TextPart('I will pay on Friday.')])

    scenario = TASKS['task_02'].user_scenario
    with clerk.clerk_agent.override(model=FunctionModel(model)):
        said = asyncio.run(clerk.haiku_clerk(scenario, (('clerk', 'Hi.'), ('agent', 'Hello, how can I help?'))))
    assert said == 'I will pay on Friday.'
    assert scenario.persona in seen['instructions'] and scenario.instructions in seen['instructions']
    assert seen['prompt'].splitlines()[1:3] == ['You: Hi.', 'Harborline: Hello, how can I help?']


def test_the_clerk_opens_the_conversation_when_the_transcript_is_empty():
    assert 'first message' in clerk.render(())
    with clerk.clerk_agent.override(model=TestModel(custom_output_text='Hello.')):
        assert asyncio.run(clerk.haiku_clerk(TASKS['task_08'].user_scenario, ())) == 'Hello.'


def test_the_judge_scores_between_zero_and_one():
    grading = {'reason': 'Polite and accurate.', 'pass': True, 'score': 1.7}
    score = asyncio.run(judge.sonnet_judge('text', 'facts', model=TestModel(custom_output_args=grading)))
    assert score == 1.0


def test_judged_text_is_new_outreach_only():
    task = TASKS['task_11']
    store = initialize(task)
    start = store.db
    assert judge.judged_text(task.id, task.annotations.customer_id, start, store.db) is None
    assert judge.judged_text('task_04', 'cus_pinecrest', start, store.db) is None


def test_ledger_facts_name_the_open_invoices():
    store = initialize(TASKS['task_12'])
    facts = judge.ledger_facts(store.db, 'cus_juniper')
    assert 'Today is 2026-11-16' in facts and 'INV-1701' in facts and 'INV-1702' in facts and 'paused' in facts


def test_ledger_facts_give_the_judge_what_a_correct_reminder_may_mention():
    """Found on the first live run: the judge marked down a correct reminder for naming the contact, the PO and
    a credit, because the facts it was given left them out."""
    store = initialize(TASKS['task_11'])
    facts = judge.ledger_facts(store.db, 'cus_garnet')
    for expected in ('Wen Zhao', 'USD', 'PO-5601', '600.00', 'pricing_variance', '37.60'):
        assert expected in facts, expected
