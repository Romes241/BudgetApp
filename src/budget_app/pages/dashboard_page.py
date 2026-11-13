"""At-a-glance personal finance dashboard."""

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.dashboard_service import get_dashboard_data
from budget_app.utils.money import format_money
from budget_app.utils.table import configure_table_header


class _BalanceChart(QWidget):
    """Draw a compact running-balance chart without an extra dependency."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.points: list[tuple[date, int]] = []
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_points(self, points: list[tuple[date, int]]) -> None:
        self.points = points
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(58, 12, -18, -34)
        painter.setPen(QPen(QColor("#30343d"), 1))
        for fraction in (0, 0.5, 1):
            y = area.top() + area.height() * fraction
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))

        if len(self.points) < 2:
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "No forecast data")
            return

        values = [value for _, value in self.points]
        minimum, maximum = min(0, min(values)), max(0, max(values))
        if minimum == maximum:
            maximum += 100
        spread = maximum - minimum
        first_date = self.points[0][0]
        last_date = self.points[-1][0]
        duration_days = max(1, (last_date - first_date).days)
        mapped = [
            QPointF(
                area.left()
                + area.width() * (point_date - first_date).days / duration_days,
                area.bottom() - (value - minimum) / spread * area.height(),
            )
            for point_date, value in self.points
        ]
        path = QPainterPath(mapped[0])
        for point in mapped[1:]:
            path.lineTo(point)
        painter.setPen(QPen(QColor("#a78bfa"), 2.5))
        painter.drawPath(path)

        painter.setPen(QColor("#9ca3af"))
        painter.drawText(4, int(area.top() + 5), format_money(maximum))
        painter.drawText(4, int(area.bottom()), format_money(minimum))
        for fraction, label in ((0, self.points[0][0]), (1, self.points[-1][0])):
            x = area.left() + area.width() * fraction
            painter.drawText(
                QRectF(x - 48, area.bottom() + 8, 96, 22),
                Qt.AlignmentFlag.AlignHCenter,
                label.strftime("%b %Y"),
            )


class DashboardPage(QWidget):
    """Show balances, near-term cashflow and concise savings/debt summaries."""

    navigate_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)

        title_row = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("pageHeading")
        subtitle = QLabel("A clear view of your current position and what’s ahead.")
        subtitle.setObjectName("secondaryText")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        title_row.addLayout(title_block)
        title_row.addStretch()
        refresh = QPushButton("Refresh")
        refresh.setObjectName("primaryButton")
        refresh.clicked.connect(self.refresh_dashboard)
        title_row.addWidget(refresh)
        layout.addLayout(title_row)

        self.cards: dict[str, QLabel] = {}
        card_grid = QGridLayout()
        card_grid.setSpacing(12)
        for index, (key, label) in enumerate(
            (
                ("balance", "Current balance"),
                ("closing", "Forecast end balance"),
                ("payday", "Next expected payday"),
                ("pay", "Estimated take-home pay"),
                ("savings", "Savings goals"),
                ("debt", "Outstanding debt"),
            )
        ):
            card = QFrame()
            card.setObjectName("summaryCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 13, 16, 13)
            card_layout.setSpacing(7)
            name = QLabel(label)
            name.setObjectName("summaryTitle")
            value = QLabel("—")
            value.setObjectName("summaryValue")
            value.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            card_grid.addWidget(card, index // 3, index % 3)
            self.cards[key] = value
        layout.addLayout(card_grid)

        balance_heading = QLabel("Projected balance")
        balance_heading.setObjectName("sectionHeading")
        layout.addWidget(balance_heading)
        self.chart = _BalanceChart()
        layout.addWidget(self.chart)

        upcoming_header = QHBoxLayout()
        upcoming_title = QLabel("Upcoming projected transactions")
        upcoming_title.setObjectName("sectionHeading")
        upcoming_header.addWidget(upcoming_title)
        upcoming_header.addStretch()
        cashflow_link = QPushButton("View cashflow")
        cashflow_link.setObjectName("smallButton")
        cashflow_link.clicked.connect(lambda: self.navigate_requested.emit("Cashflow"))
        upcoming_header.addWidget(cashflow_link)
        layout.addLayout(upcoming_header)

        self.transaction_table = QTableWidget(0, 5)
        self.transaction_table.setHorizontalHeaderLabels(
            ["Date", "Description", "Money in", "Money out", "Running balance"]
        )
        self.transaction_table.setObjectName("cashflowTable")
        self.transaction_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.transaction_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.transaction_table.setAlternatingRowColors(True)
        self.transaction_table.verticalHeader().setVisible(False)
        header = self.transaction_table.horizontalHeader()
        configure_table_header(header)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.transaction_table.setMaximumHeight(300)
        layout.addWidget(self.transaction_table)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("Savings and debt are based on active records."))
        footer.addStretch()
        for text, page in (
            ("Savings goals", "Savings Goals"),
            ("Debt management", "Debt Management"),
        ):
            button = QPushButton(text)
            button.setObjectName("smallButton")
            button.clicked.connect(
                lambda checked=False, target=page: self.navigate_requested.emit(target)
            )
            footer.addWidget(button)
        layout.addLayout(footer)
        self.status = QLabel("")
        self.status.setObjectName("secondaryText")
        layout.addWidget(self.status)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

    def refresh_dashboard(self) -> None:
        """Refresh all dashboard values from the existing application services."""
        try:
            data = get_dashboard_data()
            projection = data["projection"]
            balance = data["balance"]
            self.cards["balance"].setText(
                f"{format_money(balance['balance_pence'])}\n"
                f"Reconciled {balance['baseline_date']:%d/%m/%Y}"
            )
            self.cards["closing"].setText(
                f"{format_money(projection['closing_balance_pence'])}\n"
                f"By {projection['end_date']:%d/%m/%Y}"
            )
            pay = data["next_pay"]
            self.cards["payday"].setText(
                pay["date"].strftime("%d %b %Y") if pay else "Not configured"
            )
            self.cards["pay"].setText(
                format_money(pay["amount_pence"]) if pay else "Not available"
            )
            goals = data["savings_goals"]
            self.cards["savings"].setText(
                f"{format_money(data['savings_total_pence'])}\n{len(goals)} active goal(s)"
            )
            self.cards["debt"].setText(format_money(data["debt_total_pence"]))

            points = [(projection["start_date"], projection["opening_balance_pence"])]
            points.extend(
                (entry["date"], entry["running_balance_pence"])
                for entry in projection["entries"]
            )
            if points[-1][0] < projection["end_date"]:
                points.append(
                    (projection["end_date"], projection["closing_balance_pence"])
                )
            self.chart.set_points(points)

            entries = projection["entries"][:8]
            self.transaction_table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                values = (
                    entry["date"].strftime("%d/%m/%Y"),
                    entry["description"],
                    format_money(entry["money_in_pence"]),
                    format_money(entry["money_out_pence"]),
                    format_money(entry["running_balance_pence"]),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column in (2, 3, 4):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.transaction_table.setItem(row, column, item)
            self.status.setText(
                f"Updated {date.today():%d/%m/%Y} · forecast through {projection['end_date']:%d/%m/%Y}"
            )
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            self.chart.set_points([])
            self.transaction_table.setRowCount(0)
            self.status.setText(f"Dashboard could not be loaded: {exc}")
