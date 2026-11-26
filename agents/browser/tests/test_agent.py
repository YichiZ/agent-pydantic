import os

import pytest
from pydantic_ai.models.test import TestModel

from agents.browser.agent import agent


def test_agent_runs_offline():
    # No network and no model call: TestModel skips the browser tools.
    with agent.override(model=TestModel(call_tools=[])):
        assert isinstance(agent.run_sync('hello').output, str)


# Live: real model, real browser. Run with `uv run --env-file <path to .env> pytest -m e2e agents/browser`.
@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get('ANTHROPIC_API_KEY'), reason='ANTHROPIC_API_KEY is not set')
def test_reads_the_first_quote_on_quotes_toscrape():
    answer = agent.run_sync('Who wrote the first quote on https://quotes.toscrape.com/ ?').output
    assert 'Einstein' in answer
