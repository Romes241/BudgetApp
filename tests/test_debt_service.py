from datetime import date

import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.debt_service import (
    add_debt,
    deactivate_debt,
    get_debt,
    get_debts,
    record_debt_payment,
    update_debt,
)


@pytest.fixture
def database(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"

    with connect_database(database_path) as connection:
        initialise_database(connection)

    monkeypatch.setattr(
        "budget_app.debt_service.database_connection",
        lambda: connect_database(database_path),
    )

    return database_path


def test_add_debt(database):
    debt_id = add_debt(
        name="Credit card",
        balance="1200.00",
        original_balance="1500.00",
        monthly_payment="75.00",
        due_day=15,
        last_payment_date="2026-10-01",
    )

    debt = get_debt(debt_id)

    assert debt is not None
    assert debt["name"] == "Credit card"
    assert debt["balance_pence"] == 120000
    assert debt["balance"] == 1200
    assert debt["original_balance_pence"] == 150000
    assert debt["original_balance"] == 1500
    assert debt["monthly_payment_pence"] == 7500
    assert debt["monthly_payment"] == 75
    assert debt["due_day"] == 15
    assert debt["last_payment_date"] == "2026-10-01"
    assert debt["active"] == 1


def test_add_debt_defaults(database):
    debt_id = add_debt(
        name="Personal loan",
        balance=2000,
        original_balance=2000,
    )

    debt = get_debt(debt_id)

    assert debt["monthly_payment_pence"] == 0
    assert debt["due_day"] is None
    assert debt["last_payment_date"] is None
    assert debt["active"] == 1


def test_get_debts_returns_active_by_default(database):
    active_id = add_debt("Credit card", 1200, 1500)
    inactive_id = add_debt("Old loan", 0, 1000)

    deactivate_debt(inactive_id)

    debts = get_debts()

    assert [debt["id"] for debt in debts] == [active_id]


def test_get_debts_can_include_inactive(database):
    first_id = add_debt("Credit card", 1200, 1500)
    second_id = add_debt("Old loan", 0, 1000)

    deactivate_debt(second_id)

    debts = get_debts(include_inactive=True)

    assert {debt["id"] for debt in debts} == {
        first_id,
        second_id,
    }


def test_update_debt(database):
    debt_id = add_debt("Credit card", 1200, 1500)

    updated = update_debt(
        debt_id,
        name="Updated card",
        balance=1000,
        monthly_payment=100,
        due_day=20,
    )

    debt = get_debt(debt_id)

    assert updated is True
    assert debt["name"] == "Updated card"
    assert debt["balance_pence"] == 100000
    assert debt["monthly_payment_pence"] == 10000
    assert debt["due_day"] == 20


def test_update_preserves_unmodified_fields(database):
    debt_id = add_debt(
        "Credit card",
        1200,
        1500,
        monthly_payment=75,
        due_day=15,
    )

    update_debt(debt_id, monthly_payment=100)

    debt = get_debt(debt_id)

    assert debt["name"] == "Credit card"
    assert debt["balance_pence"] == 120000
    assert debt["original_balance_pence"] == 150000
    assert debt["monthly_payment_pence"] == 10000
    assert debt["due_day"] == 15


def test_update_can_clear_due_day_and_payment_date(database):
    debt_id = add_debt(
        "Credit card",
        1200,
        1500,
        due_day=15,
        last_payment_date="2026-10-01",
    )

    update_debt(
        debt_id,
        due_day=None,
        last_payment_date=None,
    )

    debt = get_debt(debt_id)

    assert debt["due_day"] is None
    assert debt["last_payment_date"] is None


def test_update_returns_false_for_missing_debt(database):
    assert update_debt(999, balance=100) is False


def test_update_requires_at_least_one_field(database):
    with pytest.raises(ValueError, match="At least one field"):
        update_debt(1)


def test_update_rejects_balance_above_original(database):
    debt_id = add_debt("Credit card", 1200, 1500)

    with pytest.raises(
        ValueError,
        match="cannot exceed original balance",
    ):
        update_debt(debt_id, balance=1600)


def test_add_rejects_balance_above_original(database):
    with pytest.raises(
        ValueError,
        match="cannot exceed original balance",
    ):
        add_debt("Credit card", 1600, 1500)


def test_record_debt_payment(database):
    debt_id = add_debt(
        "Credit card",
        balance=1200,
        original_balance=1500,
    )

    result = record_debt_payment(
        debt_id,
        amount=100,
        payment_date="2026-10-31",
    )

    debt = get_debt(debt_id)

    assert result is True
    assert debt["balance_pence"] == 110000
    assert debt["last_payment_date"] == "2026-10-31"


def test_record_debt_payment_accepts_date_object(database):
    debt_id = add_debt("Credit card", 1200, 1500)

    record_debt_payment(
        debt_id,
        amount=100,
        payment_date=date(2026, 10, 31),
    )

    debt = get_debt(debt_id)

    assert debt["last_payment_date"] == "2026-10-31"


def test_record_debt_payment_rejects_payment_above_balance(database):
    debt_id = add_debt("Credit card", 100, 1500)

    with pytest.raises(ValueError, match="cannot exceed"):
        record_debt_payment(
            debt_id,
            amount=200,
            payment_date="2026-10-31",
        )

    assert get_debt(debt_id)["balance_pence"] == 10000


def test_record_debt_payment_rejects_zero_amount(database):
    debt_id = add_debt("Credit card", 100, 1500)

    with pytest.raises(ValueError, match="greater than zero"):
        record_debt_payment(
            debt_id,
            amount=0,
            payment_date="2026-10-31",
        )


def test_record_debt_payment_returns_false_for_missing_debt(database):
    assert (
        record_debt_payment(
            999,
            100,
            "2026-10-31",
        )
        is False
    )


def test_deactivate_debt(database):
    debt_id = add_debt("Credit card", 1200, 1500)

    assert deactivate_debt(debt_id) is True
    assert get_debts() == []

    debt = get_debt(debt_id)

    assert debt is not None
    assert debt["active"] == 0


def test_deactivate_returns_false_for_missing_debt(database):
    assert deactivate_debt(999) is False


@pytest.mark.parametrize("name", ["", " ", None])
def test_add_rejects_invalid_name(database, name):
    with pytest.raises(ValueError, match="Debt name"):
        add_debt(name, 100, 100)


@pytest.mark.parametrize(
    "amount",
    [-1, "-0.01", "not a number"],
)
def test_add_rejects_invalid_amounts(database, amount):
    with pytest.raises(ValueError):
        add_debt("Credit card", amount, 100)


@pytest.mark.parametrize(
    "due_day",
    [0, 32, -1, 1.5, True, "1"],
)
def test_add_rejects_invalid_due_day(database, due_day):
    with pytest.raises(ValueError, match="Due day"):
        add_debt(
            "Credit card",
            100,
            100,
            due_day=due_day,
        )


@pytest.mark.parametrize(
    "payment_date",
    ["31-10-2026", "2026-02-30", "not a date"],
)
def test_add_rejects_invalid_payment_date(database, payment_date):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        add_debt(
            "Credit card",
            100,
            100,
            last_payment_date=payment_date,
        )


def test_debt_persists_after_reopening_database(database):
    debt_id = add_debt(
        "Credit card",
        1200,
        1500,
        monthly_payment=75,
        due_day=15,
    )

    with connect_database(database) as connection:
        debt = connection.execute(
            "SELECT * FROM debts WHERE id = ?",
            (debt_id,),
        ).fetchone()

    assert debt["name"] == "Credit card"
    assert debt["balance_pence"] == 120000
    assert debt["original_balance_pence"] == 150000
