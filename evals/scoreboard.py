"""Scoring helpers: accuracy, cost and speed for an eval report, compared with a saved baseline.

`summarize`, `compare` and `rows_from` score any pydantic-evals report. The rest is the AR grid
(plan section 2.6): pass^1 and pass^k overall and by label, never-events, human in the loop,
retrieval, tone and efficiency, computed by pure functions from `TrialResult`s.
"""

from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict

from evals.ar_projection import TableDiff

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


# The AR grid.

@dataclass(frozen=True)
class TaskLabels:
    flow: str
    disposition: str
    needs_human: bool
    uses_documents: bool  # the task has required_documents


@dataclass(frozen=True)
class TraceTurn:
    """One agent turn, for `--trace`."""

    prompt: str  # the event text, or the clerk's message
    history: Any  # the turn's `AgentTurn.history` (the whole conversation so far; opaque from a scripted agent),
    #               or, if the agent crashed on this turn, the messages its run had exchanged by then
    reply: str | None  # the agent's summary, or its reply to the clerk; None if it crashed on this turn


@dataclass(frozen=True)
class TrialTrace:
    """What the agent did in one trial, for `--trace`. Never scored."""

    chat: bool = False
    turns: tuple[TraceTurn, ...] = ()
    wrote: tuple[TableDiff, ...] = ()  # the agent's store after it ran against before: rows it added or changed


@dataclass(frozen=True)
class TrialResult:
    """One trial of one task, as scored by the runner."""

    task_id: str
    labels: TaskLabels
    passed: bool  # db_match and assertions_ok, and the agent did not crash
    db_match: bool
    assertions_ok: bool
    failed_assertions: tuple[str, ...]
    diff: tuple[TableDiff, ...]  # ACTUAL against TARGET, tables that differ only
    brought_in_person: bool  # a pending approval or an escalation that was not there before the agent ran
    cost_usd: float
    tool_calls: int
    seconds: float
    error: str | None = None  # the agent's exception, if it crashed
    tone: float | None = None  # judge score, 0 to 1; never part of passed
    tone_error: str | None = None
    trace: TrialTrace = field(default_factory=TrialTrace)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class PassRates(_Frozen):
    trials: int
    tasks: int
    pass_1: float  # mean over trials
    pass_k: float  # share of tasks that passed every one of their trials


class HumanInLoop(_Frozen):
    needs_human_trials: int
    brought_in_trials: int
    recall: float | None  # of needs_human trials, brought in a person and passed; None if none ran
    precision: float | None  # of trials that brought in a person, share on needs_human tasks; None if none did


class Efficiency(_Frozen):
    cost_usd: float  # means per trial
    seconds: float
    tool_calls: float


class Grid(_Frozen):
    k: int  # trials per task
    retrieval: str
    overall: PassRates
    by_flow: dict[str, PassRates]
    by_disposition: dict[str, PassRates]
    never_events: PassRates | None  # None when no never-event task ran
    human: HumanInLoop
    retrieval_pass_1: float | None  # on tasks with required_documents; None when none ran
    efficiency: Efficiency
    tone: float | None  # mean judge score; None when nothing was judged
    tone_trials: int


def pass_rates(trials: Sequence[TrialResult]) -> PassRates | None:
    return _rates(trials) if trials else None


def human_in_the_loop(trials: Sequence[TrialResult]) -> HumanInLoop:
    needs = [t for t in trials if t.labels.needs_human]
    brought = [t for t in trials if t.brought_in_person]
    return HumanInLoop(
        needs_human_trials=len(needs), brought_in_trials=len(brought),
        recall=_ratio(sum(t.brought_in_person and t.passed for t in needs), len(needs)),
        precision=_ratio(sum(t.labels.needs_human for t in brought), len(brought)),
    )


def grid(trials: Sequence[TrialResult], never_events: Collection[str], retrieval: str) -> Grid:
    if not trials:
        raise ValueError('No trials to score.')
    summary = summarize([{'passed': t.passed, 'cost_usd': t.cost_usd, 'seconds': t.seconds} for t in trials])
    documents = [t for t in trials if t.labels.uses_documents]
    toned = [t.tone for t in trials if t.tone is not None]
    return Grid(
        k=max(Counter(t.task_id for t in trials).values()), retrieval=retrieval, overall=_rates(trials),
        by_flow=_grouped(trials, lambda t: t.labels.flow),
        by_disposition=_grouped(trials, lambda t: t.labels.disposition),
        never_events=pass_rates([t for t in trials if t.task_id in never_events]),
        human=human_in_the_loop(trials),
        retrieval_pass_1=_ratio(sum(t.passed for t in documents), len(documents)),
        efficiency=Efficiency(cost_usd=summary['cost_usd_per_case'], seconds=summary['mean_seconds'],
                              tool_calls=round(mean(t.tool_calls for t in trials), 3)),
        tone=round(mean(toned), 4) if toned else None, tone_trials=len(toned),
    )


def grid_metrics(g: Grid) -> dict[str, float | None]:
    """Every number in the grid that can get better or worse, by a dotted name."""
    rates = {'overall': g.overall, 'never_events': g.never_events,
             **{f'by_flow.{name}': r for name, r in g.by_flow.items()},
             **{f'by_disposition.{name}': r for name, r in g.by_disposition.items()}}
    return {
        **{f'{name}.{field}': getattr(r, field) if r else None for name, r in rates.items()
           for field in ('pass_1', 'pass_k')},
        'human.recall': g.human.recall, 'human.precision': g.human.precision,
        'retrieval.pass_1': g.retrieval_pass_1, 'tone': g.tone,
        'efficiency.cost_usd': g.efficiency.cost_usd, 'efficiency.seconds': g.efficiency.seconds,
        'efficiency.tool_calls': g.efficiency.tool_calls,
    }


def compare_grid(current: Grid, baseline: Grid) -> list[str]:
    """One line per metric with its change from the baseline; efficiency is better lower, the rest higher."""
    note = (f'note: this run has k={current.k}, retrieval={current.retrieval}; '
            f'the baseline has k={baseline.k}, retrieval={baseline.retrieval}')
    before = grid_metrics(baseline)
    lines = [_compare_line(key, now, before.get(key)) for key, now in grid_metrics(current).items()]
    return ([note] if (current.k, current.retrieval) != (baseline.k, baseline.retrieval) else []) + lines


def format_grid(g: Grid) -> list[str]:
    human, cost = g.human, g.efficiency
    tone = f'{g.tone:.4f} mean over {g.tone_trials} judged trials' if g.tone is not None else 'not judged'
    return [
        f'{g.overall.tasks} tasks, {g.overall.trials} trials; columns are pass^1 and pass^{g.k}',
        _row('overall', g.overall),
        *(_row(f'flow  {name}', r) for name, r in sorted(g.by_flow.items())),
        *(_row(f'disposition  {name}', r) for name, r in sorted(g.by_disposition.items())),
        _row('never-events', g.never_events) + '  (pass^k must be 1.0)',
        f'{"human in the loop":<34} recall {_fmt(human.recall)} on {human.needs_human_trials} trials (must be 1.0); '
        f'precision {_fmt(human.precision)} on {human.brought_in_trials}',
        f'{f"retrieval ({g.retrieval})":<34} pass^1 {_fmt(g.retrieval_pass_1)} on tasks with required documents',
        f'{"tone":<34} {tone}',
        f'{"efficiency":<34} ${cost.cost_usd:.6f}, {cost.seconds:.3f} s, {cost.tool_calls:.3f} tool calls per trial',
    ]


def save_baseline(path: Path, g: Grid) -> None:
    path.write_text(g.model_dump_json(indent=2) + '\n')


def load_baseline(path: Path) -> Grid:
    return Grid.model_validate_json(path.read_text())


def _rates(trials: Sequence[TrialResult]) -> PassRates:
    by_task = _groups(trials, lambda t: t.task_id)
    return PassRates(trials=len(trials), tasks=len(by_task), pass_1=_ratio(sum(t.passed for t in trials), len(trials)),
                     pass_k=_ratio(sum(all(t.passed for t in group) for group in by_task.values()), len(by_task)))


def _grouped(trials: Sequence[TrialResult], key: Callable[[TrialResult], str]) -> dict[str, PassRates]:
    return {label: _rates(group) for label, group in _groups(trials, key).items()}


def _groups(trials: Sequence[TrialResult], key: Callable[[TrialResult], str]) -> dict[str, list[TrialResult]]:
    return {label: [t for t in trials if key(t) == label] for label in sorted({key(t) for t in trials})}


def _ratio(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _fmt(value: float | None) -> str:
    return 'n/a' if value is None else f'{value:.4f}'


def _row(label: str, rates: PassRates | None) -> str:
    numbers = 'n/a' if rates is None else f'{rates.pass_1:.4f}  {rates.pass_k:.4f}  ({rates.tasks} tasks)'
    return f'{label:<34} {numbers}'


def _compare_line(key: str, now: float | None, then: float | None) -> str:
    head = f'{key:<34} {_fmt(now):<8}'
    if then is None:
        return f'{head} no baseline value'
    if now is None:
        return f'{head} baseline was {_fmt(then)}'
    delta = now - then
    worse = delta > 0 if key.startswith('efficiency.') else delta < 0
    return f'{head} {delta:+.4f} vs baseline{"  WORSE" if worse else ""}'
