import sqlite3
from decimal import Decimal

import pytest

import budget_app.payslip_import_service as import_service
from budget_app.database import connect_database, initialise_database
from budget_app.payslip_extractor import EarningsLine, PayslipData
from budget_app.payslip_import_service import (
    DuplicatePayslipError,
    PayslipValidationError,
    import_payslip,
)


def make_valid_data():
    return PayslipData(
        gross_pay=Decimal("100.00"),
        tax_paid=Decimal("10.00"),
        ni_paid=Decimal("5.00"),
        pension_paid=Decimal("5.00"),
        other_deductions=Decimal("0.00"),
        net_pay=Decimal("80.00"),
        pay_date="2026-10-16",
        source_hash="integration-test-hash",
        earnings=[
            EarningsLine(
                description="Basic Pay",
                units=Decimal(10),
                rate=Decimal("10.00"),
                amount=Decimal("100.00"),
            )
        ],
    )


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "test_budget.db"

    with connect_database(path) as connection:
        initialise_database(connection)

    return path


@pytest.fixture
def extracted_data(monkeypatch):
    data = make_valid_data()
    monkeypatch.setattr(
        import_service,
        "extract_payslip_pdf",
        lambda path: data,
    )
    return data


def table_count(database_path, table):
    with connect_database(database_path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_successful_import_creates_income_lines_and_tracking(
    database_path, extracted_data
):
    result = import_payslip(
        "sample.pdf",
        confirmed=True,
        database_path=database_path,
    )
    income_id = result["income_id"]

    assert table_count(database_path, "income_history") == 1
    assert table_count(database_path, "income_payment_lines") == 1
    assert table_count(database_path, "imported_payslips") == 1
    assert result["reconciliation"]["income_id"] == income_id
    assert result["reconciliation"]["status"] == "passed"

    with connect_database(database_path) as connection:
        income = connection.execute(
            "SELECT * FROM income_history WHERE id = ?",
            (income_id,),
        ).fetchone()

        assert income["gross_pay_pence"] == 10000
        assert income["pension_paid_pence"] == 500
        assert income["other_deductions_pence"] == 0


def test_duplicate_file_is_rejected_without_extra_records(
    database_path, extracted_data
):
    import_payslip(
        "sample.pdf",
        confirmed=True,
        database_path=database_path,
    )

    with pytest.raises(DuplicatePayslipError):
        import_payslip(
            "sample.pdf",
            confirmed=True,
            database_path=database_path,
        )

    assert table_count(database_path, "income_history") == 1
    assert table_count(database_path, "income_payment_lines") == 1
    assert table_count(database_path, "imported_payslips") == 1


def test_invalid_data_writes_nothing(database_path, monkeypatch):
    data = make_valid_data()
    data.pension_paid = None

    monkeypatch.setattr(
        import_service,
        "extract_payslip_pdf",
        lambda path: data,
    )

    with pytest.raises(PayslipValidationError):
        import_payslip(
            "sample.pdf",
            confirmed=True,
            database_path=database_path,
        )

    assert table_count(database_path, "income_history") == 0
    assert table_count(database_path, "income_payment_lines") == 0
    assert table_count(database_path, "imported_payslips") == 0


def test_payment_line_failure_rolls_back_entire_import(
    database_path, extracted_data, monkeypatch
):
    original_connection = import_service.database_connection

    class FailingConnection:
        def __init__(self, path=None):
            self.path = path
            self.context = None
            self.connection = None

        def __enter__(self):
            self.context = original_connection(self.path)
            self.connection = self.context.__enter__()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self.context.__exit__(exc_type, exc_value, traceback)

        def execute(self, sql, parameters=()):
            if "INSERT INTO income_payment_lines" in sql:
                raise sqlite3.IntegrityError("Simulated payment-line failure")

            return self.connection.execute(sql, parameters)

    monkeypatch.setattr(
        import_service,
        "database_connection",
        lambda path=None: FailingConnection(path),
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Simulated payment-line failure",
    ):
        import_payslip(
            "sample.pdf",
            confirmed=True,
            database_path=database_path,
        )

    assert table_count(database_path, "income_history") == 0
    assert table_count(database_path, "income_payment_lines") == 0
    assert table_count(database_path, "imported_payslips") == 0
