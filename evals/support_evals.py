"""Evals for the bank support agent. Run from the repo root:

    uv run python -m evals.support_evals

These call the real model against the real data in ./db, so they need ANTHROPIC_API_KEY
(read from .env). This file is yours: add cases and evaluators below.
"""

from dataclasses import dataclass

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from bank_support import SupportDependencies, SupportOutput, support_agent


@dataclass
class Query:
    customer_id: str
    question: str


async def ask(query: Query) -> SupportOutput:
    """The task under evaluation: one customer question, one structured answer."""
    result = await support_agent.run(query.question, deps=SupportDependencies(customer_id=query.customer_id))
    return result.output


@dataclass
class BlockCardIs(Evaluator[Query, SupportOutput]):
    """Example evaluator: passes when `block_card` has the expected value."""

    expected: bool

    def evaluate(self, ctx: EvaluatorContext[Query, SupportOutput]) -> bool:
        return ctx.output.block_card is self.expected


dataset = Dataset[Query, SupportOutput, None](
    name='bank_support',
    cases=[
        # One worked example so the file runs. Replace or extend it.
        Case(
            name='balance_question_does_not_block_card',
            inputs=Query(customer_id='lj82d4f1a9', question='What is my balance?'),
            evaluators=(BlockCardIs(expected=False),),
        ),
        # TODO: your cases.
    ],
    evaluators=[
        # TODO: evaluators that should hold for every case.
    ],
)


if __name__ == '__main__':
    report = dataset.evaluate_sync(ask)
    report.print(include_input=True, include_output=True)
