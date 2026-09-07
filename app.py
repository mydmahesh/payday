from flask import Flask, request, jsonify, session, redirect, url_for, flash, render_template
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure key

def get_db_connection():
    conn = sqlite3.connect('Paydaytest.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS pdusers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()


def ensure_pay_structure_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Ensure table exists with a proper schema (id primary key, active flag, timestamps)
    cursor.execute("""SELECT name FROM sqlite_master WHERE type='table' AND name='pay_structure'""")
    if cursor.fetchone() is None:
        cursor.execute('''
            CREATE TABLE pay_structure (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empid INTEGER NOT NULL,
                name TEXT,
                pay_term TEXT,
                salary REAL,
                job_id TEXT,
                pay_group TEXT,
                active INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        ''')
        conn.commit()
        conn.close()
        return

    # Table exists, check if required columns exist
    cursor.execute("PRAGMA table_info(pay_structure)")
    existing_cols = {row['name'] for row in cursor.fetchall()}

    # Add missing active flag if needed
    if 'active' not in existing_cols:
        cursor.execute('ALTER TABLE pay_structure ADD COLUMN active INTEGER DEFAULT 0')

    # Add paid flag if needed
    if 'paid' not in existing_cols:
        cursor.execute('ALTER TABLE pay_structure ADD COLUMN paid INTEGER DEFAULT 0')

    # If the table has no explicit id column, migrate it to a new schema with id primary key
    if 'id' not in existing_cols:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pay_structure_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empid INTEGER NOT NULL,
                name TEXT,
                pay_term TEXT,
                salary REAL,
                job_id TEXT,
                pay_group TEXT,
                active INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        ''')

        cursor.execute('''
            INSERT INTO pay_structure_new (id, empid, name, pay_term, salary, job_id, pay_group, active, updated_at, notes)
            SELECT rowid, empid, name, pay_term, salary, job_id, pay_group,
                   COALESCE(active, 0),
                   COALESCE(updated_at, CURRENT_TIMESTAMP),
                   notes
            FROM pay_structure
        ''')

        cursor.execute('DROP TABLE pay_structure')
        cursor.execute('ALTER TABLE pay_structure_new RENAME TO pay_structure')

    conn.commit()
    conn.close()


def ensure_payments_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""SELECT name FROM sqlite_master WHERE type='table' AND name='payments'""")
    if cursor.fetchone() is None:
        cursor.execute('''
            CREATE TABLE payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                empid INTEGER NOT NULL,
                name TEXT,
                hire_date TEXT,
                pay_group TEXT,
                pay_term TEXT,
                pay_amount REAL,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                payment_handling_code TEXT,
                payment_status TEXT,
                reconcile_date TIMESTAMP,
                recon_status TEXT,
                payment_ref TEXT
            )
        ''')
        conn.commit()
        conn.close()
        return

    conn.commit()
    conn.close()


def row_to_dict(row, columns):
    return {col: row[idx] for idx, col in enumerate(columns)}


def rows_to_list(cursor, rows):
    columns = [desc[0] for desc in cursor.description]
    return [row_to_dict(row, columns) for row in rows]


def as_bool(value):
    return str(value).lower() in {'1', 'true', 'yes', 'y', 'on'}


# Initialize database on startup
init_db()
ensure_pay_structure_schema()
ensure_payments_schema()

@app.before_request
def require_login():
    allowed_routes = ['login', 'login_post', 'register', 'register_post', 'static']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        # If this is an AJAX/API request, return JSON instead of redirecting to login page
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
           'application/json' in request.headers.get('Accept', ''):
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        return redirect(url_for('login'))

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register_post():
    data = request.form
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirmPassword')

    if password != confirm_password:
        flash('Passwords do not match')
        return redirect(url_for('register'))

    conn = get_db_connection()
    try:
        hashed_password = generate_password_hash(password)
        conn.execute('INSERT INTO pdusers (name, email, password) VALUES (?, ?, ?)',
                     (name, email, hashed_password))
        conn.commit()
        flash('Account created successfully! Please log in.')
        return redirect(url_for('login'))
    except sqlite3.IntegrityError:
        flash('Email already exists')
        return redirect(url_for('register'))
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
def login_post():
    data = request.form
    email = data.get('email')
    password = data.get('password')

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM pdusers WHERE email = ?', (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return redirect(url_for('home'))
    else:
        flash('Invalid email or password')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

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
        employees = rows_to_list(cursor, cursor.fetchall())
        conn.close()
        return jsonify({"status": "success", "employees": employees}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
@app.route('/search', methods=['GET'])
def search_employees():
    try:
        field = request.args.get('field')
        value = request.args.get('value')

        if not field or value is None:
            return jsonify({"status": "error", "message": "Missing search field or value"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        query = f"SELECT * FROM pd_employees WHERE {field} = ?"
        params = (value,)

        if field == 'is_active':
            try:
                value = int(value)
            except ValueError:
                return jsonify({"status": "error", "message": "Active must be 0 or 1"}), 400
            params = (value,)

        cursor.execute(query, params)
        employees = rows_to_list(cursor, cursor.fetchall())
        conn.close()
        return jsonify({"status": "success", "employees": employees}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


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

        employee = row_to_dict(row, [description[0] for description in cursor.description])
        return jsonify({"status": "success", "employee": employee}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


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
        ''', (first_name, last_name, email, hire_date, grade, is_active, empid))

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
        conn.close()
        bank_details = rows_to_list(cursor, rows)

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

@app.route('/edit_pay_structure')
def edit_pay_structure():
    return app.send_static_file('edit_pay_structure.html')


# ----------------------------------------------------------------
#  GET /pay_structure_list   → returns list for search/table
# ----------------------------------------------------------------
@app.route('/pay_structure_list', methods=['GET'])
def pay_structure_list():
    empid_filter = request.args.get('empid')
    record_id = request.args.get('record_id')
    active_only = request.args.get('active') in ['1', 'true', 'True', 'yes']

    conn = get_db_connection()
    cursor = conn.cursor()

    base_select = """
        SELECT
            ps.id,
            ps.empid,
            e.first_name || ' ' || e.last_name AS name,
            ps.pay_term,
            ps.salary,
            ps.job_id,
            ps.pay_group,
            ps.active,
            ps.updated_at,
            ps.notes,
            e.hire_date
        FROM pay_structure ps
        LEFT JOIN pd_employees e ON ps.empid = e.empid
    """
    where_clauses = []
    params = []

    if record_id:
        where_clauses.append('ps.id = ?')
        params.append(record_id)

    if empid_filter:
        where_clauses.append('ps.empid = ?')
        params.append(empid_filter)

    if active_only:
        where_clauses.append('ps.active = 1')
        where_clauses.append('ps.paid = 0')

    if where_clauses:
        base_select += ' WHERE ' + ' AND '.join(where_clauses)

    base_select += ' ORDER BY ps.updated_at DESC'

    if not record_id and not empid_filter:
        base_select += ' LIMIT 500'

    cursor.execute(base_select, tuple(params))

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    records = []
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    for row in rows:
        record = dict(zip(columns, row))
        hire_date_str = record.get('hire_date')
        pay_term = record.get('pay_term')
        next_due = None
        if hire_date_str and pay_term:
            try:
                hire_date = datetime.fromisoformat(hire_date_str).date()
                if pay_term == 'One-time':
                    next_due = hire_date if hire_date >= today else None
                elif pay_term == 'daily':
                    next_due = today  # Daily is due every day, so today
                elif pay_term == 'weekly':
                    period = 7
                elif pay_term == 'bi-weekly':
                    period = 14
                elif pay_term == 'monthly':
                    period = 30  # Approximate
                if pay_term not in ['One-time', 'daily'] and period:
                    days_since_hire = (today - hire_date).days
                    periods_passed = days_since_hire // period
                    candidate_due = hire_date + timedelta(days=(periods_passed + 1) * period)
                    if candidate_due < today:
                        next_due = hire_date + timedelta(days=(periods_passed + 2) * period)
                    else:
                        next_due = candidate_due
            except:
                pass
        record['next_due_date'] = next_due.isoformat() if next_due else None
        records.append(record)

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

        record_id  = data.get('id') or data.get('record_id')
        empid      = data.get('empid')
        name       = data.get('name')
        pay_term   = (data.get('pay_term')   or '').strip()
        salary     = data.get('salary')           # we'll convert later
        job_id     = (data.get('job_id')     or '').strip()
        pay_group  = (data.get('pay_group')  or '').strip()
        notes      = (data.get('notes')      or '').strip()
        active     = data.get('active')
        # Normalize active flag
        active = True if str(active).lower() in ['1', 'true', 'yes'] else False

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

        # If this record should be active, clear active flag for other rows of the same employee
        if active:
            cursor.execute('UPDATE pay_structure SET active = 0 WHERE empid = ?', (empid,))

        # If an ID is provided, update that specific record
        if record_id:
            cursor.execute('SELECT empid FROM pay_structure WHERE id = ?', (record_id,))
            found = cursor.fetchone()
            if found:
                cursor.execute("""
                    UPDATE pay_structure
                    SET name = ?, pay_term = ?, salary = ?, job_id = ?, pay_group = ?, active = ?, updated_at = CURRENT_TIMESTAMP, notes = ?
                    WHERE id = ?
                """, (name, pay_term, salary, job_id, pay_group, int(active), notes, record_id))
            else:
                record_id = None

        # If no specific record is being edited, always insert a new row (preserve history)
        if not record_id:
            cursor.execute("""
                INSERT INTO pay_structure 
                (empid, name, pay_term, salary, job_id, pay_group, active, updated_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """, (empid, name, pay_term, salary, job_id, pay_group, int(active), notes))

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

        return jsonify({"status": "success", "compensation": records}), 200

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
        conn.close()
        records = rows_to_list(cursor, rows)

        return jsonify({"status": "success", "personal": records}), 200

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

    # Check if there's an active unpaid pay structure for this employee
    pay_structure = conn.execute('''
        SELECT id, pay_term, pay_group, salary
        FROM pay_structure
        WHERE empid = ? AND active = 1 AND paid = 0
    ''', (empid,)).fetchone()

    if pay_structure is None:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'No active unpaid pay structure found for this employee'
        }), 400

    # Verify the pay_term matches (optional, but good check)
    if pay_structure['pay_term'] != pay_term:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': f'Pay term mismatch: expected {pay_structure["pay_term"]}, got {pay_term}'
        }), 400

    # Save payment into payments table
    payment_handling_code = data.get('payment_handling_code') or 'AUTO'
    payment_status = data.get('payment_status') or 'completed'
    payment_ref = data.get('payment_ref') or f"PAY-{int(datetime.now().timestamp())}"
    reconcile_date = data.get('reconcile_date')  # optional
    recon_status = data.get('recon_status') or 'pending'

    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (
            empid, name, hire_date, pay_group, pay_term, pay_amount,
            payment_date, payment_handling_code, payment_status,
            reconcile_date, recon_status, payment_ref
        ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
    ''', (
        empid, data.get('name'), data.get('hire_date'), data.get('pay_group'), pay_term, amount,
        payment_handling_code, payment_status, reconcile_date, recon_status, payment_ref
    ))
    conn.commit()

    payment_id = cursor.lastrowid
    cursor.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,))
    payment_row = cursor.fetchone()
    payment_record = dict(payment_row) if payment_row else None

    # Mark the pay structure as paid
    cursor.execute('UPDATE pay_structure SET paid = 1 WHERE id = ?', (pay_structure['id'],))
    conn.commit()

    conn.close()

    return jsonify({
        'status': 'success',
        'message': f'Payment of ₹{amount:,.2f} processed successfully for employee {empid}',
        'payment': payment_record
    })


# Optional: Add this if you want to see all payments later (for testing)
@app.route('/payments')
def list_payments():
    empid_filter = request.args.get('empid')

    conn = get_db_connection()
    cursor = conn.cursor()

    if empid_filter:
        cursor.execute('SELECT * FROM payments WHERE empid = ? ORDER BY payment_date DESC', (int(empid_filter),))
    else:
        cursor.execute('SELECT * FROM payments ORDER BY payment_date DESC LIMIT 500')

    rows = cursor.fetchall()
    conn.close()
    payments = [dict(row) for row in rows]

    return jsonify({'status': 'success', 'payments': payments})


if __name__ == '__main__':
    app.run(debug=True, port=5000)