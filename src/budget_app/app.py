"""Application entry point and main window."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from budget_app import __version__
from budget_app.database import connect_database, initialise_database
from budget_app.pages.cashflow_page import CashflowPage
from budget_app.pages.debt_page import DebtPage
from budget_app.pages.fixed_expenses_page import FixedExpensesPage
from budget_app.pages.income_page import IncomePage
from budget_app.pages.payslip_import_page import PayslipImportPage
from budget_app.pages.savings_goals_page import SavingsGoalsPage
from budget_app.pages.settings_page import SettingsPage
from budget_app.pages.variable_expenses_page import VariableExpensesPage


def load_stylesheet() -> str:
    """Load the application's Qt stylesheet."""

    stylesheet_path = Path(__file__).parent / "styles" / "theme.qss"
    return stylesheet_path.read_text(encoding="utf-8")


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("BudgetApp")
        self.resize(1250, 800)
        self.setMinimumSize(950, 600)

        self._build_ui()

        status_bar = QStatusBar(self)
        status_bar.showMessage(f"BudgetApp v{__version__}")
        self.setStatusBar(status_bar)

    def _build_ui(self) -> None:
        """Build the main window and navigation."""

        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar navigation.
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 20)
        sidebar_layout.setSpacing(8)

        app_title = QLabel("BudgetApp")
        app_title.setObjectName("appTitle")
        sidebar_layout.addWidget(app_title)

        subtitle = QLabel("Personal finance")
        subtitle.setObjectName("secondaryText")
        sidebar_layout.addWidget(subtitle)

        sidebar_layout.addSpacing(24)

        self.navigation_buttons: dict[str, QPushButton] = {}

        self.page_stack = QStackedWidget()

        dashboard_page = self._create_dashboard_page()
        cashflow_page = CashflowPage()
        debt_page = DebtPage()
        debt_page.debts_changed.connect(cashflow_page.refresh_projection)
        savings_goals_page = SavingsGoalsPage()
        savings_goals_page.goals_changed.connect(cashflow_page.refresh_projection)

        fixed_expenses_page = FixedExpensesPage()
        variable_expenses_page = VariableExpensesPage()
        income_page = IncomePage()
        payslip_import_page = PayslipImportPage(income_page=income_page)
        settings_page = SettingsPage()

        self.page_stack.addWidget(dashboard_page)
        self.page_stack.addWidget(cashflow_page)
        self.page_stack.addWidget(debt_page)
        self.page_stack.addWidget(savings_goals_page)
        self.page_stack.addWidget(fixed_expenses_page)
        self.page_stack.addWidget(variable_expenses_page)
        self.page_stack.addWidget(income_page)
        self.page_stack.addWidget(payslip_import_page)
        self.page_stack.addWidget(settings_page)

        self._add_navigation_button(
            sidebar_layout,
            "Dashboard",
            dashboard_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Cashflow",
            cashflow_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Debt Management",
            debt_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Savings Goals",
            savings_goals_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Fixed Expenses",
            fixed_expenses_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Variable Expenses",
            variable_expenses_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Income",
            income_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Payslip Import",
            payslip_import_page,
        )
        self._add_navigation_button(
            sidebar_layout,
            "Settings",
            settings_page,
        )

        sidebar_layout.addStretch()

        version_label = QLabel(f"Version {__version__}")
        version_label.setObjectName("secondaryText")
        sidebar_layout.addWidget(version_label)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.page_stack, 1)

        self.setCentralWidget(central_widget)

        self._select_page("Dashboard")

    def _create_dashboard_page(self) -> QWidget:
        """Create the initial dashboard placeholder."""

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        heading = QLabel("Dashboard")
        heading.setObjectName("pageHeading")

        description = QLabel(
            "Your personal finance dashboard. "
            "Select Cashflow to view your projected financial position."
        )
        description.setObjectName("secondaryText")
        description.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addStretch()

        return page

    def _add_navigation_button(
        self,
        layout: QVBoxLayout,
        name: str,
        page: QWidget,
    ) -> None:
        """Add a navigation button connected to a stacked page."""

        button = QPushButton(name)
        button.setObjectName("navigationButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        button.clicked.connect(
            lambda checked=False, page_name=name: self._select_page(page_name)
        )

        layout.addWidget(button)
        self.navigation_buttons[name] = button

    def _select_page(self, name: str) -> None:
        """Display the selected page and update navigation state."""

        button = self.navigation_buttons[name]

        for navigation_button in self.navigation_buttons.values():
            navigation_button.setChecked(False)

        button.setChecked(True)

        page_index = list(self.navigation_buttons).index(name)
        self.page_stack.setCurrentIndex(page_index)


def main() -> None:
    """Initialise the database and start the desktop application."""

    connection = connect_database()

    try:
        initialise_database(connection)
    finally:
        connection.close()

    app = QApplication(sys.argv)
    app.setApplicationName("BudgetApp")
    app.setOrganizationName("BudgetApp")
    app.setStyleSheet(load_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
