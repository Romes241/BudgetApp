"""Operations for reading and updating application settings."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from budget_app.database import database_connection
from budget_app.services.forecast_service import HISTORICAL_LOOKBACK_DAYS
from budget_app.utils.money import from_pence, to_pence

VALID_PAY_FREQUENCIES = {"weekly", "fortnightly", "monthly"}


def _validate_non_negative_money(value: Any, field_name: str) -> int:
    amount_pence = to_pence(value)

    if amount_pence < 0:
        raise ValueError(f"{field_name} cannot be negative.")

    return amount_pence


def _validate_current_balance(value: Any) -> int:
    return to_pence(value)


def _validate_hours(value: Any) -> float:
    try:
        hours = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Average weekly hours must be a valid number.") from None

    if not hours.is_finite() or not 0 <= hours <= 168:
        raise ValueError("Average weekly hours must be between 0 and 168.")

    return float(hours)


def _validate_percentage(value: Any) -> float:
    try:
        percentage = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Pension percentage must be a valid number.") from None

    if not percentage.is_finite() or not 0 <= percentage <= 100:
        raise ValueError("Pension percentage must be between 0 and 100.")

    return float(percentage)


def _validate_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty.")

    return value.strip()


def _validate_integer(
    value: Any,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")

    return value


def _validate_pay_frequency(value: Any) -> str:
    if not isinstance(value, str) or value not in VALID_PAY_FREQUENCIES:
        raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")

    return value


def _validate_boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be True or False.")

    return value


def _validate_next_pay_date(value: str | date | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        raise ValueError("Next pay date must be a date or None.")

    if isinstance(value, date):
        return value.isoformat()

    if not isinstance(value, str):
        raise ValueError("Next pay date must use YYYY-MM-DD format, or be None.")

    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Next pay date must use YYYY-MM-DD format.") from None

    if parsed_date.isoformat() != value:
        raise ValueError("Next pay date must use YYYY-MM-DD format.")

    return value


def _validate_balance_date(value: str | date | None) -> str:
    """Validate the calendar date used for manual balance reconciliation."""
    if value is None:
        return date.today().isoformat()
    validated = _validate_next_pay_date(value)
    if validated is None or date.fromisoformat(validated) > date.today():
        raise ValueError("Balance date cannot be in the future.")
    return validated


def get_settings() -> dict:
    """Return application settings using pounds for monetary values."""

    with database_connection() as connection:
        row = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()

    if row is None:
        raise RuntimeError("BudgetApp settings have not been initialised.")

    settings = dict(row)
    settings["current_balance"] = from_pence(settings["current_balance_pence"])
    settings["hourly_wage"] = from_pence(settings["hourly_wage_pence"])
    settings["scottish_taxpayer"] = bool(settings["scottish_taxpayer"])

    return settings


def get_pension_estimate(as_of_date: date | None = None) -> dict | None:
    """Estimate the effective pension deduction rate from recent income history.

    The estimate is a weighted rate calculated as total pension deducted divided
    by total gross pay over the same 56-day lookback used by the income forecast.

    It is an observed effective rate, not necessarily the employee's scheme rate:
    pensionable earnings can differ from total gross pay.

    The function is read-only. It does not change the saved pension setting.
    Returns None when there are no positive-gross income records in the window.
    """

    if as_of_date is None:
        as_of_date = date.today()
    elif not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        raise ValueError("As-of date must be a date.")

    window_start = as_of_date - timedelta(days=HISTORICAL_LOOKBACK_DAYS)

    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS payslips_used,
                COALESCE(SUM(gross_pay_pence), 0) AS gross_pay_pence,
                COALESCE(SUM(pension_paid_pence), 0) AS pension_paid_pence
            FROM income_history
            WHERE pay_date >= ?
              AND pay_date <= ?
              AND gross_pay_pence > 0
            """,
            (window_start.isoformat(), as_of_date.isoformat()),
        ).fetchone()

    payslips_used = int(row["payslips_used"])
    gross_pay_pence = int(row["gross_pay_pence"])
    pension_paid_pence = int(row["pension_paid_pence"])

    if payslips_used == 0 or gross_pay_pence == 0:
        return None

    percentage = (
        Decimal(pension_paid_pence) / Decimal(gross_pay_pence) * Decimal(100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "percentage": percentage,
        "payslips_used": payslips_used,
        "gross_pay_pence": gross_pay_pence,
        "pension_paid_pence": pension_paid_pence,
        "window_start": window_start,
        "window_end": as_of_date,
    }


def save_settings(
    *,
    current_balance: Any,
    hourly_wage: Any,
    average_hours: Any,
    tax_code: Any,
    pension_percent: Any,
    student_loan_plan: Any,
    ni_category: Any,
    scottish_taxpayer: Any,
    projection_months: Any,
    pay_frequency: Any,
    next_pay_date: str | date | None,
    early_payment_offset_days: Any,
    balance_as_of_date: str | date | None = None,
) -> None:
    """Validate and persist the complete application settings form."""

    values = {
        "current_balance_pence": _validate_current_balance(current_balance),
        "hourly_wage_pence": _validate_non_negative_money(
            hourly_wage,
            "Hourly wage",
        ),
        "average_hours": _validate_hours(average_hours),
        "tax_code": _validate_text(tax_code, "Tax code").upper(),
        "pension_percent": _validate_percentage(pension_percent),
        "student_loan_plan": _validate_text(
            student_loan_plan,
            "Student loan plan",
        ),
        "ni_category": _validate_text(ni_category, "NI category").upper(),
        "scottish_taxpayer": int(
            _validate_boolean(scottish_taxpayer, "Scottish taxpayer")
        ),
        "projection_months": _validate_integer(
            projection_months,
            "Projection months",
            1,
            120,
        ),
        "pay_frequency": _validate_pay_frequency(pay_frequency),
        "next_pay_date": _validate_next_pay_date(next_pay_date),
        "early_payment_offset_days": _validate_integer(
            early_payment_offset_days,
            "Early payment offset",
            0,
            7,
        ),
        "balance_as_of_date": _validate_balance_date(balance_as_of_date),
    }

    with database_connection() as connection:
        existing_balance = connection.execute(
            """SELECT current_balance_pence, balance_as_of_date,
                balance_reconciled_at FROM settings WHERE id = 1"""
        ).fetchone()
        if existing_balance is None:
            raise RuntimeError("BudgetApp settings have not been initialised.")
        if (
            int(existing_balance["current_balance_pence"])
            == values["current_balance_pence"]
            and existing_balance["balance_as_of_date"] == values["balance_as_of_date"]
        ):
            values["balance_reconciled_at"] = existing_balance["balance_reconciled_at"]
        else:
            values["balance_reconciled_at"] = (
                datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
        cursor = connection.execute(
            """
            UPDATE settings
            SET current_balance_pence = :current_balance_pence,
                balance_as_of_date = :balance_as_of_date,
                balance_reconciled_at = :balance_reconciled_at,
                hourly_wage_pence = :hourly_wage_pence,
                average_hours = :average_hours,
                tax_code = :tax_code,
                pension_percent = :pension_percent,
                student_loan_plan = :student_loan_plan,
                ni_category = :ni_category,
                scottish_taxpayer = :scottish_taxpayer,
                projection_months = :projection_months,
                pay_frequency = :pay_frequency,
                next_pay_date = :next_pay_date,
                early_payment_offset_days = :early_payment_offset_days
            WHERE id = 1
            """,
            values,
        )

        if cursor.rowcount == 0:
            raise RuntimeError("BudgetApp settings have not been initialised.")
