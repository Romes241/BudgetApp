"""SQLite database connection, schema and migrations."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from budget_app.paths import get_database_path

SCHEMA_VERSION = 4


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
        CHECK (projection_months BETWEEN 1 AND 120),
    pay_frequency TEXT NOT NULL DEFAULT 'weekly'
        CHECK (pay_frequency IN ('weekly', 'fortnightly', 'monthly')),
    next_pay_date TEXT
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
    other_deductions_pence INTEGER NOT NULL DEFAULT 0
        CHECK (other_deductions_pence >= 0),
    bonus_amount_pence INTEGER
        CHECK (bonus_amount_pence IS NULL OR bonus_amount_pence >= 0),
    bonus_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    CHECK (
        length(pay_date) = 10
        AND date(pay_date) IS NOT NULL
        AND date(pay_date) = pay_date
    )
);

CREATE TABLE IF NOT EXISTS income_payment_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    income_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    units REAL,
    rate_pence INTEGER,
    amount_pence INTEGER NOT NULL,
    classification TEXT NOT NULL DEFAULT 'unknown'
        CHECK (
            classification IN (
                'regular', 'additional', 'bonus', 'holiday', 'unknown'
            )
        ),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (income_id)
        REFERENCES income_history(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS imported_payslips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_hash TEXT NOT NULL UNIQUE,
    source_file TEXT NOT NULL,
    income_id INTEGER NOT NULL UNIQUE,
    imported_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (income_id)
        REFERENCES income_history(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expected_bonuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expected_date TEXT NOT NULL,
    amount_pence INTEGER NOT NULL CHECK (amount_pence >= 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unconfirmed'
        CHECK (
            status IN (
                'unconfirmed', 'confirmed', 'received', 'cancelled'
            )
        ),
    received_income_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    CHECK (
        length(expected_date) = 10
        AND date(expected_date) IS NOT NULL
        AND date(expected_date) = expected_date
    ),
    FOREIGN KEY (received_income_id)
        REFERENCES income_history(id) ON DELETE SET NULL
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

CREATE INDEX IF NOT EXISTS idx_income_payment_lines_income
    ON income_payment_lines(income_id);

CREATE INDEX IF NOT EXISTS idx_income_payment_lines_classification
    ON income_payment_lines(classification);

CREATE INDEX IF NOT EXISTS idx_expected_bonuses_date_status
    ON expected_bonuses(expected_date, status);

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


def _table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """Return the column names for an existing table."""

    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _migrate_to_v2(connection: sqlite3.Connection) -> None:
    """Add bonus-aware income fields to a version-1 database."""

    settings_columns = _table_columns(connection, "settings")

    if "pay_frequency" not in settings_columns:
        connection.execute(
            """
            ALTER TABLE settings
            ADD COLUMN pay_frequency TEXT NOT NULL DEFAULT 'weekly'
            CHECK (pay_frequency IN ('weekly', 'fortnightly', 'monthly'))
            """
        )

    if "next_pay_date" not in settings_columns:
        connection.execute("ALTER TABLE settings ADD COLUMN next_pay_date TEXT")

    income_columns = _table_columns(connection, "income_history")
    additions = {
        "other_deductions_pence": (
            "INTEGER NOT NULL DEFAULT 0 CHECK (other_deductions_pence >= 0)"
        ),
        "bonus_amount_pence": (
            "INTEGER CHECK (bonus_amount_pence IS NULL OR bonus_amount_pence >= 0)"
        ),
        "bonus_reason": "TEXT",
    }

    for column, definition in additions.items():
        if column not in income_columns:
            connection.execute(
                f"ALTER TABLE income_history ADD COLUMN {column} {definition}"
            )


def _migrate_to_v3(connection: sqlite3.Connection) -> None:
    """Add tracking for imported payslip files."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS imported_payslips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_hash TEXT NOT NULL UNIQUE,
            source_file TEXT NOT NULL,
            income_id INTEGER NOT NULL UNIQUE,
            imported_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            FOREIGN KEY (income_id)
                REFERENCES income_history(id) ON DELETE CASCADE
        )
        """
    )


def _migrate_to_v4(connection: sqlite3.Connection) -> None:
    """Allow holiday as a payment-line classification.

    SQLite cannot alter an existing CHECK constraint directly, so rebuild
    the table and copy all existing records into the replacement.
    """

    connection.execute(
        """
        CREATE TABLE income_payment_lines_v4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            income_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            units REAL,
            rate_pence INTEGER,
            amount_pence INTEGER NOT NULL,
            classification TEXT NOT NULL DEFAULT 'unknown'
                CHECK (
                    classification IN (
                        'regular', 'additional', 'bonus',
                        'holiday', 'unknown'
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
        INSERT INTO income_payment_lines_v4 (
            id,
            income_id,
            description,
            units,
            rate_pence,
            amount_pence,
            classification,
            created_at
        )
        SELECT
            id,
            income_id,
            description,
            units,
            rate_pence,
            amount_pence,
            classification,
            created_at
        FROM income_payment_lines
        """
    )

    connection.execute("DROP TABLE income_payment_lines")

    connection.execute(
        """
        ALTER TABLE income_payment_lines_v4
        RENAME TO income_payment_lines
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


def initialise_database(
    connection: sqlite3.Connection,
) -> None:
    """Create the schema and migrate older databases."""

    current_version = connection.execute("PRAGMA user_version").fetchone()[0]

    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            "The database was created by a newer version "
            f"of BudgetApp (schema {current_version}). "
            f"This version supports schema {SCHEMA_VERSION}."
        )

    connection.execute("BEGIN")
    try:
        # Execute statements individually; executescript can implicitly commit.
        for statement in SCHEMA_SQL.split(";"):
            if statement.strip():
                connection.execute(statement)

        if current_version < 2:
            _migrate_to_v2(connection)

        if current_version < 3:
            _migrate_to_v3(connection)

        if current_version < 4:
            _migrate_to_v4(connection)

        connection.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


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
