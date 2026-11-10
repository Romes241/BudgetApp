"""Shared presentation settings for readable table headings."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView


def configure_table_header(header: QHeaderView) -> None:
    """Keep table headings centred and sections wide enough to read."""
    header.setMinimumSectionSize(88)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
