import pytest

from evals.scoreboard import compare, summarize


def test_summarize_averages_runs():
    rows = [
        {'passed': True, 'cost_usd': 0.02, 'seconds': 1.0},
        {'passed': False, 'cost_usd': 0.04, 'seconds': 3.0},
    ]
    assert summarize(rows) == {'runs': 2, 'pass_rate': 0.5, 'cost_usd_per_case': 0.03, 'mean_seconds': 2.0}


def test_summarize_rejects_empty():
    with pytest.raises(ValueError):
        summarize([])


def test_compare_flags_only_what_got_worse():
    baseline = {'pass_rate': 1.0, 'cost_usd_per_case': 0.03, 'mean_seconds': 2.0}
    current = {'pass_rate': 0.5, 'cost_usd_per_case': 0.01, 'mean_seconds': 2.5}
    accuracy, cost, speed = compare(current, baseline)
    assert 'WORSE' in accuracy
    assert 'WORSE' not in cost
    assert 'WORSE' in speed
