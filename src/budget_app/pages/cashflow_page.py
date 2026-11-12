"""Cashflow projection page."""

from datetime import date
from typing import ClassVar

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.balance_service import (
    add_actual_transaction,
    delete_actual_transaction,
    delete_recorded_transaction,
    get_actual_transactions,
    get_linkable_income_records,
    link_confirmed_income_to_payslip,
    update_actual_transaction,
    update_recorded_transaction,
)
from budget_app.services.cashflow_service import (
    forecast_entry_key,
    generate_cashflow_projection,
)
from budget_app.services.debt_service import record_debt_payment
from budget_app.services.savings_goal_service import record_savings_transaction
from budget_app.utils.money import format_money
from budget_app.utils.table import configure_table_header


class SummaryCard(QFrame):
    """A card displaying one cashflow summary metric."""

    def __init__(
        self,
        title: str,
        value: str = "£0.00",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setObjectName("summaryCard")
        self.setMinimumHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("summaryTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("summaryValue")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch()

    def set_value(self, value: str, negative: bool = False) -> None:
        """Update the displayed value and its colour."""

        self.value_label.setText(value)

        if negative:
            self.value_label.setStyleSheet("color: #f87171;")
        else:
            self.value_label.setStyleSheet("")


class CashflowPage(QWidget):
    """Display a rolling cashflow projection and transaction ledger."""

    HEADERS: ClassVar[list[str]] = [
        "Date",
        "Description",
        "Money In",
        "Money Out",
        "Running Balance",
    ]

    TYPE_LABELS: ClassVar[dict[str, str]] = {
        "regular_income": "Regular income",
        "bonus": "Expected bonus",
        "fixed_expense": "Fixed expense",
        "debt_repayment": "Debt repayment",
        "variable_expense": "Variable budget",
    }

    TYPE_COLOURS: ClassVar[dict[str, str]] = {
        "regular_income": "#86efac",
        "bonus": "#86efac",
        "fixed_expense": "#fca5a5",
        "debt_repayment": "#fca5a5",
        "variable_expense": "#fcd34d",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.projection: dict | None = None

        self._build_ui()
        self.refresh_projection()

    def _build_ui(self) -> None:
        """Create the cashflow page layout."""

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(20)

        # Page heading and refresh action.
        heading_layout = QHBoxLayout()

        heading_container = QVBoxLayout()
        heading_container.setSpacing(5)

        heading = QLabel("Cashflow")
        heading.setObjectName("pageHeading")

        self.date_range_label = QLabel("Loading projection...")
        self.date_range_label.setObjectName("secondaryText")

        heading_container.addWidget(heading)
        heading_container.addWidget(self.date_range_label)

        heading_layout.addLayout(heading_container)
        heading_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_projection)

        heading_layout.addWidget(self.refresh_button)

        main_layout.addLayout(heading_layout)

        # Summary cards.
        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(14)

        self.current_balance_card = SummaryCard("Current balance")
        self.projected_balance_card = SummaryCard(
            "Projected balance at end of forecast"
        )
        self.income_card = SummaryCard("Projected income")
        self.outgoings_card = SummaryCard("Projected outgoings")

        summary_layout.addWidget(self.current_balance_card)
        summary_layout.addWidget(self.projected_balance_card)
        summary_layout.addWidget(self.income_card)
        summary_layout.addWidget(self.outgoings_card)

        main_layout.addLayout(summary_layout)

        self.payroll_summary_label = QLabel("")
        self.payroll_summary_label.setObjectName("secondaryText")
        self.payroll_summary_label.setWordWrap(True)
        main_layout.addWidget(self.payroll_summary_label)

        actual_heading = QHBoxLayout()
        actual_heading.addWidget(QLabel("Recorded actual spending and confirmations"))
        actual_heading.addStretch()
        self.add_actual_button = QPushButton("Record transaction")
        self.add_actual_button.clicked.connect(self.add_actual_spending)
        actual_heading.addWidget(self.add_actual_button)
        self.edit_actual_button = QPushButton("Edit selected")
        self.edit_actual_button.clicked.connect(self.edit_actual_spending)
        actual_heading.addWidget(self.edit_actual_button)
        self.delete_actual_button = QPushButton("Delete selected")
        self.delete_actual_button.clicked.connect(self.delete_actual_spending)
        actual_heading.addWidget(self.delete_actual_button)
        self.link_income_button = QPushButton("Link payslip")
        self.link_income_button.clicked.connect(self.link_income_to_payslip)
        actual_heading.addWidget(self.link_income_button)
        main_layout.addLayout(actual_heading)

        self.actual_table = QTableWidget(0, 4)
        self.actual_table.setHorizontalHeaderLabels(
            ["Date", "Type", "Description", "Amount"]
        )
        self.actual_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.actual_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.actual_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.actual_table.verticalHeader().setVisible(False)
        actual_header = self.actual_table.horizontalHeader()
        configure_table_header(actual_header)
        actual_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        actual_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        actual_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        actual_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.actual_table.setMaximumHeight(190)
        self.actual_table.itemSelectionChanged.connect(self._update_actual_actions)
        main_layout.addWidget(self.actual_table)

        # Ledger heading.
        ledger_heading = QLabel("Projected transactions")
        ledger_heading.setObjectName("sectionHeading")
        ledger_heading_row = QHBoxLayout()
        ledger_heading_row.addWidget(ledger_heading)
        ledger_heading_row.addStretch()
        self.confirm_forecast_button = QPushButton("Confirm selected transaction")
        self.confirm_forecast_button.clicked.connect(self.confirm_forecast_transaction)
        ledger_heading_row.addWidget(self.confirm_forecast_button)
        main_layout.addLayout(ledger_heading_row)

        # Transaction table.
        self.transaction_table = QTableWidget(0, len(self.HEADERS))
        self.transaction_table.setHorizontalHeaderLabels(self.HEADERS)
        self.transaction_table.setObjectName("cashflowTable")

        self.transaction_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.transaction_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.transaction_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.transaction_table.setAlternatingRowColors(True)
        self.transaction_table.setShowGrid(True)
        self.transaction_table.verticalHeader().setVisible(False)

        header = self.transaction_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
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
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        self.transaction_table.setMinimumHeight(300)
        self.transaction_table.itemSelectionChanged.connect(
            self._update_forecast_actions
        )

        main_layout.addWidget(self.transaction_table, 1)

        # Status message.
        self.status_label = QLabel("")
        self.status_label.setObjectName("secondaryText")
        main_layout.addWidget(self.status_label)

    def refresh_projection(self) -> None:
        """Generate a fresh projection and update the page."""

        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")

        try:
            self.projection = generate_cashflow_projection()
            self._update_summary()
            self._update_payroll_summary()
            self._populate_table()
            self._populate_actual_transactions()

            self.status_label.setText(
                f"Last updated: {date.today().strftime('%d/%m/%Y')}"
            )

        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            self.projection = None
            self.transaction_table.setRowCount(0)
            self.current_balance_card.set_value("£0.00")
            self.projected_balance_card.title_label.setText(
                "Projected balance at end of forecast"
            )
            self.projected_balance_card.set_value("£0.00")
            self.income_card.set_value("£0.00")
            self.outgoings_card.set_value("£0.00")
            self.payroll_summary_label.clear()

            self.date_range_label.setText("Projection unavailable")
            self.status_label.setText("Unable to generate cashflow projection.")

            QMessageBox.critical(
                self,
                "Cashflow projection error",
                f"Could not generate the cashflow projection:\n\n{exc}",
            )

        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")

    def _update_summary(self) -> None:
        """Update the summary cards from the current projection."""

        if self.projection is None:
            return

        start_date = self.projection["start_date"]
        end_date = self.projection["end_date"]

        self.date_range_label.setText(
            f"{start_date:%d/%m/%Y} – {end_date:%d/%m/%Y}"
            f"  ·  {self.projection['projection_months']} months"
        )

        opening_balance = self.projection["opening_balance_pence"]
        closing_balance = self.projection["closing_balance_pence"]
        total_income = self.projection["total_income_pence"]
        total_outgoings = self.projection["total_outgoings_pence"]

        self.current_balance_card.title_label.setText(
            f"Current balance · as of {date.today():%d/%m/%Y}"
        )
        self.current_balance_card.set_value(
            format_money(opening_balance),
            negative=opening_balance < 0,
        )

        self.projected_balance_card.title_label.setText(
            f"Projected balance · {end_date:%d/%m/%Y}"
        )
        self.projected_balance_card.set_value(
            format_money(closing_balance),
            negative=closing_balance < 0,
        )

        self.income_card.set_value(format_money(total_income))
        self.outgoings_card.set_value(format_money(total_outgoings))

    def _update_payroll_summary(self) -> None:
        """Explain the projected-pay calculation and show its deductions."""

        if self.projection is None:
            return

        forecast = self.projection.get("income_forecast", {})
        breakdown = forecast.get("payroll_breakdown")
        if not breakdown:
            self.payroll_summary_label.setText(
                "Regular take-home pay uses saved payroll settings."
            )
            return

        details = [
            (
                f"{breakdown['tax_year']} settings-based estimate per pay period: "
                f"gross {format_money(breakdown['gross_pay_pence'])}, "
                f"PAYE {format_money(breakdown['tax_pence'])}, "
                f"NI {format_money(breakdown['ni_pence'])}, "
                f"pension {format_money(breakdown['pension_pence'])}, "
                f"student loan {format_money(breakdown['student_loan_pence'])}, "
                f"take-home {format_money(breakdown['net_pay_pence'])}."
            ),
        ]
        history_average = forecast.get("historical_regular_pay_average_pence")
        payslips_used = forecast.get("historical_payslips_used", 0)
        if history_average is not None:
            details.append(
                f"Recent payslips ({payslips_used}) average "
                f"{format_money(history_average)} and are shown for comparison; "
                "the forecast uses the settings-based estimate."
            )
        details.append(breakdown["assumptions"])
        self.payroll_summary_label.setText(" ".join(details))

    def _populate_table(self) -> None:
        """Populate the transaction ledger."""

        if self.projection is None:
            return

        entries = self.projection["entries"]

        # Include the opening balance as the first ledger row.
        rows = [
            {
                "date": self.projection["start_date"],
                "type": "starting_balance",
                "description": "Starting Balance",
                "money_in_pence": 0,
                "money_out_pence": 0,
                "running_balance_pence": self.projection["opening_balance_pence"],
            }
        ]

        rows.extend(entries)

        self.transaction_table.setRowCount(len(rows))

        for row_index, entry in enumerate(rows):
            entry_date = entry["date"]

            if isinstance(entry_date, str):
                entry_date = date.fromisoformat(entry_date)

            description = entry["description"]

            if entry["type"] != "starting_balance":
                type_label = self.TYPE_LABELS.get(entry["type"])

                if type_label:
                    description = f"{description} · {type_label}"

            values = [
                entry_date.strftime("%d/%m/%Y"),
                description,
                format_money(entry["money_in_pence"]),
                format_money(entry["money_out_pence"]),
                format_money(entry["running_balance_pence"]),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)

                if column >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )

                if column == 1:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )

                self.transaction_table.setItem(
                    row_index,
                    column,
                    item,
                )

            self.transaction_table.item(row_index, 1).setData(
                Qt.ItemDataRole.UserRole, entry
            )

            # Colour-code the transaction description by type.
            transaction_type = entry["type"]
            colour = self.TYPE_COLOURS.get(transaction_type)

            if colour:
                self.transaction_table.item(
                    row_index,
                    1,
                ).setForeground(QColor(colour))

            # Highlight negative running balances.
            running_balance_negative = entry["running_balance_pence"] < 0

            if running_balance_negative:
                self.transaction_table.item(
                    row_index,
                    4,
                ).setForeground(QColor("#f87171"))

            # Make the starting balance visually distinct.
            if transaction_type == "starting_balance":
                for column in range(len(self.HEADERS)):
                    item = self.transaction_table.item(row_index, column)
                    item.setBackground(QColor("#30343d"))

                    if column == 4 and running_balance_negative:
                        continue

                    item.setForeground(QColor("#ffffff"))

        self.transaction_table.resizeRowsToContents()
        self._update_forecast_actions()

    def _update_forecast_actions(self) -> None:
        row = self.transaction_table.currentRow()
        entry = (
            self.transaction_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if row >= 0
            else None
        )
        self.confirm_forecast_button.setEnabled(
            bool(entry and entry.get("type") != "starting_balance")
        )

    def confirm_forecast_transaction(self) -> None:
        """Record a forecast row at its actual date and amount."""
        row = self.transaction_table.currentRow()
        if row < 0:
            return
        entry = self.transaction_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        if not entry or entry.get("type") == "starting_balance":
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Confirm completed transaction")
        form = QFormLayout(dialog)
        amount = QDoubleSpinBox()
        amount.setRange(0.01, 999999999.99)
        amount.setDecimals(2)
        amount.setPrefix("£")
        amount.setValue(abs(int(entry["amount_pence"])) / 100)
        transaction_date = QDateEdit()
        transaction_date.setCalendarPopup(True)
        transaction_date.setDisplayFormat("dd MMM yyyy")
        transaction_date.setDate(QDate.currentDate())
        transaction_date.setMaximumDate(QDate.currentDate())
        form.addRow("Actual amount", amount)
        form.addRow("Actual date", transaction_date)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        actual_amount = amount.value()
        actual_amount = (
            actual_amount if int(entry["amount_pence"]) > 0 else -actual_amount
        )
        actual_date = transaction_date.date().toString("yyyy-MM-dd")
        try:
            if entry["type"] == "debt_repayment":
                recorded = record_debt_payment(
                    entry["source_id"],
                    abs(actual_amount),
                    actual_date,
                    forecast_key=forecast_entry_key(entry),
                )
                if not recorded:
                    raise ValueError("The related debt no longer exists.")
            elif entry["type"] == "savings_contribution":
                recorded = record_savings_transaction(
                    entry["source_id"],
                    "deposit",
                    abs(actual_amount),
                    actual_date,
                    forecast_key=forecast_entry_key(entry),
                )
                if not recorded:
                    raise ValueError("The related savings goal no longer exists.")
            else:
                add_actual_transaction(
                    entry["description"],
                    actual_amount,
                    actual_date,
                    transaction_type=entry["type"],
                    forecast_key=forecast_entry_key(entry),
                )
            self.refresh_projection()
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not confirm transaction", str(exc))

    def _populate_actual_transactions(self) -> None:
        """Show manually recorded actual spending."""
        records = get_actual_transactions()
        self.actual_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                date.fromisoformat(record["transaction_date"]).strftime("%d/%m/%Y"),
                (
                    "Regular income · payslip linked"
                    if record.get("linked_income_id") is not None
                    else record["transaction_type"].replace("_", " ").title()
                ),
                record["description"],
                format_money(abs(record["amount_pence"])),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self.actual_table.setItem(row, column, item)
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, record["id"]
            )
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole + 1, record["transaction_date"]
            )
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole + 2, record["amount"]
            )
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole + 3, record["source_kind"]
            )
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole + 4, record["transaction_type"]
            )
            self.actual_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole + 5, record.get("linked_income_id")
            )
        self._update_actual_actions()

    def _update_actual_actions(self) -> None:
        row = self.actual_table.currentRow()
        selected = row >= 0
        source_kind = (
            self.actual_table.item(row, 0).data(Qt.ItemDataRole.UserRole + 3)
            if selected
            else None
        )
        self.edit_actual_button.setEnabled(selected and source_kind != "income")
        self.edit_actual_button.setToolTip(
            "Edit income using the Income page so payslip amounts stay consistent."
            if source_kind == "income"
            else "Edit the selected recorded transaction."
        )
        self.delete_actual_button.setEnabled(selected)
        linkable = False
        if selected:
            item = self.actual_table.item(row, 0)
            linkable = (
                item.data(Qt.ItemDataRole.UserRole + 3) == "manual"
                and item.data(Qt.ItemDataRole.UserRole + 4) == "regular_income"
                and item.data(Qt.ItemDataRole.UserRole + 5) is None
            )
        self.link_income_button.setEnabled(linkable)

    def link_income_to_payslip(self) -> None:
        """Link an early bank receipt to its contractual-date payslip."""
        row = self.actual_table.currentRow()
        if row < 0:
            return
        transaction_id = self.actual_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        try:
            income_records = get_linkable_income_records(transaction_id)
            if not income_records:
                QMessageBox.information(
                    self,
                    "No matching payslips",
                    "There are no unlinked payslips dated within a week after "
                    "this confirmed pay date.",
                )
                return
            labels = [
                f"{date.fromisoformat(record['pay_date']):%d/%m/%Y} · "
                f"{format_money(record['net_pay_pence'])} · ID {record['id']}"
                for record in income_records
            ]
            selected, accepted = QInputDialog.getItem(
                self,
                "Link confirmed income",
                "Choose the payslip for this bank receipt:",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            income_id = income_records[labels.index(selected)]["id"]
            if not link_confirmed_income_to_payslip(transaction_id, income_id):
                raise ValueError("The selected income record could not be linked.")
            self.refresh_projection()
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not link payslip", str(exc))

    def _actual_spending_dialog(self, record: dict | None = None) -> dict | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            "Edit recorded transaction" if record else "Record actual transaction"
        )
        form = QFormLayout(dialog)
        description = QLineEdit(record["description"] if record else "")
        if record and record.get("source_kind") != "manual":
            description.setEnabled(False)
        direction = QComboBox()
        direction.addItem("Money out", -1)
        direction.addItem("Money in", 1)
        if record and int(record["amount_pence"]) > 0:
            direction.setCurrentIndex(1)
        if record and record.get("linked_income_id") is not None:
            direction.setEnabled(False)
        amount = QDoubleSpinBox()
        amount.setRange(0.01, 999999999.99)
        amount.setDecimals(2)
        amount.setPrefix("£")
        amount.setValue(float(record["amount"]) if record else 0.01)
        transaction_date = QDateEdit()
        transaction_date.setCalendarPopup(True)
        transaction_date.setDisplayFormat("dd MMM yyyy")
        transaction_date.setDate(
            QDate.fromString(record["transaction_date"], "yyyy-MM-dd")
            if record
            else QDate.currentDate()
        )
        form.addRow("Description", description)
        form.addRow("Direction", direction)
        form.addRow("Amount", amount)
        form.addRow("Date", transaction_date)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "description": description.text(),
            "amount": amount.value() * direction.currentData(),
            "transaction_date": transaction_date.date().toString("yyyy-MM-dd"),
            "transaction_type": (
                "regular_income" if direction.currentData() > 0 else "expense"
            ),
        }

    def add_actual_spending(self) -> None:
        values = self._actual_spending_dialog()
        if values is None:
            return
        try:
            add_actual_transaction(**values)
            self.refresh_projection()
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not record spending", str(exc))

    def edit_actual_spending(self) -> None:
        row = self.actual_table.currentRow()
        if row < 0:
            return
        item = self.actual_table.item(row, 0)
        record = {
            "id": item.data(Qt.ItemDataRole.UserRole),
            "source_kind": item.data(Qt.ItemDataRole.UserRole + 3),
            "linked_income_id": item.data(Qt.ItemDataRole.UserRole + 5),
            "transaction_date": item.data(Qt.ItemDataRole.UserRole + 1),
            "amount": abs(float(item.data(Qt.ItemDataRole.UserRole + 2))),
            "amount_pence": round(float(item.data(Qt.ItemDataRole.UserRole + 2)) * 100),
            "description": self.actual_table.item(row, 2).text(),
        }
        values = self._actual_spending_dialog(record)
        if values is None:
            return
        try:
            if record["source_kind"] == "manual":
                update_actual_transaction(record["id"], **values)
            else:
                update_recorded_transaction(
                    record["source_kind"],
                    record["id"],
                    values["amount"],
                    values["transaction_date"],
                )
            self.refresh_projection()
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Could not update spending", str(exc))

    def delete_actual_spending(self) -> None:
        row = self.actual_table.currentRow()
        if row < 0:
            return
        transaction_id = self.actual_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        source_kind = self.actual_table.item(row, 0).data(Qt.ItemDataRole.UserRole + 3)
        answer = QMessageBox.question(
            self,
            "Delete actual spending",
            "Delete the selected recorded transaction? This will update its "
            "income, debt or savings record where applicable.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if source_kind == "manual":
                delete_actual_transaction(transaction_id)
            else:
                delete_recorded_transaction(source_kind, transaction_id)
            self.refresh_projection()
