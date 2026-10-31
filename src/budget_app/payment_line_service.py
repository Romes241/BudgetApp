"""CRUD operations for individual payslip payment lines."""

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from budget_app.database import database_connection
from budget_app.money import from_pence, to_pence

CLASSIFICATIONS = {"regular", "additional", "bonus", "holiday", "unknown"}
_UNSET = object()


def _validate_description(description: Any) -> str:
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Description must be a non-empty string.")
    return description.strip()


def _validate_classification(classification: Any) -> str:
    if not isinstance(classification, str) or classification not in CLASSIFICATIONS:
        raise ValueError(
            "Classification must be one of: regular, additional, bonus, holiday, unknown."
        )
    return classification


def _validate_non_negative_money(value: Any, field_name: str) -> int:
    amount = to_pence(value)
    if amount < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return amount


def _validate_optional_non_negative_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field_name} must be a valid number or None.") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field_name} must be finite and non-negative.")
    return float(number)


def _line_to_dict(row: sqlite3.Row) -> dict:
    line = dict(row)
    line["rate"] = (
        from_pence(line["rate_pence"]) if line["rate_pence"] is not None else None
    )
    line["amount"] = from_pence(line["amount_pence"])
    return line


def add_payment_line(
    income_id: int,
    description: str,
    amount: str | float | Decimal,
    units: str | float | Decimal | None = None,
    rate: str | float | Decimal | None = None,
    classification: str = "unknown",
) -> int:
    """Create a payment line and return its ID. Monetary inputs are pounds."""
    if isinstance(income_id, bool) or not isinstance(income_id, int) or income_id <= 0:
        raise ValueError("Income ID must be a positive integer.")

    description = _validate_description(description)
    classification = _validate_classification(classification)
    amount_pence = _validate_non_negative_money(amount, "Amount")
    units_value = _validate_optional_non_negative_number(units, "Units")
    rate_pence = (
        _validate_non_negative_money(rate, "Rate") if rate is not None else None
    )

    with database_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM income_history WHERE id = ?", (income_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"Income record {income_id} does not exist.")

        cursor = connection.execute(
            """
            INSERT INTO income_payment_lines
                (income_id, description, units, rate_pence, amount_pence, classification)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                income_id,
                description,
                units_value,
                rate_pence,
                amount_pence,
                classification,
            ),
        )
        return cursor.lastrowid


def get_payment_line(payment_line_id: int) -> dict | None:
    """Return a payment line by ID, or None if it does not exist."""
    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM income_payment_lines WHERE id = ?",
            (payment_line_id,),
        ).fetchone()
    return _line_to_dict(row) if row is not None else None


def get_payment_lines(income_id: int) -> list[dict]:
    """Return all payment lines for an income record, in creation order."""
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM income_payment_lines
            WHERE income_id = ?
            ORDER BY id
            """,
            (income_id,),
        ).fetchall()
    return [_line_to_dict(row) for row in rows]


def update_payment_line(
    payment_line_id: int,
    *,
    description: Any = _UNSET,
    amount: Any = _UNSET,
    units: Any = _UNSET,
    rate: Any = _UNSET,
    classification: Any = _UNSET,
) -> bool:
    """Update supplied fields; return False if the payment line does not exist."""
    updates: dict[str, Any] = {}

    if description is not _UNSET:
        updates["description"] = _validate_description(description)
    if amount is not _UNSET:
        updates["amount_pence"] = _validate_non_negative_money(amount, "Amount")
    if units is not _UNSET:
        updates["units"] = _validate_optional_non_negative_number(units, "Units")
    if rate is not _UNSET:
        updates["rate_pence"] = (
            _validate_non_negative_money(rate, "Rate") if rate is not None else None
        )
    if classification is not _UNSET:
        updates["classification"] = _validate_classification(classification)

    if not updates:
        return get_payment_line(payment_line_id) is not None

    with database_connection() as connection:
        row = connection.execute(
            "SELECT id FROM income_payment_lines WHERE id = ?", (payment_line_id,)
        ).fetchone()
        if row is None:
            return False
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [payment_line_id]
        connection.execute(
            f"UPDATE income_payment_lines SET {assignments} WHERE id = ?", values
        )
    return True


def delete_payment_line(payment_line_id: int) -> bool:
    """Delete a payment line and return whether a row was deleted."""
    with database_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM income_payment_lines WHERE id = ?",
            (payment_line_id,),
        )
        return cursor.rowcount > 0
