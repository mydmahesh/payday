import sqlite3
import unittest
from datetime import date

from payroll import (
    GRADE_CONFIG,
    attendance_period_bounds,
    format_empid,
    grade_to_pay_group,
    pay_group_to_grade,
    is_attendance_required,
    calculate_payroll_lines,
    calendar_day_details,
    set_pay_term_setting,
    ensure_payroll_schema,
)
from app import app, get_db_connection, ensure_redesign_schema, resolve_employee


class PaydayRedesignTests(unittest.TestCase):
    def tearDown(self):
        conn = get_db_connection()
        conn.execute("DELETE FROM pd_employees WHERE email LIKE '%@example.com%'")
        conn.execute("DELETE FROM pay_structure WHERE name IN ('Ramesh Kumar', 'Sunil Verma', 'Approval Test', 'Senior Mgr', 'Behalf Test')")
        conn.execute("DELETE FROM attendance_submissions WHERE empid LIKE 'E%' OR empid LIKE 'M%' OR empid LIKE 'C%' OR empid LIKE '%F'")
        conn.commit()
        conn.close()

    def test_grade_to_pay_group_mapping(self):
        self.assertEqual(grade_to_pay_group('A'), 'Management')
        self.assertEqual(grade_to_pay_group('B'), 'Regular')
        self.assertEqual(grade_to_pay_group('C'), 'Contract')
        self.assertEqual(grade_to_pay_group('D'), 'Staff')
        self.assertEqual(grade_to_pay_group('E'), 'Supplier')
        self.assertEqual(grade_to_pay_group('F'), 'Other')

        self.assertEqual(pay_group_to_grade('Management'), 'A')
        self.assertEqual(pay_group_to_grade('Regular'), 'B')
        self.assertEqual(pay_group_to_grade('Contract'), 'C')
        self.assertEqual(pay_group_to_grade('Staff'), 'D')
        self.assertEqual(pay_group_to_grade('Supplier'), 'E')
        self.assertEqual(pay_group_to_grade('Other'), 'F')

    def test_empid_format_and_grade_f_suffix(self):
        # Grade A: M*****
        self.assertEqual(format_empid(77850, 'A'), 'M77850')
        # Grade B: E*****
        self.assertEqual(format_empid(77850, 'B'), 'E77850')
        # Grade C: C*****
        self.assertEqual(format_empid(77850, 'C'), 'C77850')
        # Grade D: S*****
        self.assertEqual(format_empid(77850, 'D'), 'S77850')
        # Grade E: *****S
        self.assertEqual(format_empid(77850, 'E'), '77850S')
        # Grade F: *****F (Grade F suffix as F)
        self.assertEqual(format_empid(77850, 'F'), '77850F')

    def test_grade_promotion_empid_transformation(self):
        # Contractor C77850 promoted to Regular -> E77850
        self.assertEqual(format_empid('C77850', 'B'), 'E77850')
        # Regular E77850 promoted to Senior Management -> M77850
        self.assertEqual(format_empid('E77850', 'A'), 'M77850')
        # Regular E77850 changed to Supplier -> 77850S
        self.assertEqual(format_empid('E77850', 'E'), '77850S')
        # Regular E77850 changed to Other -> 77850F
        self.assertEqual(format_empid('E77850', 'F'), '77850F')

    def test_attendance_requirement_by_grade(self):
        self.assertTrue(is_attendance_required('A'))
        self.assertTrue(is_attendance_required('B'))
        self.assertTrue(is_attendance_required('C'))
        self.assertTrue(is_attendance_required('D'))
        self.assertFalse(is_attendance_required('E'))
        self.assertFalse(is_attendance_required('F'))

    def test_work_week_mon_fri_vs_mon_sat(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_payroll_schema(conn)

        # Mon-Sat: Saturday (2026-11-07) is a working day
        set_pay_term_setting(conn, 'work_week', 'mon_sat')
        days_sat = calendar_day_details(conn, date(2026, 11, 7), date(2026, 11, 8))
        by_date = {d['work_date']: d for d in days_sat}
        self.assertTrue(by_date['2026-11-07']['is_working_day'])
        self.assertFalse(by_date['2026-11-08']['is_working_day']) # Sunday

        # Mon-Fri: Saturday (2026-11-07) is NOT a working day
        set_pay_term_setting(conn, 'work_week', 'mon_fri')
        days_fri = calendar_day_details(conn, date(2026, 11, 7), date(2026, 11, 8))
        by_date = {d['work_date']: d for d in days_fri}
        self.assertFalse(by_date['2026-11-07']['is_working_day'])
        self.assertFalse(by_date['2026-11-08']['is_working_day'])
        conn.close()

    def test_supplier_and_other_grades_do_not_require_attendance(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE pd_employees (
                empid TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                email TEXT,
                hire_date TEXT,
                grade TEXT,
                is_active INTEGER,
                employment_type TEXT
            );
            CREATE TABLE pay_structure (
                id INTEGER PRIMARY KEY,
                empid TEXT NOT NULL,
                pay_term TEXT,
                salary REAL,
                pay_group TEXT,
                active INTEGER
            );
            CREATE TABLE payments (
                payment_id INTEGER PRIMARY KEY,
                empid TEXT NOT NULL,
                payment_status TEXT,
                payment_ref TEXT
            );
            INSERT INTO pd_employees VALUES
                ('77850S', 'Acme', 'Supplies', 'supplier@acme.com', '2026-01-01', 'E', 1, 'supplier'),
                ('77850F', 'Jane', 'Other', 'jane@other.com', '2026-01-01', 'F', 1, 'other');
            INSERT INTO pay_structure VALUES
                (1, '77850S', 'Monthly', 50000, 'Supplier', 1),
                (2, '77850F', 'Monthly', 30000, 'Other', 1);
        """)
        ensure_payroll_schema(conn)

        # Neither has attendance records in attendance_daily. Both should calculate ready without exception!
        lines = calculate_payroll_lines(conn, date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 30))
        by_id = {line['empid']: line for line in lines}
        self.assertEqual(by_id['77850S']['line_status'], 'ready')
        self.assertEqual(by_id['77850S']['amount_minor'], 5000000)
        self.assertEqual(by_id['77850F']['line_status'], 'ready')
        self.assertEqual(by_id['77850F']['amount_minor'], 3000000)
        conn.close()

    def test_api_add_employee_and_promotion(self):
        import uuid, random
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'

        num = random.randint(10000, 99999)
        c_id = f"C{num}"
        e_id = f"E{num}"
        m_id = f"M{num}"
        f_num = random.randint(10000, 99999)
        f_id = f"{f_num}F"

        uid = uuid.uuid4().hex[:6]
        # Add Contractor (Grade C)
        res = client.post('/add_employee', json={
            'first_name': 'Ramesh',
            'last_name': 'Kumar',
            'email': f'ramesh.{uid}@example.com',
            'hire_date': '2026-01-10',
            'grade': 'C',
            'numeric_id': num
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data['empid'], c_id)

        # Add Pay Structure for contractor
        ps_res = client.post('/save_pay_structure', json={
            'empid': c_id,
            'name': 'Ramesh Kumar',
            'grade': 'C',
            'pay_group': 'Contract',
            'pay_term': 'Monthly',
            'salary': 45000,
            'job_id': 'CON-01',
            'active': True
        })
        self.assertEqual(ps_res.status_code, 200)

        # Promote contractor to Regular (Grade B)
        update_res = client.post('/update_employee', json={
            'empid': c_id,
            'first_name': 'Ramesh',
            'last_name': 'Kumar',
            'email': f'ramesh.{uid}@example.com',
            'hire_date': '2026-01-10',
            'grade': 'B',
            'is_active': 1
        })
        self.assertEqual(update_res.status_code, 200)
        up_data = update_res.get_json()
        self.assertEqual(up_data['empid'], e_id)

        # Check pay_structure was updated to e_id, pay_group Regular
        list_res = client.get(f'/pay_structure_list?empid={e_id}')
        self.assertEqual(list_res.status_code, 200)
        list_data = list_res.get_json()
        self.assertTrue(len(list_data['structures']) > 0)
        ps_record = list_data['structures'][0]
        self.assertEqual(ps_record['empid'], e_id)
        self.assertEqual(ps_record['grade'], 'B')
        self.assertEqual(ps_record['pay_group'], 'Regular')
        self.assertEqual(ps_record['pay_term'], 'Monthly')

        # Promote regular to Senior Management (Grade A)
        promote_a = client.post('/update_employee', json={
            'empid': e_id,
            'first_name': 'Ramesh',
            'last_name': 'Kumar',
            'email': f'ramesh.{uid}@example.com',
            'hire_date': '2026-01-10',
            'grade': 'A',
            'is_active': 1
        })
        self.assertEqual(promote_a.status_code, 200)
        a_data = promote_a.get_json()
        self.assertEqual(a_data['empid'], m_id)

        # Add Employee with Grade F (Other) -> suffix F
        res_f = client.post('/add_employee', json={
            'first_name': 'Sunil',
            'last_name': 'Verma',
            'email': f'sunil.{uid}@example.com',
            'hire_date': '2026-01-15',
            'grade': 'F',
            'numeric_id': f_num
        })
        self.assertEqual(res_f.status_code, 201)
        data_f = res_f.get_json()
        self.assertEqual(data_f['empid'], f_id)

    def test_attendance_period_bounds(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_payroll_schema(conn)

        # Weekly
        set_pay_term_setting(conn, 'attendance_submission_frequency', 'weekly')
        set_pay_term_setting(conn, 'work_week', 'mon_fri')
        start, end, freq = attendance_period_bounds(conn, date(2026, 11, 11))
        self.assertEqual(freq, 'weekly')
        self.assertEqual(start.weekday(), 0) # Monday
        self.assertEqual(end.weekday(), 4)   # Friday

        # Monthly
        set_pay_term_setting(conn, 'attendance_submission_frequency', 'monthly')
        start_m, end_m, freq_m = attendance_period_bounds(conn, date(2026, 11, 11))
        self.assertEqual(freq_m, 'monthly')
        self.assertEqual(start_m, date(2026, 11, 1))
        self.assertEqual(end_m, date(2026, 11, 30))
        conn.close()

    def test_attendance_submission_and_approval_workflow(self):
        import uuid
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'

        uid = uuid.uuid4().hex[:6]
        # Grade B employee (Senior Manager approval needed)
        emp_res = client.post('/add_employee', json={
            'first_name': 'Approval',
            'last_name': 'Test',
            'email': f'appr.{uid}@example.com',
            'hire_date': '2026-01-01',
            'grade': 'B'
        })
        empid_b = emp_res.get_json()['empid']
        client.post('/save_pay_structure', json={
            'empid': empid_b, 'name': 'Approval Test', 'grade': 'B', 'pay_group': 'Regular',
            'pay_term': 'Monthly', 'salary': 50000, 'job_id': 'DEV-01', 'active': True
        })

        # Submit attendance by employee
        sub_res = client.post('/payroll/attendance/submit-period', json={
            'empid': empid_b,
            'period_start': '2026-11-02',
            'period_end': '2026-11-06',
            'frequency': 'weekly',
            'submitted_by': 'employee',
            'days': [
                {'work_date': '2026-11-02', 'status': 'present', 'leave_type': None, 'notes': ''},
                {'work_date': '2026-11-03', 'status': 'present', 'leave_type': None, 'notes': ''},
                {'work_date': '2026-11-04', 'status': 'present', 'leave_type': None, 'notes': ''},
                {'work_date': '2026-11-05', 'status': 'present', 'leave_type': None, 'notes': ''},
                {'work_date': '2026-11-06', 'status': 'present', 'leave_type': None, 'notes': ''},
            ]
        })
        self.assertEqual(sub_res.status_code, 200)
        # Grade B requires Senior Manager approval -> status should be 'submitted'
        self.assertEqual(sub_res.get_json()['submission_status'], 'submitted')
        self.assertEqual(sub_res.get_json()['total_hours'], 45.0) # 5 days * 9 hrs

        # Fetch submissions
        subs = client.get('/payroll/attendance/submissions?status=submitted').get_json()['submissions']
        my_sub = next(s for s in subs if s['empid'] == empid_b)

        # Senior Manager approves
        act_res = client.post(f"/payroll/attendance/submissions/{my_sub['submission_id']}/action", json={
            'action': 'approve'
        })
        self.assertEqual(act_res.status_code, 200)
        self.assertEqual(act_res.get_json()['submission_status'], 'approved')

        # Grade A employee (Approval NOT needed)
        emp_a = client.post('/add_employee', json={
            'first_name': 'Senior',
            'last_name': 'Mgr',
            'email': f'mgr.{uid}@example.com',
            'hire_date': '2026-01-01',
            'grade': 'A'
        })
        empid_a = emp_a.get_json()['empid']
        sub_a = client.post('/payroll/attendance/submit-period', json={
            'empid': empid_a,
            'period_start': '2026-11-02',
            'period_end': '2026-11-06',
            'frequency': 'weekly',
            'submitted_by': 'employee',
            'days': [{'work_date': '2026-11-02', 'status': 'present', 'leave_type': None, 'notes': ''}]
        })
        # Grade A auto-approves
        self.assertEqual(sub_a.get_json()['submission_status'], 'approved')

    def test_manager_submit_on_behalf_auto_approves(self):
        import uuid
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'

        uid = uuid.uuid4().hex[:6]
        emp_res = client.post('/add_employee', json={
            'first_name': 'Behalf',
            'last_name': 'Test',
            'email': f'behalf.{uid}@example.com',
            'hire_date': '2026-01-01',
            'grade': 'C'
        })
        empid_c = emp_res.get_json()['empid']
        client.post('/save_pay_structure', json={
            'empid': empid_c, 'name': 'Behalf Test', 'grade': 'C', 'pay_group': 'Contract',
            'pay_term': 'Monthly', 'salary': 40000, 'job_id': 'DEV-02', 'active': True
        })

        sub_res = client.post('/payroll/attendance/submit-period', json={
            'empid': empid_c,
            'period_start': '2026-11-02',
            'period_end': '2026-11-06',
            'frequency': 'weekly',
            'submitted_by': 'manager',
            'days': [{'work_date': '2026-11-02', 'status': 'present', 'leave_type': None, 'notes': ''}]
        })
        self.assertEqual(sub_res.get_json()['submission_status'], 'approved')

    def test_leave_balance_and_loss_of_pay(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE pd_employees (
                empid TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                email TEXT,
                hire_date TEXT,
                grade TEXT,
                is_active INTEGER,
                employment_type TEXT
            );
            CREATE TABLE pay_structure (
                id INTEGER PRIMARY KEY,
                empid TEXT NOT NULL,
                pay_term TEXT,
                salary REAL,
                pay_group TEXT,
                active INTEGER
            );
            CREATE TABLE payments (
                payment_id INTEGER PRIMARY KEY,
                empid TEXT NOT NULL,
                payment_status TEXT,
                payment_ref TEXT
            );
            INSERT INTO pd_employees VALUES
                ('E55001', 'Regular', 'Emp', 'reg@test.com', '2026-01-01', 'B', 1, 'permanent');
            INSERT INTO pay_structure VALUES
                (1, 'E55001', 'Monthly', 50000, 'Regular', 1);
        """)
        ensure_payroll_schema(conn)

        # Employee takes 2 absences in June 2026
        conn.execute("INSERT INTO attendance_daily (empid, work_date, status) VALUES ('E55001', '2026-06-01', 'absent')")
        conn.execute("INSERT INTO attendance_daily (empid, work_date, status) VALUES ('E55001', '2026-06-02', 'absent')")

        lines = calculate_payroll_lines(conn, date(2026, 6, 1), date(2026, 6, 30), date(2026, 6, 30))
        line = next(l for l in lines if l['empid'] == 'E55001')
        self.assertEqual(line['lop_days'], 2)
        self.assertTrue(line['lop_amount_minor'] > 0)
        self.assertEqual(line['amount_minor'], 5000000 - line['lop_amount_minor'])
        conn.close()

    def test_payroll_run_lifecycle_and_pay_term_segmentation(self):
        import uuid
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'

        conn = get_db_connection()
        conn.execute("DELETE FROM payroll_runs WHERE period_start = '2028-05-01'")
        conn.commit()
        conn.close()

        # Generate run for monthly
        res = client.post('/payroll/runs', json={
            'cutoff_date': '2028-05-31',
            'pay_term': 'monthly'
        })
        self.assertEqual(res.status_code, 200)
        run = res.get_json()['run']
        run_id = run['run_id']
        self.assertEqual(run['status'], 'generated')

        # Submit run for approval
        sub_res = client.post(f'/payroll/runs/{run_id}/submit')
        self.assertEqual(sub_res.status_code, 200)
        self.assertEqual(sub_res.get_json()['run']['status'], 'submitted')

        # Senior Manager Approves
        appr_res = client.post(f'/payroll/runs/{run_id}/approve')
        self.assertEqual(appr_res.status_code, 200)
        self.assertEqual(appr_res.get_json()['run']['status'], 'approved')

        # Create payments
        create_res = client.post(f'/payroll/runs/{run_id}/create-payments')
        self.assertEqual(create_res.status_code, 200)
        self.assertEqual(create_res.get_json()['run']['status'], 'created')

    def test_employee_name_and_email_autofill_for_personal_details(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'

        # Fetch existing employee M00001
        res = client.get('/employee/M00001')
        self.assertEqual(res.status_code, 200)
        emp = res.get_json()['employee']
        full_name = f"{emp['first_name']} {emp['last_name']}".strip()
        self.assertEqual(full_name, 'Mahesh Dasari')
        self.assertEqual(emp['email'], 'mahesh.dasari@payday.com')


if __name__ == '__main__':
    unittest.main()
