from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import holidays


EMPLOYMENT_TYPES = {"permanent", "contractor", "contingent"}
PAYMENT_STATUSES = {"pending", "completed", "failed"}


class PayrollError(ValueError):
    """Raised when payroll input or state is invalid."""


def ensure_payroll_schema(connection: sqlite3.Connection) -> None:
    """Apply additive payroll schema changes without rewriting existing records."""
    database_path = connection.execute("PRAGMA database_list").fetchone()[2]
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    employee_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(pd_employees)")
    }
    payment_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(payments)")
    }
    payroll_tables = {"attendance_daily", "work_calendar", "payroll_runs", "payroll_lines"}
    migration_needed = (
        not payroll_tables.issubset(tables)
        or "employment_type" not in employee_columns
        or "payroll_line_id" not in payment_columns
    )
    if database_path and migration_needed:
        source = Path(database_path)
        backup_path = source.with_name(f"{source.stem}.pre_payroll{source.suffix}")
        if not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                connection.backup(backup)
            finally:
                backup.close()

    connection.execute(
        """CREATE TABLE IF NOT EXISTS attendance_daily (
            attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            empid INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'leave')),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (empid, work_date)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS work_calendar (
            work_date TEXT PRIMARY KEY,
            is_working_day INTEGER NOT NULL CHECK (is_working_day IN (0, 1)),
            description TEXT
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS pay_term_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS payroll_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            cutoff_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'approved', 'partially_paid', 'paid', 'cancelled')),
            currency TEXT NOT NULL DEFAULT 'INR',
            total_minor INTEGER NOT NULL DEFAULT 0,
            employee_count INTEGER NOT NULL DEFAULT 0,
            exception_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (period_start, period_end)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS payroll_lines (
            line_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES payroll_runs(run_id) ON DELETE CASCADE,
            empid INTEGER NOT NULL,
            source_pay_structure_id INTEGER,
            employee_name TEXT NOT NULL,
            employment_type TEXT,
            pay_group TEXT,
            pay_term TEXT,
            monthly_salary REAL,
            currency TEXT NOT NULL DEFAULT 'INR',
            scheduled_days INTEGER NOT NULL DEFAULT 0,
            present_days INTEGER NOT NULL DEFAULT 0,
            amount_minor INTEGER NOT NULL DEFAULT 0,
            line_status TEXT NOT NULL CHECK (line_status IN ('ready', 'exception')),
            payment_status TEXT NOT NULL DEFAULT 'unrecorded'
                CHECK (payment_status IN ('unrecorded', 'pending', 'completed', 'failed', 'not_payable')),
            exception_message TEXT,
            UNIQUE (run_id, empid)
        )"""
    )

    employee_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(pd_employees)")
    }
    if "employment_type" not in employee_columns:
        connection.execute(
            """ALTER TABLE pd_employees ADD COLUMN employment_type TEXT
               CHECK (employment_type IS NULL OR employment_type IN
                      ('permanent', 'contractor', 'contingent'))"""
        )

    payment_columns = {row[1] for row in connection.execute("PRAGMA table_info(payments)")}
    if "payroll_line_id" not in payment_columns:
        connection.execute(
            """ALTER TABLE payments ADD COLUMN payroll_line_id INTEGER
               REFERENCES payroll_lines(line_id)"""
        )

    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_payroll_line
           ON payments(payroll_line_id) WHERE payroll_line_id IS NOT NULL"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_attendance_emp_date ON attendance_daily(empid, work_date)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_payroll_lines_run ON payroll_lines(run_id, line_status)"
    )


def parse_iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise PayrollError(f"{field_name} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PayrollError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc


def month_bounds(cutoff: date) -> tuple[date, date]:
    month_end = date(cutoff.year, cutoff.month, calendar.monthrange(cutoff.year, cutoff.month)[1])
    return date(cutoff.year, cutoff.month, 1), month_end


def normalize_pay_term(value: Any) -> str:
    text = str(value or "").strip().lower().replace('_', '-')
    aliases = {
        'one-time': 'one_time',
        'one time': 'one_time',
        'bi-weekly': 'bi_weekly',
        'bi weekly': 'bi_weekly',
        'weekly': 'weekly',
        'daily': 'daily',
        'monthly': 'monthly',
    }
    return aliases.get(text, text)


def get_pay_term_setting(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute(
        'SELECT setting_value FROM pay_term_settings WHERE setting_key = ?',
        (key,),
    ).fetchone()
    return row['setting_value'] if row else default


def set_pay_term_setting(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        '''INSERT INTO pay_term_settings (setting_key, setting_value) VALUES (?, ?)
           ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value,
           updated_at = CURRENT_TIMESTAMP''',
        (key, str(value)),
    )


def pay_term_period_bounds(connection: sqlite3.Connection, pay_term: Any, cutoff: date) -> tuple[date, date]:
    normalized = normalize_pay_term(pay_term)
    if normalized == 'daily':
        return date(cutoff.year, cutoff.month, 1), cutoff
    if normalized == 'monthly':
        month_start = date(cutoff.year, cutoff.month, 1)
        month_days = scheduled_workdays(connection, month_start, date(cutoff.year, cutoff.month, calendar.monthrange(cutoff.year, cutoff.month)[1]))
        month_end = month_days[-1] if month_days else date(cutoff.year, cutoff.month, calendar.monthrange(cutoff.year, cutoff.month)[1])
        return month_start, month_end
    if normalized == 'weekly':
        weekday = int(get_pay_term_setting(connection, 'weekly_cutoff_weekday', '3'))
        week_start = cutoff - timedelta(days=cutoff.weekday())
        week_end = week_start + timedelta(days=weekday)
        return week_start, min(week_end, cutoff)
    if normalized == 'bi_weekly':
        weekday = int(get_pay_term_setting(connection, 'bi_weekly_cutoff_weekday', '3'))
        current_week_start = cutoff - timedelta(days=cutoff.weekday())
        period_end = current_week_start + timedelta(days=weekday)
        if cutoff < period_end:
            period_start = current_week_start - timedelta(days=7)
        else:
            period_start = current_week_start - timedelta(days=7)
        return period_start, period_end
    if normalized == 'one_time':
        return cutoff, cutoff
    return month_bounds(cutoff)


def calendar_day_details(
    connection: sqlite3.Connection, start: date, end: date
) -> list[dict[str, Any]]:
    india_holidays = holidays.country_holidays(
        "IN", years=range(start.year, end.year + 1)
    )
    overrides = {
        row[0]: {"is_working_day": bool(row[1]), "description": row[2]}
        for row in connection.execute(
            "SELECT work_date, is_working_day, description FROM work_calendar "
            "WHERE work_date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        )
    }
    days: list[dict[str, Any]] = []
    current = start
    while current <= end:
        is_sunday = current.weekday() == 6
        holiday_name = str(india_holidays.get(current, ""))
        override = overrides.get(current.isoformat())
        default_working = not is_sunday and not holiday_name
        is_working_day = False if is_sunday else (
            override["is_working_day"] if override else default_working
        )
        description = (
            "Sunday" if is_sunday else
            (override["description"] if override and override["description"] else holiday_name)
        )
        days.append({
            "work_date": current.isoformat(),
            "weekday": current.strftime("%A"),
            "weekday_number": current.weekday(),
            "is_working_day": is_working_day,
            "is_holiday": is_sunday or bool(holiday_name) or bool(override and not is_working_day),
            "holiday_name": "Sunday" if is_sunday else holiday_name,
            "description": description,
            "is_override": override is not None,
            "can_override": not is_sunday,
        })
        current += timedelta(days=1)
    return days


def scheduled_workdays(
    connection: sqlite3.Connection, start: date, end: date
) -> list[date]:
    return [
        date.fromisoformat(day["work_date"])
        for day in calendar_day_details(connection, start, end)
        if day["is_working_day"]
    ]


def _minor_units(value: Any) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayrollError("Salary must be a valid amount") from exc
    return int(amount * 100)


def _employee_name(employee: sqlite3.Row) -> str:
    name = f"{employee['first_name'] or ''} {employee['last_name'] or ''}".strip()
    return name or f"Employee {employee['empid']}"


def calculate_payroll_lines(
    connection: sqlite3.Connection, period_start: date, period_end: date, cutoff: date
) -> list[dict[str, Any]]:
    """Build server-authoritative line snapshots; unresolved data becomes an exception line."""
    month_workdays = scheduled_workdays(connection, period_start, period_end)
    through_cutoff = scheduled_workdays(connection, period_start, cutoff)
    expected_by_cutoff = {day for day in through_cutoff}
    lines: list[dict[str, Any]] = []

    employees = connection.execute(
        """SELECT empid, first_name, last_name, hire_date, is_active, employment_type
           FROM pd_employees WHERE is_active = 1 ORDER BY empid"""
    ).fetchall()
    for employee in employees:
        try:
            hire_date = parse_iso_date(employee["hire_date"], "hire_date")
        except PayrollError:
            lines.append(_exception_line(employee, "Missing or invalid hire date"))
            continue
        if hire_date > cutoff:
            continue

        structures = connection.execute(
            """SELECT id, pay_term, salary, pay_group FROM pay_structure
               WHERE empid = ? AND active = 1 ORDER BY id""",
            (employee["empid"],),
        ).fetchall()
        structure = structures[0] if len(structures) == 1 else None
        problems = []
        if not employee["employment_type"]:
            problems.append("Employment type is not classified")
        elif employee["employment_type"] not in EMPLOYMENT_TYPES:
            problems.append("Employment type is invalid")
        if not structures:
            problems.append("No active pay structure")
        elif len(structures) > 1:
            problems.append("Multiple active pay structures")
        if len(structures) == 1:
            pay_term = normalize_pay_term(structure["pay_term"])
            if not pay_term:
                problems.append("Active pay term is blank")
            try:
                salary_minor = _minor_units(structure["salary"])
                if salary_minor <= 0:
                    problems.append("Salary is missing or not positive")
            except PayrollError:
                salary_minor = 0
                problems.append("Salary is invalid")
        else:
            salary_minor = 0

        problem = "; ".join(problems) or None

        line = {
            "empid": employee["empid"],
            "source_pay_structure_id": structure["id"] if structure else None,
            "employee_name": _employee_name(employee),
            "employment_type": employee["employment_type"],
            "pay_group": structure["pay_group"] if structure else None,
            "pay_term": structure["pay_term"] if structure else None,
            "monthly_salary": structure["salary"] if structure else None,
            "currency": "INR",
            "scheduled_days": 0,
            "present_days": 0,
            "amount_minor": 0,
            "line_status": "exception" if problem else "ready",
            "payment_status": "unrecorded",
            "exception_message": problem,
        }
        if problem:
            lines.append(line)
            continue

        pay_term = normalize_pay_term(structure["pay_term"])
        period_start, period_end = pay_term_period_bounds(connection, pay_term, cutoff)
        period_days = scheduled_workdays(connection, period_start, period_end)
        line["scheduled_days"] = len(period_days)
        attendance_start = max(period_start, hire_date)
        expected_days = {
            day.isoformat() for day in scheduled_workdays(connection, attendance_start, cutoff)
        }
        attendance_rows = connection.execute(
            """SELECT work_date, status FROM attendance_daily
               WHERE empid = ? AND work_date BETWEEN ? AND ?""",
            (employee["empid"], attendance_start.isoformat(), cutoff.isoformat()),
        ).fetchall()
        recorded = {row["work_date"]: row["status"] for row in attendance_rows}
        missing_days = expected_days.difference(recorded)
        line["present_days"] = sum(
            1 for day in expected_days
            if recorded.get(day) == "present"
        )

        if employee["employment_type"] == "permanent" and pay_term == 'monthly':
            line["amount_minor"] = salary_minor
            line["present_days"] = len(
                [day for day in period_days if day <= cutoff and day >= hire_date]
            )
        elif pay_term == 'daily':
            if not period_days:
                line["line_status"] = "exception"
                line["exception_message"] = "Payroll period has no scheduled workdays"
            else:
                line["amount_minor"] = _minor_units(Decimal(salary_minor) * Decimal(line["present_days"]) / Decimal(100))
                if line["amount_minor"] == 0:
                    line["payment_status"] = "not_payable"
        elif pay_term == 'one_time':
            line["amount_minor"] = salary_minor
            if cutoff < date.today():
                line["payment_status"] = 'pending'
        else:
            if missing_days:
                line["line_status"] = "exception"
                line["exception_message"] = (
                    f"Attendance is incomplete: {len(missing_days)} scheduled day(s) have no record"
                )
            elif not period_days:
                line["line_status"] = "exception"
                line["exception_message"] = "Payroll period has no scheduled workdays"
            else:
                amount = (
                    Decimal(salary_minor)
                    / Decimal(100)
                    * Decimal(line["present_days"])
                    / Decimal(len(period_days) or 1)
                )
                line["amount_minor"] = _minor_units(amount)
                if line["amount_minor"] == 0:
                    line["payment_status"] = "not_payable"
        lines.append(line)
    return lines


def _exception_line(employee: sqlite3.Row, message: str) -> dict[str, Any]:
    return {
        "empid": employee["empid"],
        "source_pay_structure_id": None,
        "employee_name": _employee_name(employee),
        "employment_type": employee["employment_type"],
        "pay_group": None,
        "pay_term": None,
        "monthly_salary": None,
        "currency": "INR",
        "scheduled_days": 0,
        "present_days": 0,
        "amount_minor": 0,
        "line_status": "exception",
        "payment_status": "unrecorded",
        "exception_message": message,
    }


def create_or_refresh_run(connection: sqlite3.Connection, cutoff: date) -> int:
    period_start, period_end = month_bounds(cutoff)
    existing = connection.execute(
        """SELECT run_id, cutoff_date, status FROM payroll_runs
           WHERE period_start = ? AND period_end = ?""",
        (period_start.isoformat(), period_end.isoformat()),
    ).fetchone()
    if existing:
        if existing["status"] != "draft":
            if existing["cutoff_date"] != cutoff.isoformat():
                raise PayrollError(
                    "An approved payroll run already exists for this month with a different cutoff date"
                )
            return int(existing["run_id"])
        run_id = int(existing["run_id"])
        connection.execute(
            "UPDATE payroll_runs SET cutoff_date = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (cutoff.isoformat(), run_id),
        )
        connection.execute("DELETE FROM payroll_lines WHERE run_id = ?", (run_id,))
    else:
        cursor = connection.execute(
            """INSERT INTO payroll_runs
               (period_start, period_end, cutoff_date, status, currency)
               VALUES (?, ?, ?, 'draft', 'INR')""",
            (period_start.isoformat(), period_end.isoformat(), cutoff.isoformat()),
        )
        run_id = int(cursor.lastrowid)

    lines = calculate_payroll_lines(connection, period_start, period_end, cutoff)
    connection.executemany(
        """INSERT INTO payroll_lines (
            run_id, empid, source_pay_structure_id, employee_name, employment_type,
            pay_group, pay_term, monthly_salary, currency, scheduled_days, present_days,
            amount_minor, line_status, payment_status, exception_message
        ) VALUES (
            :run_id, :empid, :source_pay_structure_id, :employee_name, :employment_type,
            :pay_group, :pay_term, :monthly_salary, :currency, :scheduled_days, :present_days,
            :amount_minor, :line_status, :payment_status, :exception_message
        )""",
        [{"run_id": run_id, **line} for line in lines],
    )
    total_minor = sum(line["amount_minor"] for line in lines if line["line_status"] == "ready")
    exception_count = sum(line["line_status"] == "exception" for line in lines)
    employee_count = sum(line["line_status"] == "ready" for line in lines)
    connection.execute(
        """UPDATE payroll_runs SET total_minor = ?, employee_count = ?, exception_count = ?,
           updated_at = CURRENT_TIMESTAMP WHERE run_id = ?""",
        (total_minor, employee_count, exception_count, run_id),
    )
    return run_id


def payroll_run_payload(connection: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    run = connection.execute(
        "SELECT * FROM payroll_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        return None
    lines = connection.execute(
        """SELECT l.*, p.payment_id, p.payment_ref
           FROM payroll_lines l
           LEFT JOIN payments p ON p.payroll_line_id = l.line_id
           WHERE l.run_id = ? ORDER BY l.line_id""",
        (run_id,),
    ).fetchall()
    result = dict(run)
    result["total_amount"] = result["total_minor"] / 100
    result["lines"] = [
        {**dict(line), "amount": line["amount_minor"] / 100}
        for line in lines
    ]
    return result


def update_run_payment_status(connection: sqlite3.Connection, run_id: int) -> str:
    run = connection.execute(
        "SELECT status FROM payroll_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise PayrollError("Payroll run not found")
    if run["status"] in {"draft", "cancelled"}:
        return run["status"]
    pending = connection.execute(
        """SELECT COUNT(*) FROM payroll_lines
           WHERE run_id = ? AND line_status = 'ready' AND amount_minor > 0
             AND payment_status != 'completed'""",
        (run_id,),
    ).fetchone()[0]
    any_recorded = connection.execute(
        """SELECT COUNT(*) FROM payroll_lines
           WHERE run_id = ? AND payment_status IN ('pending', 'completed', 'failed')""",
        (run_id,),
    ).fetchone()[0]
    status = "paid" if pending == 0 else ("partially_paid" if any_recorded else "approved")
    connection.execute(
        "UPDATE payroll_runs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
        (status, run_id),
    )
    return status
