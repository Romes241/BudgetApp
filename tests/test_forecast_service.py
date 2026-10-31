from datetime import date, datetime

import pytest

from budget_app.database import (
    connect_database,
    database_connection,
    initialise_database,
)
from budget_app.forecast_service import (
    forecast_income,
    forecast_income_from_settings,
)


@pytest.fixture
def forecast_database(tmp_path, monkeypatch):
    database_path = tmp_path / "forecast.db"

    def test_connection():
        return database_connection(database_path)

    monkeypatch.setattr(
        "budget_app.forecast_service.database_connection",
        test_connection,
    )

    with connect_database(database_path) as connection:
        initialise_database(connection)

    return database_path


def configure_settings(
    database_path,
    *,
    hourly_wage_pence=1500,
    average_hours=20,
    pay_frequency="weekly",
    next_pay_date="2026-11-06",
):
    with connect_database(database_path) as connection:
        connection.execute(
            """
            UPDATE settings
            SET hourly_wage_pence = ?,
                average_hours = ?,
                pay_frequency = ?,
                next_pay_date = ?
            WHERE id = 1
            """,
            (
                hourly_wage_pence,
                average_hours,
                pay_frequency,
                next_pay_date,
            ),
        )


def add_income(
    database_path,
    pay_date,
    *,
    gross_pay_pence=30000,
    net_pay_pence=24000,
    bonus_amount_pence=None,
):
    with connect_database(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO income_history (
                pay_date,
                hours_worked,
                gross_pay_pence,
                tax_paid_pence,
                ni_paid_pence,
                pension_paid_pence,
                net_pay_pence,
                bonus_amount_pence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pay_date,
                20,
                gross_pay_pence,
                0,
                0,
                0,
                net_pay_pence,
                bonus_amount_pence,
            ),
        )
        return cursor.lastrowid


def add_payment_line(
    database_path,
    income_id,
    *,
    description,
    amount_pence,
    classification,
):
    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO income_payment_lines (
                income_id,
                description,
                amount_pence,
                classification
            )
            VALUES (?, ?, ?, ?)
            """,
            (income_id, description, amount_pence, classification),
        )


def add_expected_bonus(
    database_path,
    expected_date,
    *,
    amount_pence=10000,
    reason="Bonus",
    status="confirmed",
    received_income_id=None,
):
    with connect_database(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO expected_bonuses (
                expected_date,
                amount_pence,
                reason,
                status,
                received_income_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                expected_date,
                amount_pence,
                reason,
                status,
                received_income_id,
            ),
        )
        return cursor.lastrowid


def test_forecast_includes_regular_income_and_confirmed_bonus(
    forecast_database,
):
    add_expected_bonus(
        forecast_database,
        "2026-11-15",
        amount_pence=12500,
    )

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["regular_income_pence"] == 50000
    assert result["expected_bonus_pence"] == 12500
    assert result["total_income_pence"] == 62500


def test_forecast_includes_multiple_confirmed_bonuses(forecast_database):
    add_expected_bonus(
        forecast_database,
        "2026-11-10",
        amount_pence=10000,
    )
    add_expected_bonus(
        forecast_database,
        "2026-11-25",
        amount_pence=7500,
    )

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["expected_bonus_pence"] == 17500
    assert result["total_income_pence"] == 67500


def test_forecast_excludes_unconfirmed_and_cancelled_bonuses(
    forecast_database,
):
    add_expected_bonus(
        forecast_database,
        "2026-11-10",
        amount_pence=10000,
        status="unconfirmed",
    )
    add_expected_bonus(
        forecast_database,
        "2026-11-20",
        amount_pence=20000,
        status="cancelled",
    )

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["expected_bonus_pence"] == 0


def test_forecast_excludes_bonuses_outside_date_range(forecast_database):
    add_expected_bonus(forecast_database, "2026-10-31")
    add_expected_bonus(forecast_database, "2026-12-01")

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["expected_bonus_pence"] == 0


def test_forecast_does_not_count_received_bonus_again(forecast_database):
    income_id = add_income(
        forecast_database,
        "2026-11-10",
        gross_pay_pence=10000,
        net_pay_pence=10000,
    )
    add_expected_bonus(
        forecast_database,
        "2026-11-10",
        amount_pence=10000,
        status="received",
        received_income_id=income_id,
    )

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["expected_bonus_pence"] == 0


def test_forecast_excludes_confirmed_bonus_linked_to_income(
    forecast_database,
):
    income_id = add_income(forecast_database, "2026-11-10")
    add_expected_bonus(
        forecast_database,
        "2026-11-10",
        amount_pence=10000,
        status="confirmed",
        received_income_id=income_id,
    )

    result = forecast_income(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        regular_income_pence=50000,
    )

    assert result["expected_bonus_pence"] == 0


def test_forecast_rejects_invalid_date_range(forecast_database):
    with pytest.raises(ValueError, match="End date cannot be before start date"):
        forecast_income(
            start_date=date(2026, 12, 1),
            end_date=date(2026, 11, 1),
            regular_income_pence=50000,
        )


@pytest.mark.parametrize(
    "invalid_date",
    [
        "2026-11-01",
        datetime(2026, 11, 1, 12, 0),
        None,
    ],
)
def test_forecast_rejects_invalid_start_date(forecast_database, invalid_date):
    with pytest.raises(ValueError, match="Start date must be a date"):
        forecast_income(
            start_date=invalid_date,
            end_date=date(2026, 11, 30),
            regular_income_pence=50000,
        )


@pytest.mark.parametrize(
    "invalid_income",
    [-1, 1.5, "50000", True, None],
)
def test_forecast_rejects_invalid_regular_income(
    forecast_database,
    invalid_income,
):
    with pytest.raises(ValueError):
        forecast_income(
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30),
            regular_income_pence=invalid_income,
        )


def test_settings_forecast_uses_all_payslips_within_eight_week_window(
    forecast_database,
):
    configure_settings(forecast_database)

    for index, net in enumerate([10000, 20000, 30000, 40000, 50000, 60000, 90000]):
        add_income(
            forecast_database,
            date(2026, 10, 1 + index).isoformat(),
            gross_pay_pence=net,
            net_pay_pence=net,
        )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    # All seven payslips fall within the eight-week window.
    assert result["historical_payslips_used"] == 7
    assert result["estimation_method"] == "historical_average"
    assert result["regular_pay_estimate_pence"] == 42857
    assert result["regular_income_pence"] == 171428
    assert (
        len([entry for entry in result["entries"] if entry["type"] == "regular_income"])
        == 4
    )


def test_settings_forecast_removes_identifiable_one_off_earnings(
    forecast_database,
):
    configure_settings(forecast_database)

    income_id = add_income(
        forecast_database,
        "2026-10-20",
        gross_pay_pence=40000,
        net_pay_pence=32000,
        bonus_amount_pence=10000,
    )
    add_payment_line(
        forecast_database,
        income_id,
        description="Performance bonus",
        amount_pence=10000,
        classification="bonus",
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    # The estimated net contribution of the £100 bonus is £80.
    assert result["regular_pay_estimate_pence"] == 24000
    assert result["historical_payslips_used"] == 1


def test_settings_forecast_falls_back_to_gross_wage_estimate(
    forecast_database,
):
    configure_settings(
        forecast_database,
        hourly_wage_pence=1500,
        average_hours=20,
        pay_frequency="weekly",
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 8),
    )

    assert result["estimation_method"] == "gross_less_provisional_25_percent"
    assert result["fallback_gross_estimate_pence"] == 30000
    assert result["regular_pay_estimate_pence"] == 22500
    assert "25%" in result["estimation_note"]


@pytest.mark.parametrize(
    ("frequency", "expected_dates"),
    [
        (
            "weekly",
            [
                date(2026, 11, 6),
                date(2026, 11, 13),
                date(2026, 11, 20),
                date(2026, 11, 27),
            ],
        ),
        (
            "fortnightly",
            [date(2026, 11, 6), date(2026, 11, 20)],
        ),
        (
            "monthly",
            [date(2026, 11, 6)],
        ),
    ],
)
def test_settings_forecast_generates_pay_dates(
    forecast_database,
    frequency,
    expected_dates,
):
    configure_settings(
        forecast_database,
        pay_frequency=frequency,
        next_pay_date="2026-11-06",
    )
    add_income(forecast_database, "2026-10-20", net_pay_pence=20000)

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    actual_dates = [
        entry["date"]
        for entry in result["entries"]
        if entry["type"] == "regular_income"
    ]
    assert actual_dates == expected_dates


def test_settings_forecast_includes_bonus_as_separate_entry(
    forecast_database,
):
    configure_settings(forecast_database)
    add_income(forecast_database, "2026-10-20", net_pay_pence=20000)
    add_expected_bonus(
        forecast_database,
        "2026-11-15",
        amount_pence=12500,
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    assert result["expected_bonus_pence"] == 12500
    assert any(
        entry["type"] == "bonus"
        and entry["date"] == date(2026, 11, 15)
        and entry["amount_pence"] == 12500
        for entry in result["entries"]
    )


def test_settings_forecast_reports_missing_next_pay_date(
    forecast_database,
):
    configure_settings(forecast_database, next_pay_date=None)

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    assert result["missing_next_pay_date"] is True
    assert result["regular_income_pence"] == 0
    assert result["entries"] == []


def test_monthly_pay_date_clamps_to_last_day_of_short_month(
    forecast_database,
):
    configure_settings(
        forecast_database,
        pay_frequency="monthly",
        next_pay_date="2026-01-31",
    )
    add_income(forecast_database, "2026-01-20", net_pay_pence=20000)

    result = forecast_income_from_settings(
        start_date=date(2026, 2, 1),
        end_date=date(2026, 3, 31),
    )

    actual_dates = [
        entry["date"]
        for entry in result["entries"]
        if entry["type"] == "regular_income"
    ]

    assert actual_dates == [date(2026, 2, 28), date(2026, 3, 28)]


def test_settings_forecast_reports_unknown_payment_lines(
    forecast_database,
):
    configure_settings(forecast_database)

    income_id = add_income(
        forecast_database,
        "2026-10-20",
        gross_pay_pence=30000,
        net_pay_pence=24000,
    )
    add_payment_line(
        forecast_database,
        income_id,
        description="Unrecognised payment",
        amount_pence=5000,
        classification="unknown",
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    assert result["regular_pay_estimate_pence"] == 24000
    assert result["forecast_diagnostics"]["payslips_with_unclassified_earnings"] == 1
    assert result["forecast_diagnostics"]["unclassified_payment_lines"] == 1


def test_settings_forecast_reports_holiday_pay_without_subtracting_it(
    forecast_database,
):
    configure_settings(forecast_database)

    income_id = add_income(
        forecast_database,
        "2026-10-20",
        gross_pay_pence=30000,
        net_pay_pence=24000,
    )
    add_payment_line(
        forecast_database,
        income_id,
        description="Holiday Pay - Associates",
        amount_pence=5000,
        classification="holiday",
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    assert result["regular_pay_estimate_pence"] == 24000
    assert result["forecast_diagnostics"]["payslips_with_holiday_pay"] == 1
    assert result["forecast_diagnostics"]["holiday_payment_lines"] == 1


def test_settings_forecast_does_not_subtract_same_bonus_twice(
    forecast_database,
):
    configure_settings(forecast_database)

    income_id = add_income(
        forecast_database,
        "2026-10-20",
        gross_pay_pence=40000,
        net_pay_pence=32000,
        bonus_amount_pence=10000,
    )
    add_payment_line(
        forecast_database,
        income_id,
        description="Performance bonus",
        amount_pence=10000,
        classification="bonus",
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    assert result["regular_pay_estimate_pence"] == 24000


def test_settings_forecast_excludes_future_dated_payslips(
    forecast_database,
):
    configure_settings(forecast_database)

    add_income(
        forecast_database,
        "2026-10-30",
        gross_pay_pence=30000,
        net_pay_pence=24000,
    )

    add_income(
        forecast_database,
        "2026-11-06",
        gross_pay_pence=60000,
        net_pay_pence=48000,
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    assert result["historical_payslips_used"] == 1
    assert result["regular_pay_estimate_pence"] == 24000


def test_settings_forecast_uses_only_payslips_on_or_before_as_of_date(
    forecast_database,
):
    configure_settings(forecast_database)

    add_income(
        forecast_database,
        "2026-10-30",
        net_pay_pence=20000,
    )
    add_income(
        forecast_database,
        "2026-11-01",
        net_pay_pence=30000,
    )
    add_income(
        forecast_database,
        "2026-11-02",
        net_pay_pence=50000,
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    assert result["historical_payslips_used"] == 2
    assert result["regular_pay_estimate_pence"] == 25000


def test_settings_forecast_excludes_dates_with_actual_income(
    forecast_database,
):
    configure_settings(forecast_database)

    add_income(
        forecast_database,
        "2026-11-13",
        gross_pay_pence=30000,
        net_pay_pence=24000,
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )

    actual_dates = [
        entry["date"]
        for entry in result["entries"]
        if entry["type"] == "regular_income"
    ]

    assert actual_dates == [
        date(2026, 11, 6),
        date(2026, 11, 20),
        date(2026, 11, 27),
    ]
    assert result["regular_income_pence"] == 67500
    assert result["forecast_diagnostics"]["recorded_pay_dates_excluded"] == 1


def test_settings_forecast_only_excludes_exact_actual_pay_dates(
    forecast_database,
):
    configure_settings(forecast_database)

    add_income(
        forecast_database,
        "2026-11-12",
        gross_pay_pence=30000,
        net_pay_pence=24000,
    )

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 20),
    )

    actual_dates = [
        entry["date"]
        for entry in result["entries"]
        if entry["type"] == "regular_income"
    ]

    assert actual_dates == [
        date(2026, 11, 6),
        date(2026, 11, 13),
        date(2026, 11, 20),
    ]
    assert result["forecast_diagnostics"]["recorded_pay_dates_excluded"] == 0


def test_settings_forecast_excludes_payslips_older_than_eight_weeks(
    forecast_database,
):
    configure_settings(forecast_database)

    # Forecast starts on 1 November. The window starts on 6 September.
    add_income(forecast_database, "2026-09-05", net_pay_pence=100000)
    add_income(forecast_database, "2026-09-06", net_pay_pence=20000)
    add_income(forecast_database, "2026-10-30", net_pay_pence=40000)

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    # 5 September is outside the window; 6 September is included.
    assert result["historical_payslips_used"] == 2
    assert result["regular_pay_estimate_pence"] == 30000


def test_settings_forecast_uses_fallback_without_payslips_in_window(
    forecast_database,
):
    configure_settings(forecast_database)

    add_income(forecast_database, "2026-09-05", net_pay_pence=50000)

    result = forecast_income_from_settings(
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 6),
    )

    assert result["historical_payslips_used"] == 0
    assert result["estimation_method"] == "gross_less_provisional_25_percent"
    assert result["fallback_gross_estimate_pence"] == 30000
    assert result["regular_pay_estimate_pence"] == 22500
