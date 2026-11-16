"""Create and restore validated SQLite backups of BudgetApp data."""

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from budget_app.database import SCHEMA_VERSION, connect_database, initialise_database
from budget_app.paths import get_app_data_dir, get_database_path

_REQUIRED_TABLES = {
    "settings",
    "income_history",
    "fixed_expenses",
    "variable_expenses",
    "debts",
    "savings_goals",
}


def _database_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _validate_connection(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"Database integrity check failed: {integrity}")

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if not 1 <= version <= SCHEMA_VERSION:
        raise ValueError(
            "This file is not a supported BudgetApp backup or was created by a "
            "newer version of BudgetApp."
        )

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing_tables = _REQUIRED_TABLES - tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise ValueError(f"This file is missing BudgetApp data tables: {missing}.")

    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise ValueError("This backup contains invalid linked records.")


def _validate_backup(path: Path) -> None:
    if not path.is_file():
        raise ValueError("The selected backup file could not be found.")

    connection = None
    try:
        connection = sqlite3.connect(_database_uri(path), uri=True)
        _validate_connection(connection)
    except sqlite3.DatabaseError as exc:
        raise ValueError(
            "The selected file is not a readable BudgetApp backup."
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _temporary_database_path(directory: Path, prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(
        dir=directory,
        prefix=f".{prefix}-",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(filename)


def _copy_database(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(source_path, timeout=10)
    try:
        destination = sqlite3.connect(destination_path, timeout=10)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _write_atomic_backup(destination_path: Path) -> None:
    database_path = get_database_path()
    if not database_path.is_file():
        raise RuntimeError("The BudgetApp database could not be found.")
    if destination_path.resolve() == database_path.resolve():
        raise ValueError("Choose a backup location outside the BudgetApp data file.")

    temporary_path = _temporary_database_path(
        destination_path.parent,
        destination_path.name,
    )
    try:
        _copy_database(database_path, temporary_path)
        _validate_backup(temporary_path)
        os.replace(temporary_path, destination_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_backup(destination: str | Path) -> Path:
    """Create a consistent, validated backup at the selected destination."""

    destination_path = Path(destination).expanduser().resolve()
    _write_atomic_backup(destination_path)
    return destination_path


def _create_safety_backup() -> Path:
    backup_directory = get_app_data_dir() / "backups"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_directory / f"budget-safety-backup-{timestamp}.db"
    return create_backup(backup_path)


def restore_backup(source: str | Path) -> Path:
    """Restore a supported backup after saving a safety copy of current data."""

    source_path = Path(source).expanduser().resolve()
    database_path = get_database_path().resolve()
    if source_path == database_path:
        raise ValueError("Select a backup file, not the active BudgetApp database.")

    _validate_backup(source_path)

    temporary_path = _temporary_database_path(
        database_path.parent,
        "budget-restore",
    )
    try:
        _copy_database(source_path, temporary_path)
        replacement = connect_database(temporary_path)
        try:
            initialise_database(replacement)
            _validate_connection(replacement)
        finally:
            replacement.close()

        safety_backup = _create_safety_backup()
        os.replace(temporary_path, database_path)
        return safety_backup
    except sqlite3.DatabaseError as exc:
        raise ValueError("The selected backup could not be restored.") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
