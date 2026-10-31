"""Operations for managing variable expenses."""

import sqlite3
from decimal import Decimal
from typing import Any

from budget_app.database import database_connection
from budget_app.money import from_pence, to_pence

_UNSET = object()


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Expense name cannot be empty.")

    return name.strip()


def _validate_monthly_amount(amount: Any) -> int:
    amount_pence = to_pence(amount)

    if amount_pence < 0:
        raise ValueError("Monthly expense amount cannot be negative.")

    return amount_pence


def _record_to_dict(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["monthly_amount"] = from_pence(record["monthly_amount_pence"])
    return record


def get_variable_expenses(
    include_inactive: bool = False,
) -> list[dict]:
    """Return variable expenses, excluding inactive records by default."""

    query = "SELECT * FROM variable_expenses"

    if not include_inactive:
        query += " WHERE active = 1"

    query += " ORDER BY name COLLATE NOCASE, id"

    with database_connection() as connection:
        rows = connection.execute(query).fetchall()

    return [_record_to_dict(row) for row in rows]


def get_variable_expense(expense_id: int) -> dict | None:
    """Return a variable expense by ID, including inactive records."""

    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM variable_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()

    return _record_to_dict(row) if row is not None else None


def add_variable_expense(
    name: str,
    monthly_amount: str | float | Decimal,
) -> int:
    """Create a variable expense and return its database ID."""

    validated_name = _validate_name(name)
    amount_pence = _validate_monthly_amount(monthly_amount)

    with database_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO variable_expenses (
                name,
                monthly_amount_pence
            )
            VALUES (?, ?)
            """,
            (validated_name, amount_pence),
        )

        return cursor.lastrowid


def update_variable_expense(
    expense_id: int,
    name: str | object = _UNSET,
    monthly_amount: str | float | Decimal | object = _UNSET,
) -> bool:
    """Update a variable expense.

    Fields omitted from the call remain unchanged.
    Returns False if the expense does not exist.
    """

    if name is _UNSET and monthly_amount is _UNSET:
        raise ValueError("At least one field must be provided.")

    updates = {}

    if name is not _UNSET:
        updates["name"] = _validate_name(name)

    if monthly_amount is not _UNSET:
        updates["monthly_amount_pence"] = _validate_monthly_amount(monthly_amount)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(expense_id)

    with database_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE variable_expenses
            SET {assignments}
            WHERE id = ?
            """,
            values,
        )

        return cursor.rowcount > 0


def deactivate_variable_expense(expense_id: int) -> bool:
    """Mark a variable expense as inactive without deleting it."""

    with database_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE variable_expenses
            SET active = 0
            WHERE id = ?
            """,
            (expense_id,),
        )

        return cursor.rowcount > 0
