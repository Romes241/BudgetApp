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

COLUMNAR_SAMPLE = """
Gross Pay
£675.77
YTD £14,795.52
PAYE Tax
£90.84
YTD £1,627.71
NIC
£34.70
YTD £604.11
Net Pay
£528.00
YTD £12,103.89
PAYMENTS - EMPLOYEE DEFAULT POST
Description
Holiday Pay - Associates
Associate Monthly Bonus
Enhanced Overnight Payment Per Hr
Basic Pay - associates
21/10/2026 - 21/10/2026
Basic Pay - associates
22/10/2026 - 22/10/2026
Basic Pay - associates
23/10/2026 - 23/10/2026
Basic Pay - associates
25/10/2026 - 25/10/2026
Units
7.92
-
1.62
7.95
9.00
7.35
8.72
Rate
13.9100
-
1.0000
13.9100
13.9100
13.9100
13.9100
Amount
110.17
104.67
1.62
110.58
125.19
102.24
121.30
Total £675.77
DEDUCTIONS - EMPLOYEE DEFAULT POST
Description Amount
Tax Paid £90.84
NI Contracted In £34.70
NEST PENSION DEDUCTION £22.23
Total £147.77
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
    assert result.earnings[0].description == ("Enhanced Overnight Payment Per Hr")
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


def test_extracts_columnar_payment_lines():
    result = extract_payslip_text(COLUMNAR_SAMPLE)

    assert len(result.earnings) == 7
    assert result.earnings[0].description == "Holiday Pay - Associates"
    assert result.earnings[1].description == "Associate Monthly Bonus"
    assert result.earnings[1].units is None
    assert result.earnings[1].rate is None
    assert result.earnings[1].amount == Decimal("104.67")
    assert result.warnings == []


def test_extracts_inline_and_wrapped_payment_lines_with_inline_summaries():
    text = """
Gross Pay
£675.77
YTD £14,795.52
PAYE Tax £90.84
YTD £1,627.71
NIC £34.70
YTD £604.11
Others £22.23
YTD £459.81
Net Pay £528.00
YTD £12,103.89
PAYMENTS - EMPLOYEE DEFAULT POST
Description Units Rate Amount
Holiday Pay - Associates 7.92 13.9100 110.17
Associate Monthly Bonus - - 104.67
Enhanced Overnight
Payment Per Hr
1.62 1.0000 1.62
Basic Pay - associates
21/10/2026 - 21/10/2026
7.95 13.9100 110.58
Basic Pay - associates
22/10/2026 - 22/10/2026
9.00 13.9100 125.19
Basic Pay - associates
23/10/2026 - 23/10/2026
7.35 13.9100 102.24
Basic Pay - associates
25/10/2026 - 25/10/2026
8.72 13.9100 121.30
Total £675.77
DEDUCTIONS - EMPLOYEE DEFAULT POST
Description Amount
Tax Paid 90.84
NI Contracted In 34.70
NEST PENSION DEDUCTION 22.23
Total £147.77
MESSAGES CUMULATIVE YEAR TO DATE Amount
"""

    result = extract_payslip_text(text)

    assert result.gross_pay == Decimal("675.77")
    assert result.tax_paid == Decimal("90.84")
    assert result.ni_paid == Decimal("34.70")
    assert result.pension_paid == Decimal("22.23")
    assert result.other_deductions == Decimal("0.00")
    assert result.net_pay == Decimal("528.00")
    assert len(result.earnings) == 7
    assert result.earnings[2].description == "Enhanced Overnight Payment Per Hr"
    assert result.earnings[-1].amount == Decimal("121.30")
    assert result.warnings == []


def test_warns_when_detailed_tax_disagrees_with_summary():
    text = SAMPLE.replace("Tax Paid £90.04", "Tax Paid £89.04")
    text = text.replace("Total £146.59", "Total £145.59")

    result = extract_payslip_text(text)

    assert "Detailed tax is £89.04, but summary tax is £90.04." in (result.warnings)


def test_warns_when_detailed_total_disagrees_with_summary():
    result = extract_payslip_text(SAMPLE.replace("Total £146.59", "Total £146.58"))

    assert (
        "Detailed deductions total is £146.58, but summary deductions total is £146.59."
    ) in result.warnings


def test_missing_payments_section_is_flagged():
    result = extract_payslip_text("Gross Pay\n£672.59\nYTD £1,000.00")

    assert result.earnings == []
    assert any("payments section" in warning for warning in result.warnings)


def test_extracts_pay_date_from_filename():
    assert extract_pay_date("Payslip_PayDate_16102026.pdf") == "2026-10-16"


def test_rejects_invalid_pay_date():
    assert extract_pay_date("Payslip_PayDate_32132026.pdf") is None


def test_rejects_unexpected_filename():
    assert extract_pay_date("my_payslip.pdf") is None
