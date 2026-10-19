
# BudgetApp

A personal finance desktop application built with Python, PySide6 and SQLite.

## Planned Features

- Income tracking and payslip analysis
- Salary and take-home pay estimation
- Fixed and variable expense management
- Debt tracking and repayment projections
- Cashflow forecasting
- Savings goals
- Financial analytics
- What-if financial simulator

## Technology Stack

- Python
- PySide6 / Qt
- SQLite
- pytest
- PyInstaller (planned for distribution)

## Development Setup

Requires Python 3.12.

Clone the repository and enter the project directory:

```bash
git clone https://github.com/Romes241/BudgetApp.git
cd BudgetApp
```

Create and activate a virtual environment on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project and development dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run the Application

```powershell
python -m budget_app
```

## Run Tests

```powershell
python -m pytest
```

## Project Status

Early development. Features will be implemented incrementally with
automated tests.
