
import sqlite3

import pytest

from budget_app.database import (
    SCHEMA_VERSION,
    connect_database,
    initialise_database,
)


EXPECTED_TABLES = {
    "settings",
    "income_history",
    "fixed_expenses",
    "variable_expenses",
    "debts",
    "savings_goals",
}


def test_initialise_creates_finance_tables(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert EXPECTED_TABLES.issubset(tables)
        assert "transactions" not in tables
        assert "accounts" not in tables
        assert "categories" not in tables


def test_initialise_creates_default_settings(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        settings = connection.execute(
            "SELECT * FROM settings WHERE id = 1"
        ).fetchone()

        assert settings is not None
        assert settings["current_balance_pence"] == 0
        assert settings["projection_months"] == 12


def test_initialise_is_safe_to_repeat(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)
        initialise_database(connection)

        count = connection.execute(
            "SELECT COUNT(*) FROM settings"
        ).fetchone()[0]

        assert count == 1


def test_schema_version_is_set(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        assert version == SCHEMA_VERSION


def test_fixed_expense_can_be_saved(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        connection.execute(
            """
            INSERT INTO fixed_expenses (
                name, category, amount_pence, due_day
            )
            VALUES (?, ?, ?, ?)
            """,
            ("Rent", "Housing", 47000, 1),
        )

        expense = connection.execute(
            "SELECT * FROM fixed_expenses WHERE name = ?",
            ("Rent",),
        ).fetchone()

        assert expense["amount_pence"] == 47000
        assert expense["due_day"] == 1
        assert expense["active"] == 1


def test_expense_rejects_negative_amount(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fixed_expenses (
                    name, amount_pence
                )
                VALUES (?, ?)
                """,
                ("Invalid expense", -100),
            )


def test_income_history_persists_after_reopening(tmp_path):
    database_path = tmp_path / "test.db"

    with connect_database(database_path) as connection:
        initialise_database(connection)

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-19", 36, 50000, 5000, 2000, 1500, 41500),
        )

    with connect_database(database_path) as connection:
        income = connection.execute(
            "SELECT * FROM income_history"
        ).fetchone()

        assert income["gross_pay_pence"] == 50000
        assert income["net_pay_pence"] == 41500
        assert income["hours_worked"] == 36


def test_debt_rejects_negative_balance(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO debts (
                    name,
                    balance_pence,
                    original_balance_pence
                )
                VALUES (?, ?, ?)
                """,
                ("Invalid debt", -100, 1000),
            )


def test_savings_goal_requires_positive_target(tmp_path):
    with connect_database(tmp_path / "test.db") as connection:
        initialise_database(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO savings_goals (
                    name, target_amount_pence
                )
                VALUES (?, ?)
                """,
                ("Invalid goal", 0),
            )
            
def create_version_one_database(database_path):
    """Create the previous schema and populate an existing payslip."""

    with connect_database(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_balance_pence INTEGER NOT NULL DEFAULT 0,
                hourly_wage_pence INTEGER NOT NULL DEFAULT 0,
                average_hours REAL NOT NULL DEFAULT 0,
                tax_code TEXT NOT NULL DEFAULT '1257L',
                pension_percent REAL NOT NULL DEFAULT 0,
                student_loan_plan TEXT NOT NULL DEFAULT 'None',
                ni_category TEXT NOT NULL DEFAULT 'A',
                scottish_taxpayer INTEGER NOT NULL DEFAULT 1,
                projection_months INTEGER NOT NULL DEFAULT 12
            );

            CREATE TABLE income_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pay_date TEXT NOT NULL,
                hours_worked REAL NOT NULL DEFAULT 0,
                gross_pay_pence INTEGER NOT NULL,
                tax_paid_pence INTEGER NOT NULL DEFAULT 0,
                ni_paid_pence INTEGER NOT NULL DEFAULT 0,
                pension_paid_pence INTEGER NOT NULL DEFAULT 0,
                net_pay_pence INTEGER NOT NULL,
                source_file TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            PRAGMA user_version = 1;
            """
        )

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-19", 36, 58131, 7203, 2714, 0, 46369),
        )


def test_version_one_migration_preserves_income(tmp_path):
    database_path = tmp_path / "legacy.db"
    create_version_one_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        income = connection.execute(
            "SELECT * FROM income_history WHERE id = 1"
        ).fetchone()

        assert income["gross_pay_pence"] == 58131
        assert income["net_pay_pence"] == 46369
        assert income["bonus_amount_pence"] is None
        assert income["other_deductions_pence"] == 0


def test_migration_creates_payment_and_bonus_tables(tmp_path):
    database_path = tmp_path / "legacy.db"
    create_version_one_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert "income_payment_lines" in tables
        assert "expected_bonuses" in tables


def test_migration_updates_schema_version(tmp_path):
    database_path = tmp_path / "legacy.db"
    create_version_one_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        assert version == SCHEMA_VERSION == 4


def test_migration_is_safe_to_repeat(tmp_path):
    database_path = tmp_path / "legacy.db"
    create_version_one_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)
        initialise_database(connection)

        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM income_history
            WHERE pay_date = '2026-10-19'
            """
        ).fetchone()[0]

        assert count == 1


def test_payment_line_requires_existing_income(tmp_path):
    database_path = tmp_path / "test.db"

    with connect_database(database_path) as connection:
        initialise_database(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO income_payment_lines (
                    income_id, description, amount_pence
                )
                VALUES (999, 'Bonus', 10000)
                """
            )

def test_migration_creates_imported_payslips_table(tmp_path):
    database_path = tmp_path / "legacy.db"
    create_version_one_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(imported_payslips)"
            ).fetchall()
        }

        assert {
            "id",
            "source_hash",
            "source_file",
            "income_id",
            "imported_at",
        }.issubset(columns)

        indexes = connection.execute(
            "PRAGMA index_list(imported_payslips)"
        ).fetchall()

        unique_indexes = [
            index["name"]
            for index in indexes
            if index["unique"]
        ]
        assert len(unique_indexes) >= 2
