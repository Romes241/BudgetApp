"""Regression tests for the schema v3-to-v4 payment-line migration."""

import sqlite3

import pytest

from budget_app.database import (
    SCHEMA_VERSION,
    connect_database,
    initialise_database,
)


def create_version_three_database(database_path):
    """Create a schema-v3 database containing an existing payment line."""

    with connect_database(database_path) as connection:
        # Initialise the other tables, then recreate the payment-line table
        # with the original v3 classification constraint.
        initialise_database(connection)

        connection.execute("DROP TABLE income_payment_lines")

        connection.execute(
            """
            CREATE TABLE income_payment_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                income_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                units REAL,
                rate_pence INTEGER,
                amount_pence INTEGER NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (
                        classification IN (
                            'regular', 'additional', 'bonus', 'unknown'
                        )
                    ),
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ),
                FOREIGN KEY (income_id)
                    REFERENCES income_history(id) ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_income_payment_lines_income
            ON income_payment_lines(income_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_income_payment_lines_classification
            ON income_payment_lines(classification)
            """
        )

        cursor = connection.execute(
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
            ("2026-10-23", 8, 12000, 1000, 500, 0, 10500),
        )
        income_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO income_payment_lines (
                income_id,
                description,
                units,
                rate_pence,
                amount_pence,
                classification,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                income_id,
                "Basic Pay - associates",
                8.0,
                1391,
                11128,
                "regular",
                "2026-10-23T12:00:00.000Z",
            ),
        )

        connection.execute("PRAGMA user_version = 3")
        connection.commit()


def test_v3_migration_preserves_existing_payment_line(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        line = connection.execute(
            """
            SELECT *
            FROM income_payment_lines
            WHERE id = 1
            """
        ).fetchone()

        assert line is not None
        assert line["income_id"] == 1
        assert line["description"] == "Basic Pay - associates"
        assert line["units"] == 8.0
        assert line["rate_pence"] == 1391
        assert line["amount_pence"] == 11128
        assert line["classification"] == "regular"
        assert line["created_at"] == "2026-10-23T12:00:00.000Z"


def test_v3_migration_allows_holiday_classification(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

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
            (1, "Holiday Pay - Associates", 11017, "holiday"),
        )

        line = connection.execute(
            """
            SELECT classification
            FROM income_payment_lines
            WHERE description = ?
            """,
            ("Holiday Pay - Associates",),
        ).fetchone()

        assert line["classification"] == "holiday"


def test_payment_line_rejects_invalid_classification(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        with pytest.raises(sqlite3.IntegrityError):
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
                (1, "Invalid line", 1000, "not-a-classification"),
            )


def test_v4_migration_preserves_indexes_and_foreign_key(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(income_payment_lines)"
            ).fetchall()
        }

        assert "idx_income_payment_lines_income" in indexes
        assert "idx_income_payment_lines_classification" in indexes

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(income_payment_lines)"
        ).fetchall()

        assert any(
            row["table"] == "income_history"
            and row["from"] == "income_id"
            and row["to"] == "id"
            and row["on_delete"].upper() == "CASCADE"
            for row in foreign_keys
        )

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

        assert violations == []


def test_v3_migration_sets_schema_version_to_four(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)

        version = connection.execute("PRAGMA user_version").fetchone()[0]

        assert version == SCHEMA_VERSION == 4


def test_v4_migration_is_safe_to_repeat(tmp_path):
    database_path = tmp_path / "legacy_v3.db"
    create_version_three_database(database_path)

    with connect_database(database_path) as connection:
        initialise_database(connection)
        initialise_database(connection)

        lines = connection.execute(
            "SELECT COUNT(*) FROM income_payment_lines"
        ).fetchone()[0]

        assert lines == 1

        version = connection.execute("PRAGMA user_version").fetchone()[0]

        assert version == 4
