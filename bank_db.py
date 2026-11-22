"""Typed, read-only view of the tau2 `banking_knowledge` database (`db.json`).

Only the tables the agent uses are modelled; unknown tables and fields are ignored.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, model_validator

DATE_FORMAT = '%m/%d/%Y'


def _parse_date(value: Any) -> Any:
    return datetime.strptime(value, DATE_FORMAT).date() if isinstance(value, str) else value


def _parse_money(value: Any) -> Any:
    """Accept '129.02', 129.02 and '$1,038.52'."""
    return value.replace('$', '').replace(',', '') if isinstance(value, str) else value


UsDate = Annotated[date, BeforeValidator(_parse_date)]
Money = Annotated[Decimal, BeforeValidator(_parse_money)]


class UnknownCustomerError(LookupError):
    pass


class UnknownAccountError(LookupError):
    pass


class User(BaseModel):
    user_id: str
    name: str


class Account(BaseModel):
    account_id: str
    user_id: str
    account_class: str = Field(validation_alias='class')
    level: str
    status: str
    balance: Money = Field(validation_alias='current_holdings')


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    date: UsDate
    description: str
    amount: Money
    type: str
    status: str


class CreditCardAccount(BaseModel):
    account_id: str
    user_id: str
    card_type: str
    current_balance: Money
    reward_points: str


class BankDb(BaseModel):
    users: dict[str, User]
    accounts: dict[str, Account]
    transactions: dict[str, Transaction] = Field(validation_alias='bank_account_transaction_history')
    credit_cards: dict[str, CreditCardAccount] = Field(validation_alias='credit_card_accounts')

    @model_validator(mode='before')
    @classmethod
    def _unwrap_tables(cls, raw: Any) -> Any:
        """Each tau2 table is `{"data": {...}, "notes": "..."}`; keep only the rows."""
        if not isinstance(raw, dict):
            return raw
        return {name: table['data'] if isinstance(table, dict) and 'data' in table else table for name, table in raw.items()}

    def user(self, user_id: str) -> User:
        try:
            return self.users[user_id]
        except KeyError:
            raise UnknownCustomerError(f'No record for customer {user_id!r}.') from None

    def accounts_for(self, user_id: str) -> list[Account]:
        return [account for account in self.accounts.values() if account.user_id == user_id]

    def recent_transactions(self, user_id: str, account_id: str, limit: int) -> list[Transaction]:
        """Newest first. Refuses accounts the customer does not own."""
        account = self.accounts.get(account_id)
        if account is None or account.user_id != user_id:
            raise UnknownAccountError(f'Customer has no account {account_id!r}.')
        owned = [txn for txn in self.transactions.values() if txn.account_id == account_id]
        return sorted(owned, key=lambda txn: txn.date, reverse=True)[:limit]

    def credit_cards_for(self, user_id: str) -> list[CreditCardAccount]:
        return [card for card in self.credit_cards.values() if card.user_id == user_id]
