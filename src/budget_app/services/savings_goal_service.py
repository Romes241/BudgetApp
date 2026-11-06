"""Operations for savings goals and their deposit/withdrawal ledger."""

import calendar
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from budget_app.database import database_connection
from budget_app.utils.money import from_pence, to_pence

_UNSET = object()


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Goal name cannot be empty.")
    return name.strip()


def _validate_amount(value: Any, label: str, *, positive: bool = False) -> int:
    amount = to_pence(value)
    if amount < 0 or (positive and amount == 0):
        qualifier = "greater than zero" if positive else "zero or greater"
        raise ValueError(f"{label} must be {qualifier}.")
    return amount


def _validate_date(value: str | date) -> str:
    if isinstance(value, datetime):
        raise ValueError("Transaction date must be a date, not a datetime.")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise TypeError("Transaction date must be a valid date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Transaction date must use YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ValueError("Transaction date must use YYYY-MM-DD format.")
    return value


def _record(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["target_amount"] = from_pence(result["target_amount_pence"])
    result["current_amount"] = from_pence(result["current_amount_pence"])
    result["monthly_contribution"] = from_pence(result["monthly_contribution_pence"])
    result["remaining_amount_pence"] = max(
        0, result["target_amount_pence"] - result["current_amount_pence"]
    )
    result["progress_percent"] = min(
        100.0,
        result["current_amount_pence"] / result["target_amount_pence"] * 100,
    )
    return result


def get_savings_goals(include_inactive: bool = False) -> list[dict]:
    """Return savings goals, including inactive ones when requested."""
    query = "SELECT * FROM savings_goals"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY active DESC, name COLLATE NOCASE, id"
    with database_connection() as connection:
        rows = connection.execute(query).fetchall()
    return [_record(row) for row in rows]


def add_savings_goal(
    name: str,
    target_amount: str | float | Decimal,
    monthly_contribution: str | float | Decimal = 0,
    current_amount: str | float | Decimal = 0,
) -> int:
    """Create a goal and return its ID. Existing savings are an opening balance."""
    validated_name = _validate_name(name)
    target = _validate_amount(target_amount, "Target amount", positive=True)
    monthly = _validate_amount(monthly_contribution, "Monthly contribution")
    current = _validate_amount(current_amount, "Current savings")
    with database_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO savings_goals (
                name, target_amount_pence, current_amount_pence,
                monthly_contribution_pence
            ) VALUES (?, ?, ?, ?)""",
            (validated_name, target, current, monthly),
        )
        return int(cursor.lastrowid)


def update_savings_goal(
    goal_id: int,
    name: str | object = _UNSET,
    target_amount: str | float | Decimal | object = _UNSET,
    monthly_contribution: str | float | Decimal | object = _UNSET,
) -> bool:
    """Update goal details without changing unspecified fields."""
    if all(value is _UNSET for value in (name, target_amount, monthly_contribution)):
        raise ValueError("At least one field must be provided.")
    current = next(
        (
            goal
            for goal in get_savings_goals(include_inactive=True)
            if goal["id"] == goal_id
        ),
        None,
    )
    if current is None:
        return False
    updates = {}
    if name is not _UNSET:
        updates["name"] = _validate_name(name)
    if target_amount is not _UNSET:
        updates["target_amount_pence"] = _validate_amount(
            target_amount, "Target amount", positive=True
        )
    if monthly_contribution is not _UNSET:
        updates["monthly_contribution_pence"] = _validate_amount(
            monthly_contribution, "Monthly contribution"
        )
    assignments = ", ".join(f"{column} = ?" for column in updates)
    with database_connection() as connection:
        cursor = connection.execute(
            f"UPDATE savings_goals SET {assignments} WHERE id = ?",
            [*updates.values(), goal_id],
        )
        return cursor.rowcount > 0


def set_savings_goal_active(goal_id: int, active: bool) -> bool:
    """Set a goal's active state without deleting its history."""
    if not isinstance(active, bool):
        raise TypeError("Active must be a boolean.")
    with database_connection() as connection:
        cursor = connection.execute(
            "UPDATE savings_goals SET active = ? WHERE id = ?",
            (int(active), goal_id),
        )
        return cursor.rowcount > 0


def record_savings_transaction(
    goal_id: int,
    transaction_type: str,
    amount: str | float | Decimal,
    transaction_date: str | date,
) -> bool:
    """Record a deposit or withdrawal and atomically update the saved balance."""
    if transaction_type not in {"deposit", "withdrawal"}:
        raise ValueError("Transaction type must be deposit or withdrawal.")
    amount_pence = _validate_amount(amount, "Transaction amount", positive=True)
    validated_date = _validate_date(transaction_date)
    if date.fromisoformat(validated_date) > date.today():
        raise ValueError("Transaction date cannot be in the future.")
    with database_connection() as connection:
        row = connection.execute(
            "SELECT current_amount_pence FROM savings_goals WHERE id = ?",
            (goal_id,),
        ).fetchone()
        if row is None:
            return False
        current = int(row["current_amount_pence"])
        if transaction_type == "withdrawal" and amount_pence > current:
            raise ValueError("Withdrawal cannot exceed current savings.")
        delta = amount_pence if transaction_type == "deposit" else -amount_pence
        connection.execute(
            """INSERT INTO savings_goal_transactions
                (goal_id, transaction_type, amount_pence, transaction_date)
                VALUES (?, ?, ?, ?)""",
            (goal_id, transaction_type, amount_pence, validated_date),
        )
        connection.execute(
            "UPDATE savings_goals SET current_amount_pence = current_amount_pence + ? WHERE id = ?",
            (delta, goal_id),
        )
    return True


def get_savings_transactions(goal_id: int) -> list[dict]:
    """Return a goal's transaction history, newest first."""
    with database_connection() as connection:
        rows = connection.execute(
            """SELECT * FROM savings_goal_transactions
                WHERE goal_id = ? ORDER BY transaction_date DESC, id DESC""",
            (goal_id,),
        ).fetchall()
    return [{**dict(row), "amount": from_pence(row["amount_pence"])} for row in rows]


def get_savings_goal_summary() -> dict[str, int]:
    """Return totals across active goals."""
    with database_connection() as connection:
        row = connection.execute(
            """SELECT COALESCE(SUM(current_amount_pence), 0) AS saved,
                COALESCE(SUM(target_amount_pence), 0) AS targets,
                COUNT(*) AS count
                FROM savings_goals WHERE active = 1"""
        ).fetchone()
    return {
        "total_saved_pence": int(row["saved"]),
        "total_targets_pence": int(row["targets"]),
        "active_goals": int(row["count"]),
    }


def estimate_completion_date(
    current_amount_pence: int,
    target_amount_pence: int,
    monthly_contribution_pence: int,
    from_date: date | None = None,
) -> date | None:
    """Estimate completion in whole monthly contribution periods."""
    if from_date is None:
        from_date = date.today()
    if current_amount_pence >= target_amount_pence:
        return from_date
    if monthly_contribution_pence <= 0:
        return None
    months = (
        target_amount_pence - current_amount_pence + monthly_contribution_pence - 1
    ) // monthly_contribution_pence
    month_index = from_date.month - 1 + months
    year = from_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(from_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
