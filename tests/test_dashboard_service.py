import pytest

from budget_app.services import dashboard_service


def test_dashboard_data_uses_the_supplied_cashflow_projection(monkeypatch):
    projection = {"entries": [{"type": "regular_income", "date": "2026-11-19"}]}
    balance = {"balance_pence": 12345}
    goals = [{"current_amount_pence": 5000}]
    debts = [{"balance_pence": 7000}]
    monkeypatch.setattr(dashboard_service, "get_running_balance", lambda: balance)
    monkeypatch.setattr(dashboard_service, "get_savings_goals", lambda: goals)
    monkeypatch.setattr(dashboard_service, "get_debts", lambda: debts)

    result = dashboard_service.get_dashboard_data(projection)

    assert result["projection"] is projection
    assert result["balance"] is balance
    assert result["next_pay"] is projection["entries"][0]
    assert result["savings_total_pence"] == 5000
    assert result["debt_total_pence"] == 7000


def test_dashboard_data_requires_an_existing_projection():
    with pytest.raises(ValueError, match="Cashflow projection is unavailable"):
        dashboard_service.get_dashboard_data(None)
