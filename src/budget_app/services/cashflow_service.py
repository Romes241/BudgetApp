"""Generate a chronological cashflow projection from existing financial data."""

import calendar
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from budget_app.database import database_connection
from budget_app.services.debt_service import get_debts
from budget_app.services.fixed_expense_service import get_fixed_expenses
from budget_app.services.forecast_service import forecast_income_from_settings
from budget_app.services.variable_expense_service import get_variable_expenses


def _validate_date(value: date, field_name: str) -> date:
    """Require a date, excluding datetime values."""
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date.")
    return value


def _add_months(value: date, months: int) -> date:
    """Advance by calendar months, clamping to the month's final day."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _month_dates(start_date: date, end_date: date):
    """Yield the first day of each calendar month in an inclusive range."""
    current = date(start_date.year, start_date.month, 1)
    while current <= end_date:
        yield current
        current = _add_months(current, 1)


def _due_date(year: int, month: int, due_day: int) -> date:
    """Return a monthly due date, clamping days such as the 31st."""
    day = min(due_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _variable_weekly_entries(
    expense: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Accrue a monthly variable budget daily and group it into four buckets.

    The first three buckets cover days 1-7, 8-14 and 15-21. The fourth
    bucket covers the rest of the month. Each entry is dated on its bucket
    end, except when the projection ends earlier.

    Integer arithmetic distributes every penny across the days of each
    month without losing or creating money.
    """
    monthly_amount_pence = int(expense["monthly_amount_pence"])
    if monthly_amount_pence <= 0:
        return []

    bucket_totals: dict[date, int] = {}
    current = start_date

    while current <= end_date:
        days_in_month = calendar.monthrange(
            current.year,
            current.month,
        )[1]
        day_index = current.day - 1

        # Difference between cumulative allocations avoids rounding loss.
        allocated_before = (monthly_amount_pence * day_index) // days_in_month
        allocated_after = (monthly_amount_pence * (day_index + 1)) // days_in_month
        daily_amount = allocated_after - allocated_before

        bucket_index = min((current.day - 1) // 7, 3)
        bucket_end_day = days_in_month if bucket_index == 3 else (bucket_index + 1) * 7
        bucket_ending = date(current.year, current.month, bucket_end_day)
        bucket_ending = min(bucket_ending, end_date)

        bucket_totals[bucket_ending] = (
            bucket_totals.get(bucket_ending, 0) + daily_amount
        )

        current += timedelta(days=1)

    return [
        {
            "date": bucket_ending,
            "type": "variable_expense",
            "description": expense["name"],
            "amount_pence": -amount,
            "source_id": int(expense["id"]),
        }
        for bucket_ending, amount in sorted(bucket_totals.items())
        if amount
    ]


def generate_cashflow_projection(
    start_date: date | None = None,
) -> dict[str, Any]:
    """Generate a cashflow ledger for the configured projection horizon.

    The current balance is the opening balance on start_date. The configured
    projection horizon is measured from start_date and includes the day before
    the same calendar date after the configured number of months.

    Variable expense budgets accrue evenly across the days of each calendar
    month and are grouped into four month-local forecast entries. Debt
    repayments are capped at the outstanding balance. A debt with a recorded
    payment date in a calendar month is treated as already paid for that month;
    the schema currently stores only the latest payment date. Interest is not
    modelled because the current debt schema has no interest-rate field.
    """
    if start_date is None:
        start_date = date.today()
    _validate_date(start_date, "Start date")

    with database_connection() as connection:
        settings = connection.execute(
            """
            SELECT current_balance_pence, projection_months
            FROM settings
            WHERE id = 1
            """
        ).fetchone()

    if settings is None:
        raise RuntimeError("BudgetApp settings have not been initialised.")

    opening_balance_pence = int(settings["current_balance_pence"])
    projection_months = int(settings["projection_months"])

    if not 1 <= projection_months <= 120:
        raise ValueError("Projection months must be between 1 and 120.")

    end_date = _add_months(start_date, projection_months) - timedelta(days=1)

    with database_connection() as connection:
        savings_goals = connection.execute(
            """SELECT id, name, target_amount_pence, current_amount_pence,
                monthly_contribution_pence FROM savings_goals
                WHERE active = 1"""
        ).fetchall()
        savings_transactions = connection.execute(
            """SELECT t.goal_id, g.name, t.transaction_type, t.amount_pence,
                t.transaction_date FROM savings_goal_transactions AS t
                JOIN savings_goals AS g ON g.id = t.goal_id
                WHERE transaction_date BETWEEN ? AND ?""",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()

    income_forecast = forecast_income_from_settings(
        start_date=start_date,
        end_date=end_date,
    )

    entries: list[dict[str, Any]] = []

    # Add forecast income.
    for income in income_forecast["entries"]:
        entries.append(
            {
                "date": income["date"],
                "type": income["type"],
                "description": income["description"],
                "amount_pence": int(income["amount_pence"]),
                "source_id": income.get("expected_bonus_id"),
            }
        )

    # Add fixed expenses.
    for expense in get_fixed_expenses():
        due_day = expense["due_day"]

        if due_day is None:
            continue

        for month in _month_dates(start_date, end_date):
            due_date = _due_date(month.year, month.month, due_day)

            if start_date <= due_date <= end_date:
                entries.append(
                    {
                        "date": due_date,
                        "type": "fixed_expense",
                        "description": expense["name"],
                        "amount_pence": -int(expense["amount_pence"]),
                        "source_id": int(expense["id"]),
                    }
                )

    # Add debt repayments, stopping when the projected balance reaches zero.
    for debt in get_debts():
        due_day = debt["due_day"]
        monthly_payment = int(debt["monthly_payment_pence"])
        remaining_balance = int(debt["balance_pence"])

        if due_day is None or monthly_payment <= 0 or remaining_balance <= 0:
            continue

        last_payment_date = debt.get("last_payment_date")
        last_payment_month = (
            last_payment_date[:7] if last_payment_date is not None else None
        )

        for month in _month_dates(start_date, end_date):
            if remaining_balance <= 0:
                break

            # The schema stores only the most recent payment date, not a full
            # payment ledger. Treat a payment recorded in a calendar month as
            # that month's scheduled repayment, so it is not projected twice.
            if last_payment_month == month.strftime("%Y-%m"):
                continue

            due_date = _due_date(month.year, month.month, due_day)

            if due_date < start_date or due_date > end_date:
                continue

            payment = min(monthly_payment, remaining_balance)

            entries.append(
                {
                    "date": due_date,
                    "type": "debt_repayment",
                    "description": debt["name"],
                    "amount_pence": -payment,
                    "source_id": int(debt["id"]),
                }
            )

            remaining_balance -= payment

    # Add daily-accrued variable budgets grouped into weekly entries.
    for expense in get_variable_expenses():
        entries.extend(_variable_weekly_entries(expense, start_date, end_date))

    # Recorded future transactions enter cashflow directly. Monthly plans are
    # reduced by deposits already recorded in that month, so the same saving
    # is never counted twice. Opening balances remain user-maintained.
    transactions_by_goal_month: dict[tuple[int, str], list[sqlite3.Row]] = {}
    for transaction in savings_transactions:
        key = (int(transaction["goal_id"]), transaction["transaction_date"][:7])
        transactions_by_goal_month.setdefault(key, []).append(transaction)
        is_deposit = transaction["transaction_type"] == "deposit"
        entries.append(
            {
                "date": date.fromisoformat(transaction["transaction_date"]),
                "type": "savings_deposit" if is_deposit else "savings_withdrawal",
                "description": (
                    f"{transaction['name']} deposit"
                    if is_deposit
                    else f"{transaction['name']} withdrawal"
                ),
                "amount_pence": -int(transaction["amount_pence"])
                if is_deposit
                else int(transaction["amount_pence"]),
                "source_id": int(transaction["goal_id"]),
            }
        )

    for goal in savings_goals:
        monthly = int(goal["monthly_contribution_pence"])
        remaining = max(
            0,
            int(goal["target_amount_pence"]) - int(goal["current_amount_pence"]),
        )
        if monthly <= 0 or remaining <= 0:
            continue
        for month in _month_dates(start_date, end_date):
            due_date = _due_date(month.year, month.month, 1)
            if due_date < start_date or due_date > end_date or remaining <= 0:
                continue
            deposits_recorded = sum(
                int(transaction["amount_pence"])
                for transaction in transactions_by_goal_month.get(
                    (int(goal["id"]), month.strftime("%Y-%m")), []
                )
                if transaction["transaction_type"] == "deposit"
            )
            planned = min(max(0, monthly - deposits_recorded), remaining)
            if planned:
                entries.append(
                    {
                        "date": due_date,
                        "type": "savings_contribution",
                        "description": f"{goal['name']} contribution",
                        "amount_pence": -planned,
                        "source_id": int(goal["id"]),
                    }
                )
                remaining -= planned

    # Ensure predictable ordering when multiple transactions share a date.
    type_order = {
        "regular_income": 0,
        "bonus": 1,
        "fixed_expense": 2,
        "debt_repayment": 3,
        "variable_expense": 4,
        "savings_deposit": 5,
        "savings_contribution": 5,
        "savings_withdrawal": 0,
    }

    entries.sort(
        key=lambda entry: (
            entry["date"],
            type_order.get(entry["type"], 99),
            entry["description"].casefold(),
            entry["source_id"] or 0,
        )
    )

    # Calculate money in, money out and the running balance.
    running_balance_pence = opening_balance_pence

    for entry in entries:
        amount = entry["amount_pence"]

        entry["money_in_pence"] = max(amount, 0)
        entry["money_out_pence"] = max(-amount, 0)

        running_balance_pence += amount
        entry["running_balance_pence"] = running_balance_pence

    return {
        "start_date": start_date,
        "end_date": end_date,
        "projection_months": projection_months,
        "opening_balance_pence": opening_balance_pence,
        "closing_balance_pence": running_balance_pence,
        "total_income_pence": sum(entry["money_in_pence"] for entry in entries),
        "total_outgoings_pence": sum(entry["money_out_pence"] for entry in entries),
        "entries": entries,
        "income_forecast": income_forecast,
    }
