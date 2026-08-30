from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from routes import employee_bp, dtr_bp, payroll_bp, fingerprint_bp, attendance_bp, registry_bp, dashboard_bp
import os

app = Flask(__name__)
app.secret_key = 'paycore-secret-2026'

# Register blueprints
app.register_blueprint(employee_bp)
app.register_blueprint(dtr_bp)
app.register_blueprint(payroll_bp)
app.register_blueprint(fingerprint_bp)
app.register_blueprint(attendance_bp)
app.register_blueprint(registry_bp)
app.register_blueprint(dashboard_bp)

# DB Initialization & Real-Time Biometric Scanner Start
try:
    from init_db import init
    init()
except Exception as e:
    pass

try:
    from scanner_manager import start_device_thread
    start_device_thread()
except Exception as e:
    print(f"Failed to start scanner thread: {e}")


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
@app.route('/scanner')
@app.route('/kiosk')
def kiosk():
    """Biometric Fingerprint Scanner Kiosk Portal."""
    return render_template('kiosk.html')

scanner_portal = kiosk

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        if session['user'].get('role') in ['Admin', 'HR', 'HR Officer']:
            return redirect(url_for('enrollment'))
        return redirect(url_for('kiosk'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        authenticated_user = None
        auth_error = 'Invalid admin credentials. Please verify your username and password.'

        # 1. Try Local MySQL DB first if reachable
        try:
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
                    if emp['role'] not in ['Admin', 'HR', 'HR Officer']:
                        flash('Access Denied: Fingerprint setup is strictly restricted to Authorized Admin/HR personnel.', 'error')
                        return render_template('login.html')

                    display_name = emp['fallback_name']
                    if emp['first_name'] and emp['last_name']:
                        display_name = f"{emp['first_name']} {emp['last_name']}"

                    authenticated_user = {
                        'email': emp['username'],
                        'name': display_name,
                        'role': emp['role'],
                        'employee_id': emp['employee_id']
                    }
        except Exception as local_db_err:
            print(f"[AUTH] Local DB check notice ({local_db_err}), checking Cloud API...")

        # 2. If not authenticated locally (e.g. on another laptop without MySQL), check Cloud API
        if not authenticated_user:
            try:
                import requests
                cloud_url = os.environ.get('CLOUD_API_URL', 'http://187.52.121.22:8080')
                resp = requests.post(f"{cloud_url}/api/fingerprint/verify_admin", json={
                    'username': email,
                    'password': password
                }, timeout=6)

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('success') and data.get('user'):
                        authenticated_user = data['user']
                elif resp.status_code == 403:
                    flash('Access Denied: Fingerprint setup is strictly restricted to Authorized Admin/HR personnel.', 'error')
                    return render_template('login.html')
                elif resp.status_code == 401:
                    auth_error = 'Invalid admin credentials. Please verify your username and password.'
            except Exception as cloud_err:
                print(f"[AUTH] Cloud verification notice: {cloud_err}")

        if authenticated_user:
            session['user'] = authenticated_user
            return redirect(url_for('enrollment'))

        flash(auth_error, 'error')

    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('enrollment'))



# Serve page fragments loaded dynamically via jQuery $.load()
@app.route('/pages/<path:filename>')
@login_required
def pages(filename):
    pages_dir = os.path.join(app.root_path, 'pages')
    return send_from_directory(pages_dir, filename)


@app.route('/employees')
@login_required
def employees():
    if session['user'].get('role') != 'HR':
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=session['user'], initial_page='/pages/employee.html', title='Employees')


@app.route('/enrollment')
@login_required
def enrollment():
    if session['user'].get('role') not in ['Admin', 'HR', 'HR Officer']:
        flash('Access Restricted: Authorized Admin or HR credentials required.', 'error')
        return redirect(url_for('login'))
    return render_template('index.html', user=session['user'], initial_page='/pages/enrollment.html', title='Biometric Fingerprint Setup')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('kiosk'))

if __name__ == '__main__':
    from scanner_manager import start_device_thread
    start_device_thread()
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)