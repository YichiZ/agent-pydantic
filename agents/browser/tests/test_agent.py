import asyncio

import pytest
from pydantic_ai.models.test import TestModel

from agents.browser.agent import Quotes, _site, agent, extract


def test_site_confines_to_host():
    assert _site('https://www.example.com/a?b=1') == 'example.com'


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'example.com', 'javascript:alert(1)', ''])
def test_site_rejects_non_http(url):
    with pytest.raises(ValueError):
        _site(url)


def test_extract_returns_requested_type():
    # No network and no model call: TestModel skips the browser tools and fills the schema.
    with agent.override(model=TestModel(call_tools=[])):
        out = asyncio.run(extract('https://example.com', 'anything', Quotes))
    assert isinstance(out, Quotes)
