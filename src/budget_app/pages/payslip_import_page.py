"""User interface for reviewing and importing payslip PDFs."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from budget_app.pages.receipt_dialog import ReceiptConfirmationDialog
from budget_app.payslip_extractor import EarningsLine, PayslipData
from budget_app.services.payslip_import_service import (
    DuplicatePayslipError,
    PayslipImportError,
    PayslipImportPreview,
    import_payslip,
    preview_payslip_import,
    validate_payslip,
)
from budget_app.services.settings_service import get_settings
from budget_app.utils.table import configure_table_header


class PayslipReviewDialog(QDialog):
    """Allow the user to review and correct extracted payslip information."""

    SUMMARY_FIELDS = (
        ("Gross pay", "gross_pay"),
        ("Tax paid", "tax_paid"),
        ("National Insurance", "ni_paid"),
        ("Pension", "pension_paid"),
        ("Other deductions", "other_deductions"),
        ("Net pay", "net_pay"),
    )

    def __init__(
        self,
        preview: PayslipImportPreview,
        source_path: str | Path,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.preview = preview
        self.source_path = Path(source_path)
        self.reviewed_data: PayslipData | None = None

        self.setWindowTitle("Review payslip")
        self.resize(900, 760)

        self._build_ui()
        self._populate_fields()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("Review extracted payslip")
        title.setObjectName("pageHeading")
        layout.addWidget(title)

        filename = QLabel(self.source_path.name)
        filename.setObjectName("secondaryText")
        filename.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(filename)

        form = QFormLayout()
        form.setSpacing(9)

        self.pay_date_input = QLineEdit()
        self.pay_date_input.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Pay date", self.pay_date_input)

        self.summary_inputs: dict[str, QLineEdit] = {}

        for label, field_name in self.SUMMARY_FIELDS:
            field = QLineEdit()
            field.setPlaceholderText("Amount in pounds")
            self.summary_inputs[field_name] = field
            form.addRow(label, field)

        layout.addLayout(form)

        earnings_heading = QLabel("Earnings breakdown")
        earnings_heading.setObjectName("sectionHeading")
        layout.addWidget(earnings_heading)

        self.earnings_table = QTableWidget(0, 4)
        self.earnings_table.setHorizontalHeaderLabels(
            ["Description", "Units", "Rate (£)", "Amount (£)"]
        )
        self.earnings_table.setObjectName("cashflowTable")
        self.earnings_table.setAlternatingRowColors(True)
        self.earnings_table.verticalHeader().setVisible(False)
        self.earnings_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.earnings_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.earnings_table.setMinimumHeight(190)

        header = self.earnings_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        for column in range(1, 4):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        layout.addWidget(self.earnings_table)

        line_actions = QHBoxLayout()

        self.add_line_button = QPushButton("Add earnings line")
        self.add_line_button.clicked.connect(self._add_earnings_row)

        self.remove_line_button = QPushButton("Remove selected line")
        self.remove_line_button.clicked.connect(self._remove_earnings_row)

        line_actions.addWidget(self.add_line_button)
        line_actions.addWidget(self.remove_line_button)
        line_actions.addStretch()

        layout.addLayout(line_actions)

        self.warning_text = QTextEdit()
        self.warning_text.setReadOnly(True)
        self.warning_text.setMaximumHeight(115)
        self.warning_text.setObjectName("secondaryText")

        if self.preview.errors:
            self.warning_text.setPlainText(
                "Please review these extraction warnings and correct the "
                "values above where necessary:\n\n"
                + "\n".join(f"• {warning}" for warning in self.preview.errors)
            )
            layout.addWidget(self.warning_text)

        self.acknowledge_warnings = QCheckBox(
            "I have reviewed the extraction warnings above."
        )
        self.acknowledge_warnings.setVisible(bool(self.preview.errors))
        layout.addWidget(self.acknowledge_warnings)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Confirm import"
        )

        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)

        layout.addWidget(self.button_box)

    def _populate_fields(self) -> None:
        data = self.preview.data

        self.pay_date_input.setText(data.pay_date or "")

        for _, field_name in self.SUMMARY_FIELDS:
            value = getattr(data, field_name)

            self.summary_inputs[field_name].setText(
                str(value) if value is not None else ""
            )

        for line in data.earnings:
            self._add_earnings_row(line)

    def _add_earnings_row(
        self,
        line: EarningsLine | None = None,
    ) -> None:
        row = self.earnings_table.rowCount()
        self.earnings_table.insertRow(row)

        values = [
            line.description if line else "",
            str(line.units) if line and line.units is not None else "",
            str(line.rate) if line and line.rate is not None else "",
            str(line.amount) if line else "",
        ]

        for column, value in enumerate(values):
            self.earnings_table.setItem(
                row,
                column,
                QTableWidgetItem(value),
            )

    def _remove_earnings_row(self) -> None:
        row = self.earnings_table.currentRow()

        if row >= 0:
            self.earnings_table.removeRow(row)

    @staticmethod
    def _parse_amount(
        value: str,
        label: str,
        *,
        optional: bool = False,
    ) -> Decimal | None:
        value = value.strip()

        if not value and optional:
            return None

        if not value:
            raise ValueError(f"{label} is required.")

        try:
            amount = Decimal(value.replace("£", "").replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a valid number.") from exc

        if not amount.is_finite() or amount < 0:
            raise ValueError(f"{label} must be finite and non-negative.")

        return amount

    def _build_reviewed_data(self) -> PayslipData:
        pay_date_text = self.pay_date_input.text().strip()

        try:
            parsed_date = date.fromisoformat(pay_date_text)
        except ValueError as exc:
            raise ValueError("Enter a valid pay date in YYYY-MM-DD format.") from exc

        summary = {
            field_name: self._parse_amount(
                self.summary_inputs[field_name].text(),
                label,
            )
            for label, field_name in self.SUMMARY_FIELDS
        }

        earnings: list[EarningsLine] = []

        for row in range(self.earnings_table.rowCount()):
            cells = [self.earnings_table.item(row, column) for column in range(4)]

            values = [cell.text().strip() if cell else "" for cell in cells]

            description = values[0]

            if not description:
                raise ValueError(f"Earnings line {row + 1} needs a description.")

            units = self._parse_amount(
                values[1],
                f"Earnings line {row + 1} units",
                optional=True,
            )

            rate = self._parse_amount(
                values[2],
                f"Earnings line {row + 1} rate",
                optional=True,
            )

            amount = self._parse_amount(
                values[3],
                f"Earnings line {row + 1} amount",
            )

            earnings.append(
                EarningsLine(
                    description=description,
                    units=units,
                    rate=rate,
                    amount=amount,
                )
            )

        return PayslipData(
            **summary,
            pay_date=parsed_date.isoformat(),
            source_hash=self.preview.data.source_hash,
            earnings=earnings,
            warnings=[],
        )

    def _validate_and_accept(self) -> None:
        if self.preview.errors and not self.acknowledge_warnings.isChecked():
            self.error_label.setText(
                "Please confirm that you have reviewed the extraction warnings."
            )
            self.acknowledge_warnings.setFocus()
            return

        try:
            reviewed_data = self._build_reviewed_data()
            errors = validate_payslip(reviewed_data)

            if errors:
                raise ValueError("\n".join(errors))

        except ValueError as exc:
            self.error_label.setText(str(exc))
            return

        self.reviewed_data = reviewed_data
        self.error_label.clear()
        self.accept()


class PayslipImportPage(QWidget):
    """Select, review and import payslips from any directory."""

    def __init__(
        self,
        income_page: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.income_page = income_page
        self.selected_path: Path | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        heading = QLabel("Import Payslip")
        heading.setObjectName("pageHeading")

        description = QLabel(
            "Select a payslip PDF from anywhere on your computer. "
            "The original file will stay where it is."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(description)

        self.select_button = QPushButton("Choose payslip PDF")
        self.select_button.setObjectName("primaryButton")
        self.select_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_button.clicked.connect(self.select_payslip)

        layout.addWidget(
            self.select_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

        self.file_label = QLabel("No payslip selected.")
        self.file_label.setObjectName("secondaryText")
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.file_label)

        self.status_label = QLabel(
            "Choose a PDF to extract its pay details and review them before importing."
        )
        self.status_label.setObjectName("secondaryText")
        self.status_label.setWordWrap(True)

        layout.addWidget(self.status_label)
        layout.addStretch()

    def select_payslip(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select payslip PDF",
            "",
            "PDF files (*.pdf)",
        )

        if not file_path:
            return

        self.selected_path = Path(file_path)
        self.file_label.setText(str(self.selected_path))
        self.status_label.setText("Reading and extracting payslip information...")
        self.select_button.setEnabled(False)

        try:
            preview = preview_payslip_import(self.selected_path)
            self._review_and_import(preview)

        except (
            OSError,
            ValueError,
            RuntimeError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self,
                "Payslip error",
                f"Could not process the selected payslip:\n\n{exc}",
            )
            self.status_label.setText("The payslip could not be processed.")

        finally:
            self.select_button.setEnabled(True)

    def _review_and_import(
        self,
        preview: PayslipImportPreview,
    ) -> None:
        dialog = PayslipReviewDialog(
            preview,
            self.selected_path,
            self,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.status_label.setText("Payslip review cancelled. Nothing was imported.")
            return

        settings = get_settings()
        receipt_dialog = ReceiptConfirmationDialog(
            date.fromisoformat(dialog.reviewed_data.pay_date),
            int(settings["early_payment_offset_days"]),
            self,
        )
        if receipt_dialog.exec() != QDialog.DialogCode.Accepted:
            self.status_label.setText("Payslip import cancelled. Nothing was imported.")
            return

        try:
            result = import_payslip(
                self.selected_path,
                confirmed=True,
                reviewed_data=dialog.reviewed_data,
                receipt_date=receipt_dialog.receipt_date,
            )

        except DuplicatePayslipError as exc:
            QMessageBox.warning(
                self,
                "Payslip already imported",
                str(exc),
            )
            self.status_label.setText("This payslip has already been imported.")
            return

        except (
            PayslipImportError,
            OSError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self,
                "Import failed",
                f"The payslip was not imported:\n\n{exc}",
            )
            self.status_label.setText("Payslip import failed.")
            return

        income_id = result["income_id"]
        reconciliation = result["reconciliation"]
        reconciliation_status = reconciliation.get("status", "unknown")
        receipt_message = (
            f"\nBank receipt recorded: {receipt_dialog.receipt_date:%d/%m/%Y}."
            if receipt_dialog.receipt_date is not None
            else "\nPay remains forecast until you confirm it has reached your bank."
        )

        if self.income_page is not None:
            self.income_page.refresh_income()
            income_changed = getattr(self.income_page, "income_changed", None)
            if income_changed is not None:
                income_changed.emit()

        QMessageBox.information(
            self,
            "Payslip imported",
            (
                f"Payslip imported successfully.\n\n"
                f"Income record: #{income_id}\n"
                f"Reconciliation: {reconciliation_status.title()}"
                f"{receipt_message}"
            ),
        )

        self.status_label.setText(f"Successfully imported {self.selected_path.name}.")
