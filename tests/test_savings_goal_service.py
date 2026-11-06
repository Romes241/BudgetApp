from datetime import date, timedelta

import pytest

from budget_app.database import connect_database, initialise_database
from budget_app.services import savings_goal_service


@pytest.fixture
def savings_database(tmp_path, monkeypatch):
    database_path = tmp_path / "savings.db"

    def connection_factory():
        return connect_database(database_path)

    with connection_factory() as connection:
        initialise_database(connection)

    monkeypatch.setattr(
        savings_goal_service,
        "database_connection",
        connection_factory,
    )
    return database_path


def test_add_goal_and_derived_progress(savings_database):
    goal_id = savings_goal_service.add_savings_goal(
        "Emergency fund", "1000.00", "100.00", "250.00"
    )

    goal = savings_goal_service.get_savings_goals()[0]

    assert goal["id"] == goal_id
    assert goal["target_amount_pence"] == 100000
    assert goal["current_amount_pence"] == 25000
    assert goal["monthly_contribution_pence"] == 10000
    assert goal["remaining_amount_pence"] == 75000
    assert goal["progress_percent"] == 25


def test_update_goal_and_active_filter(savings_database):
    goal_id = savings_goal_service.add_savings_goal("Holiday", "500", "50")

    assert savings_goal_service.update_savings_goal(
        goal_id, name="Summer holiday", monthly_contribution="75"
    )
    assert savings_goal_service.set_savings_goal_active(goal_id, False)
    assert savings_goal_service.get_savings_goals() == []
    inactive = savings_goal_service.get_savings_goals(include_inactive=True)[0]
    assert inactive["name"] == "Summer holiday"
    assert inactive["monthly_contribution_pence"] == 7500
    assert inactive["active"] == 0


def test_deposit_and_withdrawal_update_balance_and_history(savings_database):
    goal_id = savings_goal_service.add_savings_goal("Car", "2000", current_amount="500")
    today = date.today()

    assert savings_goal_service.record_savings_transaction(
        goal_id, "deposit", "125.50", today
    )
    assert savings_goal_service.record_savings_transaction(
        goal_id, "withdrawal", "25.50", today
    )
    goal = savings_goal_service.get_savings_goals()[0]
    history = savings_goal_service.get_savings_transactions(goal_id)

    assert goal["current_amount_pence"] == 60000
    assert [item["transaction_type"] for item in history] == [
        "withdrawal",
        "deposit",
    ]
    assert [item["amount_pence"] for item in history] == [2550, 12550]


@pytest.mark.parametrize(
    ("transaction_type", "amount", "transaction_date"),
    [
        ("other", "1.00", date.today()),
        ("deposit", "0", date.today()),
        ("withdrawal", "11.00", date.today()),
        ("deposit", "1.00", date.today() + timedelta(days=1)),
        ("deposit", "1.00", "2026-2-01"),
    ],
)
def test_invalid_transactions_are_rejected(
    savings_database,
    transaction_type,
    amount,
    transaction_date,
):
    goal_id = savings_goal_service.add_savings_goal("Bike", "100", current_amount="10")

    with pytest.raises(ValueError):
        savings_goal_service.record_savings_transaction(
            goal_id, transaction_type, amount, transaction_date
        )

    assert savings_goal_service.get_savings_goals()[0]["current_amount_pence"] == 1000


def test_summary_counts_active_goals_only(savings_database):
    first_id = savings_goal_service.add_savings_goal("A", "100", current_amount="20")
    savings_goal_service.add_savings_goal("B", "200", current_amount="50")
    savings_goal_service.add_savings_goal("C", "100", current_amount="100")
    savings_goal_service.set_savings_goal_active(first_id, False)

    assert savings_goal_service.get_savings_goal_summary() == {
        "total_saved_pence": 15000,
        "total_targets_pence": 30000,
        "active_goals": 1,
    }


def test_completion_date_uses_monthly_contribution():
    assert savings_goal_service.estimate_completion_date(
        25000, 100000, 25000, date(2026, 1, 31)
    ) == date(2026, 4, 30)
    assert (
        savings_goal_service.estimate_completion_date(0, 100000, 0, date(2026, 1, 1))
        is None
    )
