"""Extract structured income data from selectable-text payslip PDFs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

@dataclass
class EarningsLine:
    """An individual earnings line extracted from a payslip."""

    description: str
    units: Decimal | None
    rate: Decimal | None
    amount: Decimal

@dataclass
class PayslipData:
    """Structured data extracted from a payslip."""

    gross_pay: Decimal | None = None
    tax_paid: Decimal | None = None
    ni_paid: Decimal | None = None
    pension_paid: Decimal | None = None
    other_deductions: Decimal | None = None
    net_pay: Decimal | None = None
    pay_date: str | None = None
    source_hash: str | None = None
    earnings: list[EarningsLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

def _money(value: str) -> Decimal:
    """Parse a monetary value without using binary floating point."""
    return Decimal(value.replace("£", "").replace(",", "").strip())

def _summary_amount(text: str, label: str) -> Decimal | None:
    """Extract a current-period summary amount, excluding its YTD value."""
    pattern = (
        rf"(?m)^{re.escape(label)}\s*\n\s*"
        rf"£?([\d,]+\.\d{{2}})\s*\n\s*YTD\b"
    )
    match = re.search(pattern, text, re.IGNORECASE)
    return _money(match.group(1)) if match else None

def _extract_deductions(
    text: str,
) -> tuple[Decimal | None, Decimal | None, list[str]]:
    """Extract pension and other deductions from the detailed section."""
    section = re.search(
        r"DEDUCTIONS\s*-\s*EMPLOYEE DEFAULT POST(.*?)"
        r"(?=MESSAGES\s+CUMULATIVE YEAR TO DATE|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not section:
        return None, None, [
            "Could not find the detailed deductions section."
        ]

    deduction_text = section.group(1)

    # Remove the table heading before parsing the rows.
    deduction_text = re.sub(
        r"(?im)^\s*Description\s+Amount\s*$",
        "",
        deduction_text,
    )

    rows = re.findall(
        r"(?m)^\s*(.*?)\s+£?([\d,]+\.\d{2})\s*$",
        deduction_text,
    )

    pension_amounts: list[Decimal] = []
    other_amounts: list[Decimal] = []
    found_tax = False
    found_ni = False
    found_pension = False

    for description, amount_text in rows:
        description = " ".join(description.split())
        normalised = description.casefold()

        if not description or normalised.startswith("total"):
            continue

        amount = _money(amount_text)

        if "pension" in normalised or "nest" in normalised:
            pension_amounts.append(amount)
            found_pension = True
        elif "tax" in normalised:
            found_tax = True
        elif (
            normalised.startswith("ni")
            or "national insurance" in normalised
        ):
            found_ni = True
        else:
            other_amounts.append(amount)

    if not (found_tax and found_ni and found_pension):
        return None, None, [
            "The detailed deductions section could not be fully identified."
        ]

    pension = sum(pension_amounts, start=Decimal("0.00"))
    other = sum(other_amounts, start=Decimal("0.00"))

    return pension, other, []

def extract_pay_date(filename: str | Path) -> str | None:
    """Extract the pay date from Payslip_PayDate_DDMMYYYY.pdf."""
    name = Path(filename).name

    match = re.fullmatch(
        r"Payslip_PayDate_(\d{8})\.pdf",
        name,
        re.IGNORECASE,
    )

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1), "%d%m%Y"
        ).date().isoformat()
    except ValueError:
        return None

def extract_payslip_text(text: str) -> PayslipData:
    """Parse the known payslip text layout into structured data."""
    pension_paid, other_deductions, deduction_warnings = (
        _extract_deductions(text)
    )

    result = PayslipData(
        gross_pay=_summary_amount(text, "Gross Pay"),
        tax_paid=_summary_amount(text, "PAYE Tax"),
        ni_paid=_summary_amount(text, "NIC"),
        pension_paid=pension_paid,
        other_deductions=other_deductions,
        net_pay=_summary_amount(text, "Net Pay"),
        warnings=deduction_warnings,
    )

    section = re.search(
        r"PAYMENTS\s*-\s*EMPLOYEE DEFAULT POST(.*?)"
        r"DEDUCTIONS\s*-\s*EMPLOYEE DEFAULT POST",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not section:
        result.warnings.append(
            "Could not find the employee payments section."
        )
        return result

    payment_text = section.group(1)

    payment_text = re.sub(
        r"(?m)^\s*Description\s+Units\s+Rate\s+Amount\s*$",
        "",
        payment_text,
    )
    payment_text = re.sub(
        r"(?m)^\s*Total\s+£?[\d,]+\.\d{2}\s*$",
        "",
        payment_text,
    )

    row_pattern = re.compile(
        r"(?m)^\s*(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d{1,4})?)\s+"
        r"(\d[\d,]*\.\d{2})\s*$"
    )

    matches = list(row_pattern.finditer(payment_text))

    for index, match in enumerate(matches):
        previous_end = matches[index - 1].end() if index else 0
        description = payment_text[previous_end:match.start()]
        description = " ".join(description.split())

        if not description:
            result.warnings.append(
                "Found an earnings row without a description: "
                f"{match.group(0)}"
            )
            continue

        result.earnings.append(
            EarningsLine(
                description=description,
                units=Decimal(match.group(1)),
                rate=Decimal(match.group(2)),
                amount=_money(match.group(3)),
            )
        )

    if not result.earnings:
        result.warnings.append("No earnings lines could be extracted.")

    if result.gross_pay is None:
        result.warnings.append("Gross pay could not be extracted.")
    elif result.earnings:
        line_total = sum(
            (line.amount for line in result.earnings),
            start=Decimal("0.00"),
        )

        if line_total != result.gross_pay:
            result.warnings.append(
                f"Earnings lines total £{line_total}, "
                f"but gross pay is £{result.gross_pay}."
            )

    if result.gross_pay is not None and result.net_pay is not None:
        deductions = (
            result.tax_paid,
            result.ni_paid,
            result.pension_paid,
            result.other_deductions,
        )

        if all(value is not None for value in deductions):
            expected_net = result.gross_pay - sum(
                deductions, start=Decimal("0.00")
            )

            if expected_net != result.net_pay:
                result.warnings.append(
                    f"Gross minus deductions is £{expected_net}, "
                    f"but net pay is £{result.net_pay}."
                )

    return result

def extract_payslip_pdf(path: str | Path) -> PayslipData:
    """Extract and parse text from a selectable-text PDF."""
    pdf_path = Path(path)

    if not pdf_path.is_file():
        return PayslipData(
            warnings=[
                f"Payslip file does not exist: {pdf_path.name}"
            ]
        )

    if pdf_path.suffix.lower() != ".pdf":
        return PayslipData(
            warnings=["The selected file is not a PDF."]
        )

    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
        source_hash = hashlib.sha256(
            pdf_path.read_bytes()
        ).hexdigest()
    except Exception as exc:
        return PayslipData(
            warnings=[f"Could not read the PDF: {exc}"]
        )

    if not text.strip():
        result = PayslipData(
            warnings=[
                "No selectable text was found. This PDF may require OCR."
            ]
        )
    else:
        result = extract_payslip_text(text)

    result.pay_date = extract_pay_date(pdf_path.name)
    result.source_hash = source_hash

    if result.pay_date is None:
        result.warnings.append(
            "Filename does not contain a valid pay date. "
            "Expected Payslip_PayDate_DDMMYYYY.pdf."
        )

    return result
