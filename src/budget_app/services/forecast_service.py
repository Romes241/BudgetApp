"""Income forecasting with settings-based payroll estimates and bonuses."""

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from budget_app.database import database_connection
from budget_app.services.payroll_service import (
    calculate_take_home_pay,
    tax_year_for_date,
)

HISTORICAL_LOOKBACK_DAYS = 56
VALID_PAY_FREQUENCIES = {"weekly", "fortnightly", "monthly"}


def _validate_date(value: date, field_name: str) -> date:
    """Require a date, excluding datetime values."""

    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date.")

    return value


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
    """Return the next scheduled contractual pay date."""

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
    """Generate contractual pay dates in the inclusive requested range."""

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

    All payslips dated from 56 days before as_of_date through as_of_date are
    considered. Both boundaries are inclusive.

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
            estimated_one_off_net = round(net * min(one_off_gross, gross) / gross)
            regular_net = max(0, net - estimated_one_off_net)

        else:
            regular_net = net

        regular_net_amounts.append(regular_net)

    average = round(sum(regular_net_amounts) / len(regular_net_amounts))

    return average, len(regular_net_amounts), diagnostics


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

    Regular forecast pay is calculated from saved payroll settings. Recent
    payslips are retained as a comparison so users can see the difference
    between the settings-based estimate and observed pay.

    Actual income records on contractual pay dates replace the corresponding
    projected regular-income entries. Projected entries are shifted by the
    configured early-payment offset, but historical payslip dates are never
    changed.

    If next_pay_date is not configured, regular pay dates cannot be generated.
    Confirmed expected bonuses are still returned independently.
    """

    _validate_date(start_date, "Start date")
    _validate_date(end_date, "End date")

    if end_date < start_date:
        raise ValueError("End date cannot be before start date.")

    with database_connection() as connection:
        settings = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        if settings is None:
            raise RuntimeError("BudgetApp settings have not been initialised.")

        frequency = settings["pay_frequency"]

        if frequency not in VALID_PAY_FREQUENCIES:
            raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")

        early_payment_offset_days = int(settings["early_payment_offset_days"])

        if not 0 <= early_payment_offset_days <= 7:
            raise ValueError("Early payment offset must be between 0 and 7 days.")

        historical_average, payslips_used, diagnostics = (
            _estimate_historical_regular_net_pence(connection, start_date)
        )

        tax_year = tax_year_for_date(start_date)
        payroll_estimate = calculate_take_home_pay(
            hourly_wage_pence=int(settings["hourly_wage_pence"]),
            average_hours=float(settings["average_hours"]),
            frequency=frequency,
            tax_code=settings["tax_code"],
            ni_category=settings["ni_category"],
            scottish_taxpayer=bool(settings["scottish_taxpayer"]),
            pension_percent=float(settings["pension_percent"]),
            student_loan_plan=settings["student_loan_plan"],
            tax_year=tax_year,
        )
        gross_estimate_pence = payroll_estimate["gross_pay_pence"]
        regular_net_pence = payroll_estimate["net_pay_pence"]
        estimation_method = "settings_based_payroll_estimate"
        estimation_note = (
            f"Settings-based estimate for UK tax year {tax_year}. "
            + payroll_estimate["assumptions"]
            + (
                f" Recent payslips average {historical_average} pence after identified one-off earnings; "
                "that history is shown for comparison and does not override the settings estimate."
                if historical_average is not None
                else " No recent payslips were available for comparison."
            )
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
                raise ValueError("Configured next pay date must use YYYY-MM-DD format.")

            payment_offset = timedelta(days=early_payment_offset_days)

            # The forecast range represents the dates money reaches the bank.
            # Shift the range forward to find the corresponding contractual
            # payday dates.
            contractual_start_date = start_date + payment_offset
            contractual_end_date = end_date + payment_offset

            contractual_pay_dates = _scheduled_dates(
                contractual_start_date,
                contractual_end_date,
                next_pay_date,
                frequency,
            )

            # Historical income stays on the contractual payslip date.
            # Match actual records against contractual dates, then shift only
            # the projected cashflow entries to expected receipt dates.
            recorded_rows = connection.execute(
                """
                SELECT DISTINCT pay_date
                FROM income_history
                WHERE pay_date >= ?
                  AND pay_date <= ?
                """,
                (
                    contractual_start_date.isoformat(),
                    contractual_end_date.isoformat(),
                ),
            ).fetchall()

            recorded_pay_dates = {
                date.fromisoformat(row["pay_date"]) for row in recorded_rows
            }

            original_pay_date_count = len(contractual_pay_dates)

            pay_dates = [
                contractual_pay_date - payment_offset
                for contractual_pay_date in contractual_pay_dates
                if contractual_pay_date not in recorded_pay_dates
            ]

            diagnostics["recorded_pay_dates_excluded"] = original_pay_date_count - len(
                pay_dates
            )

        else:
            pay_dates = []

        bonuses = _get_expected_bonuses(
            connection,
            start_date,
            end_date,
        )

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
        item["amount_pence"] for item in entries if item["type"] == "regular_income"
    )

    bonus_total = sum(
        item["amount_pence"] for item in entries if item["type"] == "bonus"
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "pay_frequency": frequency,
        "early_payment_offset_days": early_payment_offset_days,
        "estimation_method": estimation_method,
        "estimation_note": estimation_note,
        "historical_payslips_used": payslips_used,
        "regular_pay_estimate_pence": regular_net_pence,
        "gross_pay_estimate_pence": gross_estimate_pence,
        "payroll_breakdown": payroll_estimate,
        "historical_regular_pay_average_pence": historical_average,
        "regular_income_pence": regular_total,
        "expected_bonus_pence": bonus_total,
        "total_income_pence": regular_total + bonus_total,
        "entries": entries,
        "missing_next_pay_date": not bool(next_pay_date_value),
        "forecast_diagnostics": diagnostics,
    }
