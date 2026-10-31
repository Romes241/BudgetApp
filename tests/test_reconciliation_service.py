"""Tests for read-only income reconciliation."""

import pytest

from budget_app import database
from budget_app.income_service import add_income, get_income_history
from budget_app.payment_line_service import (
    add_payment_line,
    delete_payment_line,
    get_payment_line,
)
from budget_app.reconciliation_service import reconcile_income


@pytest.fixture
def income_record(tmp_path, monkeypatch):
    """Set up an isolated database with one consistent income record."""
    db_path = tmp_path / "reconciliation.db"
    connection = database.connect_database(db_path)
    database.initialise_database(connection)
    connection.close()
    monkeypatch.setattr(database, "get_database_path", lambda: db_path)

    return add_income(
        "2026-10-23",
        35,
        "672.59",
        "90.04",
        "34.45",
        "22.10",
        "526.00",
        other_deductions="0.00",
    )


def test_reconcile_matching_earnings_and_deductions(income_record):
    add_payment_line(income_record, "Basic Pay", "646.85", classification="regular")
    add_payment_line(
        income_record,
        "Enhanced Overnight Payment Per Hr",
        "25.74",
        classification="additional",
    )

    report = reconcile_income(income_record)

    assert report["status"] == "passed"
    assert report["payment_line_count"] == 2
    assert [check["status"] for check in report["checks"]] == ["passed", "passed"]


def test_reconcile_reports_earnings_mismatch(income_record):
    add_payment_line(income_record, "Basic Pay", "600.00", classification="regular")

    report = reconcile_income(income_record)
    check = report["checks"][0]

    assert report["status"] == "failed"
    assert check["status"] == "failed"
    assert check["expected_pence"] == 67259
    assert check["actual_pence"] == 60000
    assert check["difference_pence"] == -7259


def test_reconcile_reports_missing_breakdown(income_record):
    report = reconcile_income(income_record)
    check = report["checks"][0]

    assert report["status"] == "incomplete"
    assert check["status"] == "missing_breakdown"
    assert check["actual_pence"] is None
    assert report["checks"][1]["status"] == "passed"


def test_reconcile_reports_recorded_zero_breakdown(income_record):
    add_payment_line(income_record, "No Earnings", "0.00")

    report = reconcile_income(income_record)
    check = report["checks"][0]

    assert report["status"] == "failed"
    assert check["status"] == "failed"
    assert check["actual_pence"] == 0


def test_reconcile_reports_net_pay_mismatch(tmp_path, monkeypatch):
    db_path = tmp_path / "net-mismatch.db"
    connection = database.connect_database(db_path)
    database.initialise_database(connection)
    connection.close()
    monkeypatch.setattr(database, "get_database_path", lambda: db_path)

    income_id = add_income(
        "2026-10-23", 35, "672.59", "90.04", "34.45", "22.10", "525.00"
    )

    report = reconcile_income(income_id)
    check = next(c for c in report["checks"] if c["name"] == "net_pay")

    assert report["status"] == "failed"
    assert check["status"] == "failed"
    assert check["expected_pence"] == 52600
    assert check["actual_pence"] == 52500
    assert check["difference_pence"] == -100


def test_reconcile_missing_income_record(income_record):
    report = reconcile_income(999999)

    assert report == {
        "income_id": 999999,
        "status": "not_found",
        "checks": [],
    }


@pytest.mark.parametrize("income_id", [0, -1, True, "1", None])
def test_reconcile_rejects_invalid_income_id(income_id):
    with pytest.raises(ValueError, match="Income ID must be a positive integer"):
        reconcile_income(income_id)


def test_reconciliation_does_not_modify_stored_data(income_record):
    line_id = add_payment_line(income_record, "Basic Pay", "672.59")
    before = next(r for r in get_income_history() if r["id"] == income_record)

    reconcile_income(income_record)

    after = next(r for r in get_income_history() if r["id"] == income_record)
    assert before == after
    assert get_payment_line(line_id) is not None
    assert delete_payment_line(line_id)
