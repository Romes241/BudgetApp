
import sys

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from budget_app import __version__


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("BudgetApp")
        self.resize(1100, 720)
        self.setMinimumSize(800, 550)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)

        heading = QLabel("BudgetApp")
        heading.setObjectName("heading")

        heading.setStyleSheet(
            """
            QLabel#heading {
                font-size: 28px;
                font-weight: bold;
            }
            """
        )

        description = QLabel(
            "Your personal finance dashboard."
        )

        description.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addStretch()

        self.setCentralWidget(central_widget)

        status_bar = QStatusBar(self)
        status_bar.showMessage(
            f"BudgetApp v{__version__}"
        )

        self.setStatusBar(status_bar)


def main():
    """Start the desktop application."""

    app = QApplication(sys.argv)

    app.setApplicationName("BudgetApp")
    app.setOrganizationName("BudgetApp")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
