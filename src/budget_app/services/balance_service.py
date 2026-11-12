"""Calculate the live account balance from a reconciled baseline and activity."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from budget_app.database import database_connection
from budget_app.utils.money import from_pence, to_pence


def get_running_balance() -> dict[str, Any]:
    """Return the reconciled baseline plus actual activity after its date."""
    with database_connection() as connection:
        settings = connection.execute(
            """SELECT current_balance_pence, balance_as_of_date,
                balance_reconciled_at FROM settings WHERE id = 1"""
        ).fetchone()
        if settings is None:
            raise RuntimeError("BudgetApp settings have not been initialised.")

        baseline_date = date.fromisoformat(settings["balance_as_of_date"])
        reconciled_at = settings["balance_reconciled_at"]
        today = date.today().isoformat()
        totals = connection.execute(
            """SELECT
                COALESCE((SELECT SUM(i.net_pay_pence) FROM income_history AS i
                    WHERE (i.pay_date > ? OR
                        (i.pay_date = ? AND i.created_at > ?))
                    AND i.pay_date <= ?
                    AND NOT EXISTS (SELECT 1 FROM actual_transactions AS t
                        WHERE t.linked_income_id = i.id)), 0) AS income_pence,
                COALESCE((SELECT SUM(CASE transaction_type
                    WHEN 'deposit' THEN -amount_pence ELSE amount_pence END)
                    FROM savings_goal_transactions
                    WHERE (transaction_date > ? OR (transaction_date = ? AND created_at > ?))
                    AND transaction_date <= ?), 0)
                    AS savings_pence,
                COALESCE((SELECT -SUM(amount_pence)
                    FROM debt_payment_transactions
                    WHERE (payment_date > ? OR (payment_date = ? AND created_at > ?))
                    AND payment_date <= ?), 0)
                    AS debt_pence,
                COALESCE((SELECT SUM(t.amount_pence) FROM actual_transactions AS t
                    WHERE (t.transaction_date > ? OR
                        (t.transaction_date = ? AND t.created_at > ?))
                    AND t.transaction_date <= ?
                    ), 0)
                    AS other_pence""",
            (
                baseline_date.isoformat(),
                baseline_date.isoformat(),
                reconciled_at,
                today,
            )
            * 4,
        ).fetchone()

    activity_pence = sum(int(value) for value in totals)
    baseline_pence = int(settings["current_balance_pence"])
    return {
        "balance_pence": baseline_pence + activity_pence,
        "balance": from_pence(baseline_pence + activity_pence),
        "baseline_pence": baseline_pence,
        "baseline": from_pence(baseline_pence),
        "baseline_date": baseline_date,
        "activity_pence": activity_pence,
        "activity": from_pence(activity_pence),
    }


def add_actual_transaction(
    description: str,
    amount: str | float | Decimal,
    transaction_date: str | date,
    transaction_type: str = "expense",
    forecast_key: str | None = None,
) -> int:
    """Record actual cash in/out; positive amounts add to balance."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Description cannot be empty.")
    if isinstance(transaction_date, datetime):
        raise ValueError("Transaction date must be a date.")
    if isinstance(transaction_date, date):
        transaction_date = transaction_date.isoformat()
    if not isinstance(transaction_date, str):
        raise ValueError("Transaction date must use YYYY-MM-DD format.")
    try:
        parsed_date = date.fromisoformat(transaction_date)
    except ValueError:
        raise ValueError("Transaction date must use YYYY-MM-DD format.") from None
    if parsed_date.isoformat() != transaction_date:
        raise ValueError("Transaction date must use YYYY-MM-DD format.")
    if parsed_date > date.today():
        raise ValueError("Actual transaction date cannot be in the future.")
    amount_pence = to_pence(amount)
    if amount_pence == 0:
        raise ValueError("Transaction amount cannot be zero.")
    if not isinstance(transaction_type, str) or not transaction_type.strip():
        raise ValueError("Transaction type cannot be empty.")

    with database_connection() as connection:
        if (
            forecast_key is not None
            and connection.execute(
                "SELECT 1 FROM actual_transactions WHERE forecast_key = ?",
                (forecast_key,),
            ).fetchone()
        ):
            raise ValueError("This forecast transaction has already been confirmed.")
        cursor = connection.execute(
            """INSERT INTO actual_transactions
                (transaction_date, description, amount_pence,
                 transaction_type, forecast_key)
                VALUES (?, ?, ?, ?, ?)""",
            (
                transaction_date,
                description.strip(),
                amount_pence,
                transaction_type,
                forecast_key,
            ),
        )
        return int(cursor.lastrowid)


def get_actual_transactions() -> list[dict[str, Any]]:
    """Return actual entries from every source, newest first."""
    with database_connection() as connection:
        rows = connection.execute(
            """SELECT id, transaction_date, description, amount_pence,
                    transaction_type, forecast_key, linked_income_id,
                    'manual' AS source_kind
                FROM actual_transactions
                UNION ALL
                SELECT id, pay_date, 'Income', net_pay_pence,
                    'income', NULL, NULL, 'income' FROM income_history AS i
                WHERE NOT EXISTS (SELECT 1 FROM actual_transactions AS t
                    WHERE t.linked_income_id = i.id)
                UNION ALL
                SELECT t.id, t.transaction_date,
                    g.name || ' ' || t.transaction_type,
                    CASE t.transaction_type WHEN 'deposit' THEN -t.amount_pence
                        ELSE t.amount_pence END,
                    'savings_' || t.transaction_type, t.forecast_key, NULL, 'savings'
                FROM savings_goal_transactions AS t
                JOIN savings_goals AS g ON g.id = t.goal_id
                UNION ALL
                SELECT t.id, t.payment_date, d.name || ' payment',
                    -t.amount_pence, 'debt_payment', t.forecast_key, NULL, 'debt'
                FROM debt_payment_transactions AS t
                JOIN debts AS d ON d.id = t.debt_id
                ORDER BY 2 DESC, 1 DESC"""
        ).fetchall()
    return [{**dict(row), "amount": from_pence(row["amount_pence"])} for row in rows]


def get_linkable_income_records(transaction_id: int) -> list[dict[str, Any]]:
    """Return unlinked payslips dated within a week after a confirmed payday."""
    with database_connection() as connection:
        transaction = connection.execute(
            """SELECT transaction_date, transaction_type, linked_income_id
                FROM actual_transactions WHERE id = ?""",
            (transaction_id,),
        ).fetchone()
        if transaction is None or transaction["transaction_type"] != "regular_income":
            return []
        transaction_date = date.fromisoformat(transaction["transaction_date"])
        latest_pay_date = (transaction_date + timedelta(days=7)).isoformat()
        rows = connection.execute(
            """SELECT i.id, i.pay_date, i.net_pay_pence
                FROM income_history AS i
                WHERE i.pay_date >= ? AND i.pay_date <= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM actual_transactions AS t
                    WHERE t.linked_income_id = i.id
                  )
                ORDER BY i.pay_date DESC, i.id DESC""",
            (transaction["transaction_date"], latest_pay_date),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "pay_date": row["pay_date"],
            "net_pay_pence": row["net_pay_pence"],
            "net_pay": from_pence(row["net_pay_pence"]),
        }
        for row in rows
    ]


def link_confirmed_income_to_payslip(
    transaction_id: int,
    income_id: int,
) -> bool:
    """Link a confirmed bank receipt to its contractual-date payslip record."""
    with database_connection() as connection:
        transaction = connection.execute(
            """SELECT transaction_date, transaction_type, linked_income_id
                FROM actual_transactions WHERE id = ?""",
            (transaction_id,),
        ).fetchone()
        if transaction is None:
            return False
        if transaction["transaction_type"] != "regular_income":
            raise ValueError("Only confirmed regular income can link to a payslip.")
        if transaction["linked_income_id"] is not None:
            raise ValueError("This confirmed income is already linked to a payslip.")
        income = connection.execute(
            "SELECT pay_date FROM income_history WHERE id = ?", (income_id,)
        ).fetchone()
        if income is None:
            return False
        receipt_date = date.fromisoformat(transaction["transaction_date"])
        pay_date = date.fromisoformat(income["pay_date"])
        if not receipt_date <= pay_date <= receipt_date + timedelta(days=7):
            raise ValueError(
                "The payslip date must be within a week after the receipt."
            )
        cursor = connection.execute(
            """UPDATE actual_transactions SET linked_income_id = ?
                WHERE id = ? AND linked_income_id IS NULL""",
            (income_id, transaction_id),
        )
        return cursor.rowcount > 0


def update_actual_transaction(
    transaction_id: int,
    description: str,
    amount: str | float | Decimal,
    transaction_date: str | date,
    transaction_type: str | None = None,
) -> bool:
    """Edit an actual transaction and recalculate balance on next read."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Description cannot be empty.")
    if isinstance(transaction_date, datetime):
        raise ValueError("Transaction date must be a date.")
    if isinstance(transaction_date, date):
        transaction_date = transaction_date.isoformat()
    try:
        parsed_date = date.fromisoformat(transaction_date)
    except (ValueError, TypeError):
        raise ValueError("Transaction date must use YYYY-MM-DD format.") from None
    if parsed_date.isoformat() != transaction_date or parsed_date > date.today():
        raise ValueError("Actual transaction date must be today or earlier.")
    amount_pence = to_pence(amount)
    if amount_pence == 0:
        raise ValueError("Transaction amount cannot be zero.")
    with database_connection() as connection:
        existing = connection.execute(
            "SELECT linked_income_id FROM actual_transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        if (
            existing is not None
            and existing["linked_income_id"] is not None
            and transaction_type not in {None, "regular_income"}
        ):
            raise ValueError(
                "A payslip-linked receipt must remain money in. Delete it to "
                "use the payslip record on its own."
            )
        cursor = connection.execute(
            """UPDATE actual_transactions
                SET transaction_date = ?, description = ?, amount_pence = ?,
                    transaction_type = COALESCE(?, transaction_type),
                    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?""",
            (
                transaction_date,
                description.strip(),
                amount_pence,
                transaction_type,
                transaction_id,
            ),
        )
        return cursor.rowcount > 0


def delete_actual_transaction(transaction_id: int) -> bool:
    """Remove an actual transaction and recalculate balance on next read."""
    with database_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM actual_transactions WHERE id = ?", (transaction_id,)
        )
        return cursor.rowcount > 0


def update_recorded_transaction(
    source_kind: str,
    source_id: int,
    amount: str | float | Decimal,
    transaction_date: str | date,
) -> bool:
    """Edit a recorded transaction and update its owning financial record."""
    if isinstance(transaction_date, datetime):
        raise ValueError("Transaction date must be a date.")
    if isinstance(transaction_date, date):
        transaction_date = transaction_date.isoformat()
    try:
        parsed_date = date.fromisoformat(transaction_date)
    except (ValueError, TypeError):
        raise ValueError("Transaction date must use YYYY-MM-DD format.") from None
    if parsed_date.isoformat() != transaction_date or parsed_date > date.today():
        raise ValueError("Actual transaction date must be today or earlier.")
    amount_pence = to_pence(amount)
    if amount_pence == 0:
        raise ValueError("Transaction amount cannot be zero.")

    with database_connection() as connection:
        if source_kind == "manual":
            cursor = connection.execute(
                """UPDATE actual_transactions SET transaction_date = ?,
                    amount_pence = ?,
                    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?""",
                (transaction_date, amount_pence, source_id),
            )
            return cursor.rowcount > 0
        if source_kind == "income":
            raise ValueError(
                "Edit payslip income using the Income page to keep its "
                "pay and deduction details consistent."
            )
        if source_kind == "savings":
            row = connection.execute(
                """SELECT goal_id, transaction_type, amount_pence
                    FROM savings_goal_transactions WHERE id = ?""",
                (source_id,),
            ).fetchone()
            if row is None:
                return False
            new_type = "deposit" if amount_pence < 0 else "withdrawal"
            new_amount = abs(amount_pence)
            old_delta = int(row["amount_pence"])
            if row["transaction_type"] == "withdrawal":
                old_delta = -old_delta
            new_delta = new_amount if new_type == "deposit" else -new_amount
            goal = connection.execute(
                "SELECT current_amount_pence FROM savings_goals WHERE id = ?",
                (row["goal_id"],),
            ).fetchone()
            if (
                goal is None
                or int(goal["current_amount_pence"]) - old_delta + new_delta < 0
            ):
                raise ValueError("The updated withdrawal exceeds saved funds.")
            connection.execute(
                """UPDATE savings_goals SET current_amount_pence =
                    current_amount_pence - ? + ? WHERE id = ?""",
                (old_delta, new_delta, row["goal_id"]),
            )
            cursor = connection.execute(
                """UPDATE savings_goal_transactions SET transaction_type = ?,
                    amount_pence = ?, transaction_date = ?,
                    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?""",
                (new_type, new_amount, transaction_date, source_id),
            )
            return cursor.rowcount > 0
        if source_kind == "debt":
            if amount_pence >= 0:
                raise ValueError("Debt payments must be outgoing amounts.")
            row = connection.execute(
                """SELECT t.debt_id, t.amount_pence, d.balance_pence
                    FROM debt_payment_transactions AS t
                    JOIN debts AS d ON d.id = t.debt_id WHERE t.id = ?""",
                (source_id,),
            ).fetchone()
            if row is None:
                return False
            new_amount = abs(amount_pence)
            if new_amount > int(row["balance_pence"]) + int(row["amount_pence"]):
                raise ValueError("Payment cannot exceed the debt's original balance.")
            connection.execute(
                "UPDATE debts SET balance_pence = balance_pence + ? - ? WHERE id = ?",
                (row["amount_pence"], new_amount, row["debt_id"]),
            )
            cursor = connection.execute(
                """UPDATE debt_payment_transactions SET amount_pence = ?,
                    payment_date = ?,
                    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?""",
                (new_amount, transaction_date, source_id),
            )
            connection.execute(
                """UPDATE debts SET last_payment_date = (
                    SELECT MAX(payment_date) FROM debt_payment_transactions
                    WHERE debt_id = ?
                ) WHERE id = ?""",
                (row["debt_id"], row["debt_id"]),
            )
            return cursor.rowcount > 0
    raise ValueError("Unsupported actual transaction source.")


def delete_recorded_transaction(source_kind: str, source_id: int) -> bool:
    """Delete a transaction and reverse its impact on savings or debt totals."""
    with database_connection() as connection:
        if source_kind == "manual":
            cursor = connection.execute(
                "DELETE FROM actual_transactions WHERE id = ?", (source_id,)
            )
            return cursor.rowcount > 0
        if source_kind == "income":
            cursor = connection.execute(
                "DELETE FROM income_history WHERE id = ?", (source_id,)
            )
            return cursor.rowcount > 0
        if source_kind == "savings":
            row = connection.execute(
                """SELECT goal_id, transaction_type, amount_pence
                    FROM savings_goal_transactions WHERE id = ?""",
                (source_id,),
            ).fetchone()
            if row is None:
                return False
            delta = int(row["amount_pence"])
            if row["transaction_type"] == "withdrawal":
                delta = -delta
            connection.execute(
                """UPDATE savings_goals SET current_amount_pence =
                    current_amount_pence - ? WHERE id = ?""",
                (delta, row["goal_id"]),
            )
            connection.execute(
                "DELETE FROM savings_goal_transactions WHERE id = ?", (source_id,)
            )
            return True
        if source_kind == "debt":
            row = connection.execute(
                "SELECT debt_id, amount_pence FROM debt_payment_transactions WHERE id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE debts SET balance_pence = balance_pence + ? WHERE id = ?",
                (row["amount_pence"], row["debt_id"]),
            )
            connection.execute(
                "DELETE FROM debt_payment_transactions WHERE id = ?", (source_id,)
            )
            connection.execute(
                """UPDATE debts SET last_payment_date = (
                    SELECT MAX(payment_date) FROM debt_payment_transactions
                    WHERE debt_id = ?
                ) WHERE id = ?""",
                (row["debt_id"], row["debt_id"]),
            )
            return True
    raise ValueError("Unsupported actual transaction source.")
