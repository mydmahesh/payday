import base64
import io
import requests
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def get_mermaid_image(mermaid_code: str) -> io.BytesIO | None:
    """Fetch rendered PNG of mermaid diagram from mermaid.ink API."""
    try:
        encoded = base64.b64encode(mermaid_code.encode("utf-8")).decode("ascii")
        url = f"https://mermaid.ink/img/{encoded}?bgColor=FFFFFF"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return io.BytesIO(resp.content)
    except Exception as e:
        print(f"Warning: could not render diagram online: {e}")
    return None

def set_cell_background(cell, fill_hex: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)

def main():
    doc = Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # Document Title
    title = doc.add_paragraph()
    title_run = title.add_run("PayDay — System Architecture & Workflow Document")
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(22, 59, 91)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph("Comprehensive Architectural Flows, Sequences, Lifecycle & Data Models")
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.runs[0].font.size = Pt(12)
    subtitle.runs[0].font.italic = True
    doc.add_paragraph()

    # Diagrams definitions
    diagram1 = """flowchart TD
    User([User / HR Admin]) -->|Access Website| AuthGate{Logged In?}
    AuthGate -- No --> LoginView[Login / Register Page: /login, /register]
    LoginView -->|Authenticate POST| DB_Users[(pdusers Table)]
    AuthGate -- Yes --> Dashboard[Dashboard / Home Page: /]

    Dashboard --> NavEmp[1. Employee Details: /employee_details]
    Dashboard --> NavPersonal[2. Personal Details: /personal_details]
    Dashboard --> NavBank[3. Bank Details: /bank-details]
    Dashboard --> NavPayStructure[4. Pay Structure: /pay_structure]
    Dashboard --> NavAttendance[5. Attendance: /attendance]
    Dashboard --> NavPayroll[6. Pay / Payroll: /pay]
    Dashboard --> NavReports[7. Reports: /reports]

    NavPayStructure -.-> NavSetup[Pay Structure Setup: /pay_structure_setup]
    NavSetup -.-> NavPayroll

    subgraph Database [SQLite: Paydaytest.db]
        DB_Users
        DB_Emp[(pd_employees)]
        DB_Personal[(employee_personal_details)]
        DB_Bank[(employee_bank_details)]
        DB_PS[(pay_structure)]
        DB_Settings[(pay_term_settings)]
        DB_Att[(attendance_daily)]
        DB_Cal[(work_calendar)]
        DB_Runs[(payroll_runs)]
        DB_Lines[(payroll_lines)]
        DB_Pay[(payments)]
    end

    NavEmp <--> DB_Emp
    NavPersonal <--> DB_Personal
    NavBank <--> DB_Bank
    NavPayStructure <--> DB_PS
    NavSetup <--> DB_Settings
    NavAttendance <--> DB_Att
    NavAttendance <--> DB_Cal
    NavPayroll <--> DB_Runs
    NavPayroll <--> DB_Lines
    NavPayroll <--> DB_Pay
"""

    diagram2 = """sequenceDiagram
    autonumber
    actor User as HR / Payroll Admin
    participant App as Flask Application (app.py)
    participant Session as Flask Session
    participant DB as SQLite DB

    User->>App: Request any protected route
    App->>Session: Check user_id in session (@app.before_request)
    alt Not Logged In
        App-->>User: Redirect to /login
        User->>App: POST /login (email, password)
        App->>DB: Query pdusers WHERE email = ?
        App->>App: Verify hash via werkzeug.check_password_hash
        alt Success
            App->>Session: Store user_id, user_name, user_email
            App-->>User: Redirect to / (Dashboard)
        else Invalid Credentials
            App-->>User: Show login error toast
        end
    else Logged In
        App-->>User: Render requested page
    end
"""

    diagram3 = """flowchart LR
    Step1[1. Add Employee: Name, Email, Hire Date, Grade] --> DB_Emp[(pd_employees)]
    Step1 --> Step2[2. Add Personal Details: DOB, Phone, Address, Pan, Aadhar]
    Step2 --> DB_Personal[(employee_personal_details)]
    
    Step1 --> Step3[3. Add Bank Details: Bank Name, Acc No, IFSC, Branch]
    Step3 --> DB_Bank[(employee_bank_details)]
    
    Step1 --> Step4[4. Configure Pay Structure: Monthly/Weekly/Daily Salary, Pay Group]
    Step4 --> DB_PS[(pay_structure)]

    Step1 --> Step5[5. Mark Attendance & Calendar: Present/Absent/Leave & IN Holidays]
    Step5 --> DB_Att[(attendance_daily & work_calendar)]
"""

    diagram4 = """flowchart TD
    Start([Admin Opens /pay]) --> InputCutoff[Admin picks Cutoff Date]
    InputCutoff --> ClickGen[Click 'Generate or refresh draft']
    
    ClickGen --> Bounds[Determine Period Bounds: pay_term_period_bounds]
    Bounds --> FetchRules{Check Settings: pay_term_settings}
    FetchRules -->|Weekly/Bi-weekly| WeekBounds[Calculate Week Start to Weekday Cutoff]
    FetchRules -->|Monthly: Last Working Day| LWD[Find last scheduled workday in month]
    FetchRules -->|Monthly: Custom Day| CustomDay[Clamp custom day to month length]

    Bounds --> FetchActive[Query active employees with active pay structure]
    FetchActive --> CalcLine[For each employee in payroll_lines]

    subgraph Calculation [Per-Employee Line Calculation]
        CalcLine --> CheckCal[Check Work Calendar & IN Country Holidays]
        CheckCal --> CountSched[Count Scheduled Workdays in Period]
        CountSched --> CountAtt[Count 'present' days from attendance_daily]
        CountAtt --> ProRate[Prorated Amount: Salary/Scheduled Days * Present Days]
        ProRate --> CheckExceptions{Any Exceptions?}
        CheckExceptions -- Yes --> MarkEx[line_status = 'exception']
        CheckExceptions -- No --> MarkReady[line_status = 'ready']
    end

    CalcLine --> SaveDraft[Upsert payroll_runs draft\nInsert payroll_lines]
    SaveDraft --> DisplaySummary[Display Summary: Total, Eligible, Exceptions]

    DisplaySummary --> ApproveAction{Admin clicks 'Approve run'?}
    ApproveAction -- Yes --> MarkApproved[Run status -> 'approved']
    MarkApproved --> RecordPayBtn[Admin clicks 'Record pending payments']
    RecordPayBtn --> GenPayments[Create rows in payments table]
    GenPayments --> FinalRunStatus[Run status -> 'paid' or 'partially_paid']
"""

    diagram5 = """erDiagram
    pdusers ||--o{ pd_employees : manages
    pd_employees ||--o| employee_personal_details : has
    pd_employees ||--o| employee_bank_details : has
    pd_employees ||--o{ pay_structure : configured_with
    pd_employees ||--o{ attendance_daily : logs
    payroll_runs ||--o{ payroll_lines : contains
    payroll_lines ||--o| payments : generates
"""

    sections = [
        ("1. High-Level System Architecture",
         "The PayDay system provides a unified interface for HR and payroll personnel to record employee profiles, manage recurring compensation terms, track attendance, and run payroll calculations.",
         diagram1),
        ("2. User Journey & Authentication Flow",
         "Session-based security protects internal operations. Requests are intercepted by Flask's @app.before_request handler to ensure authenticated access.",
         diagram2),
        ("3. Employee Lifecycle & Setup Flow",
         "Employees must transition through distinct setup stages before becoming eligible for payroll calculations. Missing steps surface as actionable exceptions in payroll runs.",
         diagram3),
        ("4. End-to-End Payroll Engine Flow (/pay & payroll.py)",
         "The core calculation engine dynamically evaluates pay terms, applies India statutory holidays and calendar overrides, pro-rates attendance, and generates payment line items.",
         diagram4),
        ("5. Database Entity Relationship Diagram",
         "The relational schema maintains strict separation between employee identities, recurring structures, daily attendance records, and immutable payment records.",
         diagram5),
    ]

    for title_text, desc_text, mermaid_code in sections:
        h = doc.add_heading(title_text, level=1)
        h.runs[0].font.color.rgb = RGBColor(22, 59, 91)
        doc.add_paragraph(desc_text)

        print(f"Rendering: {title_text}...")
        img_data = get_mermaid_image(mermaid_code)
        if img_data:
            doc.add_picture(img_data, width=Inches(6.2))
            last_p = doc.paragraphs[-1]
            last_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        else:
            p = doc.add_paragraph("[Diagram rendering offline - see text representation]")
            p.runs[0].font.italic = True
        doc.add_paragraph()

    # Section 6: Module Table
    h = doc.add_heading("6. Module & Route Mapping", level=1)
    h.runs[0].font.color.rgb = RGBColor(22, 59, 91)
    
    table_data = [
        ("Module", "Front-End", "Backend Routes", "Database Tables", "Description"),
        ("Authentication", "login.html, register.html", "/login, /register, /logout", "pdusers", "User registration, password hashing (PBKDF2/Werkzeug), and session auth."),
        ("Dashboard", "home.html", "/", "—", "Main navigation cards across all functional modules."),
        ("Employee Details", "employee_details.html, edit_employee_details.html", "/employees, /employee/<id>, /search, /add_employee, /update_employee", "pd_employees", "Employee CRUD (name, email, hire date, grade, active status)."),
        ("Personal Details", "personal_details.html, edit_personal_details.html", "/personal_details, /search_personal_details, /save_personal_details", "employee_personal_details", "Demographics, contact info, DOB, PAN, and Aadhaar numbers."),
        ("Bank Details", "bank_details.html, edit_bank_details.html", "/bank-details, /search_bank_details, /save_bank_details", "employee_bank_details", "Account number, IFSC code, branch, and beneficiary holder name."),
        ("Pay Structure", "pay_structure.html, edit_pay_structure.html, pay_structure_add.html", "/pay_structure, /pay_structure_list, /save_pay_structure", "pay_structure", "Pay frequency (Monthly/Weekly/Bi-weekly/Daily), base salary, and pay group."),
        ("Pay Structure Setup", "pay_structure_setup.html", "/pay_structure_setup, /payroll/settings", "pay_term_settings", "Cutoff rules: weekday cutoff and Monthly Last Working Day vs Custom Day (1–31)."),
        ("Compensation", "compensation_details.html", "/compensation-details, /save_compensation, /search_compensation", "employee_compensation", "Itemized components: Basic, Bouquet of Benefits (HRA/LTA/Food), bonuses, PF."),
        ("Attendance & Calendar", "attendance.html", "/attendance, /payroll/attendance, /payroll/calendar", "attendance_daily, work_calendar", "Daily attendance marking (Present/Absent/Leave) and statutory holiday overrides."),
        ("Payroll Engine", "payroll.html", "/pay, /payroll/runs, /payroll/runs/<id>/approve, /payroll/runs/<id>/record-payments", "payroll_runs, payroll_lines, payments", "Draft generation, pro-rated attendance calculation, approvals, and payment tracking."),
        ("Reports", "reports.html", "/reports", "—", "Summary reporting portal for payroll, bank, and workforce audits.")
    ]

    table = doc.add_table(rows=len(table_data), cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for row_idx, row in enumerate(table_data):
        for col_idx, text in enumerate(row):
            cell = table.cell(row_idx, col_idx)
            cell.text = text
            if row_idx == 0:
                set_cell_background(cell, "163B5B")
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.bold = True
                        r.font.color.rgb = RGBColor(255, 255, 255)
            elif row_idx % 2 == 1:
                set_cell_background(cell, "F3F5F7")

    output_filename = "PayDay_Architecture_and_Flow.docx"
    doc.save(output_filename)
    print(f"Document successfully created: {output_filename}")

if __name__ == "__main__":
    main()