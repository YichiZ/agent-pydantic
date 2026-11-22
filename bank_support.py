"""Bank support agent (after https://pydantic.dev/docs/ai/overview/) backed by a local workspace.

The workspace is the tau2-bench `banking_knowledge` domain; the agent reads its `db.json`
through `ctx.workspace`.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent, Capability, ModelRetry, RunContext
from pydantic_ai.capabilities import LocalWorkspace

from bank_db import Account, BankDb, CreditCardAccount, Transaction, UnknownAccountError

load_dotenv()

DATA_DIR_ENV = 'TAU2_DATA_DIR'
DOMAIN_PATH = Path('tau2') / 'domains' / 'banking_knowledge'
DB_FILE = 'db.json'
MAX_TRANSACTIONS = 50


def workspace_dir() -> Path:
    root = os.environ.get(DATA_DIR_ENV)
    if not root:
        raise RuntimeError(f'Set {DATA_DIR_ENV} to the tau2-bench `data` directory (see README).')
    path = Path(root).expanduser() / DOMAIN_PATH
    if not (path / DB_FILE).is_file():
        raise RuntimeError(f'{path / DB_FILE} not found; check {DATA_DIR_ENV}.')
    return path


@dataclass
class SupportDependencies:
    customer_id: str


class SupportOutput(BaseModel):
    support_advice: str = Field(description='Advice returned to the customer')
    block_card: bool = Field(description="Whether to block the customer's card")
    risk: int = Field(description='Risk level of query', ge=0, le=10)


async def load_db(ctx: RunContext[SupportDependencies]) -> BankDb:
    # ponytail: re-reads and validates the whole file (~270KB) per call; cache per run if it gets slow.
    return BankDb.model_validate_json(await ctx.workspace.read_text(DB_FILE))


customer_context = Capability[SupportDependencies](
    id='customer-context',
    description="Who the customer is and what's on their bank accounts.",
)


@customer_context.instructions
async def add_customer_name(ctx: RunContext[SupportDependencies]) -> str:
    # The id comes from the application, so an unknown one ends the run (UnknownCustomerError).
    customer = (await load_db(ctx)).user(ctx.deps.customer_id)
    return f"The customer's name is {customer.name!r}"


@customer_context.tool
async def list_accounts(ctx: RunContext[SupportDependencies]) -> list[Account]:
    """List the customer's bank accounts (checking, savings) with their current balances."""
    return (await load_db(ctx)).accounts_for(ctx.deps.customer_id)


@customer_context.tool
async def recent_transactions(
    ctx: RunContext[SupportDependencies], account_id: str, limit: int = 10
) -> list[Transaction]:
    """List the most recent transactions on one of the customer's bank accounts, newest first.

    Args:
        account_id: An account id returned by `list_accounts`.
        limit: How many transactions to return (1-50).
    """
    if not 1 <= limit <= MAX_TRANSACTIONS:
        raise ModelRetry(f'limit must be between 1 and {MAX_TRANSACTIONS}.')
    try:
        return (await load_db(ctx)).recent_transactions(ctx.deps.customer_id, account_id, limit)
    except UnknownAccountError as error:
        raise ModelRetry(f'{error} Call list_accounts for valid ids.') from error


credit_cards = Capability[SupportDependencies](
    id='credit-cards',
    description="The customer's credit card accounts: balance owed and reward points.",
    defer_loading=True,
)


@credit_cards.tool
async def credit_card_accounts(ctx: RunContext[SupportDependencies]) -> list[CreditCardAccount]:
    """List the customer's credit card accounts with the balance owed and reward points."""
    return (await load_db(ctx)).credit_cards_for(ctx.deps.customer_id)


support_agent = Agent(
    'anthropic:claude-sonnet-5-5',
    name='bank_support_agent',
    defer_model_check=True,  # importable (and testable) without an API key
    deps_type=SupportDependencies,
    output_type=SupportOutput,
    instructions=(
        'You are a support agent in our bank, give the '
        'customer support and judge the risk level of their query.'
    ),
    capabilities=[
        # Tools only read records, so the workspace refuses writes and commands.
        LocalWorkspace(workspace_dir(), read_only=True),
        customer_context,
        credit_cards,
    ],
)

DEMO_CUSTOMER_ID = 'lj82d4f1a9'


async def main() -> None:
    deps = SupportDependencies(customer_id=DEMO_CUSTOMER_ID)
    for question in (
        'What is my balance?',
        'I just lost my card!',
        'How much do I owe on my credit card?',
    ):
        result = await support_agent.run(question, deps=deps)
        print(f'> {question}\n{result.output}\n')


if __name__ == '__main__':
    asyncio.run(main())
