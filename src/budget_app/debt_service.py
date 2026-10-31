"""Operations for managing debts."""

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from budget_app.database import database_connection
from budget_app.money import from_pence, to_pence

_UNSET = object()


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Debt name cannot be empty.")

    return name.strip()


def _validate_amount(amount: Any, field_name: str) -> int:
    amount_pence = to_pence(amount)

    if amount_pence < 0:
        raise ValueError(f"{field_name} cannot be negative.")

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


def _validate_payment_date(payment_date: str | date) -> str:
    if isinstance(payment_date, date):
        return payment_date.isoformat()

    if not isinstance(payment_date, str):
        raise TypeError("Payment date must be a valid date.")

    try:
        parsed_date = date.fromisoformat(payment_date)
    except ValueError:
        raise ValueError("Payment date must use YYYY-MM-DD format.") from None

    if parsed_date.isoformat() != payment_date:
        raise ValueError("Payment date must use YYYY-MM-DD format.")

    return payment_date


def _record_to_dict(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["balance"] = from_pence(record["balance_pence"])
    record["monthly_payment"] = from_pence(record["monthly_payment_pence"])
    record["original_balance"] = from_pence(record["original_balance_pence"])
    return record


def get_debts(include_inactive: bool = False) -> list[dict]:
    """Return debts, excluding inactive records by default."""

    query = "SELECT * FROM debts"

    if not include_inactive:
        query += " WHERE active = 1"

    query += " ORDER BY name COLLATE NOCASE, id"

    with database_connection() as connection:
        rows = connection.execute(query).fetchall()

    return [_record_to_dict(row) for row in rows]


def get_debt(debt_id: int) -> dict | None:
    """Return a debt by ID, including inactive records."""

    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM debts WHERE id = ?",
            (debt_id,),
        ).fetchone()

    return _record_to_dict(row) if row is not None else None


def add_debt(
    name: str,
    balance: str | float | Decimal,
    original_balance: str | float | Decimal,
    monthly_payment: str | float | Decimal = 0,
    due_day: int | None = None,
    last_payment_date: str | date | None = None,
) -> int:
    """Create a debt and return its database ID."""

    validated_name = _validate_name(name)
    balance_pence = _validate_amount(balance, "Balance")
    original_balance_pence = _validate_amount(
        original_balance,
        "Original balance",
    )
    monthly_payment_pence = _validate_amount(
        monthly_payment,
        "Monthly payment",
    )
    validated_due_day = _validate_due_day(due_day)

    if balance_pence > original_balance_pence:
        raise ValueError("Outstanding balance cannot exceed original balance.")

    validated_payment_date = (
        _validate_payment_date(last_payment_date)
        if last_payment_date is not None
        else None
    )

    with database_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO debts (
                name,
                balance_pence,
                original_balance_pence,
                monthly_payment_pence,
                due_day,
                last_payment_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                validated_name,
                balance_pence,
                original_balance_pence,
                monthly_payment_pence,
                validated_due_day,
                validated_payment_date,
            ),
        )

        return cursor.lastrowid


def update_debt(
    debt_id: int,
    name: str | object = _UNSET,
    balance: str | float | Decimal | object = _UNSET,
    original_balance: str | float | Decimal | object = _UNSET,
    monthly_payment: str | float | Decimal | object = _UNSET,
    due_day: int | None | object = _UNSET,
    last_payment_date: str | date | None | object = _UNSET,
) -> bool:
    """Update a debt without changing fields that were not provided.

    Returns False if the debt does not exist.
    """

    if all(
        value is _UNSET
        for value in (
            name,
            balance,
            original_balance,
            monthly_payment,
            due_day,
            last_payment_date,
        )
    ):
        raise ValueError("At least one field must be provided.")

    current = get_debt(debt_id)

    if current is None:
        return False

    updates = {}

    if name is not _UNSET:
        updates["name"] = _validate_name(name)

    if balance is not _UNSET:
        updates["balance_pence"] = _validate_amount(balance, "Balance")

    if original_balance is not _UNSET:
        updates["original_balance_pence"] = _validate_amount(
            original_balance, "Original balance"
        )

    if monthly_payment is not _UNSET:
        updates["monthly_payment_pence"] = _validate_amount(
            monthly_payment, "Monthly payment"
        )

    if due_day is not _UNSET:
        updates["due_day"] = _validate_due_day(due_day)

    if last_payment_date is not _UNSET:
        updates["last_payment_date"] = (
            _validate_payment_date(last_payment_date)
            if last_payment_date is not None
            else None
        )

    new_balance = updates.get("balance_pence", current["balance_pence"])
    new_original_balance = updates.get(
        "original_balance_pence",
        current["original_balance_pence"],
    )

    if new_balance > new_original_balance:
        raise ValueError("Outstanding balance cannot exceed original balance.")

    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(debt_id)

    with database_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE debts
            SET {assignments}
            WHERE id = ?
            """,
            values,
        )

        return cursor.rowcount > 0


def record_debt_payment(
    debt_id: int,
    amount: str | float | Decimal,
    payment_date: str | date,
) -> bool:
    """Record a payment against a debt.

    Reduces the outstanding balance and updates the last payment date.
    Returns False if the debt does not exist.
    """

    amount_pence = _validate_amount(amount, "Payment amount")
    validated_date = _validate_payment_date(payment_date)

    if amount_pence == 0:
        raise ValueError("Payment amount must be greater than zero.")

    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT balance_pence
            FROM debts
            WHERE id = ?
            """,
            (debt_id,),
        ).fetchone()

        if row is None:
            return False

        current_balance = row["balance_pence"]

        if amount_pence > current_balance:
            raise ValueError("Payment cannot exceed the outstanding balance.")

        connection.execute(
            """
            UPDATE debts
            SET balance_pence = balance_pence - ?,
                last_payment_date = ?
            WHERE id = ?
            """,
            (amount_pence, validated_date, debt_id),
        )

    return True


def deactivate_debt(debt_id: int) -> bool:
    """Mark a debt as inactive without deleting it."""

    with database_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE debts
            SET active = 0
            WHERE id = ?
            """,
            (debt_id,),
        )

        return cursor.rowcount > 0
