"""Approximate UK employee take-home pay from saved payroll settings.

The calculation annualises regular earnings, applies the selected tax-year
income-tax bands and per-period NI/student-loan thresholds, then divides the
annual PAYE estimate across the configured pay periods. It is a forecast, not
an HMRC payroll engine.

Rates are transcribed from the official GOV.UK 2025-26 and 2026-27 income tax,
National Insurance, and student-loan tables.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

TAX_YEAR_START = (4, 6)
SUPPORTED_TAX_YEARS = ("2025-26", "2026-27")
PERSONAL_ALLOWANCE = 1_257_000  # pence
TAX_BANDS = {
    "2025-26": {
        "rUK": ((37_700_00, 0.20), (112_570_00, 0.40), (None, 0.45)),
        "Scotland": (
            (2_827_00, 0.19),
            (14_921_00, 0.20),
            (31_092_00, 0.21),
            (62_430_00, 0.42),
            (112_570_00, 0.45),
            (None, 0.48),
        ),
    },
    "2026-27": {
        "rUK": ((37_700_00, 0.20), (112_570_00, 0.40), (None, 0.45)),
        "Scotland": (
            (3_967_00, 0.19),
            (16_956_00, 0.20),
            (31_092_00, 0.21),
            (62_430_00, 0.42),
            (112_570_00, 0.45),
            (None, 0.48),
        ),
    },
}
STUDENT_LOAN_THRESHOLDS = {
    "2025-26": {
        "Plan 1": 26_065_00,
        "Plan 2": 28_470_00,
        "Plan 4": 31_395_00,
        "Postgraduate": 21_000_00,
    },
    "2026-27": {
        "Plan 1": 26_900_00,
        "Plan 2": 29_385_00,
        "Plan 4": 33_795_00,
        "Plan 5": 25_000_00,
        "Postgraduate": 21_000_00,
    },
}
PERIODS_PER_YEAR = {"weekly": 52, "fortnightly": 26, "monthly": 12}
NI_CATEGORIES = set("ABCDEFHIJKLMNSVZ")


def tax_year_for_date(value: date) -> str:
    """Return the UK tax year containing a date (tax years start 6 April)."""
    return (
        f"{value.year}-{str(value.year + 1)[-2:]}"
        if (value.month, value.day) >= TAX_YEAR_START
        else f"{value.year - 1}-{str(value.year)[-2:]}"
    )


def _tax_allowance(code: str, annual_gross: int) -> tuple[int, bool]:
    normalized = re.sub(r"(W1|M1|X)$", "", code.upper().replace(" ", ""))
    if normalized in {"BR", "SBR"}:
        return 0, True
    if normalized in {"D0", "SD0"}:
        return 0, True
    if normalized in {"D1", "SD1"}:
        return 0, True
    if normalized in {"NT", "SNT"}:
        return annual_gross, False
    if normalized in {"0T", "S0T"}:
        return 0, True
    match = re.fullmatch(r"(S)?(K?)(\d+)(L|T|M|N)?", normalized)
    if not match:
        raise ValueError(f"Unsupported tax code: {code!r}.")
    _scottish_prefix, k_prefix, digits, suffix = match.groups()
    if k_prefix:
        return -int(digits) * 10_00, True
    allowance = int(digits) * 10_00
    if suffix in (None, "T"):
        return allowance, True
    return max(0, allowance), True


def _income_tax(
    annual_gross: int, allowance: int, scottish: bool, tax_code: str, tax_year: str
) -> int:
    normalized = tax_code.upper().replace(" ", "")
    if normalized in {"NT", "SNT"}:
        return 0
    if normalized in {"D0", "SD0"}:
        return round(annual_gross * 0.40)
    if normalized in {"D1", "SD1"}:
        return round(annual_gross * 0.45)
    if normalized in {"BR", "SBR"}:
        return round(annual_gross * 0.20)
    if annual_gross > 10_000_000:
        allowance = max(0, allowance - (annual_gross - 10_000_000) // 2)
    taxable = max(0, annual_gross - allowance)
    bands = TAX_BANDS[tax_year]["Scotland" if scottish else "rUK"]
    tax = 0
    lower = 0
    for upper, rate in bands:
        width = taxable - lower if upper is None else min(taxable, upper) - lower
        if width > 0:
            tax += round(width * rate)
        if upper is None or taxable <= upper:
            break
        lower = upper
    return tax


def _ni_for_period(gross: int, category: str, frequency: str) -> int:
    category = category.upper()
    if category not in NI_CATEGORIES:
        raise ValueError(f"Unsupported National Insurance category: {category!r}.")
    if category in {"C", "K", "S"}:
        return 0
    thresholds = {
        "weekly": (24_200, 96_700),
        "fortnightly": (48_400, 193_400),
        "monthly": (104_800, 418_900),
    }
    primary, upper = thresholds[frequency]
    reduced = {
        "B": 0.0185,
        "E": 0.0185,
        "I": 0.0185,
        "D": 0.02,
        "J": 0.02,
        "L": 0.02,
        "Z": 0.02,
    }.get(category, 0.08)
    additional = 0.02
    middle = max(0, min(gross, upper) - primary)
    above = max(0, gross - upper)
    return round(middle * reduced) + round(above * additional)


def _student_loan_for_period(
    gross: int, plan_value: str, frequency: str, tax_year: str
) -> int:
    plans = [
        p.strip()
        for p in re.split(r"[,;+]", plan_value)
        if p.strip() and p.strip().lower() != "none"
    ]
    if not plans:
        return 0
    unsupported = set(plans) - set(STUDENT_LOAN_THRESHOLDS[tax_year])
    if unsupported:
        raise ValueError(
            f"Unsupported student loan plan: {', '.join(sorted(unsupported))}."
        )
    thresholds = STUDENT_LOAN_THRESHOLDS[tax_year]
    period_count = PERIODS_PER_YEAR[frequency]
    threshold = min(thresholds.get(plan, float("inf")) for plan in plans)
    threshold_period = round(threshold / period_count)
    undergraduate = round(max(0, gross - threshold_period) * 0.09)
    postgraduate = 0
    if "Postgraduate" in plans:
        pg_threshold = round(thresholds["Postgraduate"] / period_count)
        postgraduate = round(max(0, gross - pg_threshold) * 0.06)
    return undergraduate + postgraduate


def calculate_take_home_pay(
    *,
    hourly_wage_pence: int,
    average_hours: float,
    frequency: str,
    tax_code: str,
    ni_category: str,
    scottish_taxpayer: bool,
    pension_percent: float,
    student_loan_plan: str,
    tax_year: str,
) -> dict[str, Any]:
    """Return gross and estimated deductions in pence for one pay period."""
    if not isinstance(frequency, str) or frequency not in PERIODS_PER_YEAR:
        raise ValueError("Pay frequency must be weekly, fortnightly or monthly.")
    if tax_year not in SUPPORTED_TAX_YEARS:
        raise ValueError(
            f"Unsupported tax year: {tax_year}. Supported years: {', '.join(SUPPORTED_TAX_YEARS)}."
        )
    if not isinstance(scottish_taxpayer, bool):
        raise ValueError("Scottish taxpayer must be True or False.")

    if (
        isinstance(hourly_wage_pence, bool)
        or not isinstance(hourly_wage_pence, int)
        or hourly_wage_pence < 0
    ):
        raise ValueError("Hourly wage must be a non-negative integer in pence.")
    if isinstance(average_hours, bool) or not isinstance(average_hours, (int, float)):
        raise ValueError("Hourly wage and average weekly hours must be non-negative.")
    if not 0 <= average_hours <= 168:
        raise ValueError("Average weekly hours must be between 0 and 168.")
    if not isinstance(tax_code, str) or not tax_code.strip():
        raise ValueError("Tax code cannot be empty.")
    if not isinstance(ni_category, str) or not ni_category.strip():
        raise ValueError("National Insurance category cannot be empty.")
    if not isinstance(student_loan_plan, str) or not student_loan_plan.strip():
        raise ValueError("Student loan plan cannot be empty.")
    if (
        isinstance(pension_percent, bool)
        or not isinstance(pension_percent, (int, float))
        or not 0 <= pension_percent <= 100
    ):
        raise ValueError("Pension percentage must be between 0 and 100.")
    periods = PERIODS_PER_YEAR[frequency]
    weekly_gross = round(hourly_wage_pence * average_hours)
    gross = round(weekly_gross * 52 / periods)
    annual_gross = weekly_gross * 52
    pension = round(gross * pension_percent / 100)
    allowance, apply_tax = _tax_allowance(tax_code, annual_gross)
    effective_scottish = scottish_taxpayer or tax_code.upper().startswith("S")
    annual_tax = (
        _income_tax(
            annual_gross - round(pension * periods),
            allowance,
            effective_scottish,
            tax_code,
            tax_year,
        )
        if apply_tax
        else 0
    )
    if allowance < 0:  # HMRC caps the extra deduction from a K code at half pay.
        annual_tax = min(annual_tax, annual_gross // 2)
    tax = round(annual_tax / periods)
    ni = _ni_for_period(gross, ni_category, frequency)
    student_loan = _student_loan_for_period(
        gross, student_loan_plan, frequency, tax_year
    )
    net = max(0, gross - tax - ni - pension - student_loan)
    return {
        "gross_pay_pence": gross,
        "tax_pence": tax,
        "ni_pence": ni,
        "pension_pence": pension,
        "student_loan_pence": student_loan,
        "net_pay_pence": net,
        "tax_year": tax_year,
        "assumptions": "Annualised income tax; rates and thresholds come from the tax year containing the forecast start date and are held across the forecast; PAYE pension relief is assumed (pension is deducted before income tax and based on all gross pay); standard employee NI by pay period; no other deductions or tax-code adjustments.",
    }
