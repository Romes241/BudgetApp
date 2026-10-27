
from decimal import Decimal

import pytest

from budget_app.payslip_extractor import EarningsLine, PayslipData
from budget_app.payslip_import_service import (
    PayslipValidationError,
    import_payslip,
    validate_payslip,
)

def valid_data():
    return PayslipData(
        gross_pay=Decimal("100.00"),
        tax_paid=Decimal("10.00"),
        ni_paid=Decimal("5.00"),
        pension_paid=Decimal("5.00"),
        other_deductions=Decimal("0.00"),
        net_pay=Decimal("80.00"),
        pay_date="2026-10-16",
        source_hash="test-hash",
        earnings=[
            EarningsLine(
                description="Basic Pay",
                units=Decimal("10"),
                rate=Decimal("10.00"),
                amount=Decimal("100.00"),
            )
        ],
    )

def test_valid_payslip_has_no_validation_errors():
    assert validate_payslip(valid_data()) == []

def test_missing_pension_is_rejected():
    data = valid_data()
    data.pension_paid = None

    assert any("Pension paid" in error for error in validate_payslip(data))

def test_gross_mismatch_is_rejected():
    data = valid_data()
    data.earnings[0].amount = Decimal("99.00")

    assert any("does not match gross pay" in error for error in validate_payslip(data))

def test_import_requires_confirmation():
    with pytest.raises(PayslipValidationError, match="not confirmed"):
        import_payslip("Payslip_PayDate_16102026.pdf")
