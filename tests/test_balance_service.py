from datetime import date

import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.services import balance_service


@pytest.fixture
def balance_database(tmp_path, monkeypatch):
    database_path = tmp_path / "balance.db"

    def connection_factory():
        return connect_database(database_path)

    with connection_factory() as connection:
        initialise_database(connection)
        connection.execute(
            """UPDATE settings SET current_balance_pence = 10000,
                balance_as_of_date = ?, balance_reconciled_at = ? WHERE id = 1""",
            (date.today().isoformat(), "2000-01-01T00:00:00.000Z"),
        )

    monkeypatch.setattr(balance_service, "database_connection", connection_factory)
    return connection_factory


def test_recorded_income_and_outgoings_update_balance(balance_database):
    with balance_database() as connection:
        today = date.today().isoformat()
        connection.execute(
            """INSERT INTO income_history
                (pay_date, gross_pay_pence, net_pay_pence)
                VALUES (?, 6000, 5000)""",
            (today,),
        )
        connection.execute(
            """INSERT INTO savings_goals
                (name, target_amount_pence, current_amount_pence)
                VALUES ('Holiday', 10000, 2000)"""
        )
        goal_id = connection.execute(
            "SELECT id FROM savings_goals WHERE name = 'Holiday'"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO savings_goal_transactions
                (goal_id, transaction_type, amount_pence, transaction_date)
                VALUES (?, 'deposit', 2000, ?)""",
            (goal_id, today),
        )
        connection.execute(
            """INSERT INTO debts
                (name, balance_pence, monthly_payment_pence, original_balance_pence)
                VALUES ('Card', 7000, 1000, 10000)"""
        )
        debt_id = connection.execute(
            "SELECT id FROM debts WHERE name = 'Card'"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO debt_payment_transactions
                (debt_id, payment_date, amount_pence) VALUES (?, ?, 3000)""",
            (debt_id, today),
        )

    balance_service.add_actual_transaction("Food shop", "-12.50", date.today())

    assert balance_service.get_running_balance()["balance_pence"] == 8750


def test_editing_and_deleting_manual_activity_recalculates_balance(balance_database):
    transaction_id = balance_service.add_actual_transaction(
        "Food shop", "-10", date.today()
    )
    assert balance_service.get_running_balance()["balance_pence"] == 9000

    assert balance_service.update_actual_transaction(
        transaction_id, "Weekly shop", "-15", date.today()
    )
    assert balance_service.get_running_balance()["balance_pence"] == 8500

    assert balance_service.delete_actual_transaction(transaction_id)
    assert balance_service.get_running_balance()["balance_pence"] == 10000


def test_editing_and_deleting_savings_activity_updates_goal_and_balance(
    balance_database,
):
    with balance_database() as connection:
        connection.execute(
            """INSERT INTO savings_goals
                (name, target_amount_pence, current_amount_pence)
                VALUES ('Holiday', 10000, 5000)"""
        )
        goal_id = connection.execute(
            "SELECT id FROM savings_goals WHERE name = 'Holiday'"
        ).fetchone()["id"]
        cursor = connection.execute(
            """INSERT INTO savings_goal_transactions
                (goal_id, transaction_type, amount_pence, transaction_date)
                VALUES (?, 'deposit', 5000, ?)""",
            (goal_id, date.today().isoformat()),
        )
        transaction_id = cursor.lastrowid

    assert balance_service.get_running_balance()["balance_pence"] == 5000
    assert balance_service.update_recorded_transaction(
        "savings", transaction_id, "-30", date.today()
    )
    assert balance_service.get_running_balance()["balance_pence"] == 7000
    with balance_database() as connection:
        goal = connection.execute(
            "SELECT current_amount_pence FROM savings_goals WHERE id = ?",
            (goal_id,),
        ).fetchone()
        assert goal["current_amount_pence"] == 3000

    assert balance_service.delete_recorded_transaction("savings", transaction_id)
    assert balance_service.get_running_balance()["balance_pence"] == 10000


def test_editing_and_deleting_debt_payment_updates_debt_and_balance(balance_database):
    with balance_database() as connection:
        connection.execute(
            """INSERT INTO debts
                (name, balance_pence, monthly_payment_pence, original_balance_pence)
                VALUES ('Card', 5000, 1000, 10000)"""
        )
        debt_id = connection.execute(
            "SELECT id FROM debts WHERE name = 'Card'"
        ).fetchone()["id"]
        cursor = connection.execute(
            """INSERT INTO debt_payment_transactions
                (debt_id, payment_date, amount_pence) VALUES (?, ?, 5000)""",
            (debt_id, date.today().isoformat()),
        )
        transaction_id = cursor.lastrowid

    assert balance_service.get_running_balance()["balance_pence"] == 5000
    assert balance_service.update_recorded_transaction(
        "debt", transaction_id, "-25", date.today()
    )
    assert balance_service.get_running_balance()["balance_pence"] == 7500

    assert balance_service.delete_recorded_transaction("debt", transaction_id)
    assert balance_service.get_running_balance()["balance_pence"] == 10000
    with balance_database() as connection:
        debt = connection.execute(
            "SELECT balance_pence, last_payment_date FROM debts WHERE id = ?",
            (debt_id,),
        ).fetchone()
        assert debt["balance_pence"] == 10000
        assert debt["last_payment_date"] is None


def test_linking_confirmed_early_pay_to_payslip_prevents_double_counting(
    balance_database,
):
    today = date.today()
    transaction_id = balance_service.add_actual_transaction(
        "Estimated regular take-home pay",
        "50",
        today,
        transaction_type="regular_income",
    )
    with balance_database() as connection:
        cursor = connection.execute(
            """INSERT INTO income_history
                (pay_date, gross_pay_pence, net_pay_pence)
                VALUES (?, 6000, 5000)""",
            (today.isoformat(),),
        )
        income_id = cursor.lastrowid

    assert balance_service.get_running_balance()["balance_pence"] == 20000
    assert (
        balance_service.get_linkable_income_records(transaction_id)[0]["id"]
        == income_id
    )
    assert balance_service.link_confirmed_income_to_payslip(transaction_id, income_id)
    assert balance_service.get_running_balance()["balance_pence"] == 15000

    visible_income = [
        transaction
        for transaction in balance_service.get_actual_transactions()
        if transaction["source_kind"] == "income"
    ]
    assert visible_income == []
