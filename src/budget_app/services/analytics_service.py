"""Read-only financial summaries for the Analytics page."""

import calendar
from datetime import date, datetime
from typing import Any

from budget_app.database import database_connection
from budget_app.services.payroll_service import (
    PERIODS_PER_YEAR,
    calculate_take_home_pay,
    tax_year_for_date,
)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def get_financial_analytics(
    *, months: int = 6, as_of_date: date | None = None
) -> dict[str, Any]:
    """Return actual income history and separate current planned commitments."""

    if (
        isinstance(months, bool)
        or not isinstance(months, int)
        or not 1 <= months <= 120
    ):
        raise ValueError("Analytics period must be between 1 and 120 months.")
    if as_of_date is None:
        as_of_date = date.today()
    elif not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise ValueError("Analytics date must be a date.")

    start_date = _shift_month(_month_start(as_of_date), -(months - 1))
    start_iso = start_date.isoformat()
    end_iso = as_of_date.isoformat()

    with database_connection() as connection:
        income_rows = connection.execute(
            """
            SELECT substr(pay_date, 1, 7) AS month,
                COUNT(*) AS payslips_count,
                SUM(gross_pay_pence) AS gross_pay_pence,
                SUM(tax_paid_pence) AS tax_paid_pence,
                SUM(ni_paid_pence) AS ni_paid_pence,
                SUM(pension_paid_pence) AS pension_paid_pence,
                SUM(other_deductions_pence) AS other_deductions_pence,
                SUM(net_pay_pence) AS net_pay_pence
            FROM income_history
            WHERE pay_date >= ? AND pay_date <= ?
            GROUP BY substr(pay_date, 1, 7)
            ORDER BY month
            """,
            (start_iso, end_iso),
        ).fetchall()

        fixed_rows = connection.execute(
            """
            SELECT name, category, amount_pence FROM fixed_expenses
            WHERE active = 1 ORDER BY category COLLATE NOCASE, name COLLATE NOCASE
            """
        ).fetchall()
        variable_rows = connection.execute(
            """
            SELECT name, monthly_amount_pence AS amount_pence FROM variable_expenses
            WHERE active = 1 ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        debt_rows = connection.execute(
            """
            SELECT name, monthly_payment_pence AS amount_pence FROM debts
            WHERE active = 1 ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        goal_rows = connection.execute(
            """
            SELECT id, name, target_amount_pence, current_amount_pence,
                monthly_contribution_pence
            FROM savings_goals WHERE active = 1
            ORDER BY name COLLATE NOCASE, id
            """
        ).fetchall()
        settings = connection.execute(
            """
            SELECT hourly_wage_pence, average_hours, pay_frequency, tax_code,
                ni_category, scottish_taxpayer, pension_percent, student_loan_plan
            FROM settings WHERE id = 1
            """
        ).fetchone()

    by_month = {row["month"]: dict(row) for row in income_rows}
    income_months = []
    for index in range(months):
        month_date = _shift_month(start_date, index)
        month_key = month_date.strftime("%Y-%m")
        recorded = by_month.get(month_key, {})
        income_months.append(
            {
                "month": month_key,
                "label": f"{calendar.month_abbr[month_date.month]} {str(month_date.year)[-2:]}",
                "payslips_count": int(recorded.get("payslips_count") or 0),
                **{
                    column: int(recorded.get(column) or 0)
                    for column in (
                        "gross_pay_pence",
                        "tax_paid_pence",
                        "ni_paid_pence",
                        "pension_paid_pence",
                        "other_deductions_pence",
                        "net_pay_pence",
                    )
                },
            }
        )

    fixed_items = [
        {
            "name": row["name"],
            "category": row["category"],
            "amount_pence": int(row["amount_pence"]),
        }
        for row in fixed_rows
    ]
    planned_commitments = [
        {
            "category": "Fixed expenses",
            "amount_pence": sum(item["amount_pence"] for item in fixed_items),
            "items": fixed_items,
        },
        {
            "category": "Variable budgets",
            "amount_pence": sum(int(row["amount_pence"]) for row in variable_rows),
            "items": [
                {"name": row["name"], "amount_pence": int(row["amount_pence"])}
                for row in variable_rows
            ],
        },
        {
            "category": "Debt payments",
            "amount_pence": sum(int(row["amount_pence"]) for row in debt_rows),
            "items": [
                {"name": row["name"], "amount_pence": int(row["amount_pence"])}
                for row in debt_rows
            ],
        },
        {
            "category": "Savings contributions",
            "amount_pence": sum(
                int(row["monthly_contribution_pence"]) for row in goal_rows
            ),
            "items": [
                {
                    "name": row["name"],
                    "amount_pence": int(row["monthly_contribution_pence"]),
                }
                for row in goal_rows
            ],
        },
    ]

    savings_goals = []
    for row in goal_rows:
        target = int(row["target_amount_pence"])
        saved = int(row["current_amount_pence"])
        savings_goals.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "target_amount_pence": target,
                "current_amount_pence": saved,
                "monthly_contribution_pence": int(row["monthly_contribution_pence"]),
                "progress_percent": min(100, round(saved * 100 / target)),
            }
        )

    recorded_months = [month for month in income_months if month["payslips_count"]]
    income_baseline_pence = None
    income_baseline_method = None
    income_baseline_label = "No income estimate available"
    income_baseline_note = "Enter pay details in Settings or record payslips to compare commitments with income."

    if (
        settings is not None
        and settings["hourly_wage_pence"]
        and settings["average_hours"]
    ):
        try:
            tax_year = tax_year_for_date(as_of_date)
            pay_estimate = calculate_take_home_pay(
                hourly_wage_pence=int(settings["hourly_wage_pence"]),
                average_hours=float(settings["average_hours"]),
                frequency=settings["pay_frequency"],
                tax_code=settings["tax_code"],
                ni_category=settings["ni_category"],
                scottish_taxpayer=bool(settings["scottish_taxpayer"]),
                pension_percent=float(settings["pension_percent"]),
                student_loan_plan=settings["student_loan_plan"],
                tax_year=tax_year,
            )
        except ValueError as exc:
            income_baseline_note = f"Settings-based income estimate unavailable: {exc}"
        else:
            pay_periods = PERIODS_PER_YEAR[settings["pay_frequency"]]
            income_baseline_pence = round(
                pay_estimate["net_pay_pence"] * pay_periods / 12
            )
            income_baseline_method = "settings_estimate"
            income_baseline_label = f"Estimated monthly take-home ({tax_year})"
            income_baseline_note = "Based on saved pay settings; rates are from the tax year containing the selected analytics date."

    if income_baseline_pence is None and recorded_months:
        net_total = sum(month["net_pay_pence"] for month in recorded_months)
        income_baseline_pence = round(net_total / len(recorded_months))
        income_baseline_method = "recorded_average"
        income_baseline_label = "Average recorded monthly take-home"
        income_baseline_note = "Average of months with at least one recorded payslip in the selected period."

    return {
        "start_date": start_date,
        "end_date": as_of_date,
        "months": months,
        "income_months": income_months,
        "has_income_history": any(month["payslips_count"] for month in income_months),
        "planned_commitments": planned_commitments,
        "planned_monthly_total_pence": sum(
            commitment["amount_pence"] for commitment in planned_commitments
        ),
        "has_planned_commitments": any(
            commitment["amount_pence"] for commitment in planned_commitments
        ),
        "monthly_income_baseline_pence": income_baseline_pence,
        "income_baseline_method": income_baseline_method,
        "income_baseline_label": income_baseline_label,
        "income_baseline_note": income_baseline_note,
        "savings_goals": savings_goals,
    }
