from datetime import date, datetime
from decimal import Decimal

import pytest

from budget_app.database import (
    connect_database,
    database_connection,
    initialise_database,
)
from budget_app.services.settings_service import (
    get_pension_estimate,
    get_settings,
    save_settings,
)


@pytest.fixture
def settings_database(tmp_path, monkeypatch):
    database_path = tmp_path / "settings.db"

    def test_connection():
        return database_connection(database_path)

    monkeypatch.setattr(
        "budget_app.services.settings_service.database_connection",
        test_connection,
    )

    with connect_database(database_path) as connection:
        initialise_database(connection)

    return database_path


def valid_settings(**overrides):
    values = {
        "current_balance": "1250.50",
        "hourly_wage": "15.25",
        "average_hours": 25.5,
        "tax_code": "1257L",
        "pension_percent": 5.0,
        "student_loan_plan": "Plan 2",
        "ni_category": "A",
        "scottish_taxpayer": True,
        "projection_months": 12,
        "pay_frequency": "weekly",
        "next_pay_date": date(2026, 11, 6),
        "early_payment_offset_days": 1,
    }
    values.update(overrides)
    return values


def add_income(database_path, pay_date, gross_pay_pence, pension_paid_pence):
    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO income_history (
                pay_date,
                hours_worked,
                gross_pay_pence,
                tax_paid_pence,
                ni_paid_pence,
                pension_paid_pence,
                net_pay_pence
            )
            VALUES (?, 20, ?, 0, 0, ?, ?)
            """,
            (
                pay_date,
                gross_pay_pence,
                pension_paid_pence,
                gross_pay_pence - pension_paid_pence,
            ),
        )


def test_get_settings_returns_database_defaults(settings_database):
    settings = get_settings()

    assert settings["current_balance"] == Decimal(0)
    assert settings["hourly_wage"] == Decimal(0)
    assert settings["average_hours"] == 0
    assert settings["tax_code"] == "1257L"
    assert settings["pension_percent"] == 0
    assert settings["student_loan_plan"] == "None"
    assert settings["ni_category"] == "A"
    assert settings["scottish_taxpayer"] is True
    assert settings["projection_months"] == 12
    assert settings["pay_frequency"] == "weekly"
    assert settings["next_pay_date"] is None
    assert settings["early_payment_offset_days"] == 1


def test_save_settings_persists_all_values(settings_database):
    save_settings(**valid_settings())

    settings = get_settings()

    assert settings["current_balance"] == Decimal("1250.50")
    assert settings["hourly_wage"] == Decimal("15.25")
    assert settings["average_hours"] == 25.5
    assert settings["tax_code"] == "1257L"
    assert settings["pension_percent"] == 5.0
    assert settings["student_loan_plan"] == "Plan 2"
    assert settings["ni_category"] == "A"
    assert settings["scottish_taxpayer"] is True
    assert settings["projection_months"] == 12
    assert settings["pay_frequency"] == "weekly"
    assert settings["next_pay_date"] == "2026-11-06"
    assert settings["early_payment_offset_days"] == 1


def test_save_settings_allows_negative_current_balance(settings_database):
    save_settings(**valid_settings(current_balance="-50.25"))

    assert get_settings()["current_balance"] == Decimal("-50.25")


@pytest.mark.parametrize("frequency", ["weekly", "fortnightly", "monthly"])
def test_save_settings_accepts_supported_pay_frequencies(
    settings_database,
    frequency,
):
    save_settings(**valid_settings(pay_frequency=frequency))

    assert get_settings()["pay_frequency"] == frequency


def test_save_settings_can_clear_next_pay_date(settings_database):
    save_settings(**valid_settings(next_pay_date=None))

    assert get_settings()["next_pay_date"] is None


@pytest.mark.parametrize("wage", ["-0.01", -1])
def test_save_settings_rejects_negative_hourly_wage(settings_database, wage):
    with pytest.raises(ValueError, match="Hourly wage cannot be negative"):
        save_settings(**valid_settings(hourly_wage=wage))


@pytest.mark.parametrize("hours", [-1, 168.1, float("nan"), float("inf")])
def test_save_settings_rejects_invalid_average_hours(settings_database, hours):
    with pytest.raises(ValueError, match="Average weekly hours"):
        save_settings(**valid_settings(average_hours=hours))


@pytest.mark.parametrize("percentage", [-0.1, 100.1, float("nan")])
def test_save_settings_rejects_invalid_pension_percentage(
    settings_database,
    percentage,
):
    with pytest.raises(ValueError, match="Pension percentage"):
        save_settings(**valid_settings(pension_percent=percentage))


@pytest.mark.parametrize("months", [0, 121, True, 1.5])
def test_save_settings_rejects_invalid_projection_months(
    settings_database,
    months,
):
    with pytest.raises(ValueError, match="Projection months"):
        save_settings(**valid_settings(projection_months=months))


@pytest.mark.parametrize("offset", [-1, 8, True, 1.5])
def test_save_settings_rejects_invalid_early_payment_offset(
    settings_database,
    offset,
):
    with pytest.raises(ValueError, match="Early payment offset"):
        save_settings(**valid_settings(early_payment_offset_days=offset))


def test_save_settings_rejects_invalid_pay_frequency(settings_database):
    with pytest.raises(ValueError, match="Pay frequency"):
        save_settings(**valid_settings(pay_frequency="daily"))


@pytest.mark.parametrize("pay_date", ["2026-2-06", "not-a-date", "2026-02-30"])
def test_save_settings_rejects_invalid_next_pay_date(settings_database, pay_date):
    with pytest.raises(ValueError, match="Next pay date"):
        save_settings(**valid_settings(next_pay_date=pay_date))


def test_save_settings_rejects_empty_tax_and_ni_fields(settings_database):
    with pytest.raises(ValueError, match="Tax code"):
        save_settings(**valid_settings(tax_code="  "))

    with pytest.raises(ValueError, match="NI category"):
        save_settings(**valid_settings(ni_category="  "))


def test_save_settings_requires_boolean_scottish_taxpayer(settings_database):
    with pytest.raises(ValueError, match="Scottish taxpayer"):
        save_settings(**valid_settings(scottish_taxpayer=1))


def test_save_settings_rejects_empty_student_loan_plan(settings_database):
    with pytest.raises(ValueError, match="Student loan plan"):
        save_settings(**valid_settings(student_loan_plan="  "))


def test_pension_estimate_uses_weighted_recent_income(settings_database):
    add_income(settings_database, "2026-10-30", 300000, 15000)
    add_income(settings_database, "2026-10-23", 100000, 8000)

    estimate = get_pension_estimate(as_of_date=date(2026, 11, 3))

    assert estimate["percentage"] == Decimal("5.75")
    assert estimate["payslips_used"] == 2
    assert estimate["gross_pay_pence"] == 400000
    assert estimate["pension_paid_pence"] == 23000


def test_pension_estimate_includes_lookback_boundary_and_excludes_older_and_future(
    settings_database,
):
    # 8 September is exactly 56 days before 3 November 2026.
    add_income(settings_database, "2026-09-08", 100000, 5000)
    add_income(settings_database, "2026-09-07", 900000, 90000)
    add_income(settings_database, "2026-11-04", 500000, 50000)

    estimate = get_pension_estimate(as_of_date=date(2026, 11, 3))

    assert estimate["percentage"] == Decimal("5.00")
    assert estimate["payslips_used"] == 1
    assert estimate["window_start"] == date(2026, 9, 8)
    assert estimate["window_end"] == date(2026, 11, 3)


def test_pension_estimate_returns_none_without_recent_income(settings_database):
    add_income(settings_database, "2026-09-07", 100000, 5000)

    assert get_pension_estimate(as_of_date=date(2026, 11, 3)) is None


def test_pension_estimate_can_return_zero_percent(settings_database):
    add_income(settings_database, "2026-10-30", 100000, 0)

    estimate = get_pension_estimate(as_of_date=date(2026, 11, 3))

    assert estimate["percentage"] == Decimal("0.00")
    assert estimate["payslips_used"] == 1


def test_pension_estimate_does_not_overwrite_saved_setting(settings_database):
    save_settings(**valid_settings(pension_percent=4.5))
    add_income(settings_database, "2026-10-30", 100000, 5000)

    estimate = get_pension_estimate(as_of_date=date(2026, 11, 3))
    settings = get_settings()

    assert estimate["percentage"] == Decimal("5.00")
    assert settings["pension_percent"] == 4.5


def test_pension_estimate_rejects_datetime_as_as_of_date(settings_database):
    with pytest.raises(ValueError, match="As-of date must be a date"):
        get_pension_estimate(as_of_date=datetime(2026, 11, 3, 12, 0))
