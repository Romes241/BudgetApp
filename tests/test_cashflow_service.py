from datetime import date, datetime

import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.services import cashflow_service
from budget_app.services.debt_service import add_debt
from budget_app.services.fixed_expense_service import add_fixed_expense
from budget_app.services.variable_expense_service import add_variable_expense


@pytest.fixture
def cashflow_database(tmp_path, monkeypatch):
    database_path = tmp_path / "cashflow.db"

    def connection_factory():
        return connect_database(database_path)

    with connection_factory() as connection:
        initialise_database(connection)

    for module in (
        "budget_app.services.cashflow_service",
        "budget_app.services.debt_service",
        "budget_app.services.fixed_expense_service",
        "budget_app.services.variable_expense_service",
    ):
        monkeypatch.setattr(
            f"{module}.database_connection",
            connection_factory,
        )

    monkeypatch.setattr(
        cashflow_service,
        "forecast_income_from_settings",
        lambda **kwargs: {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "entries": [],
            "total_income_pence": 0,
        },
    )

    return database_path


def set_settings(database_path, *, balance=100000, months=1):
    with connect_database(database_path) as connection:
        connection.execute(
            "UPDATE settings SET current_balance_pence = ?, "
            "projection_months = ? WHERE id = 1",
            (balance, months),
        )


def test_projection_combines_outgoings_and_calculates_running_balance(
    cashflow_database,
):
    set_settings(cashflow_database, balance=100000)

    add_fixed_expense("Rent", "Housing", "500.00", 1)
    add_debt("Credit card", "100.00", "100.00", "30.00", 2)
    add_variable_expense("Groceries", "100.00")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    assert projection["end_date"] == date(2026, 11, 30)
    assert projection["opening_balance_pence"] == 100000
    assert projection["total_outgoings_pence"] == 63000
    assert projection["closing_balance_pence"] == 37000

    assert [entry["date"] for entry in projection["entries"]] == sorted(
        entry["date"] for entry in projection["entries"]
    )

    assert projection["entries"][-1]["running_balance_pence"] == 37000


def test_variable_budget_accrues_daily_and_is_grouped_into_four_buckets(
    cashflow_database,
):
    set_settings(cashflow_database)
    add_variable_expense("Drinks", "200.00")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    allocations = [
        entry for entry in projection["entries"] if entry["type"] == "variable_expense"
    ]

    # Variable budgets use four month-local buckets rather than calendar
    # weeks, so every full month has exactly four entries.
    assert [entry["date"] for entry in allocations] == [
        date(2026, 11, 7),
        date(2026, 11, 14),
        date(2026, 11, 21),
        date(2026, 11, 30),
    ]

    assert sum(entry["money_out_pence"] for entry in allocations) == 20000

    # The final bucket contains the month's remaining days.
    assert allocations[-1]["money_out_pence"] > 0


def test_variable_budget_preserves_pennies(cashflow_database):
    set_settings(cashflow_database)
    add_variable_expense("Food", "1.01")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    allocations = [
        entry for entry in projection["entries"] if entry["type"] == "variable_expense"
    ]

    assert sum(entry["money_out_pence"] for entry in allocations) == 101


def test_variable_budget_accrues_across_month_boundaries(
    cashflow_database,
):
    set_settings(cashflow_database, months=2)
    add_variable_expense("Drinks", "200.00")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    allocations = [
        entry for entry in projection["entries"] if entry["type"] == "variable_expense"
    ]

    # November and December each contribute their full monthly budget.
    assert sum(entry["money_out_pence"] for entry in allocations) == 40000

    assert [entry["date"] for entry in allocations] == [
        date(2026, 11, 7),
        date(2026, 11, 14),
        date(2026, 11, 21),
        date(2026, 11, 30),
        date(2026, 12, 7),
        date(2026, 12, 14),
        date(2026, 12, 21),
        date(2026, 12, 31),
    ]


def test_variable_budget_only_accrues_during_projection_period(
    cashflow_database,
):
    set_settings(cashflow_database)
    add_variable_expense("Drinks", "200.00")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 15))

    allocations = [
        entry for entry in projection["entries"] if entry["type"] == "variable_expense"
    ]

    expected_november = 20000 - (20000 * 14 // 30)
    expected_december = 20000 * 14 // 31

    assert sum(entry["money_out_pence"] for entry in allocations) == (
        expected_november + expected_december
    )


def test_monthly_due_day_is_clamped_to_last_day_of_month(
    cashflow_database,
):
    set_settings(cashflow_database)
    add_fixed_expense("Subscription", "Other", "10.00", 31)

    projection = cashflow_service.generate_cashflow_projection(date(2026, 2, 1))

    expense_entries = [
        entry for entry in projection["entries"] if entry["type"] == "fixed_expense"
    ]

    assert [entry["date"] for entry in expense_entries] == [date(2026, 2, 28)]


def test_debt_repayment_is_capped_at_remaining_balance(
    cashflow_database,
):
    set_settings(cashflow_database, months=3)
    add_debt("Small debt", "50.00", "50.00", "30.00", 5)

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    repayments = [
        entry for entry in projection["entries"] if entry["type"] == "debt_repayment"
    ]

    assert [entry["money_out_pence"] for entry in repayments] == [
        3000,
        2000,
    ]

    assert [entry["date"] for entry in repayments] == [
        date(2026, 11, 5),
        date(2026, 12, 5),
    ]


def test_expenses_without_due_day_are_not_scheduled(cashflow_database):
    set_settings(cashflow_database)

    add_fixed_expense("Unscheduled", "Other", "10.00")
    add_debt("Unscheduled debt", "100.00", "100.00", "10.00")

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    assert projection["entries"] == []


def test_projection_honours_start_date_and_configured_horizon(
    cashflow_database,
):
    set_settings(cashflow_database, months=2)
    add_fixed_expense("Rent", "Housing", "500.00", 1)

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 15))

    assert projection["start_date"] == date(2026, 11, 15)
    assert projection["end_date"] == date(2027, 1, 14)

    assert [
        entry["date"]
        for entry in projection["entries"]
        if entry["type"] == "fixed_expense"
    ] == [
        date(2026, 12, 1),
        date(2027, 1, 1),
    ]


def test_projection_rejects_datetime_start_date(cashflow_database):
    with pytest.raises(ValueError, match="Start date must be a date"):
        cashflow_service.generate_cashflow_projection(datetime(2026, 11, 1))


def test_projection_maps_forecast_income_entries_and_running_balance(
    cashflow_database,
    monkeypatch,
):
    set_settings(cashflow_database, balance=10000)
    monkeypatch.setattr(
        cashflow_service,
        "forecast_income_from_settings",
        lambda **kwargs: {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "entries": [
                {
                    "date": date(2026, 11, 5),
                    "type": "regular_income",
                    "description": "Salary",
                    "amount_pence": 25000,
                },
                {
                    "date": date(2026, 11, 20),
                    "type": "bonus",
                    "description": "Bonus",
                    "amount_pence": 5000,
                    "expected_bonus_id": 42,
                },
            ],
            "total_income_pence": 30000,
        },
    )

    projection = cashflow_service.generate_cashflow_projection(date(2026, 11, 1))

    assert projection["entries"] == [
        {
            "date": date(2026, 11, 5),
            "type": "regular_income",
            "description": "Salary",
            "amount_pence": 25000,
            "source_id": None,
            "money_in_pence": 25000,
            "money_out_pence": 0,
            "running_balance_pence": 35000,
        },
        {
            "date": date(2026, 11, 20),
            "type": "bonus",
            "description": "Bonus",
            "amount_pence": 5000,
            "source_id": 42,
            "money_in_pence": 5000,
            "money_out_pence": 0,
            "running_balance_pence": 40000,
        },
    ]
    assert projection["total_income_pence"] == 30000
    assert projection["closing_balance_pence"] == 40000
