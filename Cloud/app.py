from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from routes import employee_bp, dtr_bp, payroll_bp, fingerprint_bp, attendance_bp, registry_bp, dashboard_bp, salary_grade_bp, audit_bp, approval_bp, notification_bp
from werkzeug.security import generate_password_hash, check_password_hash
from services.policy_engine import AuditService
from services.notification_service import NotificationService
from services.email_service import send_login_notification_email
import os

app = Flask(__name__)
app.secret_key = 'paycore-secret-2026'
app.url_map.strict_slashes = False

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

# Register blueprints
app.register_blueprint(employee_bp)
app.register_blueprint(dtr_bp)
app.register_blueprint(payroll_bp)
app.register_blueprint(fingerprint_bp)
app.register_blueprint(attendance_bp)
app.register_blueprint(registry_bp)
app.register_blueprint(salary_grade_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(audit_bp)
app.register_blueprint(approval_bp)
app.register_blueprint(notification_bp)


# Auto-create DB tables on startup
with app.app_context():
    try:
        from init_db import init
        init()
    except Exception as e:
        print(f"⚠️  DB init warning: {e}")

# DB Users are stored in tblusers.


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    # Redirect to proper page if logged in, otherwise login
    if 'user' in session:
        if session['user'].get('role') == 'Employee':
            return redirect(url_for('dtr'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        if session['user'].get('role') == 'Employee':
            return redirect(url_for('dtr'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # Check against tblusers
        from db import db_cursor
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                SELECT u.id, u.employee_id, u.username, u.password AS stored_password, u.name AS fallback_name, u.role, e.first_name, e.last_name, e.email AS emp_email
                FROM tblusers u
                LEFT JOIN tblemployee e ON u.employee_id = e.employee_id
                WHERE LOWER(u.username)=LOWER(%s) 
                   OR (LOWER(%s) IN ('principal', 'admin') AND LOWER(u.username) IN ('principal', 'admin'))
                   OR (LOWER(%s) IN ('accounting', 'accounting1', 'finance', 'finance1') AND LOWER(u.username) IN ('accounting', 'accounting1', 'finance', 'finance1'))
                   OR (LOWER(%s) IN ('hr', 'hr1') AND LOWER(u.username) IN ('hr', 'hr1'))
                   OR (e.email IS NOT NULL AND LOWER(e.email)=LOWER(%s))
                ORDER BY u.id DESC
                LIMIT 1
            """, (email, email, email, email, email))
            user_row = cur.fetchone()

            emp = None
            if user_row:
                stored = user_row.get('stored_password') or ''
                is_valid = False
                if stored.startswith(('scrypt:', 'pbkdf2:', 'argon2:')):
                    is_valid = check_password_hash(stored, password)
                else:
                    # Legacy plaintext fallback
                    is_valid = (stored == password)
                    if is_valid:
                        # Auto-upgrade to secure scrypt hash
                        new_hash = generate_password_hash(password)
                        cur.execute("UPDATE tblusers SET password=%s WHERE id=%s", (new_hash, user_row['id']))

                if is_valid:
                    emp = user_row

            if emp:
                # Prioritize official HR registry name if mapped, else fallback
                display_name = emp['fallback_name']
                if emp['first_name'] and emp['last_name']:
                    display_name = f"{emp['first_name']} {emp['last_name']}"

                r_raw = str(emp['role'] or '').strip().upper()
                if r_raw in ['PRINCIPAL', 'SCHOOL HEAD', 'SUPERINTENDENT', 'ADMIN', 'ADMINISTRATOR', 'SYSTEM ADMIN', 'IT']:
                    user_role = 'Principal'
                elif r_raw in ['HR', 'HR OFFICER', 'HUMAN RESOURCES']:
                    user_role = 'HR'
                elif r_raw in ['ACCOUNTING', 'ACCOUNTANT', 'FINANCE', 'FINANCE OFFICER', 'PAYROLL OFFICER', 'CASHIER', 'BOOKKEEPER']:
                    user_role = 'Accounting'
                else:
                    user_role = 'Employee'

                session['user'] = {
                    'id': emp.get('id'),
                    'email': emp['username'],
                    'name': display_name,
                    'role': user_role,
                    'employee_id': emp['employee_id']
                }
                session['just_logged_in'] = True
                
                AuditService.log_action(cur, 'LOGIN_SUCCESS', user_name=display_name, ip_address=request.remote_addr)

                # Send login notification email via Brevo to all roles
                target_email = emp.get('emp_email') or (emp['username'] if '@' in str(emp['username']) else None)
                if target_email:
                    send_login_notification_email({
                        'email': target_email,
                        'name': display_name,
                        'role': user_role,
                        'username': emp['username']
                    }, request.remote_addr)

                if user_role == 'Employee':
                    return redirect(url_for('dtr'))
                return redirect(url_for('dashboard'))
                
            AuditService.log_action(cur, 'LOGIN_FAILED', user_name=email, ip_address=request.remote_addr)

        flash('Invalid username or password.', 'error')

    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    # index.html is the shell (sidebar + topbar + content div)
    # Pass the session user so Jinja can render the name/initials
    return render_template('index.html', user=session['user'])


# Serve page fragments loaded dynamically via jQuery $.load()
@app.route('/pages/<path:filename>')
@login_required
def pages(filename):
    from flask import jsonify
    role = session.get('user', {}).get('role')
    # Principal and Admin do not have operational access to Employee Registry, Payroll Processing/Releasing, Salary Grades, or Statutory Registry
    if role in ['Principal', 'Admin'] and filename in ['employee.html', 'payroll.html', 'salary_grades.html', 'registry.html', 'payroll_releasing.html']:
        return jsonify({'error': 'Unauthorized page access: Principal/Admin does not have access to Employee Registry, Payroll, Salary Grades, or Statutory Registry'}), 403
    if role in ['HR', 'HR Officer'] and filename in ['payroll.html', 'payroll_releasing.html', 'salary_grades.html', 'registry.html', 'payroll_report.html', 'payroll_audit.html', 'audit_trail.html']:
        return jsonify({'error': 'Unauthorized page access: HR does not have access to Statutory Registry, Salary Grades, Payroll Processing/Releasing, Payroll Reports, or Audit Trail'}), 403
    if role in ['Accounting', 'Finance', 'Finance Officer'] and filename in ['employee.html', 'audit_trail.html']:
        return jsonify({'error': 'Unauthorized page access: Accounting does not have access to Employee Registry or Audit Trail'}), 403
    if role == 'Employee' and filename not in ['dtr.html', 'mypayslip.html', 'leaves.html', 'holidays.html', 'dtr_content.html']:
        return jsonify({'error': 'Unauthorized page access'}), 403
    pages_dir = os.path.join(app.root_path, 'pages')
    return send_from_directory(pages_dir, filename)


@app.route('/employees')
@login_required
def employees():
    if session['user'].get('role') not in ['HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/employee.html', title='Employees')


@app.route('/payroll')
@login_required
def payroll():
    if session['user'].get('role') not in ['Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll.html', title='Payroll Processing')


@app.route('/payroll_releasing')
@login_required
def payroll_releasing():
    if session['user'].get('role') not in ['Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll_releasing.html', title='Payroll Releasing')


@app.route('/approvals')
@app.route('/payroll_approvals')
@login_required
def approvals():
    if session['user'].get('role') not in ['Admin', 'Principal', 'HR', 'HR Officer', 'Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    title = 'Payroll Approval' if session['user'].get('role') in ['Accounting', 'Finance', 'Finance Officer'] else 'Approvals'
    return render_template('index.html', user=session['user'], initial_page='/pages/approvals.html', title=title)


@app.route('/holidays')
@login_required
def holidays():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Accounting', 'Finance', 'Finance Officer', 'HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/holidays.html', title='Holiday Calendar')


@app.route('/leaves')
@login_required
def leaves():
    return render_template('index.html', user=session['user'], initial_page='/pages/leaves.html', title='Leave Management')


@app.route('/salary_grades')
@login_required
def salary_grades():
    if session['user'].get('role') not in ['Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/salary_grades.html', title='Salary Grade Management')


@app.route('/dtr')
@login_required
def dtr():
    return render_template('index.html', user=session['user'], initial_page='/pages/dtr.html', title='DTR')


@app.route('/logs')
@app.route('/biometric_logs')
@login_required
def logs():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Accounting', 'Finance', 'Finance Officer', 'HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/logs.html', title='Biometric Logs')


@app.route('/mypayslip')
@login_required
def mypayslip():
    return render_template('index.html', user=session['user'], initial_page='/pages/mypayslip.html', title='My Payslip')


@app.route('/payroll_report')
@login_required
def payroll_report():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll_report.html', title='Payroll Report')


@app.route('/registry')
@login_required
def registry():
    if session['user'].get('role') not in ['Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/registry.html', title='Global Registry')


@app.route('/audit_trail')
@login_required
def audit_trail():
    if session['user'].get('role') not in ['Admin', 'Principal']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/audit_trail.html', title='Audit Trail')


@app.route('/payroll_audit')
@login_required
def payroll_audit():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Accounting', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll_audit.html', title='Payroll Audit')


@app.route('/api/auth/me')
@login_required
def auth_me():
    from flask import jsonify
    return jsonify(session.get('user', {}))


@app.route('/api/auth/change_password', methods=['POST'])
@login_required
def change_password():
    from flask import jsonify
    data = request.get_json(silent=True) or request.form
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()

    if not current_password or not new_password:
        return jsonify({'error': 'Current password and new password are required.'}), 400

    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters long.'}), 400

    if new_password != confirm_password:
        return jsonify({'error': 'New password and confirmation password do not match.'}), 400

    user_session = session.get('user', {})
    user_id = user_session.get('id')
    username = user_session.get('email') or user_session.get('username')
    emp_id = user_session.get('employee_id')

    from db import db_cursor
    from werkzeug.security import check_password_hash, generate_password_hash

    with db_cursor(commit=True) as (conn, cur):
        user_row = None
        if user_id:
            cur.execute("SELECT id, username, password FROM tblusers WHERE id = %s", (user_id,))
            user_row = cur.fetchone()
        if not user_row and username:
            cur.execute("SELECT id, username, password FROM tblusers WHERE LOWER(username) = LOWER(%s) ORDER BY id DESC LIMIT 1", (username,))
            user_row = cur.fetchone()
        if not user_row and emp_id:
            cur.execute("SELECT id, username, password FROM tblusers WHERE employee_id = %s ORDER BY id DESC LIMIT 1", (emp_id,))
            user_row = cur.fetchone()

        if not user_row:
            return jsonify({'error': 'User account not found.'}), 404

        stored = user_row.get('password') or ''
        is_valid = False
        if stored.startswith(('scrypt:', 'pbkdf2:', 'argon2:')):
            is_valid = check_password_hash(stored, current_password)
        else:
            is_valid = (stored == current_password)

        if not is_valid:
            return jsonify({'error': 'Incorrect current password.'}), 400

        new_hash = generate_password_hash(new_password)
        cur.execute("UPDATE tblusers SET password = %s WHERE id = %s", (new_hash, user_row['id']))

        AuditService.log_action(
            cur, 'PASSWORD_CHANGED',
            employee_id=emp_id,
            user_name=user_session.get('name', username),
            target_table='tblusers',
            target_id=str(user_row['id']),
            ip_address=request.remote_addr
        )

    return jsonify({'success': True, 'message': 'Password has been updated successfully.'})

@app.route('/logout')
def logout():
    if 'user' in session:
        from db import db_cursor
        with db_cursor(commit=True) as (conn, cur):
            AuditService.log_action(cur, 'LOGOUT', user_name=session['user'].get('name', 'Unknown'), ip_address=request.remote_addr)
    session.clear()
    return redirect(url_for('login'))

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

if __name__ == '__main__':
    app.run(debug=True)