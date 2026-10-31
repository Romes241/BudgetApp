import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.variable_expense_service import (
    add_variable_expense,
    deactivate_variable_expense,
    get_variable_expense,
    get_variable_expenses,
    update_variable_expense,
)


@pytest.fixture
def database(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"

    with connect_database(database_path) as connection:
        initialise_database(connection)

    monkeypatch.setattr(
        "budget_app.variable_expense_service.database_connection",
        lambda: connect_database(database_path),
    )

    return database_path


def test_add_variable_expense(database):
    expense_id = add_variable_expense(
        name="Groceries",
        monthly_amount="250.00",
    )

    expense = get_variable_expense(expense_id)

    assert expense is not None
    assert expense["name"] == "Groceries"
    assert expense["monthly_amount_pence"] == 25000
    assert expense["monthly_amount"] == 250
    assert expense["active"] == 1


def test_get_variable_expenses_returns_active_by_default(database):
    active_id = add_variable_expense("Groceries", 250)
    inactive_id = add_variable_expense("Entertainment", 100)

    deactivate_variable_expense(inactive_id)

    expenses = get_variable_expenses()

    assert [expense["id"] for expense in expenses] == [active_id]


def test_get_variable_expenses_can_include_inactive(database):
    first_id = add_variable_expense("Groceries", 250)
    second_id = add_variable_expense("Entertainment", 100)

    deactivate_variable_expense(second_id)

    expenses = get_variable_expenses(include_inactive=True)

    assert {expense["id"] for expense in expenses} == {
        first_id,
        second_id,
    }


def test_update_variable_expense(database):
    expense_id = add_variable_expense("Groceries", 250)

    updated = update_variable_expense(
        expense_id,
        name="Food shopping",
        monthly_amount="300.50",
    )

    expense = get_variable_expense(expense_id)

    assert updated is True
    assert expense["name"] == "Food shopping"
    assert expense["monthly_amount_pence"] == 30050
    assert expense["monthly_amount"] == 300.50


def test_update_can_change_name_only(database):
    expense_id = add_variable_expense("Groceries", 250)

    update_variable_expense(
        expense_id,
        name="Food shopping",
    )

    expense = get_variable_expense(expense_id)

    assert expense["name"] == "Food shopping"
    assert expense["monthly_amount_pence"] == 25000


def test_update_can_change_monthly_amount_only(database):
    expense_id = add_variable_expense("Groceries", 250)

    update_variable_expense(
        expense_id,
        monthly_amount=300,
    )

    expense = get_variable_expense(expense_id)

    assert expense["name"] == "Groceries"
    assert expense["monthly_amount_pence"] == 30000


def test_update_returns_false_for_missing_expense(database):
    assert update_variable_expense(999, monthly_amount=100) is False


def test_update_requires_at_least_one_field(database):
    with pytest.raises(ValueError, match="At least one field"):
        update_variable_expense(1)


def test_deactivate_variable_expense(database):
    expense_id = add_variable_expense("Groceries", 250)

    assert deactivate_variable_expense(expense_id) is True

    assert get_variable_expenses() == []

    expense = get_variable_expense(expense_id)

    assert expense is not None
    assert expense["active"] == 0


def test_deactivate_returns_false_for_missing_expense(database):
    assert deactivate_variable_expense(999) is False


@pytest.mark.parametrize(
    "name",
    ["", " ", None],
)
def test_add_rejects_invalid_name(database, name):
    with pytest.raises(ValueError, match="Expense name"):
        add_variable_expense(name, 250)


@pytest.mark.parametrize(
    "amount",
    [-1, "-0.01", "not a number"],
)
def test_add_rejects_invalid_monthly_amount(database, amount):
    with pytest.raises(ValueError):
        add_variable_expense("Groceries", amount)


def test_update_rejects_negative_monthly_amount(database):
    expense_id = add_variable_expense("Groceries", 250)

    with pytest.raises(ValueError, match="cannot be negative"):
        update_variable_expense(
            expense_id,
            monthly_amount=-10,
        )


def test_variable_expense_persists_after_reopening_database(database):
    expense_id = add_variable_expense("Groceries", 250)

    with connect_database(database) as connection:
        expense = connection.execute(
            "SELECT * FROM variable_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()

    assert expense["name"] == "Groceries"
    assert expense["monthly_amount_pence"] == 25000
