import pytest

from agents.collections.evals.run import BASELINE_PATH
from agents.collections.evals.scoreboard import (
    TaskLabels,
    TrialResult,
    compare_grid,
    format_grid,
    grid,
    grid_metrics,
    human_in_the_loop,
    load_baseline,
    pass_rates,
    save_baseline,
)
from agents.collections.evals.tasks import load_tasks


# The eval grid (plan section 2.6), on hand-built trial results.


def result(task_id, passed, *, flow='collections', disposition='act', needs_human=False, uses_documents=False,
           brought=False, assertions_ok=None, cost=0.0, seconds=0.0, tool_calls=0, tone=None):
    return TrialResult(
        task_id=task_id, labels=TaskLabels(flow=flow, disposition=disposition, needs_human=needs_human,
                                           uses_documents=uses_documents),
        passed=passed, db_match=passed, assertions_ok=passed if assertions_ok is None else assertions_ok,
        failed_assertions=(), diff=(), brought_in_person=brought, cost_usd=cost, tool_calls=tool_calls,
        seconds=seconds, tone=tone)


def test_pass_k_counts_a_task_only_if_every_trial_passed():
    rates = pass_rates([result('a', True), result('a', True), result('a', True), result('a', False)])
    assert (rates.trials, rates.tasks, rates.pass_1, rates.pass_k) == (4, 1, 0.75, 0.0)
    both = pass_rates([*(result('a', p) for p in (True, True, True, False)), *(result('b', True) for _ in range(4))])
    assert (both.pass_1, both.pass_k) == (0.875, 0.5)


def test_pass_rates_of_nothing_is_none():
    assert pass_rates([]) is None


def test_the_grid_groups_by_label():
    trials = [result('a', True, flow='disputes', disposition='ask'), result('a', False, flow='disputes', disposition='ask'),
              result('b', True, flow='collections', disposition='act'), result('b', True, flow='collections')]
    g = grid(trials, never_events={'a'}, retrieval='none')
    assert g.k == 2 and g.retrieval == 'none'
    assert set(g.by_flow) == {'disputes', 'collections'} and set(g.by_disposition) == {'ask', 'act'}
    assert (g.by_flow['disputes'].pass_1, g.by_flow['disputes'].pass_k) == (0.5, 0.0)
    assert (g.by_flow['collections'].pass_1, g.by_flow['collections'].pass_k) == (1.0, 1.0)
    assert g.never_events.pass_k == 0.0 and g.never_events.tasks == 1
    assert (g.overall.pass_1, g.overall.pass_k) == (0.75, 0.5)


def test_a_group_with_no_trials_is_none():
    g = grid([result('b', True)], never_events={'a'}, retrieval='search')
    assert g.never_events is None and g.retrieval_pass_1 is None and g.tone is None
    assert g.human.recall is None and g.human.precision is None


def test_the_grid_of_no_trials_is_an_error():
    with pytest.raises(ValueError):
        grid([], never_events=set(), retrieval='search')


def test_asking_on_every_task_scores_four_in_twenty_precision():
    trials = [result(f't{n}', n == 0, needs_human=n < 4, brought=True, assertions_ok=n == 0) for n in range(20)]
    human = human_in_the_loop(trials)
    assert (human.needs_human_trials, human.brought_in_trials) == (4, 20)
    assert human.precision == 0.2
    assert human.recall == 0.25  # only one of the four also kept to its assertions


def test_recall_needs_both_a_person_and_the_assertions():
    trials = [result('a', False, needs_human=True, brought=True, assertions_ok=False),
              result('b', True, needs_human=True, brought=True),
              result('c', False, needs_human=True, brought=False, assertions_ok=True),
              result('d', True)]
    human = human_in_the_loop(trials)
    assert human.recall == round(1 / 3, 4) and human.precision == 1.0


def test_recall_does_not_count_a_trial_that_asked_the_wrong_way():
    # Asked a person (so the assertions held) but by the wrong write, so the state did not match: not passed.
    wrong_way = result('a', False, needs_human=True, brought=True, assertions_ok=True)
    assert human_in_the_loop([wrong_way]).recall == 0.0


def test_retrieval_tone_and_efficiency():
    trials = [result('a', True, uses_documents=True, cost=0.2, seconds=4.0, tool_calls=6, tone=0.5),
              result('b', False, uses_documents=True, cost=0.4, seconds=2.0, tool_calls=2, tone=1.0),
              result('c', True, cost=0.0, seconds=0.0, tool_calls=1)]
    g = grid(trials, never_events=set(), retrieval='golden')
    assert g.retrieval_pass_1 == 0.5
    assert (g.tone, g.tone_trials) == (0.75, 2)
    assert (g.efficiency.cost_usd, g.efficiency.seconds, g.efficiency.tool_calls) == (0.2, 2.0, 3.0)


def test_metrics_compare_against_a_baseline_and_flag_what_got_worse():
    baseline = grid([result('a', True, cost=0.1), result('b', True, needs_human=True, brought=True)],
                    never_events={'a'}, retrieval='search')
    current = grid([result('a', False, cost=0.3), result('b', True, needs_human=True, brought=True)],
                   never_events={'a'}, retrieval='search')
    assert grid_metrics(current)['overall.pass_1'] == 0.5
    lines = {line.split()[0]: line for line in compare_grid(current, baseline)}
    assert 'WORSE' in lines['overall.pass_1'] and 'WORSE' in lines['never_events.pass_k']
    assert 'WORSE' in lines['efficiency.cost_usd']
    assert 'WORSE' not in lines['human.recall'] and 'WORSE' not in lines['human.precision']


def test_comparing_different_runs_says_so():
    baseline = grid([result('a', True)], never_events=set(), retrieval='search')
    current = grid([result('a', True), result('a', True), result('b', True, flow='disputes')], never_events=set(),
                   retrieval='golden')
    lines = compare_grid(current, baseline)
    assert any('k=2' in line and 'k=1' in line for line in lines)
    assert any('by_flow.disputes.pass_1' in line and 'no baseline' in line for line in lines)


def test_format_grid_prints_every_row():
    trials = [result('a', True, needs_human=True, brought=True, uses_documents=True, tone=0.9)]
    text = '\n'.join(format_grid(grid(trials, never_events={'a'}, retrieval='golden')))
    for row in ('overall', 'flow', 'disposition', 'never-events', 'human in the loop', 'retrieval (golden)', 'tone',
                'efficiency'):
        assert row in text


def test_format_grid_marks_what_is_not_applicable():
    text = '\n'.join(format_grid(grid([result('a', True)], never_events=set(), retrieval='none')))
    assert 'n/a' in text and 'not judged' in text


def test_the_baseline_round_trips(tmp_path):
    g = grid([result('a', True, tone=0.5)], never_events={'a'}, retrieval='search')
    path = tmp_path / 'baseline.json'
    save_baseline(path, g)
    assert load_baseline(path) == g


def test_the_saved_baseline_loads_and_has_a_value_for_every_flow_in_the_task_file():
    baseline = load_baseline(BASELINE_PATH)
    current = grid([result(t.id, True, flow=t.annotations.flow, disposition=t.annotations.disposition)
                    for t in load_tasks()], never_events=set(), retrieval='search')
    lines = compare_grid(current, baseline)
    flows = ('cash_application', 'collections', 'cross_flow', 'disputes')
    assert {line.split()[0] for line in lines if line.startswith('by_flow.')} == {
        f'by_flow.{flow}.{field}' for flow in flows for field in ('pass_1', 'pass_k')}
    assert not [line for line in lines if 'no baseline' in line]


def test_a_row_that_did_not_run_this_time_shows_the_old_value():
    baseline = grid([result('a', True)], never_events={'a'}, retrieval='search')
    current = grid([result('b', True)], never_events={'a'}, retrieval='search')
    lines = {line.split()[0]: line for line in compare_grid(current, baseline)}
    assert 'baseline was 1.0000' in lines['never_events.pass_k']
