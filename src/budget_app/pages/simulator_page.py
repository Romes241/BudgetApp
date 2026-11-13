"""Temporary what-if adjustments to the current cashflow projection."""

import sqlite3
from typing import Any, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.cashflow_service import generate_cashflow_projection
from budget_app.services.payroll_service import calculate_take_home_pay
from budget_app.services.scenario_service import calculate_scenario
from budget_app.services.settings_service import get_settings
from budget_app.utils.money import format_money
from budget_app.utils.table import configure_table_header
from budget_app.utils.widget_sizing import configure_form_controls


class _BalanceCard(QFrame):
    """A compact summary card for a projected balance."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("summaryCard")
        self.setMinimumHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(7)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("summaryTitle")
        self.value_label = QLabel("£0.00")
        self.value_label.setObjectName("summaryValue")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, amount_pence: int, *, negative: bool = False) -> None:
        self.value_label.setText(format_money(amount_pence))
        self.value_label.setStyleSheet("color: #f87171;" if negative else "")


class SimulatorPage(QWidget):
    """Compare a temporary scenario with the saved cashflow projection."""

    HEADERS: ClassVar[list[str]] = [
        "Month",
        "Baseline net",
        "Scenario net",
        "Baseline balance",
        "Scenario balance",
        "Change",
    ]
    ADJUSTMENTS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        (
            "expenses",
            "Additional monthly spending",
            "Add a hypothetical recurring expense or increase existing spending.",
        ),
        (
            "debt",
            "Additional monthly debt payment",
            "Add a hypothetical recurring debt repayment.",
        ),
        (
            "savings",
            "Additional monthly savings contribution",
            "Add a hypothetical recurring savings contribution.",
        ),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.baseline_projection: dict[str, Any] | None = None
        self.baseline_settings: dict[str, Any] | None = None
        self.baseline_payroll: dict[str, Any] | None = None
        self.scenario: dict[str, Any] | None = None
        self.adjustment_inputs: dict[str, QDoubleSpinBox] = {}
        self._loading_pay_inputs = False
        self._pay_assumptions_modified = False
        self._build_ui()
        configure_form_controls(self)
        self.refresh_projection()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        heading_text.setSpacing(5)
        title = QLabel("What-if simulator")
        title.setObjectName("pageHeading")
        self.date_range_label = QLabel("Loading current cashflow projection...")
        self.date_range_label.setObjectName("secondaryText")
        heading_text.addWidget(title)
        heading_text.addWidget(self.date_range_label)
        heading.addLayout(heading_text, 1)
        self.refresh_button = QPushButton("Refresh baseline")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh_projection)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)

        description = QLabel(
            "Explore temporary monthly changes against your current cashflow forecast. "
            "These adjustments are not saved."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)
        layout.addWidget(description)

        payroll_frame = QFrame()
        payroll_frame.setObjectName("summaryCard")
        payroll_layout = QVBoxLayout(payroll_frame)
        payroll_layout.setContentsMargins(16, 14, 16, 16)
        payroll_layout.setSpacing(10)
        payroll_heading = QLabel("Hypothetical pay assumptions")
        payroll_heading.setObjectName("sectionHeading")
        payroll_layout.addWidget(payroll_heading)
        payroll_form = QFormLayout()
        payroll_form.setHorizontalSpacing(18)
        payroll_form.setVerticalSpacing(10)

        self.hourly_wage_input = QDoubleSpinBox()
        self.hourly_wage_input.setRange(0, 100_000)
        self.hourly_wage_input.setDecimals(2)
        self.hourly_wage_input.setPrefix("£ ")
        self.hourly_wage_input.setSuffix(" / hour")
        self.average_hours_input = QDoubleSpinBox()
        self.average_hours_input.setRange(0, 168)
        self.average_hours_input.setDecimals(2)
        self.average_hours_input.setSuffix(" hours / week")
        self.tax_code_input = QLineEdit()
        self.tax_code_input.setMaxLength(20)
        self.ni_category_input = QLineEdit()
        self.ni_category_input.setMaxLength(3)
        self.pension_percent_input = QDoubleSpinBox()
        self.pension_percent_input.setRange(0, 100)
        self.pension_percent_input.setDecimals(2)
        self.pension_percent_input.setSuffix("%")
        self.student_loan_plan_input = QComboBox()
        self.student_loan_plan_input.setEditable(True)
        self.student_loan_plan_input.addItems(
            ["None", "Plan 1", "Plan 2", "Plan 4", "Plan 5", "Postgraduate"]
        )
        self.scottish_taxpayer_input = QCheckBox("Scottish taxpayer")

        payroll_form.addRow("Hourly rate", self.hourly_wage_input)
        payroll_form.addRow("Average weekly hours", self.average_hours_input)
        payroll_form.addRow("Tax code", self.tax_code_input)
        payroll_form.addRow("National Insurance category", self.ni_category_input)
        payroll_form.addRow("Pension contribution", self.pension_percent_input)
        payroll_form.addRow("Student loan plan", self.student_loan_plan_input)
        payroll_form.addRow("Tax region", self.scottish_taxpayer_input)
        payroll_layout.addLayout(payroll_form)
        self.pay_frequency_note = QLabel("")
        self.pay_frequency_note.setObjectName("secondaryText")
        self.pay_frequency_note.setWordWrap(True)
        payroll_layout.addWidget(self.pay_frequency_note)
        self.pay_estimate_label = QLabel("")
        self.pay_estimate_label.setObjectName("secondaryText")
        self.pay_estimate_label.setWordWrap(True)
        payroll_layout.addWidget(self.pay_estimate_label)
        self.pay_error_label = QLabel("")
        self.pay_error_label.setObjectName("errorText")
        self.pay_error_label.setWordWrap(True)
        payroll_layout.addWidget(self.pay_error_label)
        for control in (
            self.hourly_wage_input,
            self.average_hours_input,
            self.pension_percent_input,
        ):
            control.valueChanged.connect(self._pay_assumption_changed)
        self.tax_code_input.textChanged.connect(self._pay_assumption_changed)
        self.ni_category_input.textChanged.connect(self._pay_assumption_changed)
        self.student_loan_plan_input.currentTextChanged.connect(
            self._pay_assumption_changed
        )
        self.scottish_taxpayer_input.toggled.connect(self._pay_assumption_changed)
        layout.addWidget(payroll_frame)

        adjustment_frame = QFrame()
        adjustment_frame.setObjectName("summaryCard")
        adjustment_layout = QVBoxLayout(adjustment_frame)
        adjustment_layout.setContentsMargins(16, 14, 16, 16)
        adjustment_layout.setSpacing(10)
        adjustment_heading = QLabel("Monthly scenario changes")
        adjustment_heading.setObjectName("sectionHeading")
        adjustment_layout.addWidget(adjustment_heading)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        for key, label_text, tooltip in self.ADJUSTMENTS:
            amount = QDoubleSpinBox()
            amount.setRange(0, 1_000_000)
            amount.setDecimals(2)
            amount.setSingleStep(25)
            amount.setPrefix("£ ")
            amount.setSuffix(" / month")
            amount.setToolTip(tooltip)
            amount.valueChanged.connect(self._update_scenario)
            self.adjustment_inputs[key] = amount
            label = QLabel(label_text)
            label.setToolTip(tooltip)
            form.addRow(label, amount)
        adjustment_layout.addLayout(form)
        explanation = QLabel(
            "These are extra hypothetical outgoings, added once per calendar month "
            "including partial months. They do not change your saved expenses, debts "
            "or savings goals."
        )
        explanation.setObjectName("secondaryText")
        explanation.setWordWrap(True)
        adjustment_layout.addWidget(explanation)
        controls = QHBoxLayout()
        self.reset_button = QPushButton("Reset scenario")
        self.reset_button.setObjectName("filterButton")
        self.reset_button.clicked.connect(self.reset_scenario)
        controls.addWidget(self.reset_button)
        controls.addStretch()
        adjustment_layout.addLayout(controls)
        layout.addWidget(adjustment_frame)

        summary = QHBoxLayout()
        summary.setSpacing(14)
        self.baseline_card = _BalanceCard("Baseline balance at end of forecast")
        self.scenario_card = _BalanceCard("Scenario balance at end of forecast")
        self.change_card = _BalanceCard("Change from baseline")
        summary.addWidget(self.baseline_card)
        summary.addWidget(self.scenario_card)
        summary.addWidget(self.change_card)
        layout.addLayout(summary)

        self.result_note = QLabel(
            "A positive monthly net is a surplus; a negative net is a shortfall. "
            "Balances show the position at each month end."
        )
        self.result_note.setObjectName("secondaryText")
        self.result_note.setWordWrap(True)
        layout.addWidget(self.result_note)

        self.monthly_table = QTableWidget(0, len(self.HEADERS))
        self.monthly_table.setObjectName("cashflowTable")
        self.monthly_table.setHorizontalHeaderLabels(self.HEADERS)
        self.monthly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.monthly_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.monthly_table.verticalHeader().setVisible(False)
        self.monthly_table.setAlternatingRowColors(True)
        self.monthly_table.setMinimumHeight(300)
        header = self.monthly_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.monthly_table)
        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def refresh_projection(self, reset_inputs: bool = False) -> None:
        """Reload the saved baseline without changing scenario inputs."""
        self.refresh_button.setEnabled(False)
        try:
            self.baseline_settings = get_settings()
            self.baseline_projection = generate_cashflow_projection()
            self.baseline_payroll = self.baseline_projection.get(
                "income_forecast", {}
            ).get("payroll_breakdown")
            if not self._pay_assumptions_modified or reset_inputs:
                self._load_pay_assumptions(self.baseline_settings)
            self.date_range_label.setText(
                f"{self.baseline_projection['start_date']:%d/%m/%Y} – "
                f"{self.baseline_projection['end_date']:%d/%m/%Y}  ·  "
                f"{self.baseline_projection['projection_months']} months"
            )
            self._update_scenario()
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.baseline_projection = None
            self.scenario = None
            self.monthly_table.setRowCount(0)
            self.date_range_label.setText("Current projection unavailable")
            QMessageBox.critical(
                self,
                "Simulator error",
                f"Could not load the current cashflow projection:\n\n{exc}",
            )
        finally:
            self.refresh_button.setEnabled(True)

    def reset_scenario(self) -> None:
        """Restore saved payroll assumptions and clear hypothetical outgoings."""
        self._pay_assumptions_modified = False
        self.refresh_projection(reset_inputs=True)
        for amount in self.adjustment_inputs.values():
            amount.setValue(0)
        self._update_scenario()

    def _load_pay_assumptions(self, settings: dict[str, Any]) -> None:
        """Copy persisted payroll settings into the temporary controls."""
        self._loading_pay_inputs = True
        self.hourly_wage_input.setValue(float(settings["hourly_wage"]))
        self.average_hours_input.setValue(float(settings["average_hours"]))
        self.tax_code_input.setText(settings["tax_code"])
        self.ni_category_input.setText(settings["ni_category"])
        self.pension_percent_input.setValue(float(settings["pension_percent"]))
        self.student_loan_plan_input.setCurrentText(settings["student_loan_plan"])
        self.scottish_taxpayer_input.setChecked(settings["scottish_taxpayer"])
        frequency = settings["pay_frequency"].capitalize()
        self.pay_frequency_note.setText(
            f"Pay frequency remains {frequency} for this scenario."
        )
        self._loading_pay_inputs = False

    def _pay_assumption_changed(self, *_args) -> None:
        if self._loading_pay_inputs:
            return
        self._pay_assumptions_modified = True
        self._update_scenario()

    def _update_scenario(self, *_args) -> None:
        if self.baseline_projection is None or self._loading_pay_inputs:
            return
        changes = {
            f"monthly_{key}_change_pence": round(input_.value() * 100)
            for key, input_ in self.adjustment_inputs.items()
        }
        try:
            settings = self.baseline_settings
            if settings is None or self.baseline_payroll is None:
                raise ValueError("Saved payroll settings are unavailable.")
            tax_year = self.baseline_payroll["tax_year"]
            hypothetical_payroll = calculate_take_home_pay(
                hourly_wage_pence=round(self.hourly_wage_input.value() * 100),
                average_hours=self.average_hours_input.value(),
                frequency=settings["pay_frequency"],
                tax_code=self.tax_code_input.text(),
                ni_category=self.ni_category_input.text(),
                scottish_taxpayer=self.scottish_taxpayer_input.isChecked(),
                pension_percent=self.pension_percent_input.value(),
                student_loan_plan=self.student_loan_plan_input.currentText(),
                tax_year=tax_year,
            )
            pay_change = (
                hypothetical_payroll["net_pay_pence"]
                - self.baseline_payroll["net_pay_pence"]
            )
            self.scenario = calculate_scenario(
                self.baseline_projection,
                income_change_per_pay_pence=pay_change,
                **changes,
            )
        except (ValueError, TypeError, KeyError) as exc:
            self.scenario = None
            self.pay_estimate_label.clear()
            self.pay_error_label.setText(str(exc))
            self.monthly_table.setRowCount(0)
            self.scenario_card.value_label.setText("Unavailable")
            self.change_card.value_label.setText("Unavailable")
            return
        self.pay_error_label.clear()
        self.pay_estimate_label.setText(
            f"Estimated take-home per {settings['pay_frequency']} pay period: "
            f"baseline {format_money(self.baseline_payroll['net_pay_pence'])}; "
            f"scenario {format_money(hypothetical_payroll['net_pay_pence'])}; "
            f"change {format_money(pay_change)}. Tax year: {tax_year}."
        )
        self._show_scenario()

    def _show_scenario(self) -> None:
        if self.scenario is None:
            return
        baseline = self.baseline_projection["closing_balance_pence"]
        scenario = self.scenario["scenario_closing_balance_pence"]
        change = self.scenario["closing_balance_change_pence"]
        self.baseline_card.set_value(baseline, negative=baseline < 0)
        self.scenario_card.set_value(scenario, negative=scenario < 0)
        self.change_card.set_value(change, negative=change < 0)
        change_title = (
            "Change from baseline · lower"
            if change < 0
            else "Change from baseline · higher"
            if change > 0
            else "Change from baseline"
        )
        self.change_card.title_label.setText(change_title)
        rows = self.scenario["months"]
        self.monthly_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["label"],
                row["baseline_net_pence"],
                row["scenario_net_pence"],
                row["baseline_balance_pence"],
                row["scenario_balance_pence"],
                row["balance_change_pence"],
            )
            for column, value in enumerate(values):
                display = str(value) if column == 0 else format_money(value)
                item = QTableWidgetItem(display)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if column == 1 and row["baseline_net_pence"] < 0:
                    item.setForeground(QColor("#f87171"))
                if column == 2 and row["scenario_net_pence"] < 0:
                    item.setForeground(QColor("#f87171"))
                if column == 3 and row["baseline_balance_pence"] < 0:
                    item.setForeground(QColor("#f87171"))
                if column == 4 and row["scenario_balance_pence"] < 0:
                    item.setForeground(QColor("#f87171"))
                if column == 5 and row["balance_change_pence"] < 0:
                    item.setForeground(QColor("#f87171"))
                self.monthly_table.setItem(row_index, column, item)
        self.monthly_table.resizeRowsToContents()
