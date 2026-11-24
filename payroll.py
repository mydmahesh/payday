from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import holidays


EMPLOYMENT_TYPES = {"permanent", "contractor", "contingent", "supplier", "other"}
PAYMENT_STATUSES = {"pending", "completed", "failed"}

# Indian Tax Configuration (FY 2024-25 / AY 2025-26)
TAX_REGIMES = {"old", "new"}

# PF Configuration
PF_EMPLOYEE_RATE = Decimal("0.12")      # 12% employee contribution
PF_EMPLOYER_RATE = Decimal("0.12")      # 12% employer contribution
PF_EMPLOYER_EPS_RATE = Decimal("0.0833") # 8.33% goes to EPS (pension)
PF_EMPLOYER_EPF_RATE = Decimal("0.0367") # 3.67% goes to EPF
PF_WAGE_CEILING = 15000                 # Monthly wage ceiling for PF

# ESI Configuration (FY 2024-25)
ESI_EMPLOYEE_RATE = Decimal("0.0075")   # 0.75% employee contribution
ESI_EMPLOYER_RATE = Decimal("0.0325")   # 3.25% employer contribution
ESI_WAGE_CEILING = 21000                # Monthly wage ceiling for ESI

# Professional Tax Slabs (varies by state - using Maharashtra as default)
# Monthly slabs for Maharashtra
PROFESSIONAL_TAX_SLABS = [
    (0, 7500, 0),
    (7501, 10000, 175),
    (10001, float('inf'), 200),
]

# Old Tax Regime Slabs (FY 2024-25)
OLD_TAX_SLABS = [
    (0, 250000, Decimal("0")),
    (250001, 500000, Decimal("0.05")),
    (500001, 1000000, Decimal("0.20")),
    (1000001, float('inf'), Decimal("0.30")),
]

# New Tax Regime Slabs (FY 2024-25) - u/s 115BAC
NEW_TAX_SLABS = [
    (0, 300000, Decimal("0")),
    (300001, 600000, Decimal("0.05")),
    (600001, 900000, Decimal("0.10")),
    (900001, 1200000, Decimal("0.15")),
    (1200001, 1500000, Decimal("0.20")),
    (1500001, float('inf'), Decimal("0.30")),
]

# Standard Deduction (Old Regime)
STANDARD_DEDUCTION_OLD = 50000
# Standard Deduction (New Regime)
STANDARD_DEDUCTION_NEW = 75000

# Section 87A Rebate Limits
REBATE_87A_OLD_LIMIT = 500000    # Taxable income up to 5L
REBATE_87A_OLD_MAX = 12500
REBATE_87A_NEW_LIMIT = 700000    # Taxable income up to 7L
REBATE_87A_NEW_MAX = 25000

# Surcharge Rates (Old & New Regime)
SURCHARGE_SLABS = [
    (0, 5000000, Decimal("0")),
    (5000001, 10000000, Decimal("0.10")),
    (10000001, 20000000, Decimal("0.15")),
    (20000001, 50000000, Decimal("0.25")),
    (50000001, float('inf'), Decimal("0.37")),  # Capped at 25% for new regime
]

# Health & Education Cess
CESS_RATE = Decimal("0.04")

GRADE_CONFIG = {
    'A': {
        'pay_group': 'Management',
        'description': 'Senior Management',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Monthly'],
        'fixed_pay_term': True,
        'job_id_required': True,
        'empid_prefix': 'M',
        'empid_suffix': '',
        'attendance_required': True,
        'paid_leaves_apply': True,
        'lop_applicable': True,
        'approval_seeking': 'Senior Manager Approval is NOT needed',
    },
    'B': {
        'pay_group': 'Regular',
        'description': 'Regular Employee',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Monthly'],
        'fixed_pay_term': True,
        'job_id_required': True,
        'empid_prefix': 'E',
        'empid_suffix': '',
        'attendance_required': True,
        'paid_leaves_apply': True,
        'lop_applicable': True,
        'approval_seeking': 'Senior Manager Approval is needed',
    },
    'C': {
        'pay_group': 'Contract',
        'description': 'Contract Employee',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Weekly', 'Bi-Weekly', 'Monthly'],
        'fixed_pay_term': False,
        'job_id_required': True,
        'empid_prefix': 'C',
        'empid_suffix': '',
        'attendance_required': True,
        'paid_leaves_apply': True,
        'lop_applicable': True,
        'approval_seeking': 'Senior Manager Approval is needed',
    },
    'D': {
        'pay_group': 'Staff',
        'description': 'Support Office Staff',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Weekly', 'Bi-Weekly', 'Monthly'],
        'fixed_pay_term': False,
        'job_id_required': True,
        'empid_prefix': 'S',
        'empid_suffix': '',
        'attendance_required': True,
        'paid_leaves_apply': True,
        'lop_applicable': True,
        'approval_seeking': 'Senior Manager Approval is needed',
    },
    'E': {
        'pay_group': 'Supplier',
        'description': 'Suppliers',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Weekly', 'Bi-Weekly', 'Monthly', 'One-time'],
        'fixed_pay_term': False,
        'job_id_required': False,
        'empid_prefix': '',
        'empid_suffix': 'S',
        'attendance_required': False,
        'paid_leaves_apply': False,
        'lop_applicable': False,
        'approval_seeking': 'None',
    },
    'F': {
        'pay_group': 'Other',
        'description': 'any others',
        'pay_term_default': 'Monthly',
        'pay_terms': ['Weekly', 'Bi-Weekly', 'Monthly', 'One-time'],
        'fixed_pay_term': False,
        'job_id_required': False,
        'empid_prefix': '',
        'empid_suffix': 'F',
        'attendance_required': False,
        'paid_leaves_apply': False,
        'lop_applicable': False,
        'approval_seeking': 'None',
    },
}


def format_empid(numeric_val: Any, grade: str) -> str:
    """Format 5-digit employee ID with prefix or suffix according to grade."""
    digits = ''.join(c for c in str(numeric_val) if c.isdigit())
    if not digits:
        digits = "1"
    num_str = f"{int(digits):05d}"
    g = (grade or 'B').strip().upper()
    cfg = GRADE_CONFIG.get(g, GRADE_CONFIG['B'])
    return f"{cfg['empid_prefix']}{num_str}{cfg['empid_suffix']}"


def grade_to_pay_group(grade: str) -> str:
    g = (grade or 'B').strip().upper()
    cfg = GRADE_CONFIG.get(g)
    return cfg['pay_group'] if cfg else 'Regular'


def pay_group_to_grade(pay_group: str) -> str:
    pg = str(pay_group or '').strip().upper()
    mapping = {
        'MANAGEMENT': 'A', 'SENIOR MANAGEMENT': 'A', 'A': 'A',
        'REGULAR': 'B', 'REGULAR EMPLOYEE': 'B', 'B': 'B',
        'CONTRACT': 'C', 'CONTRACT EMPLOYEE': 'C', 'C': 'C',
        'STAFF': 'D', 'SUPPORT OFFICE STAFF': 'D', 'SUPPORT STAFF': 'D', 'D': 'D',
        'SUPPLIER': 'E', 'SUPPLIERS': 'E', 'E': 'E',
        'OTHER': 'F', 'OTHERS': 'F', 'ANY OTHERS': 'F', 'F': 'F',
    }
    return mapping.get(pg, 'B')


def is_attendance_required(grade: str, pay_group: str = None) -> bool:
    g = (grade or '').strip().upper()
    if g in GRADE_CONFIG:
        return GRADE_CONFIG[g]['attendance_required']
    if pay_group:
        g = pay_group_to_grade(pay_group)
        return GRADE_CONFIG.get(g, {}).get('attendance_required', True)
    return True


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
            empid TEXT NOT NULL,
            work_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'leave')),
            leave_type TEXT,
            approval_status TEXT DEFAULT 'approved',
            manager_comment TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (empid, work_date)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS attendance_submissions (
            submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            empid TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'monthly',
            total_hours REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted', 'approved', 'denied', 'resend')),
            submitted_by TEXT NOT NULL DEFAULT 'employee'
                CHECK (submitted_by IN ('employee', 'manager')),
            manager_comment TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (empid, period_start, period_end)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS employee_leave_balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empid TEXT NOT NULL,
            leave_type TEXT NOT NULL,
            max_leaves REAL NOT NULL DEFAULT 0,
            used_leaves REAL NOT NULL DEFAULT 0,
            available_leaves REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (empid, leave_type)
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
            pay_term TEXT NOT NULL DEFAULT 'all',
            status TEXT NOT NULL DEFAULT 'generated'
                CHECK (status IN ('draft', 'generated', 'submitted', 'approved', 'denied', 'created', 'partially_paid', 'paid', 'cancelled')),
            currency TEXT NOT NULL DEFAULT 'INR',
            total_minor INTEGER NOT NULL DEFAULT 0,
            employee_count INTEGER NOT NULL DEFAULT 0,
            exception_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (period_start, period_end, pay_term)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS payroll_lines (
            line_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES payroll_runs(run_id) ON DELETE CASCADE,
            empid TEXT NOT NULL,
            source_pay_structure_id INTEGER,
            employee_name TEXT NOT NULL,
            employment_type TEXT,
            pay_group TEXT,
            pay_term TEXT,
            monthly_salary REAL,
            currency TEXT NOT NULL DEFAULT 'INR',
            scheduled_days INTEGER NOT NULL DEFAULT 0,
            present_days INTEGER NOT NULL DEFAULT 0,
            lop_days INTEGER DEFAULT 0,
            lop_amount_minor INTEGER DEFAULT 0,
            -- Tax and deduction fields
            pf_employee_minor INTEGER DEFAULT 0,
            pf_employer_minor INTEGER DEFAULT 0,
            esi_employee_minor INTEGER DEFAULT 0,
            esi_employer_minor INTEGER DEFAULT 0,
            professional_tax_minor INTEGER DEFAULT 0,
            tds_minor INTEGER DEFAULT 0,
            other_deductions_minor INTEGER DEFAULT 0,
            total_deductions_minor INTEGER DEFAULT 0,
            net_pay_minor INTEGER NOT NULL DEFAULT 0,
            tax_regime TEXT DEFAULT 'new',
            amount_minor INTEGER NOT NULL DEFAULT 0,
            line_status TEXT NOT NULL CHECK (line_status IN ('ready', 'exception')),
            payment_status TEXT NOT NULL DEFAULT 'unrecorded'
                CHECK (payment_status IN ('unrecorded', 'pending', 'completed', 'failed', 'not_payable')),
            exception_message TEXT,
            UNIQUE (run_id, empid)
        )"""
    )

    # Check and add columns to existing attendance_daily if missing
    if "attendance_daily" in tables:
        att_cols = {row[1] for row in connection.execute("PRAGMA table_info(attendance_daily)")}
        if "leave_type" not in att_cols:
            connection.execute("ALTER TABLE attendance_daily ADD COLUMN leave_type TEXT")
        if "approval_status" not in att_cols:
            connection.execute("ALTER TABLE attendance_daily ADD COLUMN approval_status TEXT DEFAULT 'approved'")
        if "manager_comment" not in att_cols:
            connection.execute("ALTER TABLE attendance_daily ADD COLUMN manager_comment TEXT")

    # Check and add columns to existing payroll_lines if missing
    if "payroll_lines" in tables:
        pl_cols = {row[1] for row in connection.execute("PRAGMA table_info(payroll_lines)")}
        if "lop_days" not in pl_cols:
            connection.execute("ALTER TABLE payroll_lines ADD COLUMN lop_days INTEGER DEFAULT 0")
        if "lop_amount_minor" not in pl_cols:
            connection.execute("ALTER TABLE payroll_lines ADD COLUMN lop_amount_minor INTEGER DEFAULT 0")
        # Tax and deduction columns
        tax_columns = [
            ("pf_employee_minor", "INTEGER DEFAULT 0"),
            ("pf_employer_minor", "INTEGER DEFAULT 0"),
            ("esi_employee_minor", "INTEGER DEFAULT 0"),
            ("esi_employer_minor", "INTEGER DEFAULT 0"),
            ("professional_tax_minor", "INTEGER DEFAULT 0"),
            ("tds_minor", "INTEGER DEFAULT 0"),
            ("other_deductions_minor", "INTEGER DEFAULT 0"),
            ("total_deductions_minor", "INTEGER DEFAULT 0"),
            ("net_pay_minor", "INTEGER DEFAULT 0"),
            ("tax_regime", "TEXT DEFAULT 'new'"),
        ]
        for col_name, col_type in tax_columns:
            if col_name not in pl_cols:
                connection.execute(f"ALTER TABLE payroll_lines ADD COLUMN {col_name} {col_type}")

    if "pd_employees" in tables:
        employee_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(pd_employees)")
        }
        if "employment_type" not in employee_columns:
            connection.execute(
                """ALTER TABLE pd_employees ADD COLUMN employment_type TEXT
                   CHECK (employment_type IS NULL OR employment_type IN
                          ('permanent', 'contractor', 'contingent', 'supplier', 'other'))"""
            )

    if "payments" in tables:
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
        mode = get_pay_term_setting(connection, 'monthly_cutoff_day', 'last_working_day')
        if mode == 'custom_day':
            try:
                custom_day = int(get_pay_term_setting(connection, 'monthly_cutoff_custom_day', '31'))
            except (ValueError, TypeError):
                custom_day = 31
            max_day = calendar.monthrange(cutoff.year, cutoff.month)[1]
            day = max(1, min(custom_day, max_day))
            month_end = date(cutoff.year, cutoff.month, day)
        else:
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
            # Cutoff is before period end: period is the previous 2-week cycle
            period_start = current_week_start - timedelta(days=14)
        else:
            # Cutoff is on/after period end: period is the current 2-week cycle
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
    work_week = get_pay_term_setting(connection, 'work_week', 'mon_sat')
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
        is_saturday = current.weekday() == 5
        is_weekend_off = is_sunday or (work_week == 'mon_fri' and is_saturday)
        holiday_name = str(india_holidays.get(current, ""))
        override = overrides.get(current.isoformat())
        default_working = not is_weekend_off and not holiday_name
        is_working_day = False if is_weekend_off else (
            override["is_working_day"] if override else default_working
        )
        description = (
            "Sunday" if is_sunday else
            ("Saturday" if is_saturday and work_week == 'mon_fri' else
            (override["description"] if override and override["description"] else holiday_name))
        )
        days.append({
            "work_date": current.isoformat(),
            "weekday": current.strftime("%A"),
            "weekday_number": current.weekday(),
            "is_working_day": is_working_day,
            "is_holiday": is_weekend_off or bool(holiday_name) or bool(override and not is_working_day),
            "holiday_name": "Sunday" if is_sunday else ("Saturday" if is_saturday and work_week == 'mon_fri' else holiday_name),
            "description": description,
            "is_override": override is not None,
            "can_override": not is_sunday and not (work_week == 'mon_fri' and is_saturday),
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


# ==================== TAX CALCULATION FUNCTIONS ====================

def calculate_pf(gross_monthly: Decimal) -> tuple[int, int]:
    """Calculate PF contributions (employee and employer) in minor units.

    Returns: (employee_pf_minor, employer_pf_minor)
    PF is calculated on basic + DA, capped at ₹15,000/month wage ceiling.
    Employee: 12%, Employer: 12% (8.33% EPS + 3.67% EPF)
    """
    pf_wage = min(gross_monthly, Decimal(str(PF_WAGE_CEILING)))
    employee_pf = (pf_wage * PF_EMPLOYEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    employer_pf = (pf_wage * PF_EMPLOYER_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(employee_pf * 100), int(employer_pf * 100)


def calculate_esi(gross_monthly: Decimal) -> tuple[int, int]:
    """Calculate ESI contributions (employee and employer) in minor units.

    Returns: (employee_esi_minor, employer_esi_minor)
    ESI applies to employees with gross <= ₹21,000/month.
    Employee: 0.75%, Employer: 3.25%
    """
    if gross_monthly > Decimal(str(ESI_WAGE_CEILING)):
        return 0, 0
    employee_esi = (gross_monthly * ESI_EMPLOYEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    employer_esi = (gross_monthly * ESI_EMPLOYER_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(employee_esi * 100), int(employer_esi * 100)


def calculate_professional_tax(gross_monthly: Decimal) -> int:
    """Calculate Professional Tax in minor units (Maharashtra slabs as default).

    Monthly slabs:
    - Up to ₹7,500: ₹0
    - ₹7,501 - ₹10,000: ₹175
    - Above ₹10,000: ₹200
    """
    for min_slab, max_slab, tax in PROFESSIONAL_TAX_SLABS:
        if min_slab <= gross_monthly <= max_slab:
            return tax * 100
    return 200 * 100  # Default to highest slab


def calculate_tds_old_regime(annual_taxable_income: Decimal) -> Decimal:
    """Calculate annual TDS under Old Tax Regime."""
    tax = Decimal("0")
    remaining = annual_taxable_income

    for min_slab, max_slab, rate in OLD_TAX_SLABS:
        if remaining <= 0:
            break
        slab_income = min(remaining, Decimal(str(max_slab)) - Decimal(str(min_slab)))
        tax += slab_income * rate
        remaining -= slab_income

    # Section 87A Rebate
    if annual_taxable_income <= Decimal(str(REBATE_87A_OLD_LIMIT)):
        tax = max(Decimal("0"), tax - Decimal(str(REBATE_87A_OLD_MAX)))

    # Surcharge
    surcharge = Decimal("0")
    surcharge_rate = Decimal("0")
    for min_slab, max_slab, rate in SURCHARGE_SLABS:
        if annual_taxable_income > Decimal(str(min_slab)):
            surcharge_rate = rate
        else:
            break
    surcharge = tax * surcharge_rate

    # Health & Education Cess (4% on tax + surcharge)
    cess = (tax + surcharge) * CESS_RATE

    return (tax + surcharge + cess).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_tds_new_regime(annual_taxable_income: Decimal) -> Decimal:
    """Calculate annual TDS under New Tax Regime (u/s 115BAC)."""
    tax = Decimal("0")
    remaining = annual_taxable_income

    for min_slab, max_slab, rate in NEW_TAX_SLABS:
        if remaining <= 0:
            break
        slab_income = min(remaining, Decimal(str(max_slab)) - Decimal(str(min_slab)))
        tax += slab_income * rate
        remaining -= slab_income

    # Section 87A Rebate (New Regime)
    if annual_taxable_income <= Decimal(str(REBATE_87A_NEW_LIMIT)):
        tax = max(Decimal("0"), tax - Decimal(str(REBATE_87A_NEW_MAX)))

    # Surcharge (capped at 25% for new regime)
    surcharge = Decimal("0")
    surcharge_rate = Decimal("0")
    for min_slab, max_slab, rate in SURCHARGE_SLABS:
        if annual_taxable_income > Decimal(str(min_slab)):
            surcharge_rate = min(rate, Decimal("0.25"))  # Cap at 25% for new regime
        else:
            break
    surcharge = tax * surcharge_rate

    # Health & Education Cess (4% on tax + surcharge)
    cess = (tax + surcharge) * CESS_RATE

    return (tax + surcharge + cess).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_tds(annual_gross: Decimal, tax_regime: str = "new", deductions_80c: Decimal = Decimal("0")) -> int:
    """Calculate monthly TDS in minor units.

    Args:
        annual_gross: Annual gross salary
        tax_regime: 'old' or 'new'
        deductions_80c: Section 80C deductions (max 1.5L for old regime, 0 for new)

    Returns:
        Monthly TDS in minor units
    """
    if tax_regime == "old":
        # Old regime: Standard deduction + 80C
        taxable_income = annual_gross - Decimal(str(STANDARD_DEDUCTION_OLD)) - min(deductions_80c, Decimal("150000"))
        annual_tds = calculate_tds_old_regime(max(taxable_income, Decimal("0")))
    else:
        # New regime: Only standard deduction (₹75,000 from FY 2024-25)
        taxable_income = annual_gross - Decimal(str(STANDARD_DEDUCTION_NEW))
        annual_tds = calculate_tds_new_regime(max(taxable_income, Decimal("0")))

    # Monthly TDS
    monthly_tds = (annual_tds / Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(monthly_tds * 100)


def calculate_tax_and_deductions(
    connection: sqlite3.Connection,
    gross_monthly: Decimal,
    employment_type: str,
    tax_regime: str = "new",
    deductions_80c: Decimal = Decimal("0"),
    other_deductions: Decimal = Decimal("0"),
) -> dict[str, int]:
    """Calculate all tax and deduction components for an employee.

    Returns dict with all deduction amounts in minor units.
    """
    # Annualize gross for TDS calculation
    annual_gross = gross_monthly * Decimal("12")

    # PF (only for permanent employees)
    pf_employee_minor, pf_employer_minor = 0, 0
    if employment_type == "permanent":
        pf_employee_minor, pf_employer_minor = calculate_pf(gross_monthly)

    # ESI (for employees with gross <= 21,000)
    esi_employee_minor, esi_employer_minor = calculate_esi(gross_monthly)

    # Professional Tax
    professional_tax_minor = calculate_professional_tax(gross_monthly)

    # TDS
    tds_minor = calculate_tds(annual_gross, tax_regime, deductions_80c)

    # Other deductions
    other_deductions_minor = int(other_deductions * 100)

    # Total deductions (employee side)
    total_deductions_minor = (
        pf_employee_minor + esi_employee_minor + professional_tax_minor +
        tds_minor + other_deductions_minor
    )

    # Net pay
    gross_minor = int(gross_monthly * 100)
    net_pay_minor = max(0, gross_minor - total_deductions_minor)

    return {
        "pf_employee_minor": pf_employee_minor,
        "pf_employer_minor": pf_employer_minor,
        "esi_employee_minor": esi_employee_minor,
        "esi_employer_minor": esi_employer_minor,
        "professional_tax_minor": professional_tax_minor,
        "tds_minor": tds_minor,
        "other_deductions_minor": other_deductions_minor,
        "total_deductions_minor": total_deductions_minor,
        "net_pay_minor": net_pay_minor,
        "gross_minor": gross_minor,
    }


def _employee_name(employee: sqlite3.Row) -> str:
    name = f"{employee['first_name'] or ''} {employee['last_name'] or ''}".strip()
    return name or f"Employee {employee['empid']}"


LEAVE_TYPES = ['earned', 'casual', 'sick', 'maternity', 'paternity', 'adoption']


def _compute_leave_balances(connection: sqlite3.Connection, empid: str) -> dict[str, dict[str, float]]:
    """Compute leave balances without writing to database (read-only).

    This is a pure computation function - use init_or_update_leave_balances()
    if you need to persist the computed balances.
    """
    cursor = connection.cursor()
    cursor.execute("SELECT leave_type, max_leaves, used_leaves, available_leaves FROM employee_leave_balances WHERE empid = ?", (str(empid),))
    rows = cursor.fetchall()
    balances = {r[0]: {'max': float(r[1]), 'used': float(r[2]), 'available': float(r[3])} for r in rows}

    default_limits = {
        'earned': float(get_pay_term_setting(connection, 'earned_leaves_max', '15')),
        'casual': float(get_pay_term_setting(connection, 'casual_leaves_max', '12')),
        'sick': float(get_pay_term_setting(connection, 'sick_leaves_max', '10')),
        'maternity': float(get_pay_term_setting(connection, 'maternity_leaves_max', '180')),
        'paternity': float(get_pay_term_setting(connection, 'paternity_leaves_max', '15')),
        'adoption': float(get_pay_term_setting(connection, 'adoption_leaves_max', '60')),
    }

    cursor.execute("""
        SELECT COALESCE(leave_type, 'casual') as lt, COUNT(*) as cnt
        FROM attendance_daily
        WHERE empid = ? AND status = 'leave'
        GROUP BY COALESCE(leave_type, 'casual')
    """, (str(empid),))
    actual_used = {r[0]: float(r[1]) for r in cursor.fetchall()}

    updated_balances = {}
    for lt in LEAVE_TYPES:
        max_l = balances.get(lt, {}).get('max', default_limits[lt])
        used_l = actual_used.get(lt, balances.get(lt, {}).get('used', 0.0))
        avail_l = max(0.0, max_l - used_l)
        updated_balances[lt] = {'max': max_l, 'used': used_l, 'available': avail_l}
    return updated_balances


def init_or_update_leave_balances(connection: sqlite3.Connection, empid: str) -> dict[str, dict[str, float]]:
    """Compute and persist leave balances to database.

    Call this explicitly when you need to update stored balances (e.g., after
    attendance changes, leave approvals, or during payroll processing).
    """
    balances = _compute_leave_balances(connection, empid)
    cursor = connection.cursor()
    for lt in LEAVE_TYPES:
        b = balances[lt]
        cursor.execute("""
            INSERT INTO employee_leave_balances (empid, leave_type, max_leaves, used_leaves, available_leaves, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(empid, leave_type) DO UPDATE SET
                max_leaves = excluded.max_leaves,
                used_leaves = excluded.used_leaves,
                available_leaves = excluded.available_leaves,
                updated_at = CURRENT_TIMESTAMP
        """, (str(empid), lt, b['max'], b['used'], b['available']))
    return balances


def get_or_init_leave_balances(connection: sqlite3.Connection, empid: str) -> dict[str, dict[str, float]]:
    """Get leave balances, initializing if not present.

    Note: This function persists computed balances to the database.
    For read-only access, use _compute_leave_balances() directly.
    """
    return init_or_update_leave_balances(connection, empid)


def get_total_available_leaves(connection: sqlite3.Connection, empid: str) -> float:
    b = _compute_leave_balances(connection, empid)
    return sum(item['available'] for item in b.values())


def attendance_period_bounds(connection: sqlite3.Connection, target_date: date) -> tuple[date, date, str]:
    frequency = get_pay_term_setting(connection, 'attendance_submission_frequency', 'monthly').lower()
    work_week = get_pay_term_setting(connection, 'work_week', 'mon_sat')

    if frequency == 'weekly':
        start = target_date - timedelta(days=target_date.weekday())
        end = start + timedelta(days=4 if work_week == 'mon_fri' else 5)
    elif frequency == 'bi_weekly':
        week_num = target_date.isocalendar()[1]
        start_offset = target_date.weekday() + (7 if (week_num % 2 == 0) else 0)
        start = target_date - timedelta(days=start_offset)
        end = start + timedelta(days=11 if work_week == 'mon_fri' else 12)
    else:
        start = date(target_date.year, target_date.month, 1)
        max_day = calendar.monthrange(target_date.year, target_date.month)[1]
        end = date(target_date.year, target_date.month, max_day)
    return start, end, frequency


def calculate_payroll_lines(
    connection: sqlite3.Connection, period_start: date, period_end: date, cutoff: date, pay_term_filter: str | None = None
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

        # Filter by pay_term if specified
        if pay_term_filter and pay_term_filter not in ('all', None):
            if structure:
                norm_struct_pt = normalize_pay_term(structure["pay_term"])
                norm_filter_pt = normalize_pay_term(pay_term_filter)
                if norm_struct_pt != norm_filter_pt:
                    continue
            else:
                continue

        emp_grade = (employee["grade"] or "").strip().upper() if "grade" in employee.keys() else ""
        if not emp_grade and structure and structure["pay_group"]:
            emp_grade = pay_group_to_grade(structure["pay_group"])

        emp_type = employee["employment_type"]
        if not emp_type:
            if emp_grade == 'E':
                emp_type = 'supplier'
            elif emp_grade == 'F':
                emp_type = 'other'

        problems = []
        if not emp_type:
            problems.append("Employment type is not classified")
        elif emp_type not in EMPLOYMENT_TYPES:
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
            "employment_type": emp_type,
            "pay_group": structure["pay_group"] if structure else None,
            "pay_term": structure["pay_term"] if structure else None,
            "monthly_salary": structure["salary"] if structure else None,
            "currency": "INR",
            "scheduled_days": 0,
            "present_days": 0,
            "lop_days": 0,
            "lop_amount_minor": 0,
            "pf_employee_minor": 0,
            "pf_employer_minor": 0,
            "esi_employee_minor": 0,
            "esi_employer_minor": 0,
            "professional_tax_minor": 0,
            "tds_minor": 0,
            "other_deductions_minor": 0,
            "total_deductions_minor": 0,
            "net_pay_minor": 0,
            "tax_regime": "new",
            "amount_minor": 0,
            "line_status": "exception" if problem else "ready",
            "payment_status": "unrecorded",
            "exception_message": problem,
        }
        if problem:
            lines.append(line)
            continue

        pay_term = normalize_pay_term(structure["pay_term"])
        period_start_dt, period_end_dt = pay_term_period_bounds(connection, pay_term, cutoff)
        period_days = scheduled_workdays(connection, period_start_dt, period_end_dt)
        line["scheduled_days"] = len(period_days)
        attendance_start = max(period_start_dt, hire_date)
        expected_days = {
            day.isoformat() for day in scheduled_workdays(connection, attendance_start, cutoff)
        }
        attendance_rows = connection.execute(
            """SELECT work_date, status, leave_type FROM attendance_daily
               WHERE empid = ? AND work_date BETWEEN ? AND ?""",
            (str(employee["empid"]), attendance_start.isoformat(), cutoff.isoformat()),
        ).fetchall()
        recorded = {row["work_date"]: row["status"] for row in attendance_rows}
        missing_days = expected_days.difference(recorded)
        line["present_days"] = sum(
            1 for day in expected_days
            if recorded.get(day) == "present"
        )
        leave_days_count = sum(
            1 for day in expected_days
            if recorded.get(day) == "leave"
        )
        absent_days_count = sum(
            1 for day in expected_days
            if recorded.get(day) == "absent"
        )

        attendance_needed = is_attendance_required(emp_grade, structure["pay_group"] if structure else None)

        # Check Attendance Approval Status from attendance_submissions (Sheet 3.1 & 3.4)
        if attendance_needed and emp_grade in ('B', 'C', 'D'):
            sub_row = connection.execute("""
                SELECT status, manager_comment, created_at
                FROM attendance_submissions
                WHERE empid = ? AND period_start <= ? AND period_end >= ?
                ORDER BY submission_id DESC LIMIT 1
            """, (str(employee["empid"]), cutoff.isoformat(), attendance_start.isoformat())).fetchone()
            if sub_row:
                if sub_row["status"] == "denied":
                    line["line_status"] = "exception"
                    line["exception_message"] = "Attendance submission was denied by Senior Manager"
                    lines.append(line)
                    continue
                elif sub_row["status"] == "resend":
                    line["line_status"] = "exception"
                    line["exception_message"] = f"Attendance resent for modification: {sub_row['manager_comment'] or 'Please modify'}"
                    lines.append(line)
                    continue
                elif sub_row["status"] == "submitted":
                    try:
                        sub_dt = datetime.fromisoformat(sub_row["created_at"]).date()
                        if (cutoff - sub_dt).days > 7:
                            line["line_status"] = "exception"
                            line["exception_message"] = "Senior Manager attendance approval pending over 1 week - payroll blocked"
                            lines.append(line)
                            continue
                    except Exception:
                        pass

        # Calculate LOP (Loss of Pay) when leave balance exceeded (Sheet 3.4)
        total_available_leaves = get_total_available_leaves(connection, str(employee["empid"]))
        excess_leaves = max(0, leave_days_count - int(total_available_leaves))
        lop_days = absent_days_count + excess_leaves
        line["lop_days"] = lop_days

        if not attendance_needed:
            # Supplier (Grade E) or Other (Grade F): Attendance not required, LOP NA (Sheet 2.1, 3.1, 4.1)
            line["amount_minor"] = salary_minor
            line["present_days"] = len(period_days)
            line["lop_days"] = 0
            line["lop_amount_minor"] = 0
            if pay_term == 'one_time' and cutoff < date.today():
                line["payment_status"] = 'pending'
        elif emp_type == "permanent" and pay_term == 'monthly':
            # Monthly with leave balance and LOP applicable
            if period_days and lop_days > 0:
                daily_rate = Decimal(salary_minor) / Decimal(len(period_days))
                lop_deduction = int(min(Decimal(salary_minor), Decimal(lop_days) * daily_rate))
                line["lop_amount_minor"] = lop_deduction
                line["amount_minor"] = max(0, salary_minor - lop_deduction)
            else:
                line["amount_minor"] = salary_minor
                line["lop_amount_minor"] = 0
            line["present_days"] = len(
                [day for day in period_days if day <= cutoff and day >= hire_date and recorded.get(day.isoformat()) != 'absent']
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
            line["lop_days"] = 0
            line["lop_amount_minor"] = 0
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

        # ===== TAX AND DEDUCTION CALCULATIONS =====
        # Only calculate for ready lines with positive gross
        if line["line_status"] == "ready" and line["amount_minor"] > 0:
            gross_monthly = Decimal(line["amount_minor"]) / Decimal("100")
            tax_regime = "new"  # Default to new regime, could be made configurable per employee
            deductions_80c = Decimal("0")  # Could be fetched from employee tax declarations

            tax_calc = calculate_tax_and_deductions(
                connection=connection,
                gross_monthly=gross_monthly,
                employment_type=emp_type,
                tax_regime=tax_regime,
                deductions_80c=deductions_80c,
            )

            line["pf_employee_minor"] = tax_calc["pf_employee_minor"]
            line["pf_employer_minor"] = tax_calc["pf_employer_minor"]
            line["esi_employee_minor"] = tax_calc["esi_employee_minor"]
            line["esi_employer_minor"] = tax_calc["esi_employer_minor"]
            line["professional_tax_minor"] = tax_calc["professional_tax_minor"]
            line["tds_minor"] = tax_calc["tds_minor"]
            line["other_deductions_minor"] = tax_calc["other_deductions_minor"]
            line["total_deductions_minor"] = tax_calc["total_deductions_minor"]
            line["net_pay_minor"] = tax_calc["net_pay_minor"]
            line["tax_regime"] = tax_regime
            # Note: amount_minor remains as gross pay; net_pay_minor is the actual payable
        else:
            # Exception lines or zero pay - no deductions
            line["pf_employee_minor"] = 0
            line["pf_employer_minor"] = 0
            line["esi_employee_minor"] = 0
            line["esi_employer_minor"] = 0
            line["professional_tax_minor"] = 0
            line["tds_minor"] = 0
            line["other_deductions_minor"] = 0
            line["total_deductions_minor"] = 0
            line["net_pay_minor"] = 0
            line["tax_regime"] = "new"

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
        "lop_days": 0,
        "lop_amount_minor": 0,
        "pf_employee_minor": 0,
        "pf_employer_minor": 0,
        "esi_employee_minor": 0,
        "esi_employer_minor": 0,
        "professional_tax_minor": 0,
        "tds_minor": 0,
        "other_deductions_minor": 0,
        "total_deductions_minor": 0,
        "net_pay_minor": 0,
        "tax_regime": "new",
        "amount_minor": 0,
        "line_status": "exception",
        "payment_status": "unrecorded",
        "exception_message": message,
    }


def create_or_refresh_run(connection: sqlite3.Connection, cutoff: date, pay_term: str = 'all') -> int:
    norm_pay_term = normalize_pay_term(pay_term) if pay_term != 'all' else 'all'
    period_start, period_end = pay_term_period_bounds(connection, norm_pay_term, cutoff) if norm_pay_term != 'all' else month_bounds(cutoff)

    cursor = connection.cursor()
    pr_cols = {r[1] for r in cursor.execute("PRAGMA table_info(payroll_runs)").fetchall()}
    has_pt_col = "pay_term" in pr_cols

    if has_pt_col:
        existing = connection.execute(
            """SELECT run_id, cutoff_date, status FROM payroll_runs
               WHERE period_start = ? AND period_end = ? AND pay_term = ?""",
            (period_start.isoformat(), period_end.isoformat(), norm_pay_term),
        ).fetchone()
    else:
        existing = connection.execute(
            """SELECT run_id, cutoff_date, status FROM payroll_runs
               WHERE period_start = ? AND period_end = ?""",
            (period_start.isoformat(), period_end.isoformat()),
        ).fetchone()

    if existing:
        if existing["status"] not in ("draft", "generated", "denied"):
            if existing["cutoff_date"] != cutoff.isoformat():
                raise PayrollError(
                    "An approved or processed payroll run already exists for this period with a different cutoff date"
                )
            return int(existing["run_id"])
        run_id = int(existing["run_id"])
        connection.execute(
            "UPDATE payroll_runs SET cutoff_date = ?, status = 'generated', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (cutoff.isoformat(), run_id),
        )
        connection.execute("DELETE FROM payroll_lines WHERE run_id = ?", (run_id,))
    else:
        if has_pt_col:
            cursor = connection.execute(
                """INSERT INTO payroll_runs
                   (period_start, period_end, cutoff_date, pay_term, status, currency)
                   VALUES (?, ?, ?, ?, 'generated', 'INR')""",
                (period_start.isoformat(), period_end.isoformat(), cutoff.isoformat(), norm_pay_term),
            )
        else:
            cursor = connection.execute(
                """INSERT INTO payroll_runs
                   (period_start, period_end, cutoff_date, status, currency)
                   VALUES (?, ?, ?, 'generated', 'INR')""",
                (period_start.isoformat(), period_end.isoformat(), cutoff.isoformat()),
            )
        run_id = int(cursor.lastrowid)

    lines = calculate_payroll_lines(connection, period_start, period_end, cutoff, pay_term_filter=norm_pay_term)
    pl_cols = {r[1] for r in cursor.execute("PRAGMA table_info(payroll_lines)").fetchall()}
    has_lop = "lop_days" in pl_cols

    if has_lop:
        connection.executemany(
            """INSERT INTO payroll_lines (
                run_id, empid, source_pay_structure_id, employee_name, employment_type,
                pay_group, pay_term, monthly_salary, currency, scheduled_days, present_days,
                lop_days, lop_amount_minor,
                pf_employee_minor, pf_employer_minor, esi_employee_minor, esi_employer_minor,
                professional_tax_minor, tds_minor, other_deductions_minor, total_deductions_minor,
                net_pay_minor, tax_regime,
                amount_minor, line_status, payment_status, exception_message
            ) VALUES (
                :run_id, :empid, :source_pay_structure_id, :employee_name, :employment_type,
                :pay_group, :pay_term, :monthly_salary, :currency, :scheduled_days, :present_days,
                :lop_days, :lop_amount_minor,
                :pf_employee_minor, :pf_employer_minor, :esi_employee_minor, :esi_employer_minor,
                :professional_tax_minor, :tds_minor, :other_deductions_minor, :total_deductions_minor,
                :net_pay_minor, :tax_regime,
                :amount_minor, :line_status, :payment_status, :exception_message
            )""",
            [{"run_id": run_id, **line} for line in lines],
        )
    else:
        connection.executemany(
            """INSERT INTO payroll_lines (
                run_id, empid, source_pay_structure_id, employee_name, employment_type,
                pay_group, pay_term, monthly_salary, currency, scheduled_days, present_days,
                pf_employee_minor, pf_employer_minor, esi_employee_minor, esi_employer_minor,
                professional_tax_minor, tds_minor, other_deductions_minor, total_deductions_minor,
                net_pay_minor, tax_regime,
                amount_minor, line_status, payment_status, exception_message
            ) VALUES (
                :run_id, :empid, :source_pay_structure_id, :employee_name, :employment_type,
                :pay_group, :pay_term, :monthly_salary, :currency, :scheduled_days, :present_days,
                :pf_employee_minor, :pf_employer_minor, :esi_employee_minor, :esi_employer_minor,
                :professional_tax_minor, :tds_minor, :other_deductions_minor, :total_deductions_minor,
                :net_pay_minor, :tax_regime,
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
    connection.commit()
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
        {
            **dict(line),
            "amount": line["amount_minor"] / 100,
            "lop_amount": (line["lop_amount_minor"] or 0) / 100 if "lop_amount_minor" in line.keys() else 0.0
        }
        for line in lines
    ]
    return result


def submit_payroll_run(connection: sqlite3.Connection, run_id: int) -> str:
    run = connection.execute("SELECT status FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        raise PayrollError("Payroll run not found")
    if run["status"] not in ("draft", "generated", "denied"):
        raise PayrollError(f"Cannot submit run with status '{run['status']}'")
    connection.execute("UPDATE payroll_runs SET status = 'submitted', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (run_id,))
    return "submitted"


def deny_payroll_run(connection: sqlite3.Connection, run_id: int) -> str:
    run = connection.execute("SELECT status FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        raise PayrollError("Payroll run not found")
    connection.execute("UPDATE payroll_runs SET status = 'denied', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (run_id,))
    return "denied"


def create_payroll_run_payments(connection: sqlite3.Connection, run_id: int) -> str:
    run = connection.execute("SELECT status FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        raise PayrollError("Payroll run not found")
    if run["status"] not in ("approved", "created"):
        raise PayrollError("Only approved runs can have payments created")
    connection.execute("UPDATE payroll_runs SET status = 'created', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (run_id,))
    return "created"


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


# ==================== PAYSLIP GENERATION ====================

def generate_payslip_html(connection: sqlite3.Connection, run_id: int, empid: str) -> str:
    """Generate HTML payslip for a specific employee in a payroll run."""
    run = connection.execute("SELECT * FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        raise PayrollError("Payroll run not found")

    line = connection.execute(
        """SELECT * FROM payroll_lines WHERE run_id = ? AND empid = ?""",
        (run_id, empid)
    ).fetchone()
    if not line:
        raise PayrollError("Payroll line not found for employee")

    employee = connection.execute(
        """SELECT empid, first_name, last_name, email, hire_date, grade, employment_type
           FROM pd_employees WHERE empid = ?""",
        (empid,)
    ).fetchone()

    bank = connection.execute(
        """SELECT account_number, ifsc_code, bank_name, branch_name
           FROM bank_details WHERE empid = ? ORDER BY id DESC LIMIT 1""",
        (empid,)
    ).fetchone()

    period_start = date.fromisoformat(run["period_start"])
    period_end = date.fromisoformat(run["period_end"])

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payslip - {line['employee_name']} - {period_start.strftime('%B %Y')}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .payslip {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; border-bottom: 2px solid #2c3e50; padding-bottom: 20px; margin-bottom: 30px; }}
        .company-name {{ font-size: 28px; font-weight: bold; color: #2c3e50; margin: 0; }}
        .company-tagline {{ font-size: 14px; color: #7f8c8d; margin: 5px 0 0; }}
        .payslip-title {{ font-size: 20px; font-weight: 600; color: #34495e; margin: 20px 0 0; }}
        .period {{ font-size: 14px; color: #7f8c8d; }}
        .employee-info {{ display: flex; justify-content: space-between; margin-bottom: 30px; padding: 15px; background: #ecf0f1; border-radius: 5px; }}
        .info-group {{ display: flex; flex-direction: column; }}
        .info-label {{ font-size: 12px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 0.5px; }}
        .info-value {{ font-size: 14px; font-weight: 600; color: #2c3e50; }}
        .section {{ margin-bottom: 25px; }}
        .section-title {{ font-size: 14px; font-weight: 600; color: #2c3e50; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #bdc3c7; padding-bottom: 8px; margin-bottom: 15px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
        th {{ font-weight: 600; color: #34495e; font-size: 13px; background: #f8f9fa; }}
        td {{ font-size: 13px; color: #2c3e50; }}
        .earnings td:last-child, .deductions td:last-child {{ text-align: right; }}
        .total-row {{ font-weight: 700; background: #f8f9fa; }}
        .net-pay {{ font-size: 18px; font-weight: 700; color: #27ae60; }}
        .net-pay-label {{ color: #2c3e50; }}
        .bank-info {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
        .bank-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #ecf0f1; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #bdc3c7; font-size: 12px; color: #7f8c8d; text-align: center; }}
        .signature-line {{ margin-top: 30px; display: flex; justify-content: space-between; }}
        .signature {{ text-align: center; width: 45%; }}
        .signature p {{ margin: 40px 0 5px; border-top: 1px solid #2c3e50; padding-top: 5px; font-size: 12px; }}
        @media print {{ body {{ background: none; padding: 0; }} .payslip {{ box-shadow: none; padding: 0; }} }}
    </style>
</head>
<body>
    <div class="payslip">
        <div class="header">
            <h1 class="company-name">PAYDAY CORPORATION</h1>
            <p class="company-tagline">Employee Payroll Management System</p>
            <h2 class="payslip-title">SALARY SLIP</h2>
            <p class="period">Pay Period: {period_start.strftime('%d %b %Y')} - {period_end.strftime('%d %b %Y')}</p>
        </div>

        <div class="employee-info">
            <div class="info-group">
                <span class="info-label">Employee Name</span>
                <span class="info-value">{line['employee_name']}</span>
            </div>
            <div class="info-group">
                <span class="info-label">Employee ID</span>
                <span class="info-value">{empid}</span>
            </div>
            <div class="info-group">
                <span class="info-label">Grade / Pay Group</span>
                <span class="info-value">{line['pay_group'] or 'N/A'} ({employee['grade'] if employee else 'N/A'})</span>
            </div>
            <div class="info-group">
                <span class="info-label">Employment Type</span>
                <span class="info-value">{line['employment_type'] or 'N/A'}</span>
            </div>
            <div class="info-group">
                <span class="info-label">Pay Term</span>
                <span class="info-value">{line['pay_term'] or 'N/A'}</span>
            </div>
            <div class="info-group">
                <span class="info-label">Date of Joining</span>
                <span class="info-value">{employee['hire_date'] if employee else 'N/A'}</span>
            </div>
            <div class="info-group">
                <span class="info-label">PAN / Tax Regime</span>
                <span class="info-value">New Regime (Default)</span>
            </div>
            <div class="info-group">
                <span class="info-label">Bank Details</span>
                <span class="info-value">{bank['bank_name'] if bank else 'N/A'} - {bank['account_number'][-4:] if bank else 'N/A'}</span>
            </div>
        </div>

        <div class="section earnings">
            <h3 class="section-title">Earnings</h3>
            <table>
                <thead>
                    <tr><th>Component</th><th>Amount (₹)</th></tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Basic Salary</td>
                        <td>{line['amount_minor'] / 100:,.2f}</td>
                    </tr>
                    {f'<tr><td>LOP Deduction (-)</td><td>-{line["lop_amount_minor"] / 100:,.2f}</td></tr>' if line["lop_amount_minor"] > 0 else ''}
                </tbody>
            </table>
        </div>

        <div class="section deductions">
            <h3 class="section-title">Deductions</h3>
            <table>
                <thead>
                    <tr><th>Component</th><th>Amount (₹)</th></tr>
                </thead>
                <tbody>
                    {f'<tr><td>Provident Fund (Employee)</td><td>{line["pf_employee_minor"] / 100:,.2f}</td></tr>' if line["pf_employee_minor"] > 0 else ''}
                    {f'<tr><td>ESI (Employee)</td><td>{line["esi_employee_minor"] / 100:,.2f}</td></tr>' if line["esi_employee_minor"] > 0 else ''}
                    {f'<tr><td>Professional Tax</td><td>{line["professional_tax_minor"] / 100:,.2f}</td></tr>' if line["professional_tax_minor"] > 0 else ''}
                    {f'<tr><td>TDS (Tax Deducted at Source)</td><td>{line["tds_minor"] / 100:,.2f}</td></tr>' if line["tds_minor"] > 0 else ''}
                    {f'<tr><td>Other Deductions</td><td>{line["other_deductions_minor"] / 100:,.2f}</td></tr>' if line["other_deductions_minor"] > 0 else ''}
                    <tr class="total-row">
                        <td>Total Deductions</td>
                        <td>{line["total_deductions_minor"] / 100:,.2f}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="section">
            <h3 class="section-title">Net Pay</h3>
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 20px; background: #e8f8f5; border-radius: 5px; border: 2px solid #27ae60;">
                <span class="net-pay-label">Net Payable Amount</span>
                <span class="net-pay">₹{line["net_pay_minor"] / 100:,.2f}</span>
            </div>
        </div>

        <div class="section" style="font-size: 12px; color: #7f8c8d;">
            <p><strong>Employer Contributions (Not deducted from salary):</strong></p>
            <div class="bank-info">
                {f'<span>PF (Employer): ₹{line["pf_employer_minor"] / 100:,.2f}</span>' if line["pf_employer_minor"] > 0 else ''}
                {f'<span>ESI (Employer): ₹{line["esi_employer_minor"] / 100:,.2f}</span>' if line["esi_employer_minor"] > 0 else ''}
            </div>
        </div>

        <div class="footer">
            <p>This is a computer-generated payslip and does not require a signature.</p>
            <p>Generated on {date.today().strftime('%d %b %Y')} | Payroll Run ID: {run_id}</p>
            <div class="signature-line">
                <div class="signature"><p>Authorized Signatory</p></div>
                <div class="signature"><p>Employee Acknowledgment</p></div>
            </div>
        </div>
    </div>
</body>
</html>
"""
    return html


def generate_payslip_pdf(connection: sqlite3.Connection, run_id: int, empid: str) -> bytes:
    """Generate PDF payslip using WeasyPrint."""
    html = generate_payslip_html(connection, run_id, empid)
    from weasyprint import HTML
    pdf = HTML(string=html).write_pdf()
    return pdf


def generate_all_payslips_pdf(connection: sqlite3.Connection, run_id: int) -> bytes:
    """Generate combined PDF with all payslips for a payroll run."""
    lines = connection.execute(
        """SELECT empid FROM payroll_lines WHERE run_id = ? AND line_status = 'ready' ORDER BY empid""",
        (run_id,)
    ).fetchall()

    from weasyprint import HTML
    combined_html = ""
    for i, line in enumerate(lines):
        html = generate_payslip_html(connection, run_id, line["empid"])
        if i > 0:
            combined_html += '<div style="page-break-before: always;"></div>'
        combined_html += html

    pdf = HTML(string=combined_html).write_pdf()
    return pdf


# ==================== BANK ADVICE EXPORT ====================

def generate_bank_advice_csv(connection: sqlite3.Connection, run_id: int) -> str:
    """Generate bank advice CSV for salary disbursement (NACH/NEFT format)."""
    lines = connection.execute(
        """SELECT pl.empid, pl.employee_name, pl.net_pay_minor, pl.amount_minor,
                  bd.account_number, bd.ifsc_code, bd.bank_name, bd.branch_name,
                  bd.account_holder
           FROM payroll_lines pl
           LEFT JOIN bank_details bd ON bd.empid = pl.empid
           WHERE pl.run_id = ? AND pl.line_status = 'ready' AND pl.net_pay_minor > 0
           ORDER BY pl.empid""",
        (run_id,)
    ).fetchall()

    run = connection.execute("SELECT period_start, period_end FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    period = f"{date.fromisoformat(run['period_start']).strftime('%b%y').upper()}" if run else "SALARY"

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row (standard NACH format)
    writer.writerow([
        "Sr No", "Employee ID", "Employee Name", "Account Number", "IFSC Code",
        "Bank Name", "Branch", "Account Holder Name", "Amount (INR)", "Narration"
    ])

    for idx, line in enumerate(lines, 1):
        account_holder = line["account_holder"] or line["employee_name"]
        narration = f"SALARY {period} {line['empid']}"
        writer.writerow([
            idx,
            line["empid"],
            line["employee_name"],
            line["account_number"] or "",
            line["ifsc_code"] or "",
            line["bank_name"] or "",
            line["branch_name"] or "",
            account_holder,
            f"{line['net_pay_minor'] / 100:.2f}",
            narration
        ])

    # Total row
    total_net = sum(line["net_pay_minor"] for line in lines) / 100
    writer.writerow(["", "", "", "", "", "", "", "TOTAL", f"{total_net:.2f}", ""])

    return output.getvalue()


def generate_bank_advice_excel(connection: sqlite3.Connection, run_id: int) -> bytes:
    """Generate bank advice Excel file for salary disbursement."""
    lines = connection.execute(
        """SELECT pl.empid, pl.employee_name, pl.net_pay_minor, pl.amount_minor,
                  pl.pf_employee_minor, pl.esi_employee_minor, pl.professional_tax_minor,
                  pl.tds_minor, pl.total_deductions_minor,
                  bd.account_number, bd.ifsc_code, bd.bank_name, bd.branch_name,
                  bd.account_holder
           FROM payroll_lines pl
           LEFT JOIN bank_details bd ON bd.empid = pl.empid
           WHERE pl.run_id = ? AND pl.line_status = 'ready' AND pl.net_pay_minor > 0
           ORDER BY pl.empid""",
        (run_id,)
    ).fetchall()

    run = connection.execute("SELECT period_start, period_end FROM payroll_runs WHERE run_id = ?", (run_id,)).fetchone()
    period = f"{date.fromisoformat(run['period_start']).strftime('%B %Y')}" if run else "Salary"

    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Bank Advice"

    # Styles
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    data_alignment = Alignment(horizontal="left", vertical="center")
    amount_alignment = Alignment(horizontal="right", vertical="center")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    total_font = Font(bold=True, size=11)
    total_fill = PatternFill(start_color="E8F8F5", end_color="E8F8F5", fill_type="solid")

    # Title row
    ws.merge_cells('A1:J1')
    title_cell = ws['A1']
    title_cell.value = f"BANK ADVICE FOR SALARY DISBURSEMENT - {period.upper()}"
    title_cell.font = Font(bold=True, size=14, color="2C3E50")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells('A2:J2')
    subtitle_cell = ws['A2']
    subtitle_cell.value = f"Payroll Run ID: {run_id} | Generated on: {date.today().strftime('%d %b %Y')}"
    subtitle_cell.font = Font(size=10, color="7F8C8D")
    subtitle_cell.alignment = Alignment(horizontal="center", vertical="center")

    # Headers
    headers = [
        "Sr No", "Employee ID", "Employee Name", "Account Number", "IFSC Code",
        "Bank Name", "Branch", "Account Holder Name", "Net Amount (INR)", "Narration"
    ]

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Data rows
    for idx, line in enumerate(lines, 1):
        row_num = idx + 4
        account_holder = line["account_holder"] or line["employee_name"]
        narration = f"SALARY {period} {line['empid']}"

        data = [
            idx,
            line["empid"],
            line["employee_name"],
            line["account_number"] or "",
            line["ifsc_code"] or "",
            line["bank_name"] or "",
            line["branch_name"] or "",
            account_holder,
            line["net_pay_minor"] / 100,
            narration
        ]

        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row_num, column=col, value=value)
            cell.border = thin_border
            if col == 9:  # Amount column
                cell.alignment = amount_alignment
                cell.number_format = '#,##0.00'
            else:
                cell.alignment = data_alignment

    # Total row
    total_row = len(lines) + 5
    total_net = sum(line["net_pay_minor"] for line in lines) / 100
    total_data = ["", "", "", "", "", "", "", "TOTAL", total_net, ""]

    for col, value in enumerate(total_data, 1):
        cell = ws.cell(row=total_row, column=col, value=value)
        cell.font = total_font
        cell.fill = total_fill
        cell.border = thin_border
        if col == 9:
            cell.alignment = amount_alignment
            cell.number_format = '#,##0.00'
        else:
            cell.alignment = data_alignment

    # Adjust column widths
    column_widths = [8, 15, 25, 20, 15, 20, 15, 25, 15, 30]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Save to bytes
    import io
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


# ==================== TAX REPORTS ====================

def generate_tds_report(connection: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """Generate TDS deduction report for a payroll run."""
    lines = connection.execute(
        """SELECT empid, employee_name, pay_group, amount_minor, tds_minor,
                  pf_employee_minor, esi_employee_minor, professional_tax_minor,
                  net_pay_minor, tax_regime
           FROM payroll_lines
           WHERE run_id = ? AND line_status = 'ready' AND tds_minor > 0
           ORDER BY empid""",
        (run_id,)
    ).fetchall()

    total_tds = sum(line["tds_minor"] for line in lines) / 100
    total_pf = sum(line["pf_employee_minor"] for line in lines) / 100
    total_esi = sum(line["esi_employee_minor"] for line in lines) / 100
    total_pt = sum(line["professional_tax_minor"] for line in lines) / 100

    return {
        "run_id": run_id,
        "employees": [
            {
                "empid": line["empid"],
                "name": line["employee_name"],
                "pay_group": line["pay_group"],
                "gross": line["amount_minor"] / 100,
                "tds": line["tds_minor"] / 100,
                "pf": line["pf_employee_minor"] / 100,
                "esi": line["esi_employee_minor"] / 100,
                "professional_tax": line["professional_tax_minor"] / 100,
                "net_pay": line["net_pay_minor"] / 100,
                "tax_regime": line["tax_regime"]
            }
            for line in lines
        ],
        "summary": {
            "total_employees": len(lines),
            "total_gross": sum(line["amount_minor"] for line in lines) / 100,
            "total_tds": total_tds,
            "total_pf_employee": total_pf,
            "total_esi_employee": total_esi,
            "total_professional_tax": total_pt,
            "total_net_pay": sum(line["net_pay_minor"] for line in lines) / 100,
        }
    }
