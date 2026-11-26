import os
import warnings

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.browser.agent import agent, trace_to_logfire


def test_agent_runs_offline():
    # No network and no model call: TestModel skips the browser tools.
    with agent.override(model=TestModel(call_tools=[])):
        assert isinstance(agent.run_sync('hello').output, str)


def test_tracing_without_a_token_is_silent(monkeypatch, tmp_path, capsys):
    # A fresh clone or CI: no LOGFIRE_TOKEN and no .logfire/ credentials. Nothing may raise, warn or print.
    monkeypatch.delenv('LOGFIRE_TOKEN', raising=False)
    monkeypatch.chdir(tmp_path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            trace_to_logfire()
            with agent.override(model=TestModel(call_tools=[])):
                agent.run_sync('hello')
    finally:
        Agent.instrument_all(False)  # instrumentation is global; leave the other tests as they were
    assert capsys.readouterr() == ('', '')


# Live: real model, real browser. Run with `uv run --env-file <path to .env> pytest -m e2e agents/browser`.
@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get('ANTHROPIC_API_KEY'), reason='ANTHROPIC_API_KEY is not set')
def test_reads_the_first_quote_on_quotes_toscrape():
    answer = agent.run_sync('Who wrote the first quote on https://quotes.toscrape.com/ ?').output
    assert 'Einstein' in answer
