
"""SQLite database connection and schema initialisation."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

from budget_app.paths import get_database_path


SCHEMA_VERSION = 1


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_balance_pence INTEGER NOT NULL DEFAULT 0,
    hourly_wage_pence INTEGER NOT NULL DEFAULT 0,
    average_hours REAL NOT NULL DEFAULT 0,
    tax_code TEXT NOT NULL DEFAULT '1257L',
    pension_percent REAL NOT NULL DEFAULT 0,
    student_loan_plan TEXT NOT NULL DEFAULT 'None',
    ni_category TEXT NOT NULL DEFAULT 'A',
    scottish_taxpayer INTEGER NOT NULL DEFAULT 1
        CHECK (scottish_taxpayer IN (0, 1)),
    projection_months INTEGER NOT NULL DEFAULT 12
        CHECK (projection_months BETWEEN 1 AND 120)
);

CREATE TABLE IF NOT EXISTS income_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_date TEXT NOT NULL,
    hours_worked REAL NOT NULL DEFAULT 0
        CHECK (hours_worked >= 0),
    gross_pay_pence INTEGER NOT NULL
        CHECK (gross_pay_pence >= 0),
    tax_paid_pence INTEGER NOT NULL DEFAULT 0
        CHECK (tax_paid_pence >= 0),
    ni_paid_pence INTEGER NOT NULL DEFAULT 0
        CHECK (ni_paid_pence >= 0),
    pension_paid_pence INTEGER NOT NULL DEFAULT 0
        CHECK (pension_paid_pence >= 0),
    net_pay_pence INTEGER NOT NULL
        CHECK (net_pay_pence >= 0),
    source_file TEXT,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    CHECK (
        length(pay_date) = 10
        AND date(pay_date) IS NOT NULL
        AND date(pay_date) = pay_date
    )
);

CREATE TABLE IF NOT EXISTS fixed_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Other',
    amount_pence INTEGER NOT NULL
        CHECK (amount_pence >= 0),
    due_day INTEGER
        CHECK (due_day IS NULL OR due_day BETWEEN 1 AND 31),
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE TABLE IF NOT EXISTS variable_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    monthly_amount_pence INTEGER NOT NULL
        CHECK (monthly_amount_pence >= 0),
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    balance_pence INTEGER NOT NULL
        CHECK (balance_pence >= 0),
    monthly_payment_pence INTEGER NOT NULL DEFAULT 0
        CHECK (monthly_payment_pence >= 0),
    due_day INTEGER
        CHECK (due_day IS NULL OR due_day BETWEEN 1 AND 31),
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1)),
    original_balance_pence INTEGER NOT NULL
        CHECK (original_balance_pence >= 0),
    last_payment_date TEXT,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    CHECK (
        last_payment_date IS NULL
        OR (
            length(last_payment_date) = 10
            AND date(last_payment_date) IS NOT NULL
            AND date(last_payment_date) = last_payment_date
        )
    )
);

CREATE TABLE IF NOT EXISTS savings_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount_pence INTEGER NOT NULL
        CHECK (target_amount_pence > 0),
    current_amount_pence INTEGER NOT NULL DEFAULT 0
        CHECK (current_amount_pence >= 0),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE INDEX IF NOT EXISTS idx_income_history_pay_date
    ON income_history(pay_date);

CREATE INDEX IF NOT EXISTS idx_fixed_expenses_active
    ON fixed_expenses(active);

CREATE INDEX IF NOT EXISTS idx_variable_expenses_active
    ON variable_expenses(active);

CREATE INDEX IF NOT EXISTS idx_debts_active
    ON debts(active);
"""


def connect_database(
    database_path: str | Path | None = None,
) -> sqlite3.Connection:
    """Open a database connection with foreign keys enabled."""

    if database_path is None:
        path = get_database_path()
    else:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")

    return connection


def initialise_database(
    connection: sqlite3.Connection,
) -> None:
    """Create the application schema and initial settings if needed."""

    current_version = connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0]

    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            "The database was created by a newer version "
            f"of BudgetApp (schema {current_version}). "
            f"This version supports schema {SCHEMA_VERSION}."
        )

    connection.executescript(SCHEMA_SQL)

    connection.execute(
        """
        INSERT OR IGNORE INTO settings (id)
        VALUES (1)
        """
    )

    connection.execute(
        f"PRAGMA user_version = {SCHEMA_VERSION}"
    )
    

@contextmanager
def database_connection(database_path: str | Path | None = None):
    """Manage a database connection and always close it."""

    connection = connect_database(database_path)

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

