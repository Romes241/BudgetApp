"""Fixed expense management page."""

import sqlite3
from decimal import Decimal
from typing import ClassVar

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
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

from budget_app.services.fixed_expense_service import (
    add_fixed_expense,
    deactivate_fixed_expense,
    get_fixed_expenses,
    reactivate_fixed_expense,
    update_fixed_expense,
)
from budget_app.utils.money import format_money, to_pence
from budget_app.utils.table import configure_table_header


class FixedExpenseDialog(QDialog):
    """Dialog for creating or editing a fixed expense."""

    def __init__(
        self,
        expense: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.expense = expense

        self.setWindowTitle("Edit fixed expense" if expense else "Add fixed expense")
        self.setMinimumWidth(380)

        self._build_ui()

        if expense is not None:
            self._populate_fields()

    def _build_ui(self) -> None:
        """Build the expense form."""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Rent")

        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText("e.g. Housing")

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 999999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setSingleStep(1)
        self.amount_input.setPrefix("£")
        self.amount_input.setKeyboardTracking(False)

        self.due_day_input = QComboBox()
        self.due_day_input.addItem("Not specified", None)

        for day in range(1, 32):
            self.due_day_input.addItem(str(day), day)

        form.addRow("Name", self.name_input)
        form.addRow("Category", self.category_input)
        form.addRow("Monthly amount", self.amount_input)
        form.addRow("Due day", self.due_day_input)

        layout.addLayout(form)

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

    def _populate_fields(self) -> None:
        """Populate the form when editing an existing expense."""

        self.name_input.setText(self.expense["name"])
        self.category_input.setText(self.expense["category"])
        self.amount_input.setValue(float(self.expense["amount"]))

        due_day_index = self.due_day_input.findData(self.expense["due_day"])

        if due_day_index >= 0:
            self.due_day_input.setCurrentIndex(due_day_index)

    def _validate_and_accept(self) -> None:
        """Validate required fields before accepting the dialog."""

        if not self.name_input.text().strip():
            self.error_label.setText("Please enter an expense name.")
            self.name_input.setFocus()
            return

        if not self.category_input.text().strip():
            self.error_label.setText("Please enter an expense category.")
            self.category_input.setFocus()
            return

        self.error_label.clear()
        self.accept()

    def get_values(self) -> dict:
        """Return the values entered into the form."""

        return {
            "name": self.name_input.text().strip(),
            "category": self.category_input.text().strip(),
            "amount": Decimal(str(self.amount_input.value())),
            "due_day": self.due_day_input.currentData(),
        }


class FixedExpensesPage(QWidget):
    """Display and manage recurring fixed expenses."""

    expenses_changed = Signal()

    HEADERS: ClassVar[list[str]] = [
        "Name",
        "Category",
        "Monthly amount",
        "Due day",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.all_expenses: list[dict] = []
        self.expenses: list[dict] = []

        self._build_ui()
        self.refresh_expenses()

    @staticmethod
    def _create_filter_button(
        text: str,
        active: bool,
    ) -> QPushButton:
        """Create a checkable button for the active/inactive filter."""

        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(active)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setObjectName("filterButton")

        return button

    def _build_ui(self) -> None:
        """Create the fixed expenses page layout."""

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(20)

        # Heading and refresh action.
        heading_layout = QHBoxLayout()

        heading_container = QVBoxLayout()
        heading_container.setSpacing(5)

        heading = QLabel("Fixed Expenses")
        heading.setObjectName("pageHeading")

        description = QLabel("Manage your recurring monthly expenses.")
        description.setObjectName("secondaryText")

        heading_container.addWidget(heading)
        heading_container.addWidget(description)

        heading_layout.addLayout(heading_container)
        heading_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_expenses)

        heading_layout.addWidget(self.refresh_button)
        main_layout.addLayout(heading_layout)

        # Expense actions and active/inactive filter.
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)

        self.add_button = QPushButton("Add expense")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_expense)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.clicked.connect(self.edit_expense)
        self.edit_button.setEnabled(False)

        self.status_button = QPushButton("Deactivate")
        self.status_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_button.clicked.connect(self.toggle_expense_status)
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
        action_layout.addWidget(self.status_button)
        action_layout.addStretch()
        action_layout.addLayout(filter_layout)

        main_layout.addLayout(action_layout)

        # Expense table.
        self.expense_table = QTableWidget(0, len(self.HEADERS))
        self.expense_table.setHorizontalHeaderLabels(self.HEADERS)
        self.expense_table.setObjectName("cashflowTable")

        self.expense_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.expense_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.expense_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.expense_table.setAlternatingRowColors(True)
        self.expense_table.setShowGrid(True)
        self.expense_table.verticalHeader().setVisible(False)

        header = self.expense_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        self.expense_table.setMinimumHeight(300)
        self.expense_table.itemSelectionChanged.connect(self._update_action_buttons)

        main_layout.addWidget(self.expense_table, 1)

        # Empty state and status.
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("secondaryText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()

        main_layout.addWidget(self.empty_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondaryText")
        main_layout.addWidget(self.status_label)

    def _set_filter(self, show_active: bool) -> None:
        """Switch between active and inactive expenses."""

        self.active_filter_button.setChecked(show_active)
        self.inactive_filter_button.setChecked(not show_active)

        self._apply_filter()

    def refresh_expenses(self) -> None:
        """Retrieve all expenses and refresh the displayed list."""

        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")

        try:
            self.all_expenses = get_fixed_expenses(include_inactive=True)
            self._apply_filter()

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.status_label.setText("Unable to load fixed expenses.")

            QMessageBox.critical(
                self,
                "Fixed expenses error",
                f"Could not load fixed expenses:\n\n{exc}",
            )

        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")

    def _apply_filter(self) -> None:
        """Filter expenses according to the selected status."""

        show_active = self.active_filter_button.isChecked()

        self.expenses = [
            expense
            for expense in self.all_expenses
            if bool(expense["active"]) == show_active
        ]

        self._populate_table()

        status = "active" if show_active else "inactive"
        count = len(self.expenses)

        self.status_label.setText(
            f"{count} {status} expense{'s' if count != 1 else ''}"
        )

    def _populate_table(self) -> None:
        """Populate the table with the currently filtered expenses."""

        self.expense_table.setRowCount(len(self.expenses))

        for row_index, expense in enumerate(self.expenses):
            values = [
                expense["name"],
                expense["category"],
                format_money(to_pence(expense["amount"])),
                (
                    str(expense["due_day"])
                    if expense["due_day"] is not None
                    else "Not specified"
                ),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)

                if column == 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )

                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        expense["id"],
                    )

                self.expense_table.setItem(
                    row_index,
                    column,
                    item,
                )

        show_active = self.active_filter_button.isChecked()

        if self.expenses:
            self.empty_label.hide()
            self.expense_table.show()
        else:
            self.expense_table.hide()
            self.empty_label.setText(
                "No active fixed expenses."
                if show_active
                else "No inactive fixed expenses."
            )
            self.empty_label.show()

        self.expense_table.clearSelection()
        self._update_action_buttons()

    def _selected_expense(self) -> dict | None:
        """Return the currently selected expense, if any."""

        selected_items = self.expense_table.selectedItems()

        if not selected_items:
            return None

        current_row = self.expense_table.currentRow()

        if current_row < 0:
            return None

        first_item = self.expense_table.item(current_row, 0)

        if first_item is None:
            return None

        expense_id = first_item.data(Qt.ItemDataRole.UserRole)

        return next(
            (expense for expense in self.expenses if expense["id"] == expense_id),
            None,
        )

    def _update_action_buttons(self) -> None:
        """Update available actions based on the selected expense."""

        expense = self._selected_expense()
        has_selection = expense is not None

        self.edit_button.setEnabled(has_selection)
        self.status_button.setEnabled(has_selection)

        if expense is not None and expense["active"]:
            self.status_button.setText("Deactivate")
        else:
            self.status_button.setText("Reactivate")

    def add_expense(self) -> None:
        """Open the dialog and create a new fixed expense."""

        dialog = FixedExpenseDialog(parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            add_fixed_expense(**dialog.get_values())
            self.refresh_expenses()
            self.status_label.setText("Fixed expense added successfully.")
            self.expenses_changed.emit()

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
                "Could not add expense",
                f"The fixed expense could not be added:\n\n{exc}",
            )

    def edit_expense(self) -> None:
        """Edit the currently selected fixed expense."""

        expense = self._selected_expense()

        if expense is None:
            return

        dialog = FixedExpenseDialog(expense=expense, parent=self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            updated = update_fixed_expense(
                expense["id"],
                **dialog.get_values(),
            )

            if not updated:
                QMessageBox.warning(
                    self,
                    "Expense not found",
                    "This fixed expense no longer exists. Refresh the list.",
                )
                self.refresh_expenses()
                return

            self.refresh_expenses()
            self.status_label.setText("Fixed expense updated successfully.")
            self.expenses_changed.emit()

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
                "Could not update expense",
                f"The fixed expense could not be updated:\n\n{exc}",
            )

    def toggle_expense_status(self) -> None:
        """Deactivate or reactivate the currently selected expense."""

        expense = self._selected_expense()

        if expense is None:
            return

        is_active = bool(expense["active"])

        if is_active:
            action_past = "deactivated"
            confirmation_title = "Deactivate fixed expense"
            confirmation_message = (
                f"Are you sure you want to deactivate "
                f"'{expense['name']}'?\n\n"
                "It will no longer be included in future cashflow "
                "projections. You can reactivate it later."
            )
        else:
            action_past = "reactivated"
            confirmation_title = "Reactivate fixed expense"
            confirmation_message = (
                f"Are you sure you want to reactivate "
                f"'{expense['name']}'?\n\n"
                "It will be included in future cashflow projections again."
            )

        answer = QMessageBox.question(
            self,
            confirmation_title,
            confirmation_message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            if is_active:
                updated = deactivate_fixed_expense(expense["id"])
            else:
                updated = reactivate_fixed_expense(expense["id"])

            if not updated:
                QMessageBox.warning(
                    self,
                    "Expense not found",
                    "This fixed expense no longer exists. Refresh the list.",
                )
                self.refresh_expenses()
                return

            self.refresh_expenses()
            self.status_label.setText(f"Fixed expense {action_past} successfully.")
            self.expenses_changed.emit()

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
                f"Could not {action_past} expense",
                f"The fixed expense could not be {action_past}:\n\n{exc}",
            )
