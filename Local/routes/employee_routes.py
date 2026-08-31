from flask import Blueprint, jsonify, request
from mysql.connector import Error
from db import db_cursor

employee_bp = Blueprint('employees', __name__, url_prefix='/api/employees')


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


def _row_to_dict(row, pay_heads, enrolled_fingers=None):
    db_role = row.get("system_role", "Employee")
    ui_role = "Employee"
    if db_role == "Admin": ui_role = "Principal"
    elif db_role == "HR": ui_role = "HR Officer"
    elif db_role == "Finance": ui_role = "Finance Officer"
    
    return {
        "id":          row["employee_id"],
        "first_name":  row["first_name"],
        "last_name":   row["last_name"],
        "designation": row["designation"],
        "employee_type": row.get("employee_type", "TEACHING"),
        "salary_grade": row.get("salary_grade"),
        "step": row.get("step", 1),
        "system_role": ui_role,

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
            return 'Employee'

        return jsonify([{
            "id":          r["employee_id"],
            "first_name":  r["first_name"],
            "last_name":   r["last_name"],
            "designation": r["designation"],
            "employee_type": r.get("employee_type", "TEACHING"),
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

            cur.execute("""
                INSERT INTO tblemployee
                    (employee_id, first_name, last_name, designation, employee_type, salary_grade, step, birthday, email, contact, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                new_id,
                data['first_name'].strip(),
                data['last_name'].strip(),
                data['designation'].strip(),
                emp_type,
                sg_val,
                step_val,
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
            
            system_role_input = data.get('system_role', 'Employee').strip()
            db_role = 'Employee'
            if system_role_input == 'Principal': db_role = 'Admin'
            elif system_role_input == 'HR Officer': db_role = 'HR'
            elif system_role_input == 'Finance Officer': db_role = 'Finance'
            
            cur.execute(
                "INSERT INTO tblusers (username, password, name, role, employee_id) VALUES (%s, %s, %s, %s, %s)",
                (username, password, fullname, db_role, new_id)
            )
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
            cur.execute("SELECT id FROM tblemployee WHERE employee_id = %s", (emp_id,))
            if not cur.fetchone():
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

            cur.execute("""
                UPDATE tblemployee
                SET first_name=%s, last_name=%s, designation=%s, employee_type=%s,
                    salary_grade=%s, step=%s, birthday=%s, email=%s, contact=%s, address=%s
                WHERE employee_id=%s
            """, (
                data.get('first_name','').strip(),
                data.get('last_name','').strip(),
                data.get('designation','').strip(),
                emp_type,
                sg_val,
                step_val,
                data.get('birthday') or None,
                data.get('email','').strip(),
                data.get('contact','').strip(),
                data.get('address','').strip(),
                emp_id,
            ))

            
            system_role_input = data.get('system_role', 'Employee').strip()
            db_role = 'Employee'
            if system_role_input == 'Principal': db_role = 'Admin'
            elif system_role_input == 'HR Officer': db_role = 'HR'
            elif system_role_input == 'Finance Officer': db_role = 'Finance'
            
            cur.execute("UPDATE tblusers SET role=%s WHERE employee_id=%s", (db_role, emp_id))
            
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
            cur.execute("SELECT id FROM tblemployee WHERE employee_id=%s", (emp_id,))
            if not cur.fetchone():
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
        return jsonify({"message": f"Employee {emp_id} deleted successfully."})
    except Error as e:
        return jsonify({"error": str(e)}), 500