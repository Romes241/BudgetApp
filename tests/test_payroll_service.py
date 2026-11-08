from datetime import date

import pytest

from budget_app.services.payroll_service import (
    calculate_take_home_pay,
    tax_year_for_date,
)


def calculate(**overrides):
    values = {
        "hourly_wage_pence": 5000,
        "average_hours": 20,
        "frequency": "weekly",
        "tax_code": "1257L",
        "ni_category": "A",
        "scottish_taxpayer": False,
        "pension_percent": 0,
        "student_loan_plan": "None",
        "tax_year": "2026-27",
    }
    values.update(overrides)
    return calculate_take_home_pay(**values)


@pytest.mark.parametrize(
    ("frequency", "expected_gross"),
    [("weekly", 100000), ("fortnightly", 200000), ("monthly", 433333)],
)
def test_calculates_gross_for_supported_pay_frequencies(frequency, expected_gross):
    result = calculate(frequency=frequency)
    assert result["gross_pay_pence"] == expected_gross
    assert result["net_pay_pence"] < expected_gross


def test_tax_code_and_scottish_status_change_income_tax():
    standard = calculate()
    basic_rate = calculate(tax_code="BR")
    scottish = calculate(scottish_taxpayer=True)

    assert standard["tax_pence"] != basic_rate["tax_pence"]
    assert standard["tax_pence"] != scottish["tax_pence"]


@pytest.mark.parametrize(
    ("tax_code", "expected_weekly_tax"),
    [
        ("BR W1", 20000),
        ("BR M1", 20000),
        ("D0 X", 40000),
        ("D1 W1", 45000),
        ("NT X", 0),
        ("SD0", 21000),
        ("SD1", 42000),
        ("SD2", 45000),
        ("SD3", 48000),
    ],
)
def test_special_and_emergency_tax_codes_use_their_fixed_rates(
    tax_code, expected_weekly_tax
):
    result = calculate(tax_code=tax_code)
    assert result["tax_pence"] == expected_weekly_tax


def test_k_code_keeps_its_taxable_pay_addition_above_personal_allowance_taper():
    result = calculate(hourly_wage_pence=5000, average_hours=40, tax_code="K500")

    # £104,000 gross plus the £5,000 K-code addition is taxed progressively.
    assert result["tax_pence"] == 69346


def test_ni_category_changes_employee_ni():
    standard = calculate()
    reduced = calculate(ni_category="B")
    no_employee_ni = calculate(ni_category="C")

    assert standard["ni_pence"] > reduced["ni_pence"] > no_employee_ni["ni_pence"]
    assert no_employee_ni["ni_pence"] == 0


def test_pension_and_student_loan_are_deducted():
    base = calculate(frequency="monthly")
    deductions = calculate(
        frequency="monthly",
        pension_percent=5,
        student_loan_plan="Plan 2, Postgraduate",
    )

    assert deductions["pension_pence"] == round(base["gross_pay_pence"] * 0.05)
    assert deductions["student_loan_pence"] > 0
    assert deductions["net_pay_pence"] < base["net_pay_pence"]


def test_tax_year_boundaries_and_rate_tables_are_explicit():
    assert tax_year_for_date(date(2026, 4, 5)) == "2025-26"
    assert tax_year_for_date(date(2026, 4, 6)) == "2026-27"
    old_year = calculate(tax_year="2025-26", student_loan_plan="Plan 1")
    new_year = calculate(tax_year="2026-27", student_loan_plan="Plan 1")
    assert old_year["tax_year"] == "2025-26"
    assert old_year["student_loan_pence"] != new_year["student_loan_pence"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tax_code", "INVALID", "tax code"),
        ("ni_category", "Q", "National Insurance"),
        ("frequency", "daily", "Pay frequency"),
        ("tax_year", "2027-28", "tax year"),
        ("student_loan_plan", "Plan 9", "student loan"),
    ],
)
def test_unsupported_settings_are_reported(field, value, message):
    with pytest.raises(ValueError, match=message):
        calculate(**{field: value})
