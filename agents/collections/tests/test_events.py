"""agents/collections/db/events: every event is well formed, names real rows, and its setup replays through the real tools."""
import json
from pathlib import Path

import pytest

from agents.collections import ledger
from agents.collections.environment import call_env_function, call_tool, fresh_store

ROOT = Path(__file__).resolve().parent.parent
EVENTS = [json.loads(path.read_text()) for path in sorted((ROOT / 'db/events').glob('event_*.json'))]
TYPES = {'aging_check', 'approval_decided', 'customer_message'}


def after_setup(event: dict):
    store = fresh_store(ROOT / 'db/db.json', ROOT / 'db/documents')
    for step in (event['initial_state'] or {}).get('initialization_actions', []):
        if step['env_type'] == 'env':
            call_env_function(store, step['func_name'], step['arguments'])
        else:
            call_tool(store, event['customer_id'], step['func_name'], step['arguments'])
    return store.db


def test_there_are_twenty_collections_events_with_unique_ids():
    assert len(EVENTS) == 20
    assert len({e['id'] for e in EVENTS}) == 20
    assert {e['flow'] for e in EVENTS} == {'collections'}


@pytest.mark.parametrize('event', EVENTS, ids=lambda e: e['id'])
def test_event_is_well_formed_and_its_setup_replays(event):
    assert event['type'] in TYPES
    assert (event['ticket'] is None) != (event['user_scenario'] is None)  # exactly one way in
    db = after_setup(event)  # raises if a setup step is refused or names a missing row
    db.customer(event['customer_id'])
    if event['ticket']:
        assert event['customer_id'] in event['ticket']
    else:
        assert '###STOP###' in event['user_scenario']['instructions']


def test_setups_leave_the_amounts_the_events_describe():
    by_id = {e['id']: e for e in EVENTS}
    assert ledger.amount_due(after_setup(by_id['event_11']), ['INV-1701', 'INV-1702']) == 12050
    assert ledger.balance(after_setup(by_id['event_12']), 'INV-1502') == 9072
    assert ledger.balance(after_setup(by_id['event_15']), 'INV-2001') == 5000
    assert after_setup(by_id['event_16']).approval('apr_8001').status == 'approved'
    assert after_setup(by_id['event_17']).approval('apr_8001').status == 'rejected'
