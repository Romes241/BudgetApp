"""Shared dialog for confirming an imported payslip receipt date."""

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from budget_app.utils.widget_sizing import configure_form_controls


class ReceiptConfirmationDialog(QDialog):
    """Ask whether an imported payslip has reached the user's bank."""

    def __init__(
        self,
        pay_date: date,
        early_payment_offset_days: int,
        parent: QWidget | None = None,
        *,
        confirm_received: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Confirm bank receipt")
        self.receipt_date: date | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        explanation = QLabel(
            "Confirm whether this pay has reached your bank account. A confirmed "
            "receipt is recorded as money in and linked to the payslip. Until "
            "then, the payslip remains forecast income. The suggested receipt "
            "date uses your saved early-payment setting."
        )
        explanation.setObjectName("secondaryText")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.received_checkbox = QCheckBox("This pay has reached my bank account")
        self.received_checkbox.setVisible(not confirm_received)
        self.received_checkbox.setChecked(confirm_received)
        layout.addWidget(self.received_checkbox)

        form = QFormLayout()
        self.receipt_date_input = QDateEdit()
        self.receipt_date_input.setCalendarPopup(True)
        self.receipt_date_input.setDisplayFormat("dd MMM yyyy")

        earliest_receipt = pay_date - timedelta(days=7)
        latest_receipt = min(pay_date + timedelta(days=7), date.today())
        self.can_confirm_receipt = earliest_receipt <= latest_receipt
        if self.can_confirm_receipt:
            expected_receipt = pay_date - timedelta(days=early_payment_offset_days)
            suggested_receipt = min(
                latest_receipt, max(earliest_receipt, expected_receipt)
            )
            self.receipt_date_input.setMinimumDate(
                QDate(
                    earliest_receipt.year, earliest_receipt.month, earliest_receipt.day
                )
            )
            self.receipt_date_input.setMaximumDate(
                QDate(latest_receipt.year, latest_receipt.month, latest_receipt.day)
            )
            self.receipt_date_input.setDate(
                QDate(
                    suggested_receipt.year,
                    suggested_receipt.month,
                    suggested_receipt.day,
                )
            )
        else:
            self.received_checkbox.setEnabled(False)
            self.received_checkbox.setToolTip(
                "Receipt can be confirmed when the payslip date is within "
                "seven days of today."
            )
            self.receipt_date_input.setDate(QDate.currentDate())
        self.receipt_date_input.setEnabled(
            confirm_received and self.can_confirm_receipt
        )
        self.received_checkbox.toggled.connect(self.receipt_date_input.setEnabled)
        form.addRow("Date received", self.receipt_date_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.can_confirm_receipt or not confirm_received
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Confirm receipt" if confirm_received else "Continue import"
        )
        buttons.accepted.connect(self._accept_receipt_choice)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        configure_form_controls(self)

    def _accept_receipt_choice(self) -> None:
        if self.received_checkbox.isChecked() or not self.received_checkbox.isVisible():
            qdate = self.receipt_date_input.date()
            self.receipt_date = date(qdate.year(), qdate.month(), qdate.day())
        self.accept()
