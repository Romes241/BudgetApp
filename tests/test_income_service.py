from decimal import Decimal

import pytest

from budget_app.database import (
    connect_database,
    database_connection,
    initialise_database,
)
from budget_app.income_service import (
    add_income,
    delete_income,
    get_income_history,
    income_exists,
    update_income,
)


@pytest.fixture
def income_database(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"

    def test_connection():
        return database_connection(database_path)

    monkeypatch.setattr(
        "budget_app.income_service.database_connection",
        test_connection,
    )

    with connect_database(database_path) as connection:
        initialise_database(connection)

    return database_path


def add_sample_income():
    return add_income(
        pay_date="2026-10-19",
        hours_worked=36,
        gross_pay="500.00",
        tax_paid="50.00",
        ni_paid="20.00",
        pension_paid="15.00",
        net_pay="415.00",
    )


def test_add_income_and_retrieve_it(income_database):
    income_id = add_sample_income()

    history = get_income_history()

    assert len(history) == 1
    assert history[0]["id"] == income_id
    assert history[0]["gross_pay_pence"] == 50000
    assert history[0]["net_pay_pence"] == 41500


def test_income_exists(income_database):
    assert income_exists("2026-10-19") is False

    add_sample_income()

    assert income_exists("2026-10-19") is True


def test_update_income(income_database):
    income_id = add_sample_income()

    updated = update_income(
        income_id,
        "2026-10-26",
        38,
        "550.00",
        "60.00",
        "22.00",
        "16.00",
        "452.00",
    )

    assert updated is True

    history = get_income_history()
    assert history[0]["gross_pay_pence"] == 55000
    assert history[0]["pay_date"] == "2026-10-26"


def test_update_missing_income_returns_false(income_database):
    updated = update_income(
        999,
        "2026-10-26",
        38,
        "550.00",
        "60.00",
        "22.00",
        "16.00",
        "452.00",
    )

    assert updated is False


def test_delete_income(income_database):
    income_id = add_sample_income()

    assert delete_income(income_id) is True
    assert get_income_history() == []
    assert delete_income(income_id) is False


def test_invalid_pay_date_is_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "19/10/2026", 36, 500, 50, 20, 15, 415
        )


def test_impossible_pay_date_is_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-02-30", 36, 500, 50, 20, 15, 415
        )


def test_negative_income_is_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", 36, -500, 50, 20, 15, 415
        )


def test_negative_deduction_is_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", 36, 500, -50, 20, 15, 415
        )


def test_negative_hours_are_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", -1, 500, 50, 20, 15, 415
        )


def test_income_history_is_ordered_newest_first(income_database):
    add_income(
        "2026-10-12", 36, 500, 50, 20, 15, 415
    )
    add_income(
        "2026-10-19", 38, 550, 60, 22, 16, 452
    )

    history = get_income_history()

    assert [record["pay_date"] for record in history] == [
        "2026-10-19",
        "2026-10-12",
    ]


def test_income_persists_after_reopening(income_database):
    income_id = add_sample_income()

    # The service opens and closes its own connection.
    history = get_income_history()

    assert history[0]["id"] == income_id
    assert history[0]["net_pay_pence"] == 41500


def test_duplicate_pay_dates_can_be_recorded(income_database):
    add_sample_income()

    # A pay date is not a unique identifier: multiple payments
    # or corrections may legitimately share a date.
    add_sample_income()

    assert len(get_income_history()) == 2

def test_add_income_with_bonus_details(income_database):
    income_id = add_income(
        "2026-10-19",
        36,
        "581.31",
        "72.03",
        "27.14",
        "18.45",
        "463.69",
        other_deductions="0.00",
        bonus_amount="75.50",
        bonus_reason="Quarterly performance bonus",
    )
    record = get_income_history()[0]

    assert record["id"] == income_id
    assert record["pension_paid"] == Decimal("18.45")
    assert record["other_deductions"] == Decimal("0.00")
    assert record["other_deductions_pence"] == 0
    assert record["bonus_amount"] == Decimal("75.50")
    assert record["bonus_amount_pence"] == 7550
    assert record["bonus_reason"] == "Quarterly performance bonus"


def test_bonus_defaults_to_unknown(income_database):
    add_sample_income()
    record = get_income_history()[0]

    assert record["other_deductions"] == Decimal("0.00")
    assert record["bonus_amount"] is None
    assert record["bonus_amount_pence"] is None
    assert record["bonus_reason"] is None


def test_zero_bonus_is_distinct_from_unknown(income_database):
    add_income(
        "2026-10-19", 36, 500, 50, 20, 15, 415,
        bonus_amount=0,
    )
    record = get_income_history()[0]

    assert record["bonus_amount"] == Decimal("0.00")
    assert record["bonus_amount_pence"] == 0


def test_negative_other_deductions_are_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", 36, 500, 50, 20, 15, 415,
            other_deductions=-1,
        )


def test_negative_bonus_is_rejected(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", 36, 500, 50, 20, 15, 415,
            bonus_amount=-1,
        )


def test_bonus_reason_must_be_string_or_none(income_database):
    with pytest.raises(ValueError):
        add_income(
            "2026-10-19", 36, 500, 50, 20, 15, 415,
            bonus_reason=123,
        )


def test_update_income_changes_bonus_details(income_database):
    income_id = add_sample_income()
    updated = update_income(
        income_id,
        "2026-10-19",
        36,
        581.31,
        72.03,
        27.14,
        18.45,
        463.69,
        other_deductions="0.00",
        bonus_amount="75.50",
        bonus_reason="Performance bonus",
    )

    assert updated is True
    record = get_income_history()[0]
    assert record["other_deductions"] == Decimal("0.00")
    assert record["bonus_amount"] == Decimal("75.50")
    assert record["bonus_reason"] == "Performance bonus"


def test_legacy_update_preserves_bonus_details(income_database):
    income_id = add_income(
        "2026-10-19", 36, 500, 50, 20, 15, 415,
        other_deductions=10,
        bonus_amount=75,
        bonus_reason="Performance bonus",
    )

    update_income(
        income_id, "2026-10-26", 38, 550, 60, 22, 16, 452,
    )
    record = get_income_history()[0]

    assert record["other_deductions"] == Decimal("10.00")
    assert record["bonus_amount"] == Decimal("75.00")
    assert record["bonus_reason"] == "Performance bonus"


def test_update_other_deductions_preserves_bonus(income_database):
    income_id = add_income(
        "2026-10-19", 36, 500, 50, 20, 15, 415,
        bonus_amount=75,
        bonus_reason="Performance bonus",
    )

    update_income(
        income_id, "2026-10-26", 38, 550, 60, 22, 16, 452,
        other_deductions=12,
    )
    record = get_income_history()[0]

    assert record["other_deductions"] == Decimal("12.00")
    assert record["bonus_amount"] == Decimal("75.00")
    assert record["bonus_reason"] == "Performance bonus"


def test_update_can_clear_bonus_details(income_database):
    income_id = add_income(
        "2026-10-19", 36, 500, 50, 20, 15, 415,
        bonus_amount=75,
        bonus_reason="Performance bonus",
    )

    update_income(
        income_id, "2026-10-19", 36, 500, 50, 20, 15, 415,
        bonus_amount=None,
        bonus_reason=None,
    )
    record = get_income_history()[0]

    assert record["bonus_amount"] is None
    assert record["bonus_reason"] is None
