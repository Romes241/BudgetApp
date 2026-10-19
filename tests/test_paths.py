
from pathlib import Path

from budget_app.paths import (
    get_app_data_dir,
    get_database_path,
    get_payslip_dir,
)


def test_app_data_directory_is_created(tmp_path):
    data_dir = get_app_data_dir(tmp_path)

    assert data_dir == tmp_path / "BudgetApp"
    assert data_dir.is_dir()


def test_database_path_is_inside_app_data(tmp_path):
    database_path = get_database_path(tmp_path)

    assert database_path == (
        tmp_path / "BudgetApp" / "budget.db"
    )

    assert database_path.parent.is_dir()


def test_payslip_directory_is_created(tmp_path):
    payslip_dir = get_payslip_dir(tmp_path)

    assert payslip_dir == (
        tmp_path / "BudgetApp" / "payslips"
    )

    assert payslip_dir.is_dir()


def test_data_directory_is_reused(tmp_path):
    first = get_app_data_dir(tmp_path)
    second = get_app_data_dir(tmp_path)

    assert first == second
    assert Path(first).is_dir()
