"""Debt management page."""

import sqlite3
from datetime import date
from decimal import Decimal
from typing import ClassVar

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.debt_service import (
    add_debt,
    deactivate_debt,
    get_debts,
    reactivate_debt,
    record_debt_payment,
    update_debt,
)
from budget_app.utils.money import format_money


class DebtDialog(QDialog):
    """Dialog for creating or editing a debt."""

    def __init__(
        self,
        debt: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.debt = debt
        self.setWindowTitle("Edit debt" if debt else "Add debt")
        self.setMinimumWidth(400)

        self._build_ui()

        if debt is not None:
            self._populate_fields()

    @staticmethod
    def _money_input() -> QDoubleSpinBox:
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
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Credit card")

        self.balance_input = self._money_input()
        self.original_balance_input = self._money_input()
        self.monthly_payment_input = self._money_input()

        self.due_day_input = QComboBox()
        self.due_day_input.addItem("Not specified", None)

        for day in range(1, 32):
            self.due_day_input.addItem(str(day), day)

        form.addRow("Debt name", self.name_input)
        form.addRow("Outstanding balance", self.balance_input)
        form.addRow("Original balance", self.original_balance_input)
        form.addRow("Monthly payment", self.monthly_payment_input)
        form.addRow("Payment due day", self.due_day_input)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)

    def _populate_fields(self) -> None:
        self.name_input.setText(self.debt["name"])
        self.balance_input.setValue(float(self.debt["balance"]))
        self.original_balance_input.setValue(float(self.debt["original_balance"]))
        self.monthly_payment_input.setValue(float(self.debt["monthly_payment"]))

        index = self.due_day_input.findData(self.debt["due_day"])
        if index >= 0:
            self.due_day_input.setCurrentIndex(index)

    def _validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            self.error_label.setText("Please enter a debt name.")
            self.name_input.setFocus()
            return

        if self.balance_input.value() > self.original_balance_input.value():
            self.error_label.setText(
                "Outstanding balance cannot exceed the original balance."
            )
            self.balance_input.setFocus()
            return

        self.error_label.clear()
        self.accept()

    def get_values(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "balance": Decimal(str(self.balance_input.value())),
            "original_balance": Decimal(str(self.original_balance_input.value())),
            "monthly_payment": Decimal(str(self.monthly_payment_input.value())),
            "due_day": self.due_day_input.currentData(),
        }


class DebtPaymentDialog(QDialog):
    """Dialog for recording a payment against a debt."""

    def __init__(self, debt: dict, parent: QWidget | None = None):
        super().__init__(parent)

        self.debt = debt
        self.setWindowTitle(f"Record payment – {debt['name']}")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        balance_label = QLabel(
            f"Outstanding balance: {format_money(debt['balance_pence'])}"
        )
        balance_label.setObjectName("secondaryText")
        layout.addWidget(balance_label)

        form = QFormLayout()
        form.setSpacing(12)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0.01, float(debt["balance"]))
        self.amount_input.setDecimals(2)
        self.amount_input.setSingleStep(1)
        self.amount_input.setPrefix("£")
        self.amount_input.setKeyboardTracking(False)

        suggested_amount = float(debt["monthly_payment"])
        self.amount_input.setValue(
            min(suggested_amount, float(debt["balance"]))
            if suggested_amount > 0
            else float(debt["balance"])
        )

        self.payment_date_input = QDateEdit()
        self.payment_date_input.setCalendarPopup(True)
        self.payment_date_input.setDisplayFormat("dd MMM yyyy")
        self.payment_date_input.setDate(QDate.currentDate())

        form.addRow("Payment amount", self.amount_input)
        form.addRow("Payment date", self.payment_date_input)
        layout.addLayout(form)

        note = QLabel(
            "Recording a payment updates the balance and last payment date. "
            "Because the app currently stores only the latest payment date, "
            "any recorded payment marks that calendar month's scheduled "
            "repayment as already made in Cashflow."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)

    def _validate_and_accept(self) -> None:
        if self.amount_input.value() <= 0:
            self.error_label.setText("Payment amount must be greater than zero.")
            return

        if self.amount_input.value() > float(self.debt["balance"]):
            self.error_label.setText("Payment cannot exceed the outstanding balance.")
            return

        self.error_label.clear()
        self.accept()

    def get_values(self) -> dict:
        return {
            "amount": Decimal(str(self.amount_input.value())),
            "payment_date": self.payment_date_input.date().toString("yyyy-MM-dd"),
        }


class DebtSummaryCard(QFrame):
    """Compact summary card for a debt metric."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)

        self.setObjectName("summaryCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("summaryTitle")

        self.value_label = QLabel("—")
        self.value_label.setObjectName("summaryValue")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class DebtPage(QWidget):
    """Display and manage active and inactive debts."""

    debts_changed = Signal()

    HEADERS: ClassVar[list[str]] = [
        "Debt",
        "Outstanding",
        "Original",
        "Monthly payment",
        "Due day",
        "Progress",
        "Last payment",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.all_debts: list[dict] = []
        self.debts: list[dict] = []

        self._build_ui()
        self.refresh_debts()

    @staticmethod
    def _create_filter_button(
        text: str,
        active: bool,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(active)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setObjectName("filterButton")
        return button

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(16)

        heading_layout = QHBoxLayout()
        heading_container = QVBoxLayout()
        heading_container.setSpacing(5)

        heading = QLabel("Debt Management")
        heading.setObjectName("pageHeading")

        description = QLabel(
            "Track outstanding balances and manage your scheduled repayments."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)

        heading_container.addWidget(heading)
        heading_container.addWidget(description)

        heading_layout.addLayout(heading_container)
        heading_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_debts)

        heading_layout.addWidget(self.refresh_button)
        main_layout.addLayout(heading_layout)

        summary_layout = QGridLayout()
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(12)

        self.outstanding_card = DebtSummaryCard("Total outstanding")
        self.original_card = DebtSummaryCard("Original debt")
        self.paid_down_card = DebtSummaryCard("Paid down")
        self.count_card = DebtSummaryCard("Active debts")

        summary_layout.addWidget(self.outstanding_card, 0, 0)
        summary_layout.addWidget(self.original_card, 0, 1)
        summary_layout.addWidget(self.paid_down_card, 0, 2)
        summary_layout.addWidget(self.count_card, 0, 3)

        for column in range(4):
            summary_layout.setColumnStretch(column, 1)

        main_layout.addLayout(summary_layout)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.add_button = QPushButton("Add debt")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_debt)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.clicked.connect(self.edit_debt)
        self.edit_button.setEnabled(False)

        self.payment_button = QPushButton("Record payment")
        self.payment_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.payment_button.clicked.connect(self.record_payment)
        self.payment_button.setEnabled(False)

        self.status_button = QPushButton("Deactivate")
        self.status_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_button.clicked.connect(self.toggle_debt_status)
        self.status_button.setEnabled(False)

        self.active_filter_button = self._create_filter_button(
            "Active",
            True,
        )
        self.inactive_filter_button = self._create_filter_button(
            "Inactive",
            False,
        )

        self.active_filter_button.clicked.connect(lambda: self._set_filter(True))
        self.inactive_filter_button.clicked.connect(lambda: self._set_filter(False))

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        filter_layout.addWidget(self.active_filter_button)
        filter_layout.addWidget(self.inactive_filter_button)

        action_layout.addWidget(self.add_button)
        action_layout.addWidget(self.edit_button)
        action_layout.addWidget(self.payment_button)
        action_layout.addWidget(self.status_button)
        action_layout.addStretch()
        action_layout.addLayout(filter_layout)

        main_layout.addLayout(action_layout)

        self.debt_table = QTableWidget(0, len(self.HEADERS))
        self.debt_table.setHorizontalHeaderLabels(self.HEADERS)
        self.debt_table.setObjectName("cashflowTable")

        self.debt_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.debt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.debt_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.debt_table.setAlternatingRowColors(True)
        self.debt_table.setShowGrid(True)
        self.debt_table.verticalHeader().setVisible(False)
        self.debt_table.verticalHeader().setDefaultSectionSize(42)

        header = self.debt_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        for column in range(1, len(self.HEADERS)):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        self.debt_table.setMinimumHeight(300)
        self.debt_table.itemSelectionChanged.connect(self._update_action_buttons)

        main_layout.addWidget(self.debt_table, 1)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("secondaryText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        main_layout.addWidget(self.empty_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondaryText")
        main_layout.addWidget(self.status_label)

        note = QLabel(
            "Debt interest is not currently modelled. Paid down is calculated "
            "from original balance minus current balance. Payment history is "
            "not retained; only the latest payment date is stored."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        main_layout.addWidget(note)

    def _set_filter(self, show_active: bool) -> None:
        self.active_filter_button.setChecked(show_active)
        self.inactive_filter_button.setChecked(not show_active)
        self._apply_filter()

    def refresh_debts(self) -> None:
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")

        try:
            self.all_debts = get_debts(include_inactive=True)
            self._update_summary()
            self._apply_filter()

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.status_label.setText("Unable to load debts.")

            QMessageBox.critical(
                self,
                "Debt management error",
                f"Could not load debts:\n\n{exc}",
            )

        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")

    def _update_summary(self) -> None:
        active_debts = [debt for debt in self.all_debts if debt["active"]]

        outstanding = sum(int(debt["balance_pence"]) for debt in active_debts)

        original = sum(int(debt["original_balance_pence"]) for debt in active_debts)

        paid_down = max(original - outstanding, 0)

        self.outstanding_card.set_value(format_money(outstanding))
        self.original_card.set_value(format_money(original))
        self.paid_down_card.set_value(format_money(paid_down))
        self.count_card.set_value(str(len(active_debts)))

    def _apply_filter(self) -> None:
        show_active = self.active_filter_button.isChecked()

        self.debts = [
            debt for debt in self.all_debts if bool(debt["active"]) == show_active
        ]

        self._populate_table()

        status = "active" if show_active else "inactive"
        count = len(self.debts)

        self.status_label.setText(f"{count} {status} debt{'s' if count != 1 else ''}")

    def _populate_table(self) -> None:
        self.debt_table.setRowCount(len(self.debts))

        for row_index, debt in enumerate(self.debts):
            due_day = (
                f"Day {debt['due_day']}"
                if debt["due_day"] is not None
                else "Not specified"
            )

            payment_date = debt["last_payment_date"]

            if payment_date:
                payment_date = date.fromisoformat(payment_date).strftime("%d %b %Y")
            else:
                payment_date = "—"

            values = [
                debt["name"],
                format_money(debt["balance_pence"]),
                format_money(debt["original_balance_pence"]),
                format_money(debt["monthly_payment_pence"]),
                due_day,
                "",
                payment_date,
            ]

            for column, value in enumerate(values):
                if column == 5:
                    continue

                item = QTableWidgetItem(value)

                if column in (1, 2, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )

                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        debt["id"],
                    )

                self.debt_table.setItem(
                    row_index,
                    column,
                    item,
                )

            original = int(debt["original_balance_pence"])
            balance = int(debt["balance_pence"])

            progress = (
                round((original - balance) / original * 100) if original > 0 else 0
            )

            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(max(0, min(progress, 100)))
            progress_bar.setFormat("%p%")
            progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            progress_bar.setTextVisible(True)
            progress_bar.setObjectName("debtProgress")

            self.debt_table.setCellWidget(
                row_index,
                5,
                progress_bar,
            )

        show_active = self.active_filter_button.isChecked()

        if self.debts:
            self.empty_label.hide()
            self.debt_table.show()
        else:
            self.debt_table.hide()
            self.empty_label.setText(
                "No active debts." if show_active else "No inactive debts."
            )
            self.empty_label.show()

        self.debt_table.clearSelection()
        self._update_action_buttons()

    def _selected_debt(self) -> dict | None:
        row = self.debt_table.currentRow()

        if row < 0:
            return None

        item = self.debt_table.item(row, 0)

        if item is None:
            return None

        debt_id = item.data(Qt.ItemDataRole.UserRole)

        return next(
            (debt for debt in self.debts if debt["id"] == debt_id),
            None,
        )

    def _update_action_buttons(self) -> None:
        debt = self._selected_debt()
        has_selection = debt is not None

        self.edit_button.setEnabled(has_selection)
        self.status_button.setEnabled(has_selection)

        self.payment_button.setEnabled(
            has_selection and bool(debt["active"]) and int(debt["balance_pence"]) > 0
        )

        if debt is not None and debt["active"]:
            self.status_button.setText("Deactivate")
        else:
            self.status_button.setText("Reactivate")

    def add_debt(self) -> None:
        dialog = DebtDialog(parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            add_debt(**dialog.get_values())
            self.refresh_debts()
            self.status_label.setText("Debt added successfully.")
            self.debts_changed.emit()

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
                "Could not add debt",
                f"The debt could not be added:\n\n{exc}",
            )

    def edit_debt(self) -> None:
        debt = self._selected_debt()

        if debt is None:
            return

        dialog = DebtDialog(debt=debt, parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            updated = update_debt(
                debt["id"],
                **dialog.get_values(),
            )

            if not updated:
                QMessageBox.warning(
                    self,
                    "Debt not found",
                    "This debt no longer exists. Refresh the list.",
                )
                self.refresh_debts()
                return

            self.refresh_debts()
            self.status_label.setText("Debt updated successfully.")
            self.debts_changed.emit()

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
                "Could not update debt",
                f"The debt could not be updated:\n\n{exc}",
            )

    def record_payment(self) -> None:
        debt = self._selected_debt()

        if debt is None or not debt["active"] or debt["balance_pence"] <= 0:
            return

        dialog = DebtPaymentDialog(debt, parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            values = dialog.get_values()

            recorded = record_debt_payment(
                debt["id"],
                amount=values["amount"],
                payment_date=values["payment_date"],
            )

            if not recorded:
                QMessageBox.warning(
                    self,
                    "Debt not found",
                    "This debt no longer exists. Refresh the list.",
                )
                self.refresh_debts()
                return

            self.refresh_debts()
            self.status_label.setText("Debt payment recorded successfully.")
            self.debts_changed.emit()

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
                "Could not record payment",
                f"The payment could not be recorded:\n\n{exc}",
            )

    def toggle_debt_status(self) -> None:
        debt = self._selected_debt()

        if debt is None:
            return

        is_active = bool(debt["active"])
        action = "deactivate" if is_active else "reactivate"
        action_past = "deactivated" if is_active else "reactivated"

        message = f"Are you sure you want to {action} '{debt['name']}'?\n\n" + (
            "It will no longer be included in future cashflow "
            "projections. You can reactivate it later."
            if is_active
            else "It will be included in future cashflow projections again."
        )

        answer = QMessageBox.question(
            self,
            f"{action.title()} debt",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            updated = (
                deactivate_debt(debt["id"])
                if is_active
                else reactivate_debt(debt["id"])
            )

            if not updated:
                QMessageBox.warning(
                    self,
                    "Debt not found",
                    "This debt no longer exists. Refresh the list.",
                )
                self.refresh_debts()
                return

            self.refresh_debts()
            self.status_label.setText(f"Debt {action_past} successfully.")
            self.debts_changed.emit()

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
                f"Could not {action} debt",
                f"The debt could not be {action}d:\n\n{exc}",
            )
