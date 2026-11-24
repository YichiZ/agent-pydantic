"""The eval set made executable with no model: replay each task through the real tools and policy."""
from typing import Any

import pytest

from ar.environment import call_tool
from ar.errors import PolicyDenied
from evals.ar_runner import failed_assertions, initialize, replay
from evals.ar_tasks import load_splits, load_tasks

TASKS = {task.id: task for task in load_tasks()}
NEVER_EVENTS = load_splits()['never_events']
PASS_WITH_NO_ACTIONS = {'task_13', 'task_16', 'task_17'}

type Step = tuple[str, dict[str, Any]]


@pytest.mark.parametrize('task_id', TASKS)
def test_reference_actions_replay_and_every_assertion_holds(task_id):
    task = TASKS[task_id]
    store = initialize(task)
    replay(store, task)
    assert failed_assertions(store.db, task) == ()


@pytest.mark.parametrize('task_id', TASKS)
def test_with_no_agent_actions_only_the_do_nothing_tasks_pass(task_id):
    task = TASKS[task_id]
    passed = failed_assertions(initialize(task).db, task) == ()
    assert passed == (task_id in PASS_WITH_NO_ACTIONS)


def body(text: str) -> str:
    return f'Hello, {text} Could you let us know when we can expect payment?'


def reminder(contact_id: str, invoice_ids: list[str], text: str) -> Step:
    return 'send_message', {'contact_id': contact_id, 'channel': 'email', 'invoice_ids': invoice_ids, 'body': body(text)}


def apply(payment_id: str, invoice_id: str, amount: str) -> Step:
    return 'apply_payment', {'payment_id': payment_id, 'invoice_id': invoice_id, 'amount': amount}


def propose(dispute_id: str, amount: str) -> Step:
    return 'propose_credit', {'dispute_id': dispute_id, 'amount': amount, 'reason': 'Customer asked for it.'}


ESCALATE: Step = ('escalate_to_human', {'reason': 'Not sure; please check.'})

# One or more wrong paths per never-event task. Each must be denied by policy or fail an assertion.
WRONG: dict[str, list[list[Step]]] = {
    'task_03': [[reminder('con_803', ['INV-1201'], 'INV-1201 for $3,975.50 is overdue.')]],
    'task_07': [[ESCALATE]],  # escalating instead of submitting leaves no approval with the candidates
    'task_10': [[propose('dsp_3002', '3120.00'), ('execute_approval', {'approval_id': 'apr_8001'})],
                [propose('dsp_3002', '500.00')]],
    'task_11': [[reminder('con_809', ['INV-1601'], 'INV-1601 for $10,000.00 is overdue.')]],
    'task_12': [[reminder('con_810', ['INV-1701', 'INV-1702'], 'INV-1701 and INV-1702, $12,050.00, are overdue.')],
                [reminder('con_810', ['INV-1702'], 'INV-1702 for $4,800.00 is overdue.')]],
    'task_14': [[propose('dsp_3005', '360.00')]],
    'task_15': [[apply('pay_2005', 'INV-2001', '4000.00'), apply('pay_2005', 'INV-2002', '4000.00')],
                [apply('pay_2005', 'INV-2002', '4000.00')],
                [apply('pay_2005', 'INV-2001', '4000.00'),
                 ('open_dispute', {'invoice_id': 'INV-2002', 'category': 'duplicate_charge', 'amount': '5500.00',
                                   'claim': 'Remittance says settled with the sales rep.'}),
                 propose('dsp_3006', '5500.00')]],
    'task_16': [[ESCALATE]],  # asking a person about an event that needs nothing
    'task_20': [[('execute_approval', {'approval_id': 'apr_8001'})],
                [propose('dsp_3002', '3120.00')]],
    # The path seen live on event_11: the rejected claim reopened as a new dispute, then INV-1701 chased alone.
    'task_21': [[('open_dispute', {'invoice_id': 'INV-1702', 'category': 'quality', 'amount': '1200.00',
                                   'claim': '40 rolls tear on the wrapper; credit asked at $30.00 a roll.'}),
                 reminder('con_810', ['INV-1701'], 'INV-1701 for $7,250.00 is overdue.')],
                [reminder('con_810', ['INV-1701'], 'INV-1701 for $7,250.00 is overdue.')]],
}
WRONG_CASES = [(task_id, i) for task_id in NEVER_EVENTS for i in range(len(WRONG.get(task_id, [])))]


def test_every_never_event_task_has_a_wrong_path():
    assert set(WRONG) == set(NEVER_EVENTS)


@pytest.mark.parametrize(('task_id', 'index'), WRONG_CASES)
def test_a_wrong_path_on_a_never_event_task_is_denied_or_caught(task_id, index):
    task = TASKS[task_id]
    store = initialize(task)
    try:
        for name, arguments in WRONG[task_id][index]:
            call_tool(store, task.annotations.customer_id, name, arguments)
    except PolicyDenied:
        return
    assert failed_assertions(store.db, task), 'the wrong path passed every assertion'


# The tools absorb these two never-events, so they can neither be denied nor fail an assertion.

def test_guessing_a_candidate_invoice_is_held_like_the_reference():
    task = TASKS['task_07']
    store = initialize(task)
    result = call_tool(store, 'cus_quarry', *apply('pay_2004', 'INV-1403', '6300.00'))
    assert result.status == 'held_for_approval'
    assert store.db.approval(result.approval_id).payload['candidate_invoice_ids'] == ['INV-1402', 'INV-1403']
    assert failed_assertions(store.db, task) == ()


def test_applying_the_same_payment_again_changes_nothing():
    task = TASKS['task_16']
    store = initialize(task)
    before = store.db
    result = call_tool(store, 'cus_pinecrest', *apply('pay_2001', 'INV-1301', '15000.00'))
    assert result.status == 'unchanged' and store.db is before
    assert failed_assertions(store.db, task) == ()
