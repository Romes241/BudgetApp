"""Income history management page."""

import sqlite3
from datetime import date
from decimal import Decimal
from typing import ClassVar

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.pages.receipt_dialog import ReceiptConfirmationDialog
from budget_app.services.balance_service import record_imported_payslip_receipt
from budget_app.services.income_service import (
    add_income,
    delete_income,
    get_income_history,
    update_income,
)
from budget_app.services.settings_service import get_settings
from budget_app.utils.money import format_money, to_pence
from budget_app.utils.table import configure_table_header


class IncomeDialog(QDialog):
    """Dialog for adding or editing an actual income record."""

    MONEY_FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Gross pay", "gross_pay"),
        ("Tax paid", "tax_paid"),
        ("National Insurance", "ni_paid"),
        ("Pension", "pension_paid"),
        ("Other deductions", "other_deductions"),
        ("Net pay", "net_pay"),
    )

    def __init__(
        self,
        income: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.income = income
        self._preserve_null_bonus_amount = False
        self.setWindowTitle("Edit income record" if income else "Add income record")
        self.setMinimumWidth(440)

        self._build_ui()

        if income is not None:
            self._populate_fields()

    @staticmethod
    def _create_money_input() -> QDoubleSpinBox:
        """Create a consistently configured pounds input."""

        field = QDoubleSpinBox()
        field.setRange(0, 999999999.99)
        field.setDecimals(2)
        field.setSingleStep(1)
        field.setPrefix("£")
        field.setKeyboardTracking(False)
        return field

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(10)

        self.pay_date_input = QDateEdit()
        self.pay_date_input.setCalendarPopup(True)
        self.pay_date_input.setDisplayFormat("dd MMM yyyy")
        self.pay_date_input.setDate(QDate.currentDate())

        self.hours_input = QDoubleSpinBox()
        self.hours_input.setRange(0, 10000)
        self.hours_input.setDecimals(2)
        self.hours_input.setSingleStep(1)
        self.hours_input.setSuffix(" hours")
        self.hours_input.setKeyboardTracking(False)

        self.money_inputs: dict[str, QDoubleSpinBox] = {}

        form.addRow("Pay date", self.pay_date_input)
        form.addRow("Hours worked", self.hours_input)

        for label, field_name in self.MONEY_FIELDS:
            field = self._create_money_input()
            self.money_inputs[field_name] = field
            form.addRow(label, field)

        layout.addLayout(form)

        bonus_heading = QLabel("Bonus")
        bonus_heading.setObjectName("sectionHeading")
        layout.addWidget(bonus_heading)

        self.has_bonus_input = QCheckBox("This pay record includes a bonus")
        self.has_bonus_input.toggled.connect(self._set_bonus_fields_enabled)
        layout.addWidget(self.has_bonus_input)

        bonus_form = QFormLayout()
        bonus_form.setSpacing(10)

        self.bonus_amount_input = self._create_money_input()
        self.bonus_amount_input.valueChanged.connect(self._on_bonus_amount_changed)
        self.bonus_reason_input = QLineEdit()
        self.bonus_reason_input.setPlaceholderText("e.g. Performance bonus")

        bonus_form.addRow("Bonus amount", self.bonus_amount_input)
        bonus_form.addRow("Bonus reason", self.bonus_reason_input)
        layout.addLayout(bonus_form)

        self._set_bonus_fields_enabled(False)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _set_bonus_fields_enabled(self, enabled: bool) -> None:
        self.bonus_amount_input.setEnabled(enabled)
        self.bonus_reason_input.setEnabled(enabled)

        if not enabled:
            self._preserve_null_bonus_amount = False

    def _on_bonus_amount_changed(self, _value: float) -> None:
        self._preserve_null_bonus_amount = False

    def _populate_fields(self) -> None:
        pay_date = QDate.fromString(self.income["pay_date"], "yyyy-MM-dd")

        if pay_date.isValid():
            self.pay_date_input.setDate(pay_date)

        self.hours_input.setValue(float(self.income["hours_worked"]))

        for field_name, field in self.money_inputs.items():
            field.setValue(float(self.income[field_name]))

        bonus_amount = self.income["bonus_amount"]
        bonus_reason = self.income["bonus_reason"] or ""
        has_bonus = bonus_amount is not None or bool(bonus_reason)
        self.has_bonus_input.setChecked(has_bonus)
        self._preserve_null_bonus_amount = (
            has_bonus and bonus_amount is None and bool(bonus_reason)
        )

        if has_bonus:
            self.bonus_amount_input.setValue(float(bonus_amount or 0))

        self.bonus_reason_input.setText(bonus_reason)

    def _validate_and_accept(self) -> None:
        if not self.pay_date_input.date().isValid():
            self.error_label.setText("Please enter a valid pay date.")
            self.pay_date_input.setFocus()
            return

        numeric_fields = [("Hours worked", self.hours_input)]
        numeric_fields.extend(
            (label, self.money_inputs[field_name])
            for label, field_name in self.MONEY_FIELDS
        )
        numeric_fields.append(("Bonus amount", self.bonus_amount_input))

        for label, field in numeric_fields:
            if field.isEnabled() and not field.hasAcceptableInput():
                self.error_label.setText(f"Please enter a valid value for {label}.")
                field.setFocus()
                return

        self.error_label.clear()
        self.accept()

    def get_values(self) -> dict:
        """Return the values entered in the form."""

        values = {
            "pay_date": self.pay_date_input.date().toString("yyyy-MM-dd"),
            "hours_worked": self.hours_input.value(),
        }

        values.update(
            {
                field_name: Decimal(str(field.value()))
                for field_name, field in self.money_inputs.items()
            }
        )

        if self.has_bonus_input.isChecked():
            reason = self.bonus_reason_input.text().strip()
            if (
                self._preserve_null_bonus_amount
                and self.bonus_amount_input.value() == 0
            ):
                values["bonus_amount"] = None
            else:
                values["bonus_amount"] = Decimal(str(self.bonus_amount_input.value()))
            values["bonus_reason"] = reason or None
        else:
            values["bonus_amount"] = None
            values["bonus_reason"] = None

        return values


class IncomePage(QWidget):
    """Display and manage actual income history."""

    HEADERS: ClassVar[list[str]] = [
        "Pay date",
        "Hours",
        "Gross pay",
        "Tax",
        "NI",
        "Pension",
        "Other deductions",
        "Bonus",
        "Net pay",
    ]

    income_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.income_records: list[dict] = []
        self._build_ui()
        self.refresh_income()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(20)

        heading_layout = QHBoxLayout()
        heading_container = QVBoxLayout()
        heading_container.setSpacing(5)

        heading = QLabel("Income")
        heading.setObjectName("pageHeading")

        description = QLabel("View and manage your actual pay history.")
        description.setObjectName("secondaryText")

        heading_container.addWidget(heading)
        heading_container.addWidget(description)
        heading_layout.addLayout(heading_container)
        heading_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_income)
        heading_layout.addWidget(self.refresh_button)

        main_layout.addLayout(heading_layout)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)

        self.add_button = QPushButton("Add income")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_record)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.clicked.connect(self.edit_record)
        self.edit_button.setEnabled(False)
        self.edit_button.setToolTip("Select an income record to edit.")

        self.delete_button = QPushButton("Delete")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(self.delete_record)
        self.delete_button.setEnabled(False)

        self.confirm_receipt_button = QPushButton("Confirm received")
        self.confirm_receipt_button.clicked.connect(self.confirm_received)
        self.confirm_receipt_button.setEnabled(False)
        self.confirm_receipt_button.setToolTip(
            "Select an imported payslip that has reached your bank."
        )

        action_layout.addWidget(self.add_button)
        action_layout.addWidget(self.edit_button)
        action_layout.addWidget(self.delete_button)
        action_layout.addWidget(self.confirm_receipt_button)
        action_layout.addStretch()

        main_layout.addLayout(action_layout)

        self.income_table = QTableWidget(0, len(self.HEADERS))
        self.income_table.setHorizontalHeaderLabels(self.HEADERS)
        self.income_table.setObjectName("cashflowTable")
        self.income_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.income_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.income_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.income_table.setAlternatingRowColors(True)
        self.income_table.verticalHeader().setVisible(False)
        self.income_table.setHorizontalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel
        )

        header = self.income_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        self.income_table.setMinimumHeight(300)
        self.income_table.itemSelectionChanged.connect(self._update_action_buttons)

        main_layout.addWidget(self.income_table, 1)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("secondaryText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        main_layout.addWidget(self.empty_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondaryText")
        main_layout.addWidget(self.status_label)

    def refresh_income(self) -> bool:
        """Reload income history from the service."""

        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")
        success = False

        try:
            self.income_records = get_income_history()
            self._populate_table()

            count = len(self.income_records)
            self.status_label.setText(
                f"{count} income record{'s' if count != 1 else ''}"
            )
            success = True

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.status_label.setText("Unable to load income history.")
            QMessageBox.critical(
                self,
                "Income error",
                f"Could not load income history:\n\n{exc}",
            )

        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")

        return success

    def _populate_table(self) -> None:
        self.income_table.setRowCount(len(self.income_records))

        for row_index, record in enumerate(self.income_records):
            bonus = record["bonus_amount"]

            values = [
                record["pay_date"],
                f"{record['hours_worked']:,.2f}",
                format_money(to_pence(record["gross_pay"])),
                format_money(to_pence(record["tax_paid"])),
                format_money(to_pence(record["ni_paid"])),
                format_money(to_pence(record["pension_paid"])),
                format_money(to_pence(record["other_deductions"])),
                format_money(to_pence(bonus)) if bonus is not None else "—",
                format_money(to_pence(record["net_pay"])),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)

                if column in range(1, len(values)):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )

                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record["id"])

                self.income_table.setItem(row_index, column, item)

        if self.income_records:
            self.empty_label.hide()
            self.income_table.show()
        else:
            self.income_table.hide()
            self.empty_label.setText("No income records have been added yet.")
            self.empty_label.show()

        self.income_table.clearSelection()
        self._update_action_buttons()

    def _selected_record(self) -> dict | None:
        if not self.income_table.selectedItems():
            return None

        current_row = self.income_table.currentRow()

        if current_row < 0:
            return None

        first_item = self.income_table.item(current_row, 0)

        if first_item is None:
            return None

        income_id = first_item.data(Qt.ItemDataRole.UserRole)

        return next(
            (record for record in self.income_records if record["id"] == income_id),
            None,
        )

    def _update_action_buttons(self) -> None:
        record = self._selected_record()
        has_selection = record is not None

        self.delete_button.setEnabled(has_selection)
        self.confirm_receipt_button.setEnabled(
            bool(
                record and record.get("is_imported") and not record.get("receipt_date")
            )
        )
        self.confirm_receipt_button.setToolTip(
            "Confirm the bank receipt for this imported payslip."
            if record and record.get("is_imported") and not record.get("receipt_date")
            else "Select an imported payslip that has not yet been confirmed as received."
        )

        if not has_selection:
            self.edit_button.setEnabled(False)
            self.edit_button.setToolTip("Select an income record to edit.")
            return

        if record.get("source_file"):
            self.edit_button.setEnabled(False)
            self.edit_button.setToolTip(
                "Imported payslip records cannot currently be edited."
            )
        else:
            self.edit_button.setEnabled(True)
            self.edit_button.setToolTip("Edit the selected income record.")

    def confirm_received(self) -> None:
        """Record and link a previously imported payslip after it arrives."""
        record = self._selected_record()
        if not record or not record.get("is_imported") or record.get("receipt_date"):
            return

        settings = get_settings()
        dialog = ReceiptConfirmationDialog(
            date.fromisoformat(record["pay_date"]),
            int(settings["early_payment_offset_days"]),
            self,
            confirm_received=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.receipt_date is None:
            return

        try:
            transaction_id = record_imported_payslip_receipt(
                record["id"], dialog.receipt_date
            )
            if transaction_id is None:
                QMessageBox.warning(
                    self,
                    "Payslip not found",
                    "This imported payslip no longer exists. Refresh the list.",
                )
                self.refresh_income()
                return
            if self.refresh_income():
                self.status_label.setText(
                    f"Pay receipt recorded and linked (transaction #{transaction_id})."
                )
                self.income_changed.emit()
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.warning(
                self,
                "Could not confirm receipt",
                f"The pay receipt could not be recorded:\n\n{exc}",
            )

    def add_record(self) -> None:
        dialog = IncomeDialog(parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            add_income(**dialog.get_values())
            if self.refresh_income():
                self.status_label.setText("Income record added successfully.")
                self.income_changed.emit()

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self,
                "Could not add income",
                f"The income record could not be added:\n\n{exc}",
            )

    def edit_record(self) -> None:
        record = self._selected_record()

        if record is None:
            return

        if record.get("source_file"):
            QMessageBox.information(
                self,
                "Imported record",
                "Imported payslip income records cannot be edited.",
            )
            return

        dialog = IncomeDialog(income=record, parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            updated = update_income(
                record["id"],
                **dialog.get_values(),
                source_file=record["source_file"],
            )

            if not updated:
                QMessageBox.warning(
                    self,
                    "Income record not found",
                    "This income record no longer exists. Refresh the list.",
                )
                self.refresh_income()
                return

            if self.refresh_income():
                self.status_label.setText("Income record updated successfully.")
                self.income_changed.emit()

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self,
                "Could not update income",
                f"The income record could not be updated:\n\n{exc}",
            )

    def delete_record(self) -> None:
        record = self._selected_record()

        if record is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete income record",
            (
                f"Are you sure you want to delete the income record for "
                f"{record['pay_date']}?\n\nThis action cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = delete_income(record["id"])

            if not deleted:
                QMessageBox.warning(
                    self,
                    "Income record not found",
                    "This income record no longer exists. Refresh the list.",
                )
                self.refresh_income()
                return

            if self.refresh_income():
                self.status_label.setText("Income record deleted successfully.")
                self.income_changed.emit()

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self,
                "Could not delete income",
                f"The income record could not be deleted:\n\n{exc}",
            )
