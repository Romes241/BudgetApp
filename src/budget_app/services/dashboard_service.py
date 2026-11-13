"""Read the financial summaries needed by the Dashboard."""

from datetime import date
from typing import Any

from budget_app.services.balance_service import get_running_balance
from budget_app.services.cashflow_service import generate_cashflow_projection
from budget_app.services.debt_service import get_debts
from budget_app.services.savings_goal_service import get_savings_goals


def get_dashboard_data(as_of_date: date | None = None) -> dict[str, Any]:
    """Combine existing cashflow, debt and savings data for the overview."""
    projection = generate_cashflow_projection(start_date=as_of_date)
    goals = get_savings_goals()
    debts = get_debts()
    regular_pay = next(
        (entry for entry in projection["entries"] if entry["type"] == "regular_income"),
        None,
    )
    return {
        "projection": projection,
        "balance": get_running_balance(),
        "next_pay": regular_pay,
        "savings_goals": goals,
        "savings_total_pence": sum(goal["current_amount_pence"] for goal in goals),
        "debt_total_pence": sum(debt["balance_pence"] for debt in debts),
    }
