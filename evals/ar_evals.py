"""Run the AR eval set against the agent; print each task, the grid, and the change from the baseline.

    uv run python -m evals.ar_evals                       # all 20 tasks, one trial
    uv run python -m evals.ar_evals --trials 4            # pass^4
    uv run python -m evals.ar_evals --split never_events
    uv run python -m evals.ar_evals --task task_04 task_10
    uv run python -m evals.ar_evals --retrieval golden    # none | golden | search
    uv run python -m evals.ar_evals --judge               # tone score on tasks 1, 11, 12 and 18
    uv run python -m evals.ar_evals --task task_11 --trace  # also what the agent did, step by step, in each trial
    uv run python -m evals.ar_evals --save                # make this run evals/ar_baseline.json

Exits 1 if a never-event task failed any trial or human-in-the-loop recall is below 1.0, else 0.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from ar.agent import run_turn
from evals.ar_projection import diff_text
from evals.ar_runner import DEFAULT_CONCURRENCY, run_tasks
from evals.ar_tasks import TaskFileError, load_splits, load_tasks
from evals.clerk import haiku_clerk
from evals.judge import sonnet_judge
from evals.scoreboard import Grid, TrialResult, compare_grid, format_grid, grid, load_baseline, save_baseline
from evals.trace import trial_lines

BASELINE_PATH = Path(__file__).resolve().parent / 'ar_baseline.json'
DEFAULT_SPLIT = 'base'
NEVER_EVENTS_SPLIT = 'never_events'


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()  # ANTHROPIC_API_KEY from .env, found by walking up from this file; real env vars win
    try:
        tasks = load_tasks()
        splits = load_splits(task_ids={t.id for t in tasks})
    except TaskFileError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    args = parse_args(argv, [t.id for t in tasks], sorted(splits))
    wanted = set(args.task or splits[args.split or DEFAULT_SPLIT])
    trials = asyncio.run(run_tasks(
        [t for t in tasks if t.id in wanted], run_turn, trials=args.trials, concurrency=args.concurrency,
        clerk=haiku_clerk, retrieval=args.retrieval, judge=sonnet_judge if args.judge else None,
        progress=sys.stdout.isatty()))
    result = grid(trials, never_events=set(splits.get(NEVER_EVENTS_SPLIT, ())), retrieval=args.retrieval)
    failures = gate(result)
    print('\n'.join([*task_lines(trials, trace=args.trace), '', *format_grid(result), '',
                     *baseline_lines(result, args.save),
                     *(f'FAIL: {reason}' for reason in failures)]))
    return 1 if failures else 0


def parse_args(argv: Sequence[str] | None, task_ids: Sequence[str], split_names: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='python -m evals.ar_evals', description=__doc__.splitlines()[0])
    parser.add_argument('--trials', type=positive_int, default=1, help='trials per task (k in pass^k); default 1')
    which = parser.add_mutually_exclusive_group()
    which.add_argument('--split', choices=split_names, help=f'tasks of one split; default {DEFAULT_SPLIT}')
    which.add_argument('--task', nargs='+', choices=task_ids, metavar='ID', help='these tasks only')
    parser.add_argument('--retrieval', choices=('none', 'golden', 'search'), default='search')
    parser.add_argument('--concurrency', type=positive_int, default=DEFAULT_CONCURRENCY,
                        help=f'trials at once; default {DEFAULT_CONCURRENCY}')
    parser.add_argument('--judge', action='store_true', help='score tone on tasks 1, 11, 12 and 18 (Sonnet)')
    parser.add_argument('--trace', action='store_true', help="under each task, every trial's tool calls step by step")
    parser.add_argument('--save', action='store_true', help=f'write the grid to {BASELINE_PATH.name}')
    return parser.parse_args(argv)


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f'{text!r} is not a whole number') from error
    if value < 1:
        raise argparse.ArgumentTypeError(f'must be at least 1, got {value}')
    return value


def gate(result: Grid) -> list[str]:
    """Why the run fails its gates; empty when it passes. A row with no trials (None) gates nothing."""
    checks = (
        (result.never_events is not None and result.never_events.pass_k < 1.0,
         'a never-event task failed at least one trial'),
        (result.human.recall is not None and result.human.recall < 1.0, 'human-in-the-loop recall is below 1.0'),
    )
    return [reason for failed, reason in checks if failed]


def task_lines(trials: Sequence[TrialResult], trace: bool = False) -> list[str]:
    """One line per task, in run order: passes/trials, then what went wrong in any trial. With `trace`, each
    task's trials follow its line, one block each, and a blank line separates the tasks."""
    groups = {task_id: [t for t in trials if t.task_id == task_id] for task_id in dict.fromkeys(t.task_id for t in trials)}
    if not trace:
        return [_task_line(task_id, group) for task_id, group in groups.items()]
    return [line for i, (task_id, group) in enumerate(groups.items())
            for line in [*([''] if i else []), _task_line(task_id, group), *_trial_blocks(group)]]


def _trial_blocks(trials: Sequence[TrialResult]) -> list[str]:
    return [line for number, trial in enumerate(trials, 1) for line in trial_lines(number, trial)]


def _task_line(task_id: str, trials: Sequence[TrialResult]) -> str:
    failed = sorted({label for t in trials for label in t.failed_assertions})
    diffs = sorted({diff_text(d) for t in trials for d in t.diff})
    errors = sorted({t.error for t in trials if t.error})
    details = [f'failed: {"; ".join(failed)}' if failed else '', f'db: {"; ".join(diffs)}' if diffs else '',
               f'error: {"; ".join(errors)}' if errors else '']
    return '  '.join([task_id, f'{sum(t.passed for t in trials)}/{len(trials)}', *filter(None, details)])


def baseline_lines(result: Grid, save: bool) -> list[str]:
    if save:
        save_baseline(BASELINE_PATH, result)
        return [f'Saved baseline to {BASELINE_PATH}.']
    if not BASELINE_PATH.is_file():
        return [f'No baseline yet; run with --save to create {BASELINE_PATH.name}.']
    try:
        baseline = load_baseline(BASELINE_PATH)
    except ValidationError as error:
        return [f'{BASELINE_PATH} is not a saved grid ({error.error_count()} errors); run with --save to replace it.']
    return ['Against the baseline:', *compare_grid(result, baseline)]


if __name__ == '__main__':
    sys.exit(main())
