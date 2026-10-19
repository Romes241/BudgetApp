
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
