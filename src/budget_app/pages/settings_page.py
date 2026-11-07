"""Application settings page."""

import sqlite3
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.settings_service import (
    get_pension_estimate,
    get_settings,
    save_settings,
)


class SettingsPage(QWidget):
    """View and update the settings used by BudgetApp."""

    settings_saved = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.pension_estimate: dict | None = None
        self._build_ui()
        self.refresh_settings()

    @staticmethod
    def _create_money_input(*, allow_negative: bool = False) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        minimum = -999999999.99 if allow_negative else 0
        field.setRange(minimum, 999999999.99)
        field.setDecimals(2)
        field.setSingleStep(1)
        field.setPrefix("£")
        field.setKeyboardTracking(False)
        return field

    @staticmethod
    def _create_card(
        title: str,
        description: str = "",
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("summaryCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("secondaryText")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        return card, layout

    @staticmethod
    def _create_form() -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        return form

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(18)

        heading_layout = QHBoxLayout()
        heading_container = QVBoxLayout()
        heading_container.setSpacing(5)

        heading = QLabel("Settings")
        heading.setObjectName("pageHeading")

        description = QLabel(
            "Manage your starting balance, income assumptions and forecast settings."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)

        heading_container.addWidget(heading)
        heading_container.addWidget(description)
        heading_layout.addLayout(heading_container)
        heading_layout.addStretch()
        main_layout.addLayout(heading_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content_layout = QGridLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 4)
        content_layout.setHorizontalSpacing(16)
        content_layout.setVerticalSpacing(16)

        self._build_balance_card(content_layout)
        self._build_income_card(content_layout)
        self._build_tax_card(content_layout)

        content_layout.setColumnStretch(0, 1)
        content_layout.setColumnStretch(1, 1)
        content_layout.setRowStretch(1, 1)

        scroll_area.setWidget(content)
        main_layout.addWidget(scroll_area, 1)

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label, 1)

        self.reload_button = QPushButton("Discard changes")
        self.reload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload_button.clicked.connect(self.refresh_settings)
        footer_layout.addWidget(self.reload_button)

        self.save_button = QPushButton("Save settings")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self.save)
        footer_layout.addWidget(self.save_button)

        main_layout.addLayout(footer_layout)

    def _build_balance_card(self, grid: QGridLayout) -> None:
        card, layout = self._create_card(
            "Account & forecast",
            "Set the balance used as the opening point for your cashflow projection.",
        )
        form = self._create_form()

        self.current_balance_input = self._create_money_input(allow_negative=True)
        self.current_balance_input.setToolTip(
            "Your current account balance. A negative value can be used "
            "for an overdraft."
        )

        self.projection_months_input = QSpinBox()
        self.projection_months_input.setRange(1, 120)
        self.projection_months_input.setSuffix(" months")
        self.projection_months_input.setToolTip(
            "The number of months included in the cashflow projection."
        )

        form.addRow("Current balance", self.current_balance_input)
        form.addRow("Forecast duration", self.projection_months_input)
        layout.addLayout(form)
        grid.addWidget(card, 0, 0)

    def _build_income_card(self, grid: QGridLayout) -> None:
        card, layout = self._create_card(
            "Income & payday",
            "These assumptions are used when recent payslips are unavailable "
            "and to schedule future paydays.",
        )
        form = self._create_form()

        self.hourly_wage_input = self._create_money_input()
        self.hourly_wage_input.setSuffix(" per hour")

        self.average_hours_input = QDoubleSpinBox()
        self.average_hours_input.setRange(0, 168)
        self.average_hours_input.setDecimals(2)
        self.average_hours_input.setSingleStep(1)
        self.average_hours_input.setSuffix(" hours / week")
        self.average_hours_input.setKeyboardTracking(False)

        self.pay_frequency_input = QComboBox()
        self.pay_frequency_input.addItem("Weekly", "weekly")
        self.pay_frequency_input.addItem("Fortnightly", "fortnightly")
        self.pay_frequency_input.addItem("Monthly", "monthly")

        self.next_pay_date_enabled_input = QCheckBox(
            "I know my next contractual payday"
        )

        self.next_pay_date_input = QDateEdit()
        self.next_pay_date_input.setCalendarPopup(True)
        self.next_pay_date_input.setDisplayFormat("dd MMM yyyy")
        self.next_pay_date_input.setDate(QDate.currentDate())
        self.next_pay_date_input.setEnabled(False)
        self.next_pay_date_enabled_input.toggled.connect(
            self.next_pay_date_input.setEnabled
        )
        self.next_pay_date_input.setToolTip(
            "Enter the contractual payday shown on your payslip, not the "
            "earlier date Revolut makes the money available."
        )

        pay_date_container = QWidget()
        pay_date_layout = QVBoxLayout(pay_date_container)
        pay_date_layout.setContentsMargins(0, 0, 0, 0)
        pay_date_layout.setSpacing(6)
        pay_date_layout.addWidget(self.next_pay_date_enabled_input)
        pay_date_layout.addWidget(self.next_pay_date_input)

        self.early_payment_offset_input = QSpinBox()
        self.early_payment_offset_input.setRange(0, 7)
        self.early_payment_offset_input.setSuffix(" days early")
        self.early_payment_offset_input.setToolTip(
            "Use 1 for money arriving one day before the contractual payday. "
            "Use 0 to disable the offset."
        )

        form.addRow("Hourly wage", self.hourly_wage_input)
        form.addRow("Average hours", self.average_hours_input)
        form.addRow("Pay frequency", self.pay_frequency_input)
        form.addRow("Next pay date", pay_date_container)
        form.addRow("Early payment", self.early_payment_offset_input)

        note = QLabel(
            "The early-payment offset changes projected receipt dates only. "
            "Actual payslip dates remain unchanged."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)

        layout.addLayout(form)
        layout.addWidget(note)
        grid.addWidget(card, 0, 1)

    def _build_tax_card(self, grid: QGridLayout) -> None:
        card, layout = self._create_card(
            "Tax & deductions",
            "These settings drive the projected take-home pay calculation. "
            "Tax rates are selected automatically from the forecast date.",
        )
        form = self._create_form()

        self.tax_code_input = QLineEdit()
        self.tax_code_input.setMaxLength(20)
        self.tax_code_input.setPlaceholderText("e.g. 1257L")

        self.pension_percent_input = QDoubleSpinBox()
        self.pension_percent_input.setRange(0, 100)
        self.pension_percent_input.setDecimals(2)
        self.pension_percent_input.setSingleStep(0.5)
        self.pension_percent_input.setSuffix(" %")
        self.pension_percent_input.setKeyboardTracking(False)

        pension_container = QWidget()
        pension_layout = QVBoxLayout(pension_container)
        pension_layout.setContentsMargins(0, 0, 0, 0)
        pension_layout.setSpacing(6)

        pension_input_row = QHBoxLayout()
        pension_input_row.setContentsMargins(0, 0, 0, 0)
        pension_input_row.setSpacing(8)
        pension_input_row.addWidget(self.pension_percent_input)

        self.use_pension_estimate_button = QPushButton("Use estimate")
        self.use_pension_estimate_button.setObjectName("smallButton")
        self.use_pension_estimate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.use_pension_estimate_button.clicked.connect(self._use_pension_estimate)
        pension_input_row.addWidget(self.use_pension_estimate_button)
        pension_input_row.addStretch()
        pension_layout.addLayout(pension_input_row)

        self.pension_estimate_label = QLabel("")
        self.pension_estimate_label.setObjectName("secondaryText")
        self.pension_estimate_label.setWordWrap(True)
        pension_layout.addWidget(self.pension_estimate_label)

        self.student_loan_plan_input = QComboBox()
        self.student_loan_plan_input.setEditable(True)
        self.student_loan_plan_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.student_loan_plan_input.addItems(
            ["None", "Plan 1", "Plan 2", "Plan 4", "Plan 5", "Postgraduate"]
        )
        self.student_loan_plan_input.setToolTip(
            "You can type a combined plan if you repay more than one loan type."
        )

        self.ni_category_input = QLineEdit()
        self.ni_category_input.setMaxLength(3)
        self.ni_category_input.setPlaceholderText("e.g. A")

        self.scottish_taxpayer_input = QCheckBox("I am a Scottish taxpayer")

        form.addRow("Tax code", self.tax_code_input)
        form.addRow("Pension contribution", pension_container)
        form.addRow("Student loan plan", self.student_loan_plan_input)
        form.addRow("NI category", self.ni_category_input)
        form.addRow("Scottish taxpayer", self.scottish_taxpayer_input)

        assumptions = QLabel(
            "Pension is estimated as a PAYE/net-pay contribution based on all "
            "gross earnings. Payroll rounding, tax-code adjustments, other "
            "deductions and scheme-specific pensionable pay can change the "
            "actual payslip. Recent payslips are shown as a comparison."
        )
        assumptions.setObjectName("secondaryText")
        assumptions.setWordWrap(True)

        layout.addLayout(form)
        layout.addWidget(assumptions)
        grid.addWidget(card, 1, 0, 1, 2)

    def refresh_settings(self) -> bool:
        """Reload the saved settings and the latest pension estimate."""

        self.reload_button.setEnabled(False)
        self.save_button.setEnabled(False)

        try:
            settings = get_settings()
            self.pension_estimate = get_pension_estimate()

            self.current_balance_input.setValue(float(settings["current_balance"]))
            self.projection_months_input.setValue(settings["projection_months"])
            self.hourly_wage_input.setValue(float(settings["hourly_wage"]))
            self.average_hours_input.setValue(settings["average_hours"])
            self._set_combo_data(
                self.pay_frequency_input,
                settings["pay_frequency"],
            )

            next_pay_date = settings["next_pay_date"]
            self.next_pay_date_enabled_input.setChecked(next_pay_date is not None)

            if next_pay_date:
                self.next_pay_date_input.setDate(
                    QDate.fromString(next_pay_date, "yyyy-MM-dd")
                )
            else:
                self.next_pay_date_input.setDate(QDate.currentDate())

            self.early_payment_offset_input.setValue(
                settings["early_payment_offset_days"]
            )
            self.tax_code_input.setText(settings["tax_code"])
            self.pension_percent_input.setValue(settings["pension_percent"])
            self._set_student_loan_plan(settings["student_loan_plan"])
            self.ni_category_input.setText(settings["ni_category"])
            self.scottish_taxpayer_input.setChecked(settings["scottish_taxpayer"])
            self._update_pension_estimate_display()

            self.status_label.setText("Settings loaded.")
            return True

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.status_label.setText("Unable to load settings.")
            QMessageBox.critical(
                self,
                "Settings error",
                f"Could not load settings:\n\n{exc}",
            )
            return False

        finally:
            self.reload_button.setEnabled(True)
            self.save_button.setEnabled(True)

    def _update_pension_estimate_display(self) -> None:
        """Show the recent-payslip estimate without changing the saved value."""

        if self.pension_estimate is None:
            self.pension_estimate_label.setText(
                "No income records with gross pay were found in the last 8 weeks."
            )
            self.use_pension_estimate_button.setEnabled(False)
            return

        percentage = self.pension_estimate["percentage"]
        payslips_used = self.pension_estimate["payslips_used"]
        payslip_word = "payslip" if payslips_used == 1 else "payslips"

        self.pension_estimate_label.setText(
            f"Estimated {percentage:.2f}% of gross pay from "
            f"{payslips_used} recent {payslip_word} (last 8 weeks). "
            "This is an effective rate; pensionable earnings may differ. "
            "It will not change your setting unless you select Use estimate and save."
        )
        self.use_pension_estimate_button.setEnabled(True)

    def _use_pension_estimate(self) -> None:
        """Copy the estimate into the editable pension percentage field."""

        if self.pension_estimate is None:
            return

        self.pension_percent_input.setValue(float(self.pension_estimate["percentage"]))
        self.status_label.setText(
            "Estimate copied into the pension field. Save settings to keep it."
        )

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentIndex(0)

    def _set_student_loan_plan(self, value: str) -> None:
        index = self.student_loan_plan_input.findText(
            value,
            Qt.MatchFlag.MatchFixedString,
        )
        if index >= 0:
            self.student_loan_plan_input.setCurrentIndex(index)
        else:
            self.student_loan_plan_input.setCurrentText(value)

    def _get_form_values(self) -> dict[str, Any]:
        next_pay_date = None
        if self.next_pay_date_enabled_input.isChecked():
            next_pay_date = self.next_pay_date_input.date().toString("yyyy-MM-dd")

        return {
            "current_balance": self.current_balance_input.value(),
            "hourly_wage": self.hourly_wage_input.value(),
            "average_hours": self.average_hours_input.value(),
            "tax_code": self.tax_code_input.text(),
            "pension_percent": self.pension_percent_input.value(),
            "student_loan_plan": self.student_loan_plan_input.currentText(),
            "ni_category": self.ni_category_input.text(),
            "scottish_taxpayer": self.scottish_taxpayer_input.isChecked(),
            "projection_months": self.projection_months_input.value(),
            "pay_frequency": self.pay_frequency_input.currentData(),
            "next_pay_date": next_pay_date,
            "early_payment_offset_days": self.early_payment_offset_input.value(),
        }

    def save(self) -> None:
        """Validate and persist the settings currently shown in the form."""

        self.save_button.setEnabled(False)
        self.reload_button.setEnabled(False)
        self.save_button.setText("Saving...")

        try:
            save_settings(**self._get_form_values())

        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.status_label.setText("Settings could not be saved.")
            QMessageBox.critical(
                self,
                "Settings error",
                f"Could not save settings:\n\n{exc}",
            )

        else:
            self.status_label.setText("Settings saved successfully.")
            self.settings_saved.emit()

        finally:
            self.save_button.setEnabled(True)
            self.save_button.setText("Save settings")
            self.reload_button.setEnabled(True)
