"""Tests for individual payslip payment-line operations."""

from decimal import Decimal

import pytest

from budget_app.database import database_connection
from budget_app.income_service import add_income, delete_income
from budget_app.payment_line_service import (
    add_payment_line,
    delete_payment_line,
    get_payment_line,
    get_payment_lines,
    update_payment_line,
)


@pytest.fixture
def income_record(tmp_path, monkeypatch):
    """Create an isolated database and one income record."""
    from budget_app import database

    db_path = tmp_path / "payment-lines.db"
    connection = database.connect_database(db_path)
    database.initialise_database(connection)
    connection.close()
    monkeypatch.setattr(database, "get_database_path", lambda: db_path)
    income_id = add_income(
        "2026-10-23", 35, "500.00", "50.00", "20.00",
        "10.00", "420.00"
    )
    return income_id


def test_add_and_retrieve_payment_line(income_record):
    line_id = add_payment_line(
        income_record, "Basic Pay - associates", "500.00",
        units="35", rate="14.2857", classification="regular"
    )

    line = get_payment_line(line_id)
    assert line["income_id"] == income_record
    assert line["description"] == "Basic Pay - associates"
    assert line["amount"] == Decimal("500")
    assert line["amount_pence"] == 50000
    assert line["units"] == 35.0
    assert line["rate"] == Decimal("14.29")
    assert line["classification"] == "regular"


def test_get_payment_lines_for_income(income_record):
    add_payment_line(income_record, "Basic Pay", "400", classification="regular")
    add_payment_line(income_record, "Bonus", "100", classification="bonus")

    lines = get_payment_lines(income_record)
    assert [line["description"] for line in lines] == ["Basic Pay", "Bonus"]


def test_update_payment_line_preserves_omitted_fields(income_record):
    line_id = add_payment_line(
        income_record, "Bonus", "50", classification="bonus", units=2
    )

    assert update_payment_line(line_id, amount="60.50")
    line = get_payment_line(line_id)
    assert line["amount"] == Decimal("60.50")
    assert line["description"] == "Bonus"
    assert line["classification"] == "bonus"
    assert line["units"] == 2.0


def test_update_can_clear_optional_fields(income_record):
    line_id = add_payment_line(income_record, "Basic Pay", "100", units=5, rate=20)
    assert update_payment_line(line_id, units=None, rate=None)
    line = get_payment_line(line_id)
    assert line["units"] is None
    assert line["rate"] is None


def test_delete_payment_line(income_record):
    line_id = add_payment_line(income_record, "Basic Pay", "100")
    assert delete_payment_line(line_id) is True
    assert get_payment_line(line_id) is None
    assert delete_payment_line(line_id) is False


@pytest.mark.parametrize("amount", [-1, "-0.01", "NaN", "Infinity", "not money"])
def test_add_rejects_invalid_amounts(income_record, amount):
    with pytest.raises(ValueError):
        add_payment_line(income_record, "Basic Pay", amount)


@pytest.mark.parametrize("classification", ["", "other", "REGULAR", None])
def test_add_rejects_invalid_classifications(income_record, classification):
    with pytest.raises(ValueError):
        add_payment_line(income_record, "Basic Pay", "100", classification=classification)


@pytest.mark.parametrize("units", [-1, float("nan"), float("inf"), "bad"])
def test_add_rejects_invalid_units(income_record, units):
    with pytest.raises(ValueError):
        add_payment_line(income_record, "Basic Pay", "100", units=units)


def test_add_rejects_blank_description(income_record):
    with pytest.raises(ValueError):
        add_payment_line(income_record, "  ", "100")


def test_add_rejects_missing_parent():
    with pytest.raises(ValueError, match="does not exist"):
        add_payment_line(999999, "Basic Pay", "100")


def test_add_rejects_missing_parent(income_record):
    with pytest.raises(ValueError, match="does not exist"):
        add_payment_line(999999, "Basic Pay", "100")
