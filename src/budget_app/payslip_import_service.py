"""Validate and atomically import extracted payslip data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from budget_app.database import database_connection
from budget_app.money import to_pence
from budget_app.payslip_extractor import (
    EarningsLine,
    PayslipData,
    extract_payslip_pdf,
)


class PayslipImportError(Exception):
    """Base exception for payslip import failures."""


class DuplicatePayslipError(PayslipImportError):
    """Raised when the same payslip file has already been imported."""


class PayslipValidationError(PayslipImportError):
    """Raised when a payslip cannot safely be imported."""


@dataclass
class PayslipImportPreview:
    """Validation results shown before the user confirms an import."""

    data: PayslipData
    valid: bool
    errors: list[str]


def _basic_hours(earnings: list[EarningsLine]) -> Decimal:
    """Calculate worked hours from Basic Pay lines only."""
    return sum(
        (
            line.units
            for line in earnings
            if line.units is not None
            and "basic pay" in line.description.casefold()
        ),
        start=Decimal("0"),
    )


def validate_payslip(data: PayslipData) -> list[str]:
    """Return errors that prevent safe import of the payslip."""
    errors = list(data.warnings)

    if not data.source_hash:
        errors.append("The payslip file hash is missing.")

    if not data.pay_date:
        errors.append("The pay date is missing or invalid.")

    required_amounts = {
        "Gross pay": data.gross_pay,
        "Tax paid": data.tax_paid,
        "National Insurance": data.ni_paid,
        "Pension paid": data.pension_paid,
        "Other deductions": data.other_deductions,
        "Net pay": data.net_pay,
    }

    for label, amount in required_amounts.items():
        if amount is None:
            errors.append(f"{label} could not be extracted.")
        elif not amount.is_finite() or amount < 0:
            errors.append(f"{label} must be finite and non-negative.")

    if not data.earnings:
        errors.append("No earnings lines were extracted.")

    for index, line in enumerate(data.earnings, start=1):
        if not line.description.strip():
            errors.append(f"Earnings line {index} has no description.")
        if not line.amount.is_finite() or line.amount < 0:
            errors.append(
                f"Earnings line {index} has an invalid amount."
            )

    if data.gross_pay is not None and data.earnings:
        line_total = sum(
            (line.amount for line in data.earnings),
            start=Decimal("0.00"),
        )
        if line_total != data.gross_pay:
            errors.append(
                f"Earnings total £{line_total} does not match "
                f"gross pay £{data.gross_pay}."
            )

    amounts = (
        data.tax_paid,
        data.ni_paid,
        data.pension_paid,
        data.other_deductions,
    )

    if (
        data.gross_pay is not None
        and data.net_pay is not None
        and all(amount is not None for amount in amounts)
    ):
        expected_net = data.gross_pay - sum(
            amounts, start=Decimal("0.00")
        )
        if expected_net != data.net_pay:
            errors.append(
                f"Expected net pay £{expected_net}, "
                f"but extracted net pay is £{data.net_pay}."
            )

    return list(dict.fromkeys(errors))


def preview_payslip_import(
    path: str | Path,
) -> PayslipImportPreview:
    """Extract a payslip and validate it without changing the database."""
    data = extract_payslip_pdf(path)
    errors = validate_payslip(data)

    return PayslipImportPreview(
        data=data,
        valid=not errors,
        errors=errors,
    )


def _classification(description: str) -> str:
    """Infer a conservative payment-line classification."""
    normalised = description.casefold()

    if "bonus" in normalised:
        return "bonus"
    if "basic pay" in normalised:
        return "regular"
    if "enhanced" in normalised or "overtime" in normalised:
        return "additional"

    return "unknown"


def import_payslip(
    path: str | Path,
    *,
    confirmed: bool = False,
    database_path: str | Path | None = None,
) -> int:
    """Import a validated payslip and return its new income ID.

    All inserts happen in one transaction. The caller must explicitly
    confirm the import after reviewing the preview.
    """
    if not confirmed:
        raise PayslipValidationError(
            "Import not confirmed. Preview and review the payslip first."
        )

    pdf_path = Path(path)
    preview = preview_payslip_import(pdf_path)

    if not preview.valid:
        raise PayslipValidationError(
            "Payslip cannot be imported:\n- "
            + "\n- ".join(preview.errors)
        )

    data = preview.data

    assert data.source_hash is not None
    assert data.pay_date is not None
    assert data.gross_pay is not None
    assert data.tax_paid is not None
    assert data.ni_paid is not None
    assert data.pension_paid is not None
    assert data.other_deductions is not None
    assert data.net_pay is not None

    hours_worked = _basic_hours(data.earnings)
    source_file = pdf_path.name

    try:
        with database_connection(database_path) as connection:
            existing = connection.execute(
                """
                SELECT 1
                FROM imported_payslips
                WHERE source_hash = ?
                """,
                (data.source_hash,),
            ).fetchone()

            if existing is not None:
                raise DuplicatePayslipError(
                    "This exact payslip file has already been imported."
                )

            cursor = connection.execute(
                """
                INSERT INTO income_history (
                    pay_date,
                    hours_worked,
                    gross_pay_pence,
                    tax_paid_pence,
                    ni_paid_pence,
                    pension_paid_pence,
                    net_pay_pence,
                    source_file,
                    other_deductions_pence,
                    bonus_amount_pence,
                    bonus_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    data.pay_date,
                    float(hours_worked),
                    to_pence(data.gross_pay),
                    to_pence(data.tax_paid),
                    to_pence(data.ni_paid),
                    to_pence(data.pension_paid),
                    to_pence(data.net_pay),
                    source_file,
                    to_pence(data.other_deductions),
                ),
            )
            income_id = cursor.lastrowid

            for line in data.earnings:
                units = float(line.units) if line.units is not None else None
                rate_pence = (
                    to_pence(line.rate) if line.rate is not None else None
                )

                connection.execute(
                    """
                    INSERT INTO income_payment_lines (
                        income_id,
                        description,
                        units,
                        rate_pence,
                        amount_pence,
                        classification
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        income_id,
                        line.description,
                        units,
                        rate_pence,
                        to_pence(line.amount),
                        _classification(line.description),
                    ),
                )

            connection.execute(
                """
                INSERT INTO imported_payslips (
                    source_hash,
                    source_file,
                    income_id
                )
                VALUES (?, ?, ?)
                """,
                (data.source_hash, source_file, income_id),
            )

            return income_id

    except sqlite3.IntegrityError as exc:
        if "source_hash" in str(exc).casefold():
            raise DuplicatePayslipError(
                "This exact payslip file has already been imported."
            ) from exc
        raise
