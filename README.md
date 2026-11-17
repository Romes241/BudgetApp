
# BudgetApp

A personal finance desktop application built with Python, PySide6 and SQLite.

## Features

- Income tracking, payslip import and analysis
- UK take-home pay estimates based on saved payroll settings
- Fixed and variable expense budgets
- Debt tracking and repayment projections
- Cashflow forecasting with a running balance based on recorded income, savings and debt activity
- Savings goals and contribution tracking
- Financial analytics for recorded income, deductions, planned commitments and savings progress
- What-if payroll scenarios using temporary pay and spending assumptions
- SQLite data backups and restore, with an automatic safety backup before restoring
- A per-user Windows installer for sharing BudgetApp without requiring Python

## Technology Stack

- Python
- PySide6 / Qt
- SQLite
- pytest
- PyInstaller (Windows packaging)
- Inno Setup 7 (Windows installer)

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

## Build the Windows Installer

The installer is built on Windows. The person building it needs Python 3.12 and
Inno Setup 7 installed. Inno Setup 6 is also accepted as a compatibility
fallback. From the project root, run:

```powershell
.\packaging\build_windows.ps1
```

The installer is written to `dist\installer\BudgetApp-Setup-<version>.exe`.
Send that installer to other Windows x64 users; they do not need Python, Git,
or a development environment. The installer creates a Start Menu shortcut and
offers an optional desktop shortcut.

Each Windows account gets its own database and payslip folder under
`%APPDATA%\BudgetApp\BudgetApp`. Installing or uninstalling the application
does not remove that personal data. Use **Settings → Data backup** in the app
to back it up or move it to another computer.

The installer is per-user and does not require administrator access. It does not
include the developer's database, payslips, or other local financial data.

## Project Status

BudgetApp is under active development. Work in progress is tracked in GitHub
issues, and the current automated test suite can be run with `python -m pytest`.
