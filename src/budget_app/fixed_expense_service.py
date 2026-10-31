"""Operations for managing fixed expenses."""

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


def _validate_category(category: str) -> str:
    if not isinstance(category, str) or not category.strip():
        raise ValueError("Expense category cannot be empty.")

    return category.strip()


def _validate_amount(amount: Any) -> int:
    amount_pence = to_pence(amount)

    if amount_pence < 0:
        raise ValueError("Expense amount cannot be negative.")

    return amount_pence


def _validate_due_day(due_day: int | None) -> int | None:
    if due_day is None:
        return None

    if (
        isinstance(due_day, bool)
        or not isinstance(due_day, int)
        or not 1 <= due_day <= 31
    ):
        raise ValueError("Due day must be between 1 and 31, or None.")

    return due_day


def _record_to_dict(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["amount"] = from_pence(record["amount_pence"])
    return record


def get_fixed_expenses(
    include_inactive: bool = False,
) -> list[dict]:
    """Return fixed expenses, excluding inactive records by default."""

    query = "SELECT * FROM fixed_expenses"

    if not include_inactive:
        query += " WHERE active = 1"

    query += " ORDER BY name COLLATE NOCASE, id"

    with database_connection() as connection:
        rows = connection.execute(query).fetchall()

    return [_record_to_dict(row) for row in rows]


def get_fixed_expense(expense_id: int) -> dict | None:
    """Return a fixed expense by ID, including inactive records."""

    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM fixed_expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()

    return _record_to_dict(row) if row is not None else None


def add_fixed_expense(
    name: str,
    category: str,
    amount: str | float | Decimal,
    due_day: int | None = None,
) -> int:
    """Create a fixed expense and return its database ID."""

    validated_name = _validate_name(name)
    validated_category = _validate_category(category)
    amount_pence = _validate_amount(amount)
    validated_due_day = _validate_due_day(due_day)

    with database_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO fixed_expenses (
                name,
                category,
                amount_pence,
                due_day
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                validated_name,
                validated_category,
                amount_pence,
                validated_due_day,
            ),
        )

        return cursor.lastrowid


def update_fixed_expense(
    expense_id: int,
    name: str | object = _UNSET,
    category: str | object = _UNSET,
    amount: str | float | Decimal | object = _UNSET,
    due_day: int | None | object = _UNSET,
) -> bool:
    """Update a fixed expense.

    Fields omitted from the call remain unchanged. Pass None explicitly
    for due_day to clear its value.

    Returns False if the expense does not exist.
    """

    if name is _UNSET and category is _UNSET and amount is _UNSET and due_day is _UNSET:
        raise ValueError("At least one field must be provided.")

    updates = {}

    if name is not _UNSET:
        updates["name"] = _validate_name(name)

    if category is not _UNSET:
        updates["category"] = _validate_category(category)

    if amount is not _UNSET:
        updates["amount_pence"] = _validate_amount(amount)

    if due_day is not _UNSET:
        updates["due_day"] = _validate_due_day(due_day)

    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(expense_id)

    with database_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE fixed_expenses
            SET {assignments}
            WHERE id = ?
            """,
            values,
        )

        return cursor.rowcount > 0


def deactivate_fixed_expense(expense_id: int) -> bool:
    """Mark a fixed expense as inactive without deleting it."""

    with database_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE fixed_expenses
            SET active = 0
            WHERE id = ?
            """,
            (expense_id,),
        )

        return cursor.rowcount > 0
