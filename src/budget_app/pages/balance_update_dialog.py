"""Dialog for updating the reconciled account balance."""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.settings_service import (
    get_settings,
    update_reconciled_balance,
)
from budget_app.utils.widget_sizing import configure_form_controls


class BalanceUpdateDialog(QDialog):
    """Collect and save an account balance and the date it applies to."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Update account balance")

        settings = get_settings()
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Enter your reconciled account balance and the date it applies to. "
                "Recorded activity after that date is applied automatically."
            )
        )

        form = QFormLayout()
        self.balance_input = QDoubleSpinBox()
        self.balance_input.setRange(-999999999.99, 999999999.99)
        self.balance_input.setDecimals(2)
        self.balance_input.setPrefix("£")
        self.balance_input.setValue(float(settings["current_balance"]))
        form.addRow("Reconciled balance", self.balance_input)

        self.balance_date_input = QDateEdit()
        self.balance_date_input.setCalendarPopup(True)
        self.balance_date_input.setDisplayFormat("dd MMM yyyy")
        self.balance_date_input.setDate(QDate.currentDate())
        self.balance_date_input.setMaximumDate(QDate.currentDate())
        form.addRow("Balance date", self.balance_date_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        configure_form_controls(self)

    def save_balance(self) -> bool:
        """Persist the entered balance, showing validation errors if needed."""

        try:
            update_reconciled_balance(
                current_balance=self.balance_input.value(),
                balance_as_of_date=self.balance_date_input.date().toString(
                    "yyyy-MM-dd"
                ),
            )
        except (ValueError, RuntimeError, OSError) as exc:
            QMessageBox.critical(self, "Could not update balance", str(exc))
            return False

        return True


def prompt_update_balance(parent: QWidget) -> bool:
    """Show the balance dialog and return whether a balance was saved."""

    try:
        dialog = BalanceUpdateDialog(parent)
    except (ValueError, RuntimeError, OSError) as exc:
        QMessageBox.critical(parent, "Could not load balance", str(exc))
        return False

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    return dialog.save_balance()
