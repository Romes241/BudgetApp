"""Savings goals management page."""

import sqlite3
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
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.savings_goal_service import (
    add_savings_goal,
    estimate_completion_date,
    get_savings_goal_summary,
    get_savings_goals,
    record_savings_transaction,
    set_savings_goal_active,
    update_savings_goal,
)
from budget_app.utils.money import format_money
from budget_app.utils.widget_sizing import configure_form_controls


class SavingsGoalDialog(QDialog):
    """Add or edit goal details."""

    def __init__(self, goal: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.goal = goal
        self.setWindowTitle("Edit savings goal" if goal else "Add savings goal")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Emergency fund")
        self.target_input = self._money_input()
        self.monthly_input = self._money_input()
        form.addRow("Goal name", self.name_input)
        form.addRow("Target amount", self.target_input)
        form.addRow("Monthly contribution", self.monthly_input)
        if goal is None:
            self.current_input = self._money_input()
            form.addRow("Already saved", self.current_input)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if goal:
            self.name_input.setText(goal["name"])
            self.target_input.setValue(float(goal["target_amount"]))
            self.monthly_input.setValue(float(goal["monthly_contribution"]))
        configure_form_controls(self)

    @staticmethod
    def _money_input() -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(0, 999999999.99)
        field.setDecimals(2)
        field.setSingleStep(10)
        field.setPrefix("£")
        field.setKeyboardTracking(False)
        return field

    def _accept_if_valid(self) -> None:
        if not self.name_input.text().strip():
            self.error_label.setText("Please enter a goal name.")
            return
        if self.target_input.value() <= 0:
            self.error_label.setText("Target amount must be greater than zero.")
            return
        self.error_label.clear()
        self.accept()

    def get_values(self) -> dict:
        values = {
            "name": self.name_input.text().strip(),
            "target_amount": Decimal(str(self.target_input.value())),
            "monthly_contribution": Decimal(str(self.monthly_input.value())),
        }
        if self.goal is None:
            values["current_amount"] = Decimal(str(self.current_input.value()))
        return values


class SavingsTransactionDialog(QDialog):
    """Record a deposit or withdrawal."""

    def __init__(self, goal: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.goal = goal
        self.setWindowTitle(f"Record transaction — {goal['name']}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.type_input = QComboBox()
        self.type_input.addItem("Deposit", "deposit")
        self.type_input.addItem("Withdrawal", "withdrawal")
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0.01, 999999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setPrefix("£")
        self.amount_input.setKeyboardTracking(False)
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd MMM yyyy")
        self.date_input.setMaximumDate(QDate.currentDate())
        form.addRow("Transaction type", self.type_input)
        form.addRow("Amount", self.amount_input)
        form.addRow("Date", self.date_input)
        layout.addLayout(form)
        note = QLabel(
            "Transactions update the saved balance and are reflected in "
            "Cashflow when dated in the projection period."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.type_input.currentIndexChanged.connect(self._update_amount_limit)
        self._update_amount_limit()
        configure_form_controls(self)

    def _update_amount_limit(self) -> None:
        is_withdrawal = self.type_input.currentData() == "withdrawal"
        if is_withdrawal:
            self.amount_input.setRange(
                0.01, max(0.01, float(self.goal["current_amount"]))
            )
            self.amount_input.setToolTip(
                f"Cannot exceed {format_money(self.goal['current_amount_pence'])} saved."
            )
        else:
            self.amount_input.setRange(0.01, 999999999.99)
            self.amount_input.setToolTip("")

    def _accept_if_valid(self) -> None:
        if self.type_input.currentData() == "withdrawal" and (
            self.amount_input.value() > float(self.goal["current_amount"])
        ):
            self.error_label.setText("Withdrawal cannot exceed current savings.")
            return
        self.accept()

    def get_values(self) -> dict:
        return {
            "transaction_type": self.type_input.currentData(),
            "amount": Decimal(str(self.amount_input.value())),
            "transaction_date": self.date_input.date().toString("yyyy-MM-dd"),
        }


class SavingsSummaryCard(QFrame):
    """Summary value card."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("summaryCard")
        layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("summaryTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("summaryValue")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)


class SavingsGoalsPage(QWidget):
    """Display and manage active, completed and inactive savings goals."""

    goals_changed = Signal()
    FILTERS: ClassVar[tuple[str, ...]] = ("Active", "Completed", "Inactive")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.goals: list[dict] = []
        self._build_ui()
        self.refresh_goals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        heading_row = QHBoxLayout()
        headings = QVBoxLayout()
        title = QLabel("Savings Goals")
        title.setObjectName("pageHeading")
        description = QLabel(
            "Set your own monthly contributions and track deposits toward each goal."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)
        headings.addWidget(title)
        headings.addWidget(description)
        heading_row.addLayout(headings)
        heading_row.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_goals)
        heading_row.addWidget(self.refresh_button)
        layout.addLayout(heading_row)

        summary = QGridLayout()
        self.saved_card = SavingsSummaryCard("Total saved")
        self.targets_card = SavingsSummaryCard("Total targets")
        self.count_card = SavingsSummaryCard("Active goals")
        summary.addWidget(self.saved_card, 0, 0)
        summary.addWidget(self.targets_card, 0, 1)
        summary.addWidget(self.count_card, 0, 2)
        layout.addLayout(summary)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Add goal")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self.add_goal)
        self.filter_input = QComboBox()
        self.filter_input.addItems(self.FILTERS)
        self.filter_input.currentTextChanged.connect(self._render_goals)
        actions.addWidget(self.add_button)
        actions.addStretch()
        actions.addWidget(QLabel("Show"))
        actions.addWidget(self.filter_input)
        layout.addLayout(actions)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(12)
        self.scroll_area.setWidget(self.cards_container)
        layout.addWidget(self.scroll_area, 1)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("secondaryText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self.status_label = QLabel()
        self.status_label.setObjectName("secondaryText")
        layout.addWidget(self.status_label)

    def refresh_goals(self) -> None:
        try:
            self.goals = get_savings_goals(include_inactive=True)
            summary = get_savings_goal_summary()
            self.saved_card.value_label.setText(
                format_money(summary["total_saved_pence"])
            )
            self.targets_card.value_label.setText(
                format_money(summary["total_targets_pence"])
            )
            self.count_card.value_label.setText(str(summary["active_goals"]))
            self._render_goals()
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self, "Savings goals error", f"Could not load goals:\n\n{exc}"
            )

    def _render_goals(self, _filter: str | None = None) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        selected = self.filter_input.currentText()
        if selected == "Active":
            visible = [
                g
                for g in self.goals
                if g["active"] and g["current_amount_pence"] < g["target_amount_pence"]
            ]
        elif selected == "Completed":
            visible = [
                g
                for g in self.goals
                if g["active"] and g["current_amount_pence"] >= g["target_amount_pence"]
            ]
        else:
            visible = [g for g in self.goals if not g["active"]]
        for goal in visible:
            self.cards_layout.addWidget(self._goal_card(goal))
        self.cards_layout.addStretch()
        self.empty_label.setText(f"No {selected.lower()} savings goals.")
        self.empty_label.setVisible(not visible)
        self.scroll_area.setVisible(bool(visible))
        self.status_label.setText(
            f"{len(visible)} {selected.lower()} goal{'s' if len(visible) != 1 else ''}"
        )

    def _goal_card(self, goal: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("summaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        title = QLabel(goal["name"])
        title.setObjectName("sectionHeading")
        top.addWidget(title)
        top.addStretch()
        edit = QPushButton("Edit")
        edit.clicked.connect(lambda _checked=False, g=goal: self.edit_goal(g))
        top.addWidget(edit)
        transaction = QPushButton("Deposit / withdraw")
        transaction.clicked.connect(
            lambda _checked=False, g=goal: self.record_transaction(g)
        )
        top.addWidget(transaction)
        status = QPushButton("Deactivate" if goal["active"] else "Reactivate")
        status.clicked.connect(lambda _checked=False, g=goal: self.toggle_goal(g))
        top.addWidget(status)
        layout.addLayout(top)
        metrics = QHBoxLayout()
        metrics.addWidget(
            QLabel(f"Saved: {format_money(goal['current_amount_pence'])}")
        )
        metrics.addWidget(
            QLabel(f"Target: {format_money(goal['target_amount_pence'])}")
        )
        metrics.addWidget(
            QLabel(f"Remaining: {format_money(goal['remaining_amount_pence'])}")
        )
        metrics.addWidget(
            QLabel(f"Monthly: {format_money(goal['monthly_contribution_pence'])}")
        )
        metrics.addStretch()
        layout.addLayout(metrics)
        progress = QProgressBar()
        progress.setObjectName("savingsProgress")
        progress.setRange(0, 1000)
        progress.setValue(round(goal["progress_percent"] * 10))
        progress.setFormat(f"{goal['progress_percent']:.1f}%")
        layout.addWidget(progress)
        eta = estimate_completion_date(
            goal["current_amount_pence"],
            goal["target_amount_pence"],
            goal["monthly_contribution_pence"],
        )
        eta_text = (
            "Goal reached"
            if goal["current_amount_pence"] >= goal["target_amount_pence"]
            else f"Estimated completion: {eta.strftime('%b %Y')}"
            if eta
            else "Set a monthly contribution to estimate completion"
        )
        hint = QLabel(eta_text)
        hint.setObjectName("secondaryText")
        layout.addWidget(hint)
        return card

    def add_goal(self) -> None:
        dialog = SavingsGoalDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            add_savings_goal(**dialog.get_values())
            self._changed("Savings goal added.")
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            QMessageBox.critical(
                self, "Could not add goal", f"The goal could not be added:\n\n{exc}"
            )

    def edit_goal(self, goal: dict) -> None:
        dialog = SavingsGoalDialog(goal=goal, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if update_savings_goal(goal["id"], **dialog.get_values()):
                self._changed("Savings goal updated.")
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
                "Could not update goal",
                f"The goal could not be updated:\n\n{exc}",
            )

    def record_transaction(self, goal: dict) -> None:
        dialog = SavingsTransactionDialog(goal, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if record_savings_transaction(goal["id"], **dialog.get_values()):
                self._changed("Savings transaction recorded.")
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
                "Could not record transaction",
                f"The transaction could not be recorded:\n\n{exc}",
            )

    def toggle_goal(self, goal: dict) -> None:
        active = bool(goal["active"])
        action = "deactivate" if active else "reactivate"
        answer = QMessageBox.question(
            self,
            f"{action.title()} savings goal",
            f"{action.title()} '{goal['name']}'? Its saved balance and transaction history will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if set_savings_goal_active(goal["id"], not active):
                self._changed(f"Savings goal {action}d.")
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
                "Could not update goal",
                f"The goal could not be updated:\n\n{exc}",
            )

    def _changed(self, message: str) -> None:
        self.refresh_goals()
        self.status_label.setText(message)
        self.goals_changed.emit()
