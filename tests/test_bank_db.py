from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bank_db import BankDb, UnknownAccountError, UnknownCustomerError

FIXTURE = Path(__file__).parent / 'data' / 'tau2' / 'domains' / 'banking_knowledge' / 'db.json'


@pytest.fixture(scope='module')
def db() -> BankDb:
    return BankDb.model_validate_json(FIXTURE.read_text())


def test_user_lookup(db: BankDb) -> None:
    assert db.user('u1').name == 'Jane Doe'
    with pytest.raises(UnknownCustomerError, match='nobody'):
        db.user('nobody')


def test_accounts_are_scoped_to_the_customer_with_exact_balances(db: BankDb) -> None:
    accounts = {a.account_id: a for a in db.accounts_for('u1')}
    assert set(accounts) == {'chk_u1', 'sav_u1'}
    assert accounts['chk_u1'].balance == Decimal('100.10')
    assert accounts['chk_u1'].account_class == 'checking'


def test_recent_transactions_are_newest_first_and_limited(db: BankDb) -> None:
    txns = db.recent_transactions('u1', 'chk_u1', limit=2)
    assert [t.transaction_id for t in txns] == ['t2', 't1']
    assert txns[0].date == date(2025, 12, 15)
    assert txns[1].amount == Decimal('-4.5')


@pytest.mark.parametrize('account_id', ['chk_u2', 'missing'])
def test_transactions_refuse_accounts_the_customer_does_not_own(db: BankDb, account_id: str) -> None:
    with pytest.raises(UnknownAccountError):
        db.recent_transactions('u1', account_id, limit=5)


def test_credit_card_money_strings_are_parsed(db: BankDb) -> None:
    (card,) = db.credit_cards_for('u1')
    assert card.current_balance == Decimal('1038.52')
    assert db.credit_cards_for('u2') == []
