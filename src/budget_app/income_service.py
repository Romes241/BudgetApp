
"""Operations for actual income history."""

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from budget_app.database import database_connection
from budget_app.money import to_pence, from_pence


MONEY_FIELDS = (
    "gross_pay",
    "tax_paid",
    "ni_paid",
    "pension_paid",
    "net_pay",
)


def _validate_date(pay_date: str) -> None:
    try:
        parsed = date.fromisoformat(pay_date)
    except (TypeError, ValueError):
        raise ValueError("Pay date must use YYYY-MM-DD format.") from None

    if parsed.isoformat() != pay_date:
        raise ValueError("Pay date must use YYYY-MM-DD format.")


def _validate_hours(hours_worked: int | float) -> float:
    try:
        hours = Decimal(str(hours_worked))
    except Exception:
        raise ValueError("Hours worked must be a valid number.") from None

    if not hours.is_finite() or hours < 0:
        raise ValueError("Hours worked must be finite and non-negative.")

    return float(hours)


def _validate_amounts(
    gross_pay: Any,
    tax_paid: Any,
    ni_paid: Any,
    pension_paid: Any,
    net_pay: Any,
) -> dict[str, int]:
    amounts = {
        "gross_pay": to_pence(gross_pay),
        "tax_paid": to_pence(tax_paid),
        "ni_paid": to_pence(ni_paid),
        "pension_paid": to_pence(pension_paid),
        "net_pay": to_pence(net_pay),
    }

    if any(amount < 0 for amount in amounts.values()):
        raise ValueError("Income and deduction amounts cannot be negative.")

    return amounts


def _record_to_dict(row: sqlite3.Row) -> dict:
    record = dict(row)

    for field in MONEY_FIELDS:
        record[field] = from_pence(record[f"{field}_pence"])

    return record


def get_income_history() -> list[dict]:
    """Return income records ordered by most recent pay date."""

    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM income_history
            ORDER BY pay_date DESC, id DESC
            """
        ).fetchall()

    return [_record_to_dict(row) for row in rows]


def add_income(
    pay_date: str,
    hours_worked: int | float,
    gross_pay: str | int | float | Decimal,
    tax_paid: str | int | float | Decimal,
    ni_paid: str | int | float | Decimal,
    pension_paid: str | int | float | Decimal,
    net_pay: str | int | float | Decimal,
    source_file: str | None = None,
) -> int:
    """Add an actual pay record and return its database ID."""

    _validate_date(pay_date)
    hours = _validate_hours(hours_worked)
    amounts = _validate_amounts(
        gross_pay, tax_paid, ni_paid, pension_paid, net_pay
    )

    with database_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO income_history (
                pay_date,
                hours_worked,
                gross_pay_pence,
                tax_paid_pence,
                ni_paid_pence,
                pension_paid_pence,
                net_pay_pence,
                source_file
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pay_date,
                hours,
                amounts["gross_pay"],
                amounts["tax_paid"],
                amounts["ni_paid"],
                amounts["pension_paid"],
                amounts["net_pay"],
                source_file,
            ),
        )
        return cursor.lastrowid


def update_income(
    income_id: int,
    pay_date: str,
    hours_worked: int | float,
    gross_pay: str | int | float | Decimal,
    tax_paid: str | int | float | Decimal,
    ni_paid: str | int | float | Decimal,
    pension_paid: str | int | float | Decimal,
    net_pay: str | int | float | Decimal,
    source_file: str | None = None,
) -> bool:
    """Update a pay record. Return False if its ID does not exist."""

    _validate_date(pay_date)
    hours = _validate_hours(hours_worked)
    amounts = _validate_amounts(
        gross_pay, tax_paid, ni_paid, pension_paid, net_pay
    )

    with database_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE income_history
            SET pay_date = ?,
                hours_worked = ?,
                gross_pay_pence = ?,
                tax_paid_pence = ?,
                ni_paid_pence = ?,
                pension_paid_pence = ?,
                net_pay_pence = ?,
                source_file = ?
            WHERE id = ?
            """,
            (
                pay_date,
                hours,
                amounts["gross_pay"],
                amounts["tax_paid"],
                amounts["ni_paid"],
                amounts["pension_paid"],
                amounts["net_pay"],
                source_file,
                income_id,
            ),
        )
        return cursor.rowcount > 0


def delete_income(income_id: int) -> bool:
    """Delete a pay record. Return False if it does not exist."""

    with database_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM income_history WHERE id = ?",
            (income_id,),
        )
        return cursor.rowcount > 0


def income_exists(pay_date: str) -> bool:
    """Check whether any income record exists for a pay date."""

    _validate_date(pay_date)

    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM income_history WHERE pay_date = ?
            )
            """,
            (pay_date,),
        ).fetchone()

    return bool(row[0])
