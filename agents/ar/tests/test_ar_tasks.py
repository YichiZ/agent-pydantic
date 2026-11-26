import json

import pytest

from agents.ar.evals.tasks import TASKS_PATH, TaskFileError, load_splits, load_tasks


def test_loads_the_twenty_one_tasks_typed():
    tasks = load_tasks()
    assert [t.id for t in tasks] == [f'task_{n:02d}' for n in range(1, 22)]
    chat = {t.id for t in tasks if t.user_scenario is not None}
    assert chat == {'task_02', 'task_08'}
    by_id = {t.id: t for t in tasks}
    assert by_id['task_02'].ticket is None and 'Marcus' in by_id['task_02'].user_scenario.persona
    assert [s.func_name for s in by_id['task_19'].initial_state.initialization_actions] == [
        'propose_credit', 'decide_approval']
    assert by_id['task_06'].required_documents == ('doc_deduction_reason_codes',)
    assert by_id['task_03'].annotations.needs_human is True


def test_tasks_are_frozen():
    task = load_tasks()[0]
    with pytest.raises(ValueError):
        task.id = 'task_99'


def test_loads_the_splits():
    splits = load_splits()
    assert len(splits['base']) == 21
    assert splits['never_events'] == ('task_03', 'task_07', 'task_10', 'task_11', 'task_12', 'task_14', 'task_15',
                                      'task_16', 'task_20', 'task_21')


def _write(tmp_path, content):
    path = tmp_path / 'tasks.json'
    path.write_text(content)
    return path


def test_a_file_that_is_not_json_fails_clearly(tmp_path):
    path = _write(tmp_path, '{not json')
    with pytest.raises(TaskFileError, match='tasks.json'):
        load_tasks(path)


def test_a_task_missing_a_field_fails_clearly(tmp_path):
    raw = json.loads(TASKS_PATH.read_text())
    del raw[0]['annotations']
    with pytest.raises(TaskFileError, match='annotations'):
        load_tasks(_write(tmp_path, json.dumps(raw)))


def test_a_task_with_both_ticket_and_scenario_fails(tmp_path):
    raw = json.loads(TASKS_PATH.read_text())
    raw[1]['ticket'] = 'Event: aging_check.'
    with pytest.raises(TaskFileError, match='exactly one'):
        load_tasks(_write(tmp_path, json.dumps(raw)))


def test_duplicate_task_ids_fail(tmp_path):
    raw = json.loads(TASKS_PATH.read_text())
    with pytest.raises(TaskFileError, match='task_01'):
        load_tasks(_write(tmp_path, json.dumps([raw[0], raw[0]])))


def test_a_split_naming_an_unknown_task_fails(tmp_path):
    path = tmp_path / 'splits.json'
    path.write_text(json.dumps({'base': ['task_01', 'task_99']}))
    with pytest.raises(TaskFileError, match='task_99'):
        load_splits(path)


def test_a_malformed_splits_file_fails(tmp_path):
    path = tmp_path / 'splits.json'
    path.write_text(json.dumps({'base': 'task_01'}))
    with pytest.raises(TaskFileError, match='splits.json'):
        load_splits(path)


def test_a_missing_file_fails_clearly(tmp_path):
    with pytest.raises(TaskFileError, match='cannot be read'):
        load_tasks(tmp_path / 'missing.json')
