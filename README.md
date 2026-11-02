# PayDay Employee Management

PayDay is a Flask application for employee records, pay structures, attendance, and monthly payroll preparation. It uses SQLite for local data storage and serves its HTML pages from `static/` and `templates/`.

## Features

- Employee management, including active status and hire dates.
- Employee personal, bank, and compensation details.
- Pay structures with one active structure per employee and an employment type: permanent, contractor, or contingent.
- Attendance search by employee ID, date, and status; attendance entry and editing are available for active employees with an active pay structure.
- A work calendar with Sundays and India national/festival holidays treated as non-working days by default. Monday through Saturday are working by default; weekday overrides can mark a date non-working or restore it as working.
- Monthly payroll drafts with itemized lines and totals, exception review, approval, and payment-status tracking.

The application records payroll and payment statuses; it does not initiate a bank transfer. The legacy `/process_pay` endpoint is disabled.

## Requirements

- Windows, macOS, or Linux.
- Python 3.10 or later (the project has been exercised with Python 3.14).
- Dependencies listed in `requirements.txt`.
- A project SQLite database named `Paydaytest.db` in the repository root. Database files are excluded from Git, so a fresh clone must receive an approved database file or be provisioned with the required employee tables before starting the application.

## Setup on Windows PowerShell

From the repository directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Place the approved `Paydaytest.db` in the repository root. The database contains employee and payroll data and should be handled as confidential; do not commit it.

Start the development server:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. Register an account, sign in, and use the Home page to navigate between modules. The app creates/updates its application schemas on startup. Before the first payroll schema migration on a database, it creates a sibling `Paydaytest.pre_payroll.db` backup if that backup does not already exist. Back up the database separately before making operational changes.

## Main Pages

- `/employee_details` — add and search employee records.
- `/personal_details` — manage employee personal details.
- `/pay_structure` — search/add pay structures and set employment type. Search by employee ID to review that employee's pay structure and type.
- `/attendance` — search attendance by employee ID, exact date, and/or status; mark and edit attendance; open the work calendar.
- `/pay` — generate, review, approve, and track a monthly payroll run.
- `/bank-details` — manage employee bank details.
- `/compensation-details` — manage compensation components.
- `/reports` — reports landing page.

Application pages require a signed-in session, except login, registration, and static assets.

## Payroll Rules

- Payroll basis is the employee's single active `pay_structure.salary` with a monthly pay term. Unsupported terms, missing classification, invalid salary, and missing/ambiguous active pay structures are exceptions that must be resolved before approval.
- Permanent employees hired and active by the cutoff receive the full monthly amount.
- Contractor and contingent employees are paid in proportion to present scheduled workdays: monthly salary divided by scheduled workdays in the period, multiplied by present workdays through the cutoff. Amounts are rounded to two decimal places.
- Scheduled days come from the work calendar. Sundays and India holidays from the `holidays` package default to non-working. A weekday override may change whether it is scheduled. Sundays cannot be overridden.
- `pd_compensation` fields are not included in payroll totals; tax/deduction and net-pay calculations are not implemented.
- Draft runs can be refreshed. Once approved, the period's cutoff is locked. Payment records are created as pending after approval, then their statuses can be tracked. The app does not connect to a bank or transfer money.

## Tests

Run the payroll tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The tests cover payroll calculation, draft refresh behavior, holiday/workday rules, schema migration repeatability, and preservation of historical payment rows.

## Data and Backups

`Paydaytest.db`, SQLite backups, and other `*.db` files are ignored by Git. Keep a protected backup before modifying or clearing employee, attendance, pay-structure, payroll-run, or payment data. The file `Paydaytest.sqbpro` is a SQLite browser project file, not a substitute for the database itself.
