"""The comparable projection: free text and the action log are left out; amounts, rows and statuses are not."""
import pytest

from ar.data_model import InvoiceStatus
from ar.environment import call_tool
from evals.ar_projection import FREE_TEXT, TableDiff, diff, project
from evals.ar_runner import initialize, replay
from evals.ar_tasks import Action, Task, load_tasks

TASKS = {task.id: task for task in load_tasks()}
TEXT_ARGUMENTS = {'body', 'claim', 'reason'}
WRITES_TEXT = [task_id for task_id, task in TASKS.items()
               if any(TEXT_ARGUMENTS & set(action.arguments) for action in task.evaluation_criteria.actions)]


def reworded(task: Task) -> Task:
    """The same reference path, every free-text argument written differently (amounts in a body are kept)."""
    actions = tuple(action.model_copy(update={'arguments': {
        key: f'Put another way. {value}' if key in TEXT_ARGUMENTS else value
        for key, value in action.arguments.items()}}) for action in task.evaluation_criteria.actions)
    return task.model_copy(update={'evaluation_criteria': task.evaluation_criteria.model_copy(
        update={'actions': actions})})


def target(task: Task):
    store = initialize(task)
    replay(store, task)
    return store.db


def with_actions(task: Task, actions: list[Action]) -> Task:
    return task.model_copy(update={'evaluation_criteria': task.evaluation_criteria.model_copy(
        update={'actions': tuple(actions)})})


def test_most_reference_paths_write_free_text():
    assert len(WRITES_TEXT) == 12


@pytest.mark.parametrize('task_id', WRITES_TEXT)
def test_replays_that_differ_only_in_free_text_compare_equal(task_id):
    task = TASKS[task_id]
    first, second = target(task), target(reworded(task))
    assert first.dump() != second.dump()  # the raw databases do differ
    assert project(first) == project(second)
    assert diff(project(first), project(second)) == ()


def test_every_free_text_field_names_a_real_table():
    tables = set(target(TASKS['task_01']).dump())
    assert {path[0] for path in FREE_TEXT} <= tables


def test_the_action_log_is_left_out():
    task = TASKS['task_04']
    store = initialize(task)
    before = project(store.db)
    call_tool(store, task.annotations.customer_id, 'escalate_to_human', {'reason': 'Just checking.'})
    assert project(store.db) == before
    assert 'action_log' not in before


def test_a_wrong_amount_does_not_compare_equal():
    task = TASKS['task_04']
    wrong = Action(action_id='04_x', requestor='assistant', name='apply_payment',
                   arguments={'payment_id': 'pay_2001', 'invoice_id': 'INV-1301', 'amount': '14000.00'})
    changes = diff(project(target(task)), project(target(with_actions(task, [wrong]))))
    assert TableDiff(table='applications', changed=('pay_2001:INV-1301 (amount)',)) in changes


def test_a_missing_row_does_not_compare_equal():
    task = TASKS['task_05']
    short = with_actions(task, list(task.evaluation_criteria.actions[:2]))
    changes = {d.table: d for d in diff(project(target(task)), project(target(short)))}
    assert changes['applications'].removed == ('pay_2002:INV-1304',)
    assert changes['applications'].added == ()


def test_an_added_row_is_reported():
    task = TASKS['task_13']
    promised = initialize(task)
    call_tool(promised, 'cus_kestrel', 'log_promise',
              {'invoice_id': 'INV-1801', 'promised_date': '2026-11-30', 'amount': '100.00'})
    changes = diff(project(target(task)), project(promised.db))
    assert changes == (TableDiff(table='promises', added=('prm_8502',)),)


def test_a_wrong_status_does_not_compare_equal():
    db = target(TASKS['task_04'])
    reopened = db.with_rows('invoices', {'INV-1301': db.invoice('INV-1301').model_copy(
        update={'status': InvoiceStatus.OPEN})})
    assert diff(project(db), project(reopened)) == (TableDiff(table='invoices', changed=('INV-1301 (status)',)),)


def test_the_draft_body_inside_an_approval_payload_is_left_out_but_the_rest_is_kept():
    projected = project(target(TASKS['task_18']))
    payload = projected['approvals']['apr_8001']['payload']
    assert 'body' not in payload
    assert payload['invoice_ids'] == ['INV-2201'] and payload['contact_id'] == 'con_819'
    assert 'reason' not in projected['approvals']['apr_8001']


def test_the_order_of_applications_does_not_matter():
    """Found on the first live run: the agent applied task 5's three lines in another order and was marked wrong."""
    task = TASKS['task_05']
    backwards = with_actions(task, list(reversed(task.evaluation_criteria.actions)))
    assert diff(project(target(task)), project(target(backwards))) == ()

