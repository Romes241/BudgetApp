
from decimal import Decimal

from budget_app.payslip_extractor import (
    extract_pay_date,
    extract_payslip_text,
)

SAMPLE = """
Gross Pay
£672.59
YTD £14,119.75
PAYE Tax
£90.04
YTD £1,536.87
NIC
£34.45
YTD £569.41
Others
£22.10
YTD £437.58
Net Pay
£526.00
YTD £11,575.89
PAYMENTS - EMPLOYEE DEFAULT POST
Description Units Rate Amount
Enhanced Overnight
Payment Per Hr
1.85 1.0000 1.85
Basic Pay - associates
13/10/2026 - 13/10/2026
8.40 13.9100 116.84
Basic Pay - associates
14/10/2026 - 14/10/2026
8.87 13.9100 123.38
Basic Pay - associates
15/10/2026 - 15/10/2026
8.90 13.9100 123.80
Basic Pay - associates
16/10/2026 - 16/10/2026
5.00 13.9100 69.55
Basic Pay - associates
17/10/2026 - 17/10/2026
9.00 13.9100 125.19
Basic Pay - associates
18/10/2026 - 18/10/2026
8.05 13.9100 111.98
Total £672.59
DEDUCTIONS - EMPLOYEE DEFAULT POST
Description Amount
Tax Paid £90.04
NI Contracted In £34.45
NEST PENSION DEDUCTION £22.10
Total £146.59
"""


def test_extracts_current_period_summary():
    result = extract_payslip_text(SAMPLE)

    assert result.gross_pay == Decimal("672.59")
    assert result.tax_paid == Decimal("90.04")
    assert result.ni_paid == Decimal("34.45")
    assert result.pension_paid == Decimal("22.10")
    assert result.other_deductions == Decimal("0.00")
    assert result.net_pay == Decimal("526.00")

def test_extracts_all_earnings_lines():
    result = extract_payslip_text(SAMPLE)

    assert len(result.earnings) == 7
    assert result.earnings[0].description == (
        "Enhanced Overnight Payment Per Hr"
    )
    assert result.earnings[0].units == Decimal("1.85")
    assert result.earnings[0].rate == Decimal("1.0000")
    assert result.earnings[0].amount == Decimal("1.85")

    assert result.earnings[1].description == (
        "Basic Pay - associates 13/10/2026 - 13/10/2026"
    )
    assert result.earnings[1].amount == Decimal("116.84")


def test_validates_totals():
    result = extract_payslip_text(SAMPLE)

    assert result.warnings == []

def test_warns_when_detailed_tax_disagrees_with_summary():
    text = SAMPLE.replace("Tax Paid £90.04", "Tax Paid £89.04")
    text = text.replace("Total £146.59", "Total £145.59")

    result = extract_payslip_text(text)

    assert "Detailed tax is £89.04, but summary tax is £90.04." in (
        result.warnings
    )


def test_warns_when_detailed_total_disagrees_with_summary():
    result = extract_payslip_text(
        SAMPLE.replace("Total £146.59", "Total £146.58")
    )

    assert (
        "Detailed deductions total is £146.58, but summary deductions "
        "total is £146.59."
    ) in result.warnings


def test_missing_payments_section_is_flagged():
    result = extract_payslip_text("Gross Pay\n£672.59\nYTD £1,000.00")

    assert result.earnings == []
    assert any("payments section" in warning for warning in result.warnings)
    

def test_extracts_pay_date_from_filename():
    assert (
        extract_pay_date("Payslip_PayDate_16102026.pdf")
        == "2026-10-16"
    )


def test_rejects_invalid_pay_date():
    assert extract_pay_date("Payslip_PayDate_32132026.pdf") is None


def test_rejects_unexpected_filename():
    assert extract_pay_date("my_payslip.pdf") is None
