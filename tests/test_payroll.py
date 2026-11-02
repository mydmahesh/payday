import sqlite3
import unittest
from datetime import date

from payroll import (
    PayrollError,
    calendar_day_details,
    calculate_payroll_lines,
    create_or_refresh_run,
    ensure_payroll_schema,
    payroll_run_payload,
)


class PayrollCalculationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE pd_employees (
                empid INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                email TEXT,
                hire_date TEXT,
                grade TEXT,
                is_active INTEGER
            );
            CREATE TABLE pay_structure (
                id INTEGER PRIMARY KEY,
                empid INTEGER NOT NULL,
                pay_term TEXT,
                salary REAL,
                pay_group TEXT,
                active INTEGER
            );
            CREATE TABLE payments (
                payment_id INTEGER PRIMARY KEY,
                empid INTEGER NOT NULL,
                payment_status TEXT,
                payment_ref TEXT
            );
            INSERT INTO pd_employees VALUES
                (1, 'Pat', 'Permanent', NULL, '2026-01-01', NULL, 1),
                (2, 'Casey', 'Contractor', NULL, '2026-06-01', NULL, 1),
                (3, 'Taylor', 'Unclassified', NULL, '2026-01-01', NULL, 1);
            INSERT INTO pay_structure VALUES
                (11, 1, 'monthly', 2200, 'A', 1),
                (12, 2, 'monthly', 2200, 'D', 1),
                (13, 3, 'monthly', 1500, 'C', 1);
            INSERT INTO payments VALUES (91, 1, 'completed', 'LEGACY-91');
        """)
        ensure_payroll_schema(self.connection)
        self.connection.execute("UPDATE pd_employees SET employment_type='permanent' WHERE empid=1")
        self.connection.execute("UPDATE pd_employees SET employment_type='contractor' WHERE empid=2")
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_permanent_receives_full_month_and_contractor_is_prorated_to_cutoff(self):
        for work_date, status in [
            ('2026-06-01', 'present'),
            ('2026-06-02', 'present'),
            ('2026-06-03', 'absent'),
        ]:
            self.connection.execute(
                'INSERT INTO attendance_daily (empid, work_date, status) VALUES (2, ?, ?)',
                (work_date, status),
            )
        lines = calculate_payroll_lines(
            self.connection, date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 3)
        )
        by_empid = {line['empid']: line for line in lines}
        self.assertEqual(by_empid[1]['amount_minor'], 220000)
        self.assertEqual(by_empid[2]['scheduled_days'], 25)
        self.assertEqual(by_empid[2]['present_days'], 2)
        self.assertEqual(by_empid[2]['amount_minor'], 17600)
        self.assertEqual(by_empid[2]['line_status'], 'ready')
        self.assertEqual(by_empid[3]['line_status'], 'exception')
        self.assertIn('not classified', by_empid[3]['exception_message'])

    def test_sundays_and_india_festivals_are_default_holidays(self):
        days = calendar_day_details(
            self.connection, date(2026, 11, 1), date(2026, 11, 8)
        )
        by_date = {day['work_date']: day for day in days}
        self.assertFalse(by_date['2026-11-01']['is_working_day'])
        self.assertEqual(by_date['2026-11-01']['holiday_name'], 'Sunday')
        self.assertFalse(by_date['2026-11-08']['is_working_day'])
        self.assertEqual(by_date['2026-11-08']['holiday_name'], 'Sunday')
        self.assertFalse(by_date['2026-11-08']['can_override'])
        self.assertFalse(by_date['2026-11-08']['is_working_day'])

    def test_missing_contractor_attendance_is_exception(self):
        lines = calculate_payroll_lines(
            self.connection, date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 3)
        )
        contractor = next(line for line in lines if line['empid'] == 2)
        self.assertEqual(contractor['line_status'], 'exception')
        self.assertIn('Attendance is incomplete', contractor['exception_message'])

    def test_draft_refresh_is_idempotent_and_preserves_legacy_payments(self):
        cutoff = date(2026, 6, 3)
        first_id = create_or_refresh_run(self.connection, cutoff)
        second_id = create_or_refresh_run(self.connection, cutoff)
        self.assertEqual(first_id, second_id)
        payload = payroll_run_payload(self.connection, first_id)
        self.assertEqual(payload['exception_count'], 2)
        self.assertEqual(
            self.connection.execute('SELECT payment_ref FROM payments WHERE payment_id=91').fetchone()[0],
            'LEGACY-91',
        )

    def test_draft_run_can_be_refreshed_with_a_different_cutoff(self):
        run_id = create_or_refresh_run(self.connection, date(2026, 6, 3))
        refreshed_id = create_or_refresh_run(self.connection, date(2026, 6, 4))
        self.assertEqual(run_id, refreshed_id)
        payload = payroll_run_payload(self.connection, run_id)
        self.assertEqual(payload['cutoff_date'], '2026-06-04')

    def test_approved_run_rejects_a_different_cutoff(self):
        run_id = create_or_refresh_run(self.connection, date(2026, 6, 3))
        self.connection.execute(
            "UPDATE payroll_runs SET status='approved' WHERE run_id=?", (run_id,)
        )
        with self.assertRaises(PayrollError):
            create_or_refresh_run(self.connection, date(2026, 6, 4))

    def test_schema_migration_is_repeatable(self):
        ensure_payroll_schema(self.connection)
        ensure_payroll_schema(self.connection)
        columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(payments)')}
        self.assertIn('payroll_line_id', columns)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM payments').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
