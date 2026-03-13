from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('Paydaytest.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    return app.send_static_file('home.html')
@app.route('/employee_details')
def main_page():
    return app.send_static_file('employee_details.html')

@app.route('/add_employee', methods=['POST'])
def add_employee():
    try:
        data = request.get_json()
        
        first_name = data['first_name']
        last_name  = data['last_name']
        email      = data.get('email')
        hire_date  = data.get('hire_date')
        Grade      = data.get('Grade')
        # salary column removed from pd_employees, ignore any incoming value
        is_active  = data.get('is_active', 1)

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO pd_employees (first_name, last_name, email, hire_date, grade, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (first_name, last_name, email, hire_date, data.get('grade'), is_active))
        
        conn.commit()
        # Get the newly inserted empid
        new_empid = cursor.lastrowid
        conn.close()
        
        return jsonify({"status": "success", "message": "Employee added successfully","empid": new_empid}), 201
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
@app.route('/employees', methods=['GET'])
def get_employees():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pd_employees ORDER BY empid DESC')
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        conn.close()
        
        employees = []
        for row in rows:
            emp_dict = {}
            for idx, col_name in enumerate(columns):
                emp_dict[col_name] = row[idx]
            employees.append(emp_dict)
        
        return jsonify({
            "status": "success",
            "employees": employees
        }), 200
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/search', methods=['GET'])
def search_employees():
    try:
        field = request.args.get('field')
        value = request.args.get('value')

        if not field or value is None:
            return jsonify({"status": "error", "message": "Missing search field or value"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Build query safely
        query = f"SELECT * FROM pd_employees WHERE {field} = ?"
        params = (value,)

        # Special handling for is_active (it's integer 0/1)
        if field == 'is_active':
            try:
                value = int(value)  # convert "1" or "0" to int
            except ValueError:
                return jsonify({"status": "error", "message": "Active must be 0 or 1"}), 400

        # For text fields, if you want partial match (LIKE) instead of exact, uncomment next line
        # if field in ['first_name', 'last_name', 'email']:
        #     query = f"SELECT * FROM pd_employees WHERE {field} LIKE ?"
         #    params = (f"%{value}%",)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        conn.close()

        employees = []
        for row in rows:
            emp_dict = {}
            for idx, col_name in enumerate(columns):
                emp_dict[col_name] = row[idx]
            employees.append(emp_dict)

        return jsonify({
            "status": "success",
            "employees": employees
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/employee/<int:empid>', methods=['GET'])
def get_employee(empid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pd_employees WHERE empid = ?', (empid,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return jsonify({"status": "error", "message": "Employee not found"}), 404

        # Convert row to dict using actual column names
        columns = [description[0] for description in cursor.description]
        employee = {}
        for idx, col_name in enumerate(columns):
            employee[col_name] = row[idx]

        return jsonify({
            "status": "success",
            "employee": employee
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/update_employee', methods=['POST'])
def update_employee():
    try:
        data = request.get_json()

        empid = data['empid']
        first_name = data['first_name']
        last_name = data['last_name']
        email = data.get('email')
        hire_date = data.get('hire_date')
        grade = data.get('grade')
        # salary column removed, ignore
        is_active = data.get('is_active', 1)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE pd_employees
            SET first_name = ?, last_name = ?, email = ?, hire_date = ?, grade = ?, is_active = ?
            WHERE empid = ?
        ''', (first_name, last_name, email, hire_date, data.get('grade'), is_active, empid))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Employee updated successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

@app.route('/save_bank_details', methods=['POST'])
def save_bank_details():
    data = request.get_json()

    record_id      = data.get('record_id')               # will be None or empty string on add
    empid          = data.get('empid')
    bank_name      = data.get('bank_name')
    account_number = data.get('account_number')
    ifsc_code      = data.get('ifsc_code')
    account_holder = data.get('account_holder')
    branch_name    = data.get('branch_name') or None

    if not empid or not bank_name or not account_number or not ifsc_code or not account_holder:
        return jsonify({
            'status': 'error',
            'message': 'Missing required fields'
        }), 400

    conn = get_db_connection()   # your function to get connection
    cursor = conn.cursor()

    try:
        if record_id:  # ────────────── UPDATE mode ──────────────
            cursor.execute("""
                UPDATE bank_details
                SET 
                    bank_name      = ?,
                    account_number = ?,
                    ifsc_code      = ?,
                    account_holder = ?,
                    branch_name    = ?
                WHERE id = ?
            """, (
                bank_name,
                account_number,
                ifsc_code,
                account_holder,
                branch_name,
                record_id
            ))

            if cursor.rowcount == 0:
                return jsonify({
                    'status': 'error',
                    'message': 'No record found with this ID'
                }), 404

            message = 'Bank details updated successfully'

        else:  # ────────────── INSERT mode ──────────────
            # Optional: extra safety check (though frontend already prevents this)
            cursor.execute("SELECT 1 FROM bank_details WHERE empid = ?", (empid,))
            if cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': 'Bank details already exist for this employee'
                }), 409

            cursor.execute("""
                INSERT INTO bank_details 
                (empid, bank_name, account_number, ifsc_code, account_holder, branch_name)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                empid,
                bank_name,
                account_number,
                ifsc_code,
                account_holder,
                branch_name
            ))

            message = 'Bank details added successfully'

        conn.commit()
        return jsonify({'status': 'success', 'message': message})

    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if "UNIQUE constraint" in error_msg:
            return jsonify({
                'status': 'error',
                'message': 'Bank details already exist for this employee (unique constraint)'
            }), 409
        else:
            return jsonify({
                'status': 'error',
                'message': f'Database error: {error_msg}'
            }), 500

@app.route('/bank-details')
def bank_details():
    return app.send_static_file('bank_details.html')
@app.route('/search_bank_details', methods=['GET'])
def search_bank_details():
    try:
        empid_filter = request.args.get('empid')

        conn = get_db_connection()
        cursor = conn.cursor()

        if empid_filter:
            cursor.execute('''
                SELECT * FROM bank_details 
                WHERE empid = ?
                ORDER BY id DESC
            ''', (int(empid_filter),))
        else:
            cursor.execute('SELECT * FROM bank_details ORDER BY id DESC')

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        bank_details = []
        for row in rows:
            record = {}
            for idx, col_name in enumerate(columns):
                record[col_name] = row[idx]
            bank_details.append(record)

        return jsonify({
            "status": "success",
            "bank_details": bank_details
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/bank_record/<int:record_id>', methods=['GET'])
def get_bank_record(record_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.empid, b.bank_name, b.account_number, b.ifsc_code,
                   b.account_holder, b.branch_name,
                   e.first_name || ' ' || e.last_name AS name,
                   e.email
            FROM bank_details b
            LEFT JOIN pd_employees e ON b.empid = e.empid
            WHERE b.id = ?
        """, (record_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return jsonify({
                'status': 'success',
                'record': {
                    'id': row['id'],
                    'empid': row['empid'],
                    'bank_name': row['bank_name'],
                    'account_number': row['account_number'],
                    'ifsc_code': row['ifsc_code'],
                    'account_holder': row['account_holder'],
                    'branch_name': row['branch_name'],
                    'name': row['name'],
                    'email': row['email']
                }
            })
        else:
            return jsonify({'status': 'error', 'message': 'Record not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
# Get bank record by employee id (for Add form duplicate check)
@app.route('/bank_by_empid/<int:empid>', methods=['GET'])
def get_bank_by_empid(empid):
   try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, empid, bank_name, account_number, ifsc_code,
               account_holder, branch_name
        FROM bank_details
        WHERE empid = ?
    """, (empid,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return jsonify({
            'status': 'success',
            'record': dict(row)
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'No bank details for this employee'
        }),404
   except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
@app.route('/personal_details')
def personal_details():
    return app.send_static_file('personal_details.html')


@app.route('/save_personal_details', methods=['POST'])
def save_personal_details():
    try:
        data = request.get_json()
        empid = data['empid']
        Name = data['Name']
        Gender = data.get('Gender')
        dob = data.get('dob')
        phone = data['phone']
        email = data.get('email')
        marrital_status = data.get('marrital_status')
        blood_group = data.get('blood_group')
        Address1 = data['Address1']
        Address2 = data.get('Address2')
        City = data.get('City')
        State = data.get('State')
        Country = data.get('Country')
        PINCode = data.get('PINCode')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if empid exists in pd_employees
        cursor.execute("SELECT empid FROM pd_employees WHERE empid = ?", (empid,))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"status": "error", "message": f"Employee ID {empid} does not exist"}), 400

        # Check if personal record already exists for this empid
        cursor.execute("SELECT empid FROM pd_empersonal WHERE empid = ?", (empid,))
        existing = cursor.fetchone()

        if existing:
            # UPDATE existing record
            cursor.execute('''
                UPDATE pd_empersonal
                SET Name = ?, Gender = ?, dob = ?, phone = ?, email = ?, marrital_status = ?,
                    blood_group = ?, Address1 = ?, Address2 = ?, City = ?, State = ?,
                    Country = ?, PINCode = ?
                WHERE empid = ?
            ''', (Name, Gender, dob, phone, email, marrital_status,
                  blood_group, Address1, Address2, City, State, Country, PINCode, empid))
            message = "Personal details updated successfully"
        else:
            # INSERT new record
            cursor.execute('''
                INSERT INTO pd_empersonal (
                    empid, Name, Gender, dob, phone, email, marrital_status,
                    blood_group, Address1, Address2, City, State, Country, PINCode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (empid, Name, Gender, dob, phone, email, marrital_status,
                  blood_group, Address1, Address2, City, State, Country, PINCode))
            message = "Personal details saved successfully"

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": message
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/compensation-details')
def compensation_details():
    return app.send_static_file('compensation_details.html')
@app.route('/compensation/employee/<int:empid>', methods=['GET'])
def get_employee_for_compensation(empid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                e.empid,
                COALESCE(p.Name, '') AS name,
                e.email,
                e.hire_date,
                e.grade
            FROM pd_employees e
            LEFT JOIN pd_empersonal p
                ON e.empid = p.empid
            WHERE e.empid = ?
        """, (empid,))

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return jsonify({
                "status": "error",
                "message": "Employee not found"
            }), 404

        return jsonify({
            "status": "success",
            "employee": {
                "empid": row["empid"],
                "name": row["name"],
                "email": row["email"],
                "hire_date": row["hire_date"],
                "grade": row["grade"]
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

# Route to serve the pay_structure.html page (static file)
@app.route('/pay_structure')
def serve_pay_structure():
    return app.send_static_file('pay_structure.html')


# ----------------------------------------------------------------
#  GET /pay_structure_list   → returns list for search/table
# ----------------------------------------------------------------
@app.route('/pay_structure_list', methods=['GET'])
def pay_structure_list():
    empid_filter = request.args.get('empid')

    conn = get_db_connection()
    cursor = conn.cursor()

    if empid_filter:
        cursor.execute("""
            SELECT 
    ps.empid,
    e.first_name || ' ' || e.last_name AS name,
    ps.pay_term,
    ps.salary,
    ps.job_id,
    ps.pay_group,
    ps.updated_at,
    ps.notes
FROM pay_structure ps
LEFT JOIN pd_employees e ON ps.empid = e.empid
            WHERE ps.empid = ?
            ORDER BY ps.empid
        """, (empid_filter,))
    else:
        cursor.execute("""
            SELECT 
    ps.empid,
    e.first_name || ' ' || e.last_name AS name,
    ps.pay_term,
    ps.salary,
    ps.job_id,
    ps.pay_group,
    ps.updated_at,
    ps.notes
FROM pay_structure ps
LEFT JOIN pd_employees e ON ps.empid = e.empid
            ORDER BY ps.updated_at DESC
            LIMIT 500
        """)

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    records = [dict(zip(columns, row)) for row in rows]

    conn.close()

    return jsonify({
        "status": "success",
        "structures": records
    })


# ----------------------------------------------------------------
#  POST /save_pay_structure   → create or update record
# ----------------------------------------------------------------
@app.route('/save_pay_structure', methods=['POST'])
def save_pay_structure():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        print("DEBUG - Received pay_structure data:", data)  # Debug print

        empid      = data.get('empid')
        name       = data.get('name')
        pay_term   = (data.get('pay_term')   or '').strip()
        salary     = data.get('salary')           # we'll convert later
        job_id     = (data.get('job_id')     or '').strip()
        pay_group  = (data.get('pay_group')  or '').strip()
        notes      = (data.get('notes')      or '').strip()
        if not empid:
            return jsonify({"status": "error", "message": "Employee ID is required"}), 400

        # Optional: convert salary safely
        try:
            salary = float(salary) if salary else None
        except (ValueError, TypeError):
            salary = None

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if empid exists in pd_employees
        cursor.execute("SELECT empid FROM pd_employees WHERE empid = ?", (empid,))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"status": "error", "message": f"Employee ID {empid} does not exist"}), 400

        # Try UPDATE first (if record exists)
        cursor.execute("""
            UPDATE pay_structure 
            SET name = ?, pay_term = ?, salary = ?, job_id = ?, pay_group = ?, updated_at = CURRENT_TIMESTAMP, notes=?
            WHERE empid = ?
        """, (name, pay_term, salary, job_id, pay_group, notes, empid))

        if cursor.rowcount == 0:
            # INSERT if no record existed
            cursor.execute("""
                INSERT INTO pay_structure 
                (empid, name, pay_term, salary, job_id, pay_group, updated_at,notes)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,?)
            """, (empid,name, pay_term, salary, job_id, pay_group, notes))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Pay structure saved successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    
@app.route('/tax-deductions')
def tax_deductions():
    return app.send_static_file('tax_deductions.html')
@app.route('/reports')
def reports():
    return app.send_static_file('reports.html')
    
@app.route('/compensation_record/<int:empid>', methods=['GET'])
def get_compensation_record(empid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT empid, name, email, hire_date, grade,
                   basic_monthly, monthly_performance, performance_bonus, city_allowance,
                   hra, lta, food_card, communication, personal_allowance,
                   health_insurance, provident_fund, gratuity,
                   overtime_pay, transport_allowance,
                   currency, pay_period
            FROM pd_compensation
            WHERE empid = ?
        ''', (empid,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return jsonify({"status": "error", "message": "Compensation record not found"}), 404

        record = dict(row)
        return jsonify({"status": "success", "record": record}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
@app.route('/save_compensation', methods=['POST'])
def save_compensation():
    try:
        data = request.get_json()
        print("DEBUG - Received payload:", data)  # ← Look at this in terminal

        empid = data.get('empid')
        if not empid:
            return jsonify({"status": "error", "message": "Employee ID is required"}), 400

        # All fields use .get() → None if missing
        name                   = data.get('name')
        email                  = data.get('email')
        hire_date              = data.get('hire_date')
        grade                  = data.get('grade')

        basic_monthly          = data.get('basic_monthly')
        monthly_performance    = data.get('monthly_performance')
        performance_bonus      = data.get('performance_bonus')
        city_allowance         = data.get('city_allowance')

        hra                    = data.get('hra')
        lta                    = data.get('lta')
        food_card              = data.get('food_card')
        communication          = data.get('communication')
        personal_allowance     = data.get('personal_allowance')

        health_insurance       = data.get('health_insurance')
        provident_fund         = data.get('provident_fund')
        gratuity               = data.get('gratuity')

        overtime_pay           = data.get('overtime_pay')
        transport_allowance    = data.get('transport_allowance')

        currency               = data.get('currency', 'INR')
        pay_period             = data.get('pay_period', 'Monthly')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check employee exists
        cursor.execute("SELECT empid FROM pd_employees WHERE empid = ?", (empid,))
        if cursor.fetchone() is None:
            conn.close()
            return jsonify({"status": "error", "message": f"Employee ID {empid} does not exist"}), 400

        # Check if record exists
        cursor.execute("SELECT empid FROM pd_compensation WHERE empid = ?", (empid,))
        exists = cursor.fetchone() is not None

        if exists:
            # UPDATE - only update fields that are sent (others stay as-is)
            cursor.execute('''
                UPDATE pd_compensation
                SET 
                    name = COALESCE(?, name),
                    email = COALESCE(?, email),
                    hire_date = COALESCE(?, hire_date),
                    grade = COALESCE(?, grade),
                    basic_monthly = COALESCE(?, basic_monthly),
                    monthly_performance = COALESCE(?, monthly_performance),
                    performance_bonus = COALESCE(?, performance_bonus),
                    city_allowance = COALESCE(?, city_allowance),
                    hra = COALESCE(?, hra),
                    lta = COALESCE(?, lta),
                    food_card = COALESCE(?, food_card),
                    communication = COALESCE(?, communication),
                    personal_allowance = COALESCE(?, personal_allowance),
                    health_insurance = COALESCE(?, health_insurance),
                    provident_fund = COALESCE(?, provident_fund),
                    gratuity = COALESCE(?, gratuity),
                    overtime_pay = COALESCE(?, overtime_pay),
                    transport_allowance = COALESCE(?, transport_allowance),
                    currency = COALESCE(?, currency),
                    pay_period = COALESCE(?, pay_period),
                    updated_at = datetime('now')
                WHERE empid = ?
            ''', (name, email, hire_date, grade,
                  basic_monthly, monthly_performance, performance_bonus, city_allowance,
                  hra, lta, food_card, communication, personal_allowance,
                  health_insurance, provident_fund, gratuity,
                  overtime_pay, transport_allowance,
                  currency, pay_period,
                  empid))
            message = "Compensation details updated successfully"
        else:
            # INSERT - use defaults for missing fields
            cursor.execute('''
                INSERT INTO pd_compensation (
                    empid, name, email, hire_date, grade,
                    basic_monthly, monthly_performance, performance_bonus, city_allowance,
                    hra, lta, food_card, communication, personal_allowance,
                    health_insurance, provident_fund, gratuity,
                    overtime_pay, transport_allowance,
                    currency, pay_period,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ''', (empid, name, email, hire_date, grade,
                  basic_monthly, monthly_performance, performance_bonus, city_allowance,
                  hra, lta, food_card, communication, personal_allowance,
                  health_insurance, provident_fund, gratuity,
                  overtime_pay, transport_allowance,
                  currency, pay_period))
            message = "Compensation details saved successfully"

        conn.commit()
        conn.close()

        return jsonify({"status": "success", "message": message}), 200

    except Exception as e:
        print("Save error:", str(e))  # Print full error in terminal
        return jsonify({"status": "error", "message": str(e)}), 400
        
@app.route('/search_compensation', methods=['GET'])
def search_compensation():
    try:
        empid_filter = request.args.get('empid')

        conn = get_db_connection()
        cursor = conn.cursor()

        if empid_filter:
            cursor.execute('''
                SELECT empid, name, 
                       basic_monthly, monthly_performance, performance_bonus, city_allowance,
                       hra, lta, food_card, communication, personal_allowance,
                       health_insurance, provident_fund, gratuity,
                       overtime_pay, transport_allowance,
                       currency, pay_period
                FROM pd_compensation 
                WHERE empid = ?
                ORDER BY empid DESC
            ''', (int(empid_filter),))
        else:
            cursor.execute('''
                SELECT empid, name, 
                       basic_monthly, monthly_performance, performance_bonus, city_allowance,
                       hra, lta, food_card, communication, personal_allowance,
                       health_insurance, provident_fund, gratuity,
                       overtime_pay, transport_allowance,
                       currency, pay_period
                FROM pd_compensation 
                ORDER BY empid DESC
            ''')

        rows = cursor.fetchall()
        conn.close()

        records = [dict(row) for row in rows]

        return jsonify({
            "status": "success",
            "compensation": records
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
@app.route('/search_personal_details', methods=['GET'])
def search_personal_details():
    try:
        empid_filter = request.args.get('empid')

        conn = get_db_connection()
        cursor = conn.cursor()

        if empid_filter:
            cursor.execute('''
                SELECT * FROM pd_empersonal 
                WHERE empid = ?
                ORDER BY empid DESC
            ''', (int(empid_filter),))
        else:
            cursor.execute('SELECT * FROM pd_empersonal ORDER BY empid DESC')

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        records = []
        for row in rows:
            record = {}
            for idx, col_name in enumerate(columns):
                record[col_name] = row[idx]
            records.append(record)

        return jsonify({
            "status": "success",
            "personal": records
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/personal_record/<int:empid>', methods=['GET'])
def get_personal_record(empid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pd_empersonal WHERE empid = ?', (empid,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return jsonify({"status": "error", "message": "Personal record not found"}), 404

        columns = [desc[0] for desc in cursor.description]
        record = {}
        for idx, col_name in enumerate(columns):
            record[col_name] = row[idx]

        return jsonify({
            "status": "success",
            "record": record
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
@app.route('/pay')
def pay():
    return app.send_static_file('pay.html')


# NEW: Process payment endpoint (called when user clicks "Pay Now")
@app.route('/process_pay', methods=['POST'])
def process_pay():
    data = request.get_json()
    
    required_fields = ['empid', 'pay_term', 'amount', 'monthly_salary']  # monthly_salary will be provided by frontend
    for field in required_fields:
        if field not in data:
            return jsonify({
                'status': 'error',
                'message': f'Missing required field: {field}'
            }), 400
    
    empid = data['empid']
    pay_term = data['pay_term']
    amount = float(data['amount'])
    monthly_salary = float(data['monthly_salary'])
    
    if amount <= 0:
        return jsonify({
            'status': 'error',
            'message': 'Invalid payment amount'
        }), 400
    
    conn = get_db_connection()
    
    # Verify employee exists and is active (no salary check any more)
    employee = conn.execute('''
        SELECT empid, is_active
        FROM pd_employees
        WHERE empid = ?
    ''', (empid,)).fetchone()
    
    if employee is None:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'Employee not found'
        }), 404
    
    if not employee['is_active']:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'Employee is not active'
        }), 400
    
    
    # For now: just simulate success (in Step 3/4 we'll record this in a payments table)
    payment_record = {
        'empid': empid,
        'pay_term': pay_term,
        'amount': amount,
        'monthly_base': monthly_salary,
        'paid_at': datetime.now().isoformat(),
        'status': 'completed'  # we'll use real status later
    }
    
    # TODO (future step): Insert into a payments table
    # conn.execute('''
    #     INSERT INTO payments (empid, pay_term, amount, monthly_base, paid_at, status)
    #     VALUES (?, ?, ?, ?, ?, ?)
    # ''', (empid, pay_term, amount, monthly_salary, datetime.now(), 'completed'))
    # conn.commit()
    
    conn.close()
    
    return jsonify({
        'status': 'success',
        'message': f'Payment of ₹{amount:,.2f} processed successfully for employee {empid}',
        'payment': payment_record
    })


# Optional: Add this if you want to see all payments later (for testing)
@app.route('/payments')
def list_payments():
    # We'll implement properly when we add the table
    return jsonify({'message': 'Payments list coming in future step'})    
if __name__ == '__main__':
    app.run(debug=True, port=5000)