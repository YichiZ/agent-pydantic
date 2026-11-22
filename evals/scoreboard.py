"""Scoreboard: accuracy, cost and speed for the eval dataset, compared with a saved baseline.

    uv run python -m evals.scoreboard              # run and compare with evals/baseline.json
    uv run python -m evals.scoreboard --repeat 5   # each case 5 times, to see past model noise
    uv run python -m evals.scoreboard --save       # also make this run the new baseline

Uses the cases and evaluators in evals/support_evals.py as they are; it only swaps in a task
that also records token cost.
"""

import argparse
import json
from pathlib import Path
from statistics import mean

from pydantic_evals.dataset import increment_eval_metric

from bank_support import SupportDependencies, SupportOutput, support_agent
from evals.support_evals import Query, dataset

BASELINE = Path(__file__).parent / 'baseline.json'
COST_METRIC = 'cost_usd'
# Lower is better for these; pass_rate is the only metric where higher is better.
LOWER_IS_BETTER = ('cost_usd_per_case', 'mean_seconds')


async def ask_with_cost(query: Query) -> SupportOutput:
    result = await support_agent.run(query.question, deps=SupportDependencies(customer_id=query.customer_id))
    increment_eval_metric(COST_METRIC, float(result.usage.cost or 0))
    return result.output


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--save', action='store_true', help='write this run to evals/baseline.json')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be at least 1')

    report = dataset.evaluate_sync(ask_with_cost, repeat=args.repeat)
    report.print(include_input=True, include_output=True)
    current = summarize(rows_from(report))

    if BASELINE.is_file():
        print('\n'.join(compare(current, json.loads(BASELINE.read_text()))))
    else:
        print(json.dumps(current, indent=2))
        print(f'No baseline yet; run with --save to create {BASELINE.name}.')
    if args.save:
        BASELINE.write_text(json.dumps(current, indent=2) + '\n')
        print(f'Saved baseline to {BASELINE}.')


if __name__ == '__main__':
    main()
