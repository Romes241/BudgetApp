
"""Utilities for handling monetary values safely."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_pence(amount: str | int | float | Decimal) -> int:
    """Convert a pound amount to integer pennies.

    Amounts with more than two decimal places are rounded
    to the nearest penny, with half-pennies rounded away
    from zero.
    """

    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise ValueError("Amount must be a valid number.") from None

    if not value.is_finite():
        raise ValueError("Amount must be finite.")

    rounded = value.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return int(rounded * 100)


def from_pence(amount_pence: int) -> Decimal:
    """Convert integer pennies into a Decimal pound amount."""

    return Decimal(amount_pence) / Decimal(100)


def format_money(amount_pence: int) -> str:
    """Format integer pennies as a GBP currency string."""

    amount = from_pence(amount_pence)
    return f"£{amount:,.2f}"
