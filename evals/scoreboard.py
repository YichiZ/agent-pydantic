"""Scoring helpers: accuracy, cost and speed for an eval report, compared with a saved baseline.

The bank agent these were written for is gone; the AR eval runner will call them.
"""

from statistics import mean

COST_METRIC = 'cost_usd'
# Lower is better for these; pass_rate is the only metric where higher is better.
LOWER_IS_BETTER = ('cost_usd_per_case', 'mean_seconds')


def summarize(rows: list[dict]) -> dict:
    """rows: one {'passed': bool, 'cost_usd': float, 'seconds': float} per case run."""
    if not rows:
        raise ValueError('No case runs to score.')
    return {
        'runs': len(rows),
        'pass_rate': round(mean(1.0 if r['passed'] else 0.0 for r in rows), 4),
        'cost_usd_per_case': round(mean(r['cost_usd'] for r in rows), 6),
        'mean_seconds': round(mean(r['seconds'] for r in rows), 3),
    }


def compare(current: dict, baseline: dict) -> list[str]:
    """One line per metric: value, change from baseline, and whether it got worse."""
    lines = []
    for key in ('pass_rate', *LOWER_IS_BETTER):
        delta = current[key] - baseline[key]
        worse = delta > 0 if key in LOWER_IS_BETTER else delta < 0
        lines.append(f'{key:<18} {current[key]:<10} {delta:+.4f} vs baseline{"  WORSE" if worse else ""}')
    return lines


def rows_from(report) -> list[dict]:
    ran = [
        {
            # A case with no assertions has nothing to fail, so it counts as passed.
            'passed': all(a.value for a in case.assertions.values()) and not case.evaluator_failures,
            'cost_usd': case.metrics.get(COST_METRIC, 0.0),
            'seconds': case.task_duration,
        }
        for case in report.cases
    ]
    # The task itself raised: a failed run with no cost or time we can trust.
    crashed = [{'passed': False, 'cost_usd': 0.0, 'seconds': 0.0} for _ in report.failures]
    return ran + crashed
