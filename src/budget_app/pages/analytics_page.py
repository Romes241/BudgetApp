"""Historical income and planned-commitment analytics page."""

import sqlite3
from typing import Any, ClassVar

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_app.services.analytics_service import get_financial_analytics
from budget_app.utils.money import format_money


def _compact_money(amount_pence: int) -> str:
    """Short currency labels for chart axes."""
    pounds = amount_pence / 100
    if pounds >= 1_000_000:
        return f"£{pounds / 1_000_000:.1f}m"
    if pounds >= 1_000:
        return f"£{pounds / 1_000:.0f}k"
    return f"£{pounds:.0f}"


class IncomeChart(QWidget):
    """Paint a simple monthly gross-versus-net income bar chart."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.months: list[dict[str, Any]] = []
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_months(self, months: list[dict[str, Any]]) -> None:
        self.months = months
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart = self.rect().adjusted(58, 34, -18, -42)
        if not chart.isValid():
            return

        values = [month["gross_pay_pence"] for month in self.months]
        maximum = max(values, default=0)
        if maximum <= 0:
            painter.setPen(QColor("#a1a1aa"))
            painter.drawText(chart, Qt.AlignmentFlag.AlignCenter, "No recorded income")
            return

        maximum = max(100, int(maximum * 1.15))
        painter.setFont(self.font())
        painter.setPen(QPen(QColor("#41444d"), 1))
        for step in range(5):
            value = maximum * step / 4
            y = chart.bottom() - chart.height() * step / 4
            painter.drawLine(chart.left(), round(y), chart.right(), round(y))
            painter.setPen(QColor("#a1a1aa"))
            painter.drawText(
                0,
                round(y - 9),
                50,
                18,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _compact_money(round(value)),
            )
            painter.setPen(QPen(QColor("#41444d"), 1))

        slot_width = chart.width() / max(1, len(self.months))
        bar_width = min(22, slot_width * 0.32)
        for index, month in enumerate(self.months):
            centre = chart.left() + slot_width * (index + 0.5)
            for offset, key, colour in (
                (-bar_width / 2, "gross_pay_pence", "#86efac"),
                (bar_width / 2, "net_pay_pence", "#60a5fa"),
            ):
                amount = month[key]
                height = chart.height() * amount / maximum
                painter.fillRect(
                    round(centre + offset),
                    round(chart.bottom() - height),
                    max(2, round(bar_width)),
                    max(0, round(height)),
                    QColor(colour),
                )
            painter.setPen(QColor("#d4d4d8"))
            painter.drawText(
                round(centre - slot_width / 2),
                chart.bottom() + 8,
                round(slot_width),
                24,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                month["label"],
            )

        painter.fillRect(self.width() - 150, 8, 10, 10, QColor("#86efac"))
        painter.setPen(QColor("#d4d4d8"))
        painter.drawText(self.width() - 136, 18, "Gross")
        painter.fillRect(self.width() - 82, 8, 10, 10, QColor("#60a5fa"))
        painter.drawText(self.width() - 68, 18, "Net")


class CommitmentAllocationChart(QWidget):
    """Show how planned monthly commitments relate to take-home income."""

    COLOURS: ClassVar[dict[str, str]] = {
        "Fixed expenses": "#f87171",
        "Variable budgets": "#fb923c",
        "Debt payments": "#c084fc",
        "Savings contributions": "#38bdf8",
        "Remaining income": "#4b5563",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.commitments: list[dict[str, Any]] = []
        self.monthly_income_pence: int | None = None
        self.income_label = "Monthly take-home"
        self.view_mode = "stacked"
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(
        self,
        commitments: list[dict[str, Any]],
        monthly_income_pence: int | None,
        income_label: str,
        view_mode: str,
    ) -> None:
        self.commitments = commitments
        self.monthly_income_pence = monthly_income_pence
        self.income_label = income_label
        self.view_mode = view_mode
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rows = [item for item in self.commitments if item["amount_pence"] > 0]
        if not rows:
            painter.setPen(QColor("#a1a1aa"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No active planned commitments",
            )
            return
        if self.view_mode == "donut":
            self._draw_donut(painter, rows)
        else:
            self._draw_stacked_bar(painter, rows)

    def _draw_stacked_bar(self, painter: QPainter, rows: list[dict[str, Any]]) -> None:
        width = self.width()
        total = sum(item["amount_pence"] for item in rows)
        income = self.monthly_income_pence or 0
        has_income_baseline = self.monthly_income_pence is not None
        scale = max(total, income)
        if scale <= 0:
            return

        painter.setFont(self.font())
        if has_income_baseline:
            painter.setPen(QColor("#e4e4e7"))
            painter.drawText(
                8,
                24,
                f"{self.income_label}: {format_money(income)} per month",
            )
        else:
            painter.setPen(QColor("#fbbf24"))
            painter.drawText(8, 24, "Income estimate unavailable")
        painter.setPen(QColor("#e4e4e7"))
        commitment_label = f"Planned commitments: {format_money(total)} per month"
        if has_income_baseline and total > income:
            commitment_label += f"  ·  Over by {format_money(total - income)}"
        painter.drawText(8, 48, commitment_label)

        bar_x = 8
        bar_y = 68
        bar_width = max(20, width - 24)
        bar_height = 30
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#30343d"))
        painter.drawRoundedRect(bar_x, bar_y, bar_width, bar_height, 6, 6)

        if total < income:
            display_rows = [
                *rows,
                {"category": "Remaining income", "amount_pence": income - total},
            ]
        else:
            display_rows = rows

        current_x = bar_x
        for item in display_rows:
            segment_width = bar_width * item["amount_pence"] / scale
            painter.setBrush(QColor(self.COLOURS[item["category"]]))
            painter.drawRect(
                round(current_x),
                bar_y,
                max(0, round(segment_width)),
                bar_height,
            )
            current_x += segment_width

        if has_income_baseline:
            income_x = bar_x + round(bar_width * income / scale)
            painter.setPen(QPen(QColor("#ffffff"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(income_x, bar_y - 8, income_x, bar_y + bar_height + 8)

        legend_rows = [
            (item["category"], item["amount_pence"]) for item in display_rows
        ]
        if not has_income_baseline:
            legend_rows = [(item["category"], item["amount_pence"]) for item in rows]
        left = 8
        column_width = max(200, (width - 24) // 2)
        for index, (name, amount) in enumerate(legend_rows):
            column = index % 2
            row = index // 2
            x = left + column * column_width
            y = 128 + row * 32
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.COLOURS[name]))
            painter.drawRoundedRect(x, y + 4, 12, 12, 3, 3)
            painter.setPen(QColor("#d4d4d8"))
            painter.drawText(x + 20, y + 16, name)
            painter.drawText(
                x + column_width - 100,
                y + 16,
                92,
                18,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_money(amount),
            )

    def _draw_donut(self, painter: QPainter, rows: list[dict[str, Any]]) -> None:
        total = sum(item["amount_pence"] for item in rows)
        income = self.monthly_income_pence or 0
        has_unallocated_income = income > total
        denominator = income if has_unallocated_income else total
        parts = [
            {"category": item["category"], "amount_pence": item["amount_pence"]}
            for item in rows
        ]
        if has_unallocated_income:
            parts.append(
                {"category": "Remaining income", "amount_pence": income - total}
            )

        diameter = min(204, self.height() - 24, self.width() // 3)
        pie = QRectF(12, 12, diameter, diameter)
        angle = 90 * 16
        for part in parts:
            span = round(part["amount_pence"] / denominator * 360 * 16)
            painter.setPen(QPen(QColor("#111318"), 2))
            painter.setBrush(QColor(self.COLOURS[part["category"]]))
            painter.drawPie(pie, angle, span)
            angle += span

        inner = pie.adjusted(
            diameter * 0.25, diameter * 0.25, -diameter * 0.25, -diameter * 0.25
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111318"))
        painter.drawEllipse(inner)
        painter.setPen(QColor("#9ca3af"))
        centre_title = "Income baseline" if has_unallocated_income else "Planned"
        centre_value = income if has_unallocated_income else total
        painter.drawText(
            inner,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{centre_title}\n{format_money(centre_value)}",
        )

        legend_x = diameter + 36
        available_width = max(120, self.width() - legend_x - 12)
        row_height = max(30, (self.height() - 24) // len(parts))
        for index, part in enumerate(parts):
            y = 12 + index * row_height
            percentage = round(part["amount_pence"] * 100 / denominator)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.COLOURS[part["category"]]))
            painter.drawRoundedRect(legend_x, y + 6, 12, 12, 3, 3)
            painter.setPen(QColor("#d4d4d8"))
            painter.drawText(legend_x + 20, y + 18, part["category"])
            painter.drawText(
                legend_x,
                y + 18,
                available_width,
                18,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{format_money(part['amount_pence'])}  ·  {percentage}%",
            )


class AnalyticsPage(QWidget):
    """Show recorded income, planned commitments, and savings progress."""

    INCOME_HEADERS: ClassVar[list[str]] = [
        "Month",
        "Gross",
        "PAYE",
        "NI",
        "Pension",
        "Other",
        "Net",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.analytics: dict[str, Any] | None = None
        self._build_ui()
        self.refresh_analytics()

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

        header = QHBoxLayout()
        heading_stack = QVBoxLayout()
        heading_stack.setSpacing(5)
        title = QLabel("Analytics")
        title.setObjectName("pageHeading")
        subtitle = QLabel(
            "Review recorded income separately from your current planned commitments."
        )
        subtitle.setObjectName("secondaryText")
        subtitle.setWordWrap(True)
        heading_stack.addWidget(title)
        heading_stack.addWidget(subtitle)
        header.addLayout(heading_stack, 1)

        self.period_input = QComboBox()
        self.period_input.addItem("Last 3 months", 3)
        self.period_input.addItem("Last 6 months", 6)
        self.period_input.addItem("Last 12 months", 12)
        self.period_input.setCurrentIndex(1)
        self.period_input.currentIndexChanged.connect(self.refresh_analytics)
        header.addWidget(self.period_input)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh_analytics)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.income_heading = QLabel("Recorded income")
        self.income_heading.setObjectName("sectionHeading")
        layout.addWidget(self.income_heading)
        income_note = QLabel(
            "Actual payslip totals for the selected period. Months without a recorded payslip show as £0.00."
        )
        income_note.setObjectName("secondaryText")
        income_note.setWordWrap(True)
        layout.addWidget(income_note)

        self.income_chart = IncomeChart()
        self.income_chart.setObjectName("analyticsIncomeChart")
        layout.addWidget(self.income_chart)

        self.income_empty_label = QLabel("No payslip income recorded for this period.")
        self.income_empty_label.setObjectName("secondaryText")
        self.income_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.income_empty_label)

        self.income_table = self._create_table(self.INCOME_HEADERS)
        self.income_table.setObjectName("analyticsIncomeTable")
        layout.addWidget(self.income_table)

        self.planned_heading = QLabel("Current planned commitments")
        self.planned_heading.setObjectName("sectionHeading")
        layout.addWidget(self.planned_heading)
        planned_note = QLabel(
            "Monthly amounts from active fixed expenses, variable budgets, debt payments, and savings contributions. These are plans, not recorded spending."
        )
        planned_note.setObjectName("secondaryText")
        planned_note.setWordWrap(True)
        layout.addWidget(planned_note)

        view_selector = QHBoxLayout()
        view_label = QLabel("Visualisation")
        view_label.setObjectName("secondaryText")
        view_selector.addWidget(view_label)
        self.stacked_view_button = self._create_view_button("Stacked bar", True)
        self.donut_view_button = self._create_view_button("Donut chart", False)
        self.commitment_view_group = QButtonGroup(self)
        self.commitment_view_group.setExclusive(True)
        self.commitment_view_group.addButton(self.stacked_view_button)
        self.commitment_view_group.addButton(self.donut_view_button)
        self.stacked_view_button.clicked.connect(
            lambda: self._set_commitment_view("stacked")
        )
        self.donut_view_button.clicked.connect(
            lambda: self._set_commitment_view("donut")
        )
        view_selector.addWidget(self.stacked_view_button)
        view_selector.addWidget(self.donut_view_button)
        view_selector.addStretch()
        layout.addLayout(view_selector)

        self.commitment_view_mode = "stacked"
        self.commitment_view_note = QLabel("")
        self.commitment_view_note.setObjectName("secondaryText")
        self.commitment_view_note.setWordWrap(True)
        layout.addWidget(self.commitment_view_note)

        self.commitment_chart = CommitmentAllocationChart()
        self.commitment_chart.setObjectName("analyticsCommitmentChart")
        layout.addWidget(self.commitment_chart)
        self.commitment_empty_label = QLabel("No active planned commitments.")
        self.commitment_empty_label.setObjectName("secondaryText")
        self.commitment_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.commitment_empty_label)
        self.planned_total_label = QLabel("")
        self.planned_total_label.setObjectName("sectionHeading")
        layout.addWidget(self.planned_total_label)

        self.goals_heading = QLabel("Savings goal progress")
        self.goals_heading.setObjectName("sectionHeading")
        layout.addWidget(self.goals_heading)
        self.goals_container = QVBoxLayout()
        self.goals_container.setSpacing(10)
        layout.addLayout(self.goals_container)
        self.goals_empty_label = QLabel("No active savings goals.")
        self.goals_empty_label.setObjectName("secondaryText")
        layout.addWidget(self.goals_empty_label)
        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    @staticmethod
    def _create_view_button(text: str, checked: bool) -> QPushButton:
        """Create a checkable visualisation selector button."""
        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(checked)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setObjectName("filterButton")
        return button

    def _set_commitment_view(self, mode: str) -> None:
        self.commitment_view_mode = mode
        if self.analytics is not None:
            self._show_commitment_chart()

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        return table

    def refresh_analytics(self, *_args) -> None:
        """Reload analytics for the selected number of months."""
        self.refresh_button.setEnabled(False)
        try:
            self.analytics = get_financial_analytics(
                months=self.period_input.currentData()
            )
            self._show_analytics()
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            sqlite3.Error,
        ) as exc:
            self.analytics = None
            QMessageBox.critical(
                self,
                "Analytics error",
                f"Could not load financial analytics:\n\n{exc}",
            )
        finally:
            self.refresh_button.setEnabled(True)

    def _show_analytics(self) -> None:
        if self.analytics is None:
            return
        months = self.analytics["income_months"]
        has_income = self.analytics["has_income_history"]
        self.income_chart.set_months(months)
        self.income_chart.setVisible(has_income)
        self.income_empty_label.setVisible(not has_income)
        self.income_table.setVisible(has_income)
        self._show_income_table(months)

        has_commitments = self.analytics["has_planned_commitments"]
        self._show_commitment_chart()
        self.commitment_chart.setVisible(has_commitments)
        self.commitment_empty_label.setVisible(not has_commitments)
        self.planned_total_label.setText(
            "Total planned per month: "
            + format_money(self.analytics["planned_monthly_total_pence"])
            if has_commitments
            else ""
        )
        self.planned_total_label.setVisible(has_commitments)
        self._show_savings_goals(self.analytics["savings_goals"])

    def _show_commitment_chart(self) -> None:
        if self.analytics is None:
            return
        income = self.analytics["monthly_income_baseline_pence"]
        total = self.analytics["planned_monthly_total_pence"]
        self.commitment_chart.set_data(
            self.analytics["planned_commitments"],
            income,
            self.analytics["income_baseline_label"],
            self.commitment_view_mode,
        )
        if self.commitment_view_mode == "stacked":
            if income is None:
                explanation = "Income is unavailable, so the bar shows the relative planned amounts only. "
            elif total > income:
                explanation = (
                    f"The dashed marker is the monthly income baseline; commitments "
                    f"exceed it by {format_money(total - income)} per month. "
                )
            else:
                explanation = (
                    "The dashed marker is the monthly income baseline; the remaining segment "
                    "shows income left after planned commitments. "
                )
        elif income is not None and total <= income:
            explanation = (
                "The donut shows each commitment category as a share of the monthly "
                "income baseline, including the amount left over. "
            )
        elif income is not None:
            explanation = (
                f"Commitments exceed the monthly income baseline by {format_money(total - income)}; "
                "the donut shows each category's share of total commitments. "
            )
        else:
            explanation = "The donut shows each category's share of total commitments. "
        self.commitment_view_note.setText(
            explanation + self.analytics["income_baseline_note"]
        )

    def _show_income_table(self, months: list[dict[str, Any]]) -> None:
        self.income_table.setRowCount(len(months))
        keys = (
            "label",
            "gross_pay_pence",
            "tax_paid_pence",
            "ni_paid_pence",
            "pension_paid_pence",
            "other_deductions_pence",
            "net_pay_pence",
        )
        for row_index, month in enumerate(months):
            for column, key in enumerate(keys):
                value = month[key] if column == 0 else format_money(month[key])
                item = QTableWidgetItem(str(value))
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.income_table.setItem(row_index, column, item)
        self.income_table.resizeRowsToContents()
        self.income_table.setMinimumHeight(42 + len(months) * 34)

    def _show_savings_goals(self, goals: list[dict[str, Any]]) -> None:
        while self.goals_container.count():
            item = self.goals_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.goals_empty_label.setVisible(not goals)
        for goal in goals:
            row = QVBoxLayout()
            label = QLabel(
                f"{goal['name']}  ·  {format_money(goal['current_amount_pence'])} of "
                f"{format_money(goal['target_amount_pence'])}"
            )
            label.setObjectName("secondaryText")
            progress = QProgressBar()
            progress.setObjectName("savingsProgress")
            progress.setRange(0, 100)
            progress.setValue(goal["progress_percent"])
            progress.setFormat(f"{goal['progress_percent']}%")
            row.addWidget(label)
            row.addWidget(progress)
            container = QWidget()
            container.setLayout(row)
            self.goals_container.addWidget(container)
