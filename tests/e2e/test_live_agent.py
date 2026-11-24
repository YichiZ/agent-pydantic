"""Live runs of the agent on the real model, one per task, checked against the task's own assertions.

Run with `uv run --env-file <path to .env> pytest -m e2e`; skipped when ANTHROPIC_API_KEY is not set.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from ar.agent import run_turn
from ar.environment import check_assertion, fresh_store

DB_DIR = Path(__file__).resolve().parents[2] / 'db'
TASKS = {task['id']: task for task in json.loads((DB_DIR / 'tasks.json').read_text())}

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get('ANTHROPIC_API_KEY'), reason='ANTHROPIC_API_KEY is not set; '
                                                                       'live tests call the real model.'),
]


@pytest.mark.parametrize('task_id', ['task_04', 'task_10'])
def test_a_live_run_meets_every_assertion_of_the_task(task_id: str) -> None:
    task = TASKS[task_id]
    assert task['initial_state'] is None, 'these live tests start from the base database'
    store = fresh_store(DB_DIR / 'db.json', DB_DIR / 'documents')
    logged_before = set(store.db.action_log)
    turn = asyncio.run(run_turn(store, task['annotations']['customer_id'], task['ticket']))
    logged = [f'{row.action} {row.target_id}' for key, row in sorted(store.db.action_log.items())
              if key not in logged_before]
    print(f'\n{task_id}: {turn.tool_calls} tool calls, ${turn.cost_usd:.4f}, wrote {logged}; said: {turn.text}')
    failed = [assertion for assertion in task['evaluation_criteria']['env_assertions']
              if check_assertion(store.db, assertion['func_name'], assertion['arguments'])
              is not assertion['assert_value']]
    assert not failed, f'{task_id} failed {failed}; the agent said: {turn.text}'
