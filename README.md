
# BudgetApp

A personal finance desktop application built with Python, PySide6 and SQLite.

## Features

- Income tracking, payslip import and analysis
- UK take-home pay estimates based on saved payroll settings
- Fixed and variable expense budgets
- Debt tracking and repayment projections
- Cashflow forecasting
- Savings goals and contribution tracking
- Financial analytics for recorded income, deductions, planned commitments and savings progress

## Planned

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

BudgetApp is under active development. Work in progress is tracked in GitHub
issues, and the current automated test suite can be run with `python -m pytest`.
