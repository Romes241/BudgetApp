"""Income forecasting with historical pay estimates and expected bonuses.

The fallback net-pay estimate uses a provisional 25% deduction from
estimated gross pay. It is not a tax calculator and should not be
treated as a guaranteed take-home amount.
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from budget_app.database import database_connection


FALLBACK_DEDUCTION_RATE = 0.25
HISTORICAL_LOOKBACK_DAYS = 56
VALID_PAY_FREQUENCIES = {"weekly", "fortnightly", "monthly"}


def _validate_date(value: date, field_name: str) -> None:
    """Require a date, excluding datetime values."""
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date.")


def _validate_regular_income(amount_pence: int) -> None:
    """Validate a caller-provided income baseline in pence."""
    if isinstance(amount_pence, bool) or not isinstance(amount_pence, int):
        raise ValueError("Regular income must be an integer amount in pence.")
    if amount_pence < 0:
        raise ValueError("Regular income cannot be negative.")


def _add_months(value: date, months: int = 1) -> date:
    """Advance a date by whole months, clamping to the month's last day."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance_pay_date(value: date, frequency: str) -> date:
    """Return the next scheduled pay date."""
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "fortnightly":
        return value + timedelta(days=14)
    if frequency == "monthly":
        return _add_months(value)
    raise ValueError(f"Unsupported pay frequency: {frequency}")


def _scheduled_dates(
    start_date: date,
    end_date: date,
    next_pay_date: date,
    frequency: str,
) -> list[date]:
    """Generate pay dates in the inclusive requested date range."""
    if frequency not in VALID_PAY_FREQUENCIES:
        raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")

    current = next_pay_date
    iterations = 0

    while current < start_date:
        following = _advance_pay_date(current, frequency)
        if following <= current:
            raise ValueError("Pay-date schedule failed to advance.")
        current = following
        iterations += 1
        if iterations > 10000:
            raise ValueError("Pay-date schedule is outside the supported range.")

    dates = []
    while current <= end_date:
        dates.append(current)
        following = _advance_pay_date(current, frequency)
        if following <= current:
            raise ValueError("Pay-date schedule failed to advance.")
        current = following
        iterations += 1
        if iterations > 20000:
            raise ValueError("Pay-date schedule is outside the supported range.")

    return dates


def _estimate_historical_regular_net_pence(
    connection: Any,
    as_of_date: date,
) -> tuple[int | None, int, dict[str, int]]:
    """Estimate regular net pay and report payment-line uncertainty.

    All payslips dated within the 56 days ending on as_of_date are considered.
    Both boundaries are inclusive.

    Bonus and additional lines are treated as non-recurring. Their estimated
    net contribution is removed from each payslip. The bonus field and bonus
    payment lines are reconciled using the larger amount to avoid double
    counting.

    Holiday and unknown payment lines are not automatically subtracted:
    they may replace ordinary earnings or be recurring. Instead, their
    presence is reported for review.

    Returns (average_regular_net_pence, payslips_used, diagnostics).
    """
    window_start = as_of_date - timedelta(days=HISTORICAL_LOOKBACK_DAYS)

    rows = connection.execute(
        """
        SELECT
            id,
            gross_pay_pence,
            net_pay_pence,
            bonus_amount_pence
        FROM income_history
        WHERE pay_date >= ?
          AND pay_date <= ?
        ORDER BY pay_date DESC, id DESC
        """,
        (window_start.isoformat(), as_of_date.isoformat()),
    ).fetchall()

    diagnostics = {
        "payslips_with_unclassified_earnings": 0,
        "payslips_with_holiday_pay": 0,
        "unclassified_payment_lines": 0,
        "holiday_payment_lines": 0,
        "recorded_pay_dates_excluded": 0,
    }

    if not rows:
        return None, 0, diagnostics

    regular_net_amounts = []

    for row in rows:
        gross = int(row["gross_pay_pence"])
        net = int(row["net_pay_pence"])

        payment_lines = connection.execute(
            """
            SELECT classification, amount_pence
            FROM income_payment_lines
            WHERE income_id = ?
            """,
            (row["id"],),
        ).fetchall()

        classified_one_off_gross = 0
        has_unknown = False
        has_holiday = False

        for line in payment_lines:
            classification = line["classification"]

            if classification in ("bonus", "additional"):
                classified_one_off_gross += int(line["amount_pence"])
            elif classification == "unknown":
                has_unknown = True
                diagnostics["unclassified_payment_lines"] += 1
            elif classification == "holiday":
                has_holiday = True
                diagnostics["holiday_payment_lines"] += 1

        if has_unknown:
            diagnostics["payslips_with_unclassified_earnings"] += 1
        if has_holiday:
            diagnostics["payslips_with_holiday_pay"] += 1

        recorded_bonus_gross = int(row["bonus_amount_pence"] or 0)
        one_off_gross = max(
            classified_one_off_gross,
            recorded_bonus_gross,
        )

        if gross > 0 and one_off_gross > 0:
            estimated_one_off_net = round(
                net * min(one_off_gross, gross) / gross
            )
            regular_net = max(0, net - estimated_one_off_net)
        else:
            regular_net = net

        regular_net_amounts.append(regular_net)

    average = round(sum(regular_net_amounts) / len(regular_net_amounts))
    return average, len(regular_net_amounts), diagnostics


def _estimate_fallback_net_pence(
    hourly_wage_pence: int,
    average_hours: float,
    frequency: str,
) -> tuple[int, int]:
    """Estimate gross and net pay using wage, hours and a 25% deduction."""
    if hourly_wage_pence < 0:
        raise ValueError("Hourly wage cannot be negative.")
    if average_hours < 0:
        raise ValueError("Average hours cannot be negative.")

    weekly_gross = round(hourly_wage_pence * average_hours)

    if frequency == "weekly":
        gross = weekly_gross
    elif frequency == "fortnightly":
        gross = weekly_gross * 2
    elif frequency == "monthly":
        gross = round(weekly_gross * 52 / 12)
    else:
        raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")

    estimated_net = round(gross * (1 - FALLBACK_DEDUCTION_RATE))
    return gross, estimated_net


def _get_expected_bonuses(
    connection: Any,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Return confirmed, not-yet-received bonuses in the requested range."""
    rows = connection.execute(
        """
        SELECT id, expected_date, amount_pence, reason
        FROM expected_bonuses
        WHERE expected_date >= ?
          AND expected_date <= ?
          AND status = 'confirmed'
          AND received_income_id IS NULL
        ORDER BY expected_date, id
        """,
        (start_date.isoformat(), end_date.isoformat()),
    ).fetchall()

    return [
        {
            "type": "bonus",
            "date": date.fromisoformat(row["expected_date"]),
            "amount_pence": int(row["amount_pence"]),
            "description": row["reason"],
            "expected_bonus_id": int(row["id"]),
        }
        for row in rows
    ]


def forecast_income(
    *,
    start_date: date,
    end_date: date,
    regular_income_pence: int,
) -> dict[str, Any]:
    """Forecast a caller-provided regular-income baseline plus bonuses."""
    _validate_date(start_date, "Start date")
    _validate_date(end_date, "End date")
    _validate_regular_income(regular_income_pence)

    if end_date < start_date:
        raise ValueError("End date cannot be before start date.")

    with database_connection() as connection:
        bonuses = _get_expected_bonuses(connection, start_date, end_date)

    expected_bonus_pence = sum(item["amount_pence"] for item in bonuses)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "regular_income_pence": regular_income_pence,
        "expected_bonus_pence": expected_bonus_pence,
        "total_income_pence": regular_income_pence + expected_bonus_pence,
    }


def forecast_income_from_settings(
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Forecast dated income using settings, recent payslips and bonuses.

    Historical mode averages eligible payslips dated within the 56 days
    ending on the forecast start date, adjusting for identifiable bonus
    and additional earnings. Holiday and unknown payment lines are reported
    as uncertainty rather than automatically subtracted.

    Actual income records already recorded for a scheduled pay date replace
    the projected regular-income entry for that date.

    Without eligible historical payslips, income is estimated from wage and
    hours using a provisional 25% deduction.

    If next_pay_date is not configured, regular pay dates cannot be generated.
    Confirmed expected bonuses are still returned independently.
    """
    _validate_date(start_date, "Start date")
    _validate_date(end_date, "End date")

    if end_date < start_date:
        raise ValueError("End date cannot be before start date.")

    with database_connection() as connection:
        settings = connection.execute(
            "SELECT * FROM settings WHERE id = 1"
        ).fetchone()

        if settings is None:
            raise RuntimeError("BudgetApp settings have not been initialised.")

        frequency = settings["pay_frequency"]
        if frequency not in VALID_PAY_FREQUENCIES:
            raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")

        historical_average, payslips_used, diagnostics = (
            _estimate_historical_regular_net_pence(connection, start_date)
        )

        if historical_average is not None:
            regular_net_pence = historical_average
            gross_estimate_pence = None
            estimation_method = "historical_average"
            estimation_note = (
                f"Average of payslips dated from {HISTORICAL_LOOKBACK_DAYS} days "
                "before the forecast start date up to and including that date, "
                "with estimated net contributions "
                "from identifiable bonus and additional earnings removed. "
                "Holiday and unclassified payment lines are not automatically "
                "removed because their recurrence and relationship to normal "
                "earnings are uncertain."
            )
        else:
            gross_estimate_pence, regular_net_pence = _estimate_fallback_net_pence(
                int(settings["hourly_wage_pence"]),
                float(settings["average_hours"]),
                frequency,
            )
            estimation_method = "gross_less_provisional_25_percent"
            estimation_note = (
                "Estimated gross pay from hourly wage and average weekly hours. "
                "Net pay assumes 25% total deductions; this is a rough estimate, "
                "not a calculation of tax, National Insurance, pension or "
                "student-loan deductions."
            )

        next_pay_date_value = settings["next_pay_date"]
        if next_pay_date_value:
            try:
                next_pay_date = date.fromisoformat(next_pay_date_value)
            except (TypeError, ValueError):
                raise ValueError(
                    "Configured next pay date must use YYYY-MM-DD format."
                ) from None

            if next_pay_date.isoformat() != next_pay_date_value:
                raise ValueError(
                    "Configured next pay date must use YYYY-MM-DD format."
                )

            pay_dates = _scheduled_dates(
                start_date,
                end_date,
                next_pay_date,
                frequency,
            )
            recorded_rows = connection.execute(
                """
                SELECT DISTINCT pay_date
                FROM income_history
                WHERE pay_date >= ?
                  AND pay_date <= ?
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()

            recorded_pay_dates = {
                date.fromisoformat(row["pay_date"])
                for row in recorded_rows
            }

            original_pay_date_count = len(pay_dates)
            pay_dates = [
                pay_date
                for pay_date in pay_dates
                if pay_date not in recorded_pay_dates
            ]

            diagnostics["recorded_pay_dates_excluded"] = (
                original_pay_date_count - len(pay_dates)
            )
        else:
            pay_dates = []

        bonuses = _get_expected_bonuses(connection, start_date, end_date)

    entries = [
        {
            "type": "regular_income",
            "date": pay_date,
            "amount_pence": regular_net_pence,
            "description": "Estimated regular take-home pay",
        }
        for pay_date in pay_dates
    ]
    entries.extend(bonuses)
    entries.sort(key=lambda item: (item["date"], item["type"]))

    regular_total = sum(
        item["amount_pence"]
        for item in entries
        if item["type"] == "regular_income"
    )
    bonus_total = sum(
        item["amount_pence"]
        for item in entries
        if item["type"] == "bonus"
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "pay_frequency": frequency,
        "estimation_method": estimation_method,
        "estimation_note": estimation_note,
        "historical_payslips_used": payslips_used,
        "regular_pay_estimate_pence": regular_net_pence,
        "fallback_gross_estimate_pence": gross_estimate_pence,
        "regular_income_pence": regular_total,
        "expected_bonus_pence": bonus_total,
        "total_income_pence": regular_total + bonus_total,
        "entries": entries,
        "missing_next_pay_date": not bool(next_pay_date_value),
        "forecast_diagnostics": diagnostics,
    }
