"""Content-aware sizing helpers for form controls."""

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QLineEdit,
    QSizePolicy,
    QWidget,
)


def configure_form_controls(container: QWidget) -> None:
    """Size controls from their contents and let form rows adapt to available space."""

    for form in container.findChildren(QFormLayout):
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    for control in container.findChildren(QWidget):
        if isinstance(control, QLineEdit):
            control.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                control.sizePolicy().verticalPolicy(),
            )
            continue

        if isinstance(control, QComboBox):
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        elif not isinstance(control, (QDateEdit, QAbstractSpinBox)):
            continue

        control.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            control.sizePolicy().verticalPolicy(),
        )
        control.setMinimumWidth(
            max(
                control.minimumWidth(),
                control.minimumSizeHint().width(),
                control.sizeHint().width(),
            )
        )
