from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from routes import employee_bp, dtr_bp, payroll_bp, fingerprint_bp, attendance_bp, registry_bp, dashboard_bp, salary_grade_bp
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
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT u.employee_id, u.username, u.name AS fallback_name, u.role, e.first_name, e.last_name
                FROM tblusers u
                LEFT JOIN tblemployee e ON u.employee_id = e.employee_id
                WHERE u.username=%s AND u.password=%s
            """, (email, password))
            emp = cur.fetchone()
            if emp:
                # Prioritize official HR registry name if mapped, else fallback
                display_name = emp['fallback_name']
                if emp['first_name'] and emp['last_name']:
                    display_name = f"{emp['first_name']} {emp['last_name']}"

                session['user'] = {
                    'email': emp['username'],
                    'name': display_name,
                    'role': emp['role'],
                    'employee_id': emp['employee_id']
                }
                if emp['role'] == 'Employee':
                    return redirect(url_for('dtr'))
                return redirect(url_for('dashboard'))
                
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
    pages_dir = os.path.join(app.root_path, 'pages')
    return send_from_directory(pages_dir, filename)


@app.route('/employees')
@login_required
def employees():
    if session['user'].get('role') not in ['Admin', 'Principal', 'HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/employee.html', title='Employees')


@app.route('/payroll')
@login_required
def payroll():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll.html', title='Payroll Processing')

@app.route('/payroll_approvals')
@login_required
def payroll_approvals():
    if session['user'].get('role') not in ['Admin', 'Principal']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll_approval.html', title='Payroll Approvals')


@app.route('/holidays')
@login_required
def holidays():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Finance', 'Finance Officer', 'HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/holidays.html', title='Holiday Calendar')


@app.route('/leaves')
@login_required
def leaves():
    return render_template('index.html', user=session['user'], initial_page='/pages/leaves.html', title='Leave Management')


@app.route('/salary_grades')
@login_required
def salary_grades():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Finance', 'Finance Officer', 'HR', 'HR Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/salary_grades.html', title='Salary Grade Management')



@app.route('/dtr')
@login_required
def dtr():
    return render_template('index.html', user=session['user'], initial_page='/pages/dtr.html', title='DTR')


@app.route('/mypayslip')
@login_required
def mypayslip():
    return render_template('index.html', user=session['user'], initial_page='/pages/mypayslip.html', title='My Payslip')


@app.route('/payroll_report')
@login_required
def payroll_report():
    return render_template('index.html', user=session['user'], initial_page='/pages/payroll_report.html', title='Payroll Report')


@app.route('/registry')
@login_required
def registry():
    if session['user'].get('role') not in ['Admin', 'Principal', 'Finance', 'Finance Officer']:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/registry.html', title='Global Registry')


@app.route('/api/auth/me')
@login_required
def auth_me():
    from flask import jsonify
    return jsonify(session.get('user', {}))

@app.route('/logout')
def logout():
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