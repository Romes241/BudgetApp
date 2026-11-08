from datetime import date

import pytest

from budget_app.database import (
    connect_database,
    database_connection,
    initialise_database,
)
from budget_app.services.analytics_service import get_financial_analytics
from budget_app.services.payroll_service import calculate_take_home_pay


@pytest.fixture
def analytics_database(tmp_path, monkeypatch):
    database_path = tmp_path / "analytics.db"

    def connection_factory():
        return database_connection(database_path)

    monkeypatch.setattr(
        "budget_app.services.analytics_service.database_connection",
        connection_factory,
    )
    with connect_database(database_path) as connection:
        initialise_database(connection)
    return database_path


def add_income(database_path, pay_date, gross, tax, ni, pension, other, net):
    with connect_database(database_path) as connection:
        connection.execute(
            """INSERT INTO income_history (
                pay_date, gross_pay_pence, tax_paid_pence, ni_paid_pence,
                pension_paid_pence, other_deductions_pence, net_pay_pence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pay_date, gross, tax, ni, pension, other, net),
        )


def test_monthly_income_sums_actual_payslips_and_fills_missing_months(
    analytics_database,
):
    add_income(analytics_database, "2026-08-31", 999, 0, 0, 0, 0, 999)
    add_income(
        analytics_database, "2026-09-30", 300000, 25000, 15000, 10000, 5000, 245000
    )
    add_income(analytics_database, "2026-11-07", 200000, 15000, 12000, 8000, 0, 165000)
    add_income(analytics_database, "2026-11-09", 500000, 0, 0, 0, 0, 500000)

    result = get_financial_analytics(
        months=3,
        as_of_date=date(2026, 11, 8),
    )

    assert [month["month"] for month in result["income_months"]] == [
        "2026-09",
        "2026-10",
        "2026-11",
    ]
    september, october, november = result["income_months"]
    assert september["gross_pay_pence"] == 300000
    assert september["tax_paid_pence"] == 25000
    assert september["ni_paid_pence"] == 15000
    assert september["pension_paid_pence"] == 10000
    assert september["other_deductions_pence"] == 5000
    assert september["net_pay_pence"] == 245000
    assert october["gross_pay_pence"] == 0
    assert november["net_pay_pence"] == 165000
    assert result["has_income_history"] is True


def test_planned_totals_include_active_items_only_and_goals_are_capped(
    analytics_database,
):
    with connect_database(analytics_database) as connection:
        connection.executemany(
            "INSERT INTO fixed_expenses (name, category, amount_pence, active) VALUES (?, ?, ?, ?)",
            [
                ("Rent", "Housing", 100000, 1),
                ("Old service", "Bills", 99000, 0),
            ],
        )
        connection.executemany(
            "INSERT INTO variable_expenses (name, monthly_amount_pence, active) VALUES (?, ?, ?)",
            [("Food", 30000, 1), ("Inactive budget", 50000, 0)],
        )
        connection.executemany(
            """INSERT INTO debts (
                name, balance_pence, monthly_payment_pence, active, original_balance_pence
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                ("Card", 500000, 20000, 1, 500000),
                ("Closed", 0, 99000, 0, 99000),
            ],
        )
        connection.executemany(
            """INSERT INTO savings_goals (
                name, target_amount_pence, current_amount_pence,
                monthly_contribution_pence, active
            ) VALUES (?, ?, ?, ?, ?)""",
            [
                ("Emergency fund", 1000000, 250000, 50000, 1),
                ("Holiday", 100000, 150000, 10000, 1),
                ("Archived", 500000, 100000, 90000, 0),
            ],
        )

    result = get_financial_analytics(months=1, as_of_date=date(2026, 11, 8))
    commitments = {
        item["category"]: item["amount_pence"] for item in result["planned_commitments"]
    }

    assert commitments == {
        "Fixed expenses": 100000,
        "Variable budgets": 30000,
        "Debt payments": 20000,
        "Savings contributions": 60000,
    }
    assert result["planned_monthly_total_pence"] == 210000
    assert result["has_planned_commitments"] is True
    assert [goal["progress_percent"] for goal in result["savings_goals"]] == [25, 100]


def test_empty_database_returns_zero_months_and_empty_planned_sections(
    analytics_database,
):
    result = get_financial_analytics(months=3, as_of_date=date(2026, 11, 8))

    assert len(result["income_months"]) == 3
    assert all(month["gross_pay_pence"] == 0 for month in result["income_months"])
    assert result["has_income_history"] is False
    assert result["has_planned_commitments"] is False
    assert result["planned_monthly_total_pence"] == 0
    assert result["savings_goals"] == []
    assert result["monthly_income_baseline_pence"] is None


@pytest.mark.parametrize("months", [0, 121, True, 3.5])
def test_rejects_invalid_analytics_periods(analytics_database, months):
    with pytest.raises(ValueError, match="between 1 and 120"):
        get_financial_analytics(months=months, as_of_date=date(2026, 11, 8))


def test_rejects_datetime_as_analytics_date(analytics_database):
    from datetime import datetime

    with pytest.raises(ValueError, match="must be a date"):
        get_financial_analytics(as_of_date=datetime(2026, 11, 8))


def test_monthly_income_baseline_uses_saved_payroll_settings(analytics_database):
    with connect_database(analytics_database) as connection:
        connection.execute(
            """UPDATE settings SET hourly_wage_pence = 1500, average_hours = 20,
                pay_frequency = 'weekly', tax_code = '1257L', ni_category = 'A',
                scottish_taxpayer = 0 WHERE id = 1"""
        )

    weekly = calculate_take_home_pay(
        hourly_wage_pence=1500,
        average_hours=20,
        frequency="weekly",
        tax_code="1257L",
        ni_category="A",
        scottish_taxpayer=False,
        pension_percent=0,
        student_loan_plan="None",
        tax_year="2026-27",
    )
    result = get_financial_analytics(months=3, as_of_date=date(2026, 11, 8))

    assert result["income_baseline_method"] == "settings_estimate"
    assert result["monthly_income_baseline_pence"] == round(
        weekly["net_pay_pence"] * 52 / 12
    )


def test_income_baseline_falls_back_to_average_months_with_recorded_payslips(
    analytics_database,
):
    add_income(analytics_database, "2026-09-30", 30000, 0, 0, 0, 0, 24000)
    add_income(analytics_database, "2026-11-07", 60000, 0, 0, 0, 0, 48000)

    result = get_financial_analytics(months=3, as_of_date=date(2026, 11, 8))

    assert result["income_baseline_method"] == "recorded_average"
    assert result["monthly_income_baseline_pence"] == 36000
