"""Pure what-if calculations over an existing cashflow projection."""

import calendar
from datetime import date, datetime
from typing import Any


def _month_starts(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        yield current
        year = current.year + (current.month == 12)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)


def _entry_date(value: date | str) -> date:
    if isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raise ValueError("Projection entries must have a valid date.")


def _changed_amount(current: int, change: int) -> tuple[int, int]:
    """Return the adjusted non-negative amount and the actual applied change."""
    adjusted = max(0, current + change)
    return adjusted, adjusted - current


def calculate_scenario(
    projection: dict[str, Any],
    *,
    income_change_per_pay_pence: int = 0,
    monthly_expenses_change_pence: int = 0,
    monthly_debt_change_pence: int = 0,
    monthly_savings_change_pence: int = 0,
) -> dict[str, Any]:
    """Compare monthly hypothetical changes with a cashflow projection.

    Positive changes increase income or outgoings for their respective fields;
    negative changes reduce them. Reductions are capped at zero for the
    relevant category. The input projection is never mutated.
    """
    changes = {
        "income": income_change_per_pay_pence,
        "expenses": monthly_expenses_change_pence,
        "debt": monthly_debt_change_pence,
        "savings": monthly_savings_change_pence,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in changes.values()
    ):
        raise ValueError("Scenario changes must be integer amounts in pence.")

    start_date = _entry_date(projection["start_date"])
    end_date = _entry_date(projection["end_date"])
    if end_date < start_date:
        raise ValueError("Projection end date must not be before its start date.")

    monthly: dict[str, dict[str, int]] = {}
    for month in _month_starts(start_date, end_date):
        monthly[month.strftime("%Y-%m")] = {
            "cash_in": 0,
            "cash_out": 0,
            "regular_income": 0,
            "pay_periods": 0,
            "expenses": 0,
            "debt": 0,
            "savings": 0,
        }

    for entry in projection["entries"]:
        entry_date = _entry_date(entry["date"])
        key = entry_date.strftime("%Y-%m")
        if key not in monthly:
            continue
        amount = int(entry["amount_pence"])
        bucket = monthly[key]
        bucket["cash_in"] += max(amount, 0)
        bucket["cash_out"] += max(-amount, 0)
        category = entry["type"]
        if category in ("regular_income", "bonus") and amount > 0:
            if category == "regular_income":
                bucket["regular_income"] += amount
                bucket["pay_periods"] += 1
        elif category in ("fixed_expense", "variable_expense") and amount < 0:
            bucket["expenses"] += -amount
        elif category == "debt_repayment" and amount < 0:
            bucket["debt"] += -amount
        elif category == "savings_contribution" and amount < 0:
            bucket["savings"] += -amount

    opening_balance = int(projection["opening_balance_pence"])
    baseline_balance = opening_balance
    scenario_balance = opening_balance
    rows = []

    for month_key, amounts in monthly.items():
        _, income_delta = _changed_amount(
            amounts["regular_income"],
            income_change_per_pay_pence * amounts["pay_periods"],
        )
        _, expenses_delta = _changed_amount(
            amounts["expenses"], monthly_expenses_change_pence
        )
        _, debt_delta = _changed_amount(amounts["debt"], monthly_debt_change_pence)
        _, savings_delta = _changed_amount(
            amounts["savings"], monthly_savings_change_pence
        )

        baseline_net = amounts["cash_in"] - amounts["cash_out"]
        scenario_cash_in = amounts["cash_in"] + income_delta
        scenario_cash_out = (
            amounts["cash_out"] + expenses_delta + debt_delta + savings_delta
        )
        scenario_net = scenario_cash_in - scenario_cash_out
        baseline_balance += baseline_net
        scenario_balance += scenario_net

        year, month_number = (int(part) for part in month_key.split("-"))
        rows.append(
            {
                "month": month_key,
                "label": f"{calendar.month_abbr[month_number]} {str(year)[-2:]}",
                "baseline_income_pence": amounts["cash_in"],
                "scenario_income_pence": scenario_cash_in,
                "baseline_outgoings_pence": amounts["cash_out"],
                "scenario_outgoings_pence": scenario_cash_out,
                "baseline_net_pence": baseline_net,
                "scenario_net_pence": scenario_net,
                "baseline_balance_pence": baseline_balance,
                "scenario_balance_pence": scenario_balance,
                "balance_change_pence": scenario_balance - baseline_balance,
            }
        )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance_pence": opening_balance,
        "baseline_closing_balance_pence": baseline_balance,
        "scenario_closing_balance_pence": scenario_balance,
        "closing_balance_change_pence": scenario_balance - baseline_balance,
        "monthly_changes_pence": {
            "income_per_pay": income_change_per_pay_pence,
            "expenses": monthly_expenses_change_pence,
            "debt": monthly_debt_change_pence,
            "savings": monthly_savings_change_pence,
        },
        "months": rows,
    }
