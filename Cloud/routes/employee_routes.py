from flask import Blueprint, jsonify, request, session
from mysql.connector import Error
from db import db_cursor
from services.policy_engine import AuditService
from services.email_service import send_welcome_email
import json

employee_bp = Blueprint('employees', __name__, url_prefix='/api/employees')

@employee_bp.before_request
def check_role_access():
    role = session.get('user', {}).get('role')
    if role == 'Admin':
        return jsonify({'error': 'Unauthorized: Admin does not have access to Employee Registry'}), 403
    if request.method != 'GET' and role == 'Auditor':
        return jsonify({'error': 'Unauthorized: Auditors have read-only access'}), 403


# ── Helpers ────────────────────────────────────────────────────────────────────

def _next_employee_id(cur):
    """Generate the next EMP-000-XXX id based on the highest existing one."""
    cur.execute("SELECT employee_id FROM tblemployee WHERE employee_id LIKE 'EMP-%' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return "EMP-000-001"
    last = row["employee_id"]
    try:
        parts = last.split("-")
        num = int(parts[-1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"EMP-000-{num:03d}"


def _get_payheads(cur, employee_id):
    cur.execute(
        "SELECT id, pay_head, description, amount, mode, percentage_value FROM tblpayhead WHERE employee_id = %s ORDER BY id",
        (employee_id,)
    )
    rows = cur.fetchall()
    return [{
        "id": r["id"], 
        "pay_head": r["pay_head"], 
        "description": r["description"],
        "amount": float(r["amount"]), 
        "category": "Earning",
        "mode": r.get("mode", "Amount"),
        "percentage_value": float(r["percentage_value"]) if r.get("percentage_value") is not None else 0.0
    } for r in rows]


def _get_enrolled_fingers(cur, employee_id):
    cur.execute("SELECT finger_index FROM fingerprints WHERE employee_id = %s ORDER BY finger_index", (employee_id,))
    rows = cur.fetchall()
    return [int(r["finger_index"]) for r in rows]


def normalize_role(role_input):
    if not role_input:
        return 'Employee'
    r = str(role_input).strip()
    r_upper = r.upper()
    if r_upper in ['ADMIN', 'PRINCIPAL', 'ADMINISTRATOR']:
        return 'Admin'
    elif r_upper in ['HR', 'HR OFFICER', 'HUMAN RESOURCES']:
        return 'HR'
    elif r_upper in ['FINANCE', 'FINANCE OFFICER', 'PAYROLL OFFICER']:
        return 'Finance'
    elif r_upper in ['AUDITOR', 'AUDIT']:
        return 'Auditor'
    return 'Employee'


def _row_to_dict(row, pay_heads, enrolled_fingers=None):
    db_role = normalize_role(row.get("system_role"))
    
    return {
        "id":          row["employee_id"],
        "first_name":  row["first_name"],
        "last_name":   row["last_name"],
        "designation": row["designation"],
        "employee_type": row.get("employee_type", "TEACHING"),
        "salary_grade": row.get("salary_grade"),
        "step": row.get("step", 1),
        "employment_status": row.get("employment_status") or "Active",
        "system_role": db_role,

        "birthday":    str(row["birthday"]) if row.get("birthday") else "",
        "email":       row["email"],
        "contact":     row["contact"],
        "address":     row["address"],
        "pay_heads":   pay_heads,
        "enrolled_fingers": enrolled_fingers or []
    }


# ── GET NEXT ID ────────────────────────────────────────────────────────────────
@employee_bp.route('/next_id', methods=['GET'])
def get_next_id():
    try:
        with db_cursor() as (conn, cur):
            new_id = _next_employee_id(cur)
        return jsonify({"next_id": new_id})
    except Error as e:
        return jsonify({"error": str(e)}), 500


@employee_bp.route('/test_email', methods=['POST'])
def test_email_route():
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({"error": "Recipient email is required"}), 400

    result = send_welcome_email({
        'employee_id': 'EMP-TEST-999',
        'first_name': 'Test',
        'last_name': 'User',
        'email': email,
        'designation': 'Test Staff',
        'employment_status': 'Active'
    }, 'testuser', 'testpass123', async_send=False)

    return jsonify(result)



# ── LIST ───────────────────────────────────────────────────────────────────────
@employee_bp.route('/', methods=['GET'])
def list_employees():
    q = request.args.get('q', '').strip()
    try:
        with db_cursor() as (conn, cur):
            if q:
                like = f"%{q}%"
                cur.execute("""
                    SELECT e.employee_id, 
                           MAX(e.first_name) as first_name, 
                           MAX(e.last_name) as last_name, 
                           MAX(e.designation) as designation, 
                           MAX(e.employee_type) as employee_type, 
                           MAX(e.employment_status) as employment_status, 
                           MAX(u.role) as system_role
                    FROM tblemployee e
                    LEFT JOIN tblusers u ON e.employee_id = u.employee_id
                    WHERE e.first_name  LIKE %s
                       OR e.last_name   LIKE %s
                       OR e.employee_id LIKE %s
                       OR e.designation LIKE %s
                    GROUP BY e.employee_id
                    ORDER BY MIN(e.id)
                """, (like, like, like, like))
            else:
                cur.execute("""
                    SELECT e.employee_id, 
                           MAX(e.first_name) as first_name, 
                           MAX(e.last_name) as last_name, 
                           MAX(e.designation) as designation, 
                           MAX(e.employee_type) as employee_type, 
                           MAX(e.employment_status) as employment_status, 
                           MAX(u.role) as system_role
                    FROM tblemployee e
                    LEFT JOIN tblusers u ON e.employee_id = u.employee_id
                    GROUP BY e.employee_id
                    ORDER BY MIN(e.id)
                """)
            rows = cur.fetchall()

            # Query enrolled fingerprints mapping
            cur.execute("SELECT employee_id, finger_index FROM fingerprints")
            fp_rows = cur.fetchall()
            fp_map = {}
            for fp in fp_rows:
                emp_id = fp['employee_id']
                if emp_id not in fp_map:
                    fp_map[emp_id] = []
                fp_map[emp_id].append(int(fp['finger_index']))

        def _map_role(r):
            if r == 'Admin': return 'Principal'
            if r == 'HR': return 'HR Officer'
            if r == 'Finance': return 'Finance Officer'
            if r == 'Auditor': return 'Auditor'
            return 'Employee'

        return jsonify([{
            "id":          r["employee_id"],
            "first_name":  r["first_name"],
            "last_name":   r["last_name"],
            "designation": r["designation"],
            "employee_type": r.get("employee_type", "TEACHING"),
            "employment_status": r.get("employment_status") or "Active",
            "system_role": _map_role(r.get("system_role")),
            "enrolled_fingers": fp_map.get(r["employee_id"], [])
        } for r in rows])

    except Error as e:
        return jsonify({"error": str(e)}), 500


# ── GET ONE ────────────────────────────────────────────────────────────────────
@employee_bp.route('/<emp_id>', methods=['GET'])
def get_employee(emp_id):
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT e.*, u.role as system_role
                FROM tblemployee e
                LEFT JOIN tblusers u ON e.employee_id = u.employee_id
                WHERE e.employee_id = %s
                ORDER BY u.id DESC
            """, (emp_id,))
            rows = cur.fetchall()
            if not rows:
                return jsonify({"error": "Employee not found"}), 404
            row = rows[0]
            pay_heads = _get_payheads(cur, emp_id)
            enrolled_fingers = _get_enrolled_fingers(cur, emp_id)
        return jsonify(_row_to_dict(row, pay_heads, enrolled_fingers))
    except Error as e:
        return jsonify({"error": str(e)}), 500


# ── CREATE ─────────────────────────────────────────────────────────────────────
@employee_bp.route('/', methods=['POST'])
def create_employee():
    data = request.get_json(force=True)
    required = ['first_name', 'last_name', 'designation', 'birthday', 'email', 'contact', 'address']
    for field in required:
        if not str(data.get(field, '')).strip():
            return jsonify({"error": f"'{field}' is required"}), 400
    try:
        with db_cursor(commit=True) as (conn, cur):
            provided_id = data.get('employee_id', '').strip()
            if provided_id:
                new_id = provided_id
            else:
                new_id = _next_employee_id(cur)
                
            emp_type = data.get('employee_type', 'NON_TEACHING').strip()
            if emp_type.lower() == 'faculty':
                emp_type = 'TEACHING'
            elif emp_type.lower() == 'staff':
                emp_type = 'NON_TEACHING'

            sg = data.get('salary_grade')
            step = data.get('step', 1)
            sg_val = int(sg) if sg and str(sg).isdigit() else None
            step_val = int(step) if step and str(step).isdigit() else 1
            emp_status = data.get('employment_status', 'Active').strip()
            if emp_status not in ['Active', 'Inactive']:
                emp_status = 'Active'

            cur.execute("""
                INSERT INTO tblemployee
                    (employee_id, first_name, last_name, designation, employee_type, salary_grade, step, employment_status, birthday, email, contact, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                new_id,
                data['first_name'].strip(),
                data['last_name'].strip(),
                data['designation'].strip(),
                emp_type,
                sg_val,
                step_val,
                emp_status,
                data['birthday'] or None,
                data['email'].strip(),
                data['contact'].strip(),
                data['address'].strip(),
            ))


            # Initialize leave balances (4800 mins = 10 days default)
            cur.execute(
                "INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes) VALUES (%s, 4800, 4800) ON DUPLICATE KEY UPDATE employee_id=employee_id",
                (new_id,)
            )

            for ph in data.get('pay_heads', []):
                if str(ph.get('pay_head', '')).strip():
                    cur.execute(
                        "INSERT INTO tblpayhead (employee_id, pay_head, description, amount, category, mode, percentage_value) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (new_id, ph['pay_head'].strip(), ph.get('description', '').strip(), float(ph.get('amount', 0)), ph.get('category', 'Earning'), ph.get('mode', 'Amount'), float(ph.get('percentage_value', 0)))
                    )
            
            # --- CREATE USER LOGIN ---
            # Username/Password = last_name (lowercase, stripped)
            username = data['last_name'].strip().lower()
            password = username
            fullname = f"{data['first_name'].strip()} {data['last_name'].strip()}"
            
            # Check for username collision (tblusers.username is UNIQUE)
            cur.execute("SELECT id FROM tblusers WHERE username = %s", (username,))
            if cur.fetchone():
                # If collision, append employee ID suffix (e.g., smith001)
                suffix = new_id.split('-')[-1] if '-' in new_id else new_id
                username = f"{username}{suffix}"
                password = username # Keep password same as username for initial setup
            
            db_role = normalize_role(data.get('system_role'))
            
            cur.execute(
                "INSERT INTO tblusers (username, password, name, role, employee_id) VALUES (%s, %s, %s, %s, %s)",
                (username, password, fullname, db_role, new_id)
            )
            
            AuditService.log_action(cur, 'EMPLOYEE_CREATED', employee_id=new_id, user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblemployee', target_id=new_id, new_value=json.dumps(data))
            
            # Send welcome & account activation email via Brevo
            send_welcome_email({
                'employee_id': new_id,
                'first_name': data['first_name'].strip(),
                'last_name': data['last_name'].strip(),
                'email': data['email'].strip(),
                'designation': data['designation'].strip(),
                'employment_status': emp_status
            }, username, password)
            cur.execute("""
                SELECT e.*, u.role as system_role
                FROM tblemployee e
                LEFT JOIN tblusers u ON e.employee_id = u.employee_id
                WHERE e.employee_id = %s
            """, (new_id,))
            row = cur.fetchone()
            ph_saved = _get_payheads(cur, new_id)
            enrolled_fingers = _get_enrolled_fingers(cur, new_id)
        return jsonify(_row_to_dict(row, ph_saved, enrolled_fingers)), 201
    except Error as e:
        return jsonify({"error": str(e)}), 500


# ── UPDATE ─────────────────────────────────────────────────────────────────────
@employee_bp.route('/<emp_id>', methods=['PUT'])
def update_employee(emp_id):
    data = request.get_json(force=True)
    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT * FROM tblemployee WHERE employee_id = %s", (emp_id,))
            old_row = cur.fetchone()
            if not old_row:
                return jsonify({"error": "Employee not found"}), 404
            emp_type = data.get('employee_type', 'NON_TEACHING').strip()
            if emp_type.lower() == 'faculty':
                emp_type = 'TEACHING'
            elif emp_type.lower() == 'staff':
                emp_type = 'NON_TEACHING'

            sg = data.get('salary_grade')
            step = data.get('step', 1)
            sg_val = int(sg) if sg and str(sg).isdigit() else None
            step_val = int(step) if step and str(step).isdigit() else 1
            emp_status = data.get('employment_status', old_row.get('employment_status') or 'Active').strip()
            if emp_status not in ['Active', 'Inactive']:
                emp_status = 'Active'

            cur.execute("""
                UPDATE tblemployee
                SET first_name=%s, last_name=%s, designation=%s, employee_type=%s,
                    salary_grade=%s, step=%s, employment_status=%s, birthday=%s, email=%s, contact=%s, address=%s
                WHERE employee_id=%s
            """, (
                data.get('first_name','').strip(),
                data.get('last_name','').strip(),
                data.get('designation','').strip(),
                emp_type,
                sg_val,
                step_val,
                emp_status,
                data.get('birthday') or None,
                data.get('email','').strip(),
                data.get('contact','').strip(),
                data.get('address','').strip(),
                emp_id,
            ))

            
            db_role = normalize_role(data.get('system_role'))
            cur.execute("UPDATE tblusers SET role=%s WHERE employee_id=%s", (db_role, emp_id))
            
            AuditService.log_action(cur, 'EMPLOYEE_UPDATED', employee_id=emp_id, user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblemployee', target_id=emp_id, old_value=json.dumps(old_row, default=str), new_value=json.dumps(data))
            
            cur.execute("DELETE FROM tblpayhead WHERE employee_id=%s", (emp_id,))
            for ph in data.get('pay_heads', []):
                if str(ph.get('pay_head', '')).strip():
                    cur.execute(
                        "INSERT INTO tblpayhead (employee_id, pay_head, description, amount, category, mode, percentage_value) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (emp_id, ph['pay_head'].strip(), ph.get('description', '').strip(), float(ph.get('amount', 0)), ph.get('category', 'Earning'), ph.get('mode', 'Amount'), float(ph.get('percentage_value', 0)))
                    )
            cur.execute("""
                SELECT e.*, u.role as system_role
                FROM tblemployee e
                LEFT JOIN tblusers u ON e.employee_id = u.employee_id
                WHERE e.employee_id=%s
            """, (emp_id,))
            row = cur.fetchone()
            ph_saved = _get_payheads(cur, emp_id)
            enrolled_fingers = _get_enrolled_fingers(cur, emp_id)
        return jsonify(_row_to_dict(row, ph_saved, enrolled_fingers))
    except Error as e:
        return jsonify({"error": str(e)}), 500


# ── DELETE ─────────────────────────────────────────────────────────────────────
@employee_bp.route('/<emp_id>', methods=['DELETE'])
def delete_employee(emp_id):
    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT * FROM tblemployee WHERE employee_id=%s", (emp_id,))
            old_row = cur.fetchone()
            if not old_row:
                return jsonify({"error": "Employee not found"}), 404
            
            # Cascade delete to all foreign tables
            cur.execute("DELETE FROM tblpayhead WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tblpayroll_details WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM fingerprints WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tblbiometric_logs WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tbltime_logs WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tblleaves WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tblenrollment_tasks WHERE employee_id=%s", (emp_id,))
            cur.execute("DELETE FROM tblusers WHERE employee_id=%s", (emp_id,))
            
            cur.execute("DELETE FROM tblemployee WHERE employee_id=%s", (emp_id,))
            
            AuditService.log_action(cur, 'EMPLOYEE_DELETED', employee_id=emp_id, user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblemployee', target_id=emp_id, old_value=json.dumps(old_row, default=str))
        return jsonify({"message": f"Employee {emp_id} deleted successfully."})
    except Error as e:
        return jsonify({"error": str(e)}), 500