import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.fixed_expense_service import (
    add_fixed_expense,
    deactivate_fixed_expense,
    get_fixed_expense,
    get_fixed_expenses,
    update_fixed_expense,
)


@pytest.fixture
def database(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"

    with connect_database(database_path) as connection:
        initialise_database(connection)

    monkeypatch.setattr(
        "budget_app.fixed_expense_service.database_connection",
        lambda: connect_database(database_path),
    )

    return database_path


def test_add_fixed_expense(database):
    expense_id = add_fixed_expense(
        name="Rent",
        category="Housing",
        amount="470.00",
        due_day=1,
    )

    expense = get_fixed_expense(expense_id)

    assert expense is not None
    assert expense["name"] == "Rent"
    assert expense["category"] == "Housing"
    assert expense["amount_pence"] == 47000
    assert expense["amount"] == 470
    assert expense["due_day"] == 1
    assert expense["active"] == 1


def test_get_fixed_expenses_returns_active_expenses_by_default(database):
    active_id = add_fixed_expense("Rent", "Housing", 470, 1)
    inactive_id = add_fixed_expense("Old rent", "Housing", 400, 1)

    deactivate_fixed_expense(inactive_id)

    expenses = get_fixed_expenses()

    assert [expense["id"] for expense in expenses] == [active_id]


def test_get_fixed_expenses_can_include_inactive(database):
    first_id = add_fixed_expense("Rent", "Housing", 470)
    second_id = add_fixed_expense("Old rent", "Housing", 400)

    deactivate_fixed_expense(second_id)

    expenses = get_fixed_expenses(include_inactive=True)

    assert {expense["id"] for expense in expenses} == {
        first_id,
        second_id,
    }


def test_update_fixed_expense(database):
    expense_id = add_fixed_expense("Rent", "Housing", 470, 1)

    updated = update_fixed_expense(
        expense_id,
        name="New rent",
        amount="500.50",
        due_day=5,
    )

    expense = get_fixed_expense(expense_id)

    assert updated is True
    assert expense["name"] == "New rent"
    assert expense["category"] == "Housing"
    assert expense["amount_pence"] == 50050
    assert expense["due_day"] == 5


def test_update_fixed_expense_can_clear_due_day(database):
    expense_id = add_fixed_expense("Rent", "Housing", 470, 1)

    update_fixed_expense(expense_id, due_day=None)

    expense = get_fixed_expense(expense_id)

    assert expense["due_day"] is None


def test_update_preserves_fields_that_are_not_provided(database):
    expense_id = add_fixed_expense("Rent", "Housing", 470, 1)

    update_fixed_expense(expense_id, amount=500)

    expense = get_fixed_expense(expense_id)

    assert expense["name"] == "Rent"
    assert expense["category"] == "Housing"
    assert expense["amount_pence"] == 50000
    assert expense["due_day"] == 1


def test_update_returns_false_for_missing_expense(database):
    assert update_fixed_expense(999, amount=100) is False


def test_update_requires_at_least_one_field(database):
    with pytest.raises(ValueError, match="At least one field"):
        update_fixed_expense(1)


def test_deactivate_fixed_expense(database):
    expense_id = add_fixed_expense("Rent", "Housing", 470)

    assert deactivate_fixed_expense(expense_id) is True

    assert get_fixed_expenses() == []

    expense = get_fixed_expense(expense_id)
    assert expense is not None
    assert expense["active"] == 0


def test_deactivate_returns_false_for_missing_expense(database):
    assert deactivate_fixed_expense(999) is False


@pytest.mark.parametrize(
    "name",
    ["", " ", None],
)
def test_add_rejects_invalid_name(database, name):
    with pytest.raises(ValueError, match="Expense name"):
        add_fixed_expense(name, "Housing", 470)


@pytest.mark.parametrize(
    "category",
    ["", " ", None],
)
def test_add_rejects_invalid_category(database, category):
    with pytest.raises(ValueError, match="Expense category"):
        add_fixed_expense("Rent", category, 470)


@pytest.mark.parametrize(
    "amount",
    [-1, "-0.01", "not a number"],
)
def test_add_rejects_invalid_amount(database, amount):
    with pytest.raises(ValueError):
        add_fixed_expense("Rent", "Housing", amount)


@pytest.mark.parametrize(
    "due_day",
    [0, 32, -1, 1.5, True, "1"],
)
def test_add_rejects_invalid_due_day(database, due_day):
    with pytest.raises(ValueError, match="Due day"):
        add_fixed_expense("Rent", "Housing", 470, due_day)


def test_expense_persists_after_reopening_database(database):
    expense_id = add_fixed_expense("Rent", "Housing", 470, 1)

    with connect_database(database) as connection:
        expense = connection.execute(
            "SELECT * FROM fixed_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()

    assert expense["name"] == "Rent"
    assert expense["amount_pence"] == 47000
