from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "BudgetApp"
APP_AUTHOR = "BudgetApp"


def get_app_data_dir(
    base_dir: str | Path | None = None,
) -> Path:
    """Return the writable application-data directory.

    The optional base_dir is intended for tests. Normal application
    usage resolves the platform's standard user-data directory.
    """

    if base_dir is None:
        data_dir = Path(
            user_data_dir(
                APP_NAME,
                APP_AUTHOR,
            )
        )
    else:
        data_dir = Path(base_dir) / APP_NAME

    data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return data_dir


def get_database_path(
    base_dir: str | Path | None = None,
) -> Path:
    """Return the path for the application's SQLite database."""

    return get_app_data_dir(base_dir) / "budget.db"


def get_payslip_dir(
    base_dir: str | Path | None = None,
) -> Path:
    """Return the directory for incoming payslips."""

    directory = get_app_data_dir(base_dir) / "payslips"

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory
