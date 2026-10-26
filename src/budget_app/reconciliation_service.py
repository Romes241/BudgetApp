"""Read-only reconciliation checks for actual income records."""

from budget_app.income_service import get_income_history
from budget_app.payment_line_service import get_payment_lines


def reconcile_income(income_id: int) -> dict:
    """Reconcile an income record's earnings lines and deductions.

    Overall status is ``passed``, ``failed``, ``incomplete`` or ``not_found``.
    Monetary comparisons use integer pence. Stored data is never modified.
    """
    if isinstance(income_id, bool) or not isinstance(income_id, int) or income_id <= 0:
        raise ValueError("Income ID must be a positive integer.")

    income = next(
        (record for record in get_income_history() if record["id"] == income_id),
        None,
    )
    if income is None:
        return {"income_id": income_id, "status": "not_found", "checks": []}

    payment_lines = get_payment_lines(income_id)
    gross_pence = int(income["gross_pay_pence"])
    checks = []

    if not payment_lines:
        checks.append({
            "name": "earnings_total",
            "status": "missing_breakdown",
            "expected_pence": gross_pence,
            "actual_pence": None,
            "difference_pence": None,
            "message": "No payment lines are recorded; the earnings breakdown cannot be reconciled.",
        })
    else:
        lines_total_pence = sum(int(line["amount_pence"]) for line in payment_lines)
        difference = lines_total_pence - gross_pence
        checks.append({
            "name": "earnings_total",
            "status": "passed" if difference == 0 else "failed",
            "expected_pence": gross_pence,
            "actual_pence": lines_total_pence,
            "difference_pence": difference,
            "message": (
                "Payment lines match gross pay."
                if difference == 0
                else "Payment-line total does not match gross pay."
            ),
        })

    deductions_pence = (
        int(income["tax_paid_pence"])
        + int(income["ni_paid_pence"])
        + int(income["pension_paid_pence"])
        + int(income["other_deductions_pence"])
    )
    expected_net_pence = gross_pence - deductions_pence
    actual_net_pence = int(income["net_pay_pence"])
    net_difference = actual_net_pence - expected_net_pence
    checks.append({
        "name": "net_pay",
        "status": "passed" if net_difference == 0 else "failed",
        "expected_pence": expected_net_pence,
        "actual_pence": actual_net_pence,
        "difference_pence": net_difference,
        "message": (
            "Net pay matches gross pay minus deductions."
            if net_difference == 0
            else "Net pay does not match gross pay minus deductions."
        ),
    })

    statuses = {check["status"] for check in checks}
    if "failed" in statuses:
        overall_status = "failed"
    elif "missing_breakdown" in statuses:
        overall_status = "incomplete"
    else:
        overall_status = "passed"

    return {
        "income_id": income_id,
        "status": overall_status,
        "gross_pay_pence": gross_pence,
        "payment_line_count": len(payment_lines),
        "checks": checks,
    }
