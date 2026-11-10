"""Cashflow projection page."""

from datetime import date
from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.cashflow_service import generate_cashflow_projection
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

        # Ledger heading.
        ledger_heading = QLabel("Projected transactions")
        ledger_heading.setObjectName("sectionHeading")

        main_layout.addWidget(ledger_heading)

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
