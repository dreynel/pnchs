import base64
from flask import Blueprint, jsonify, request
from db import db_cursor

fingerprint_bp = Blueprint('fingerprints', __name__, url_prefix='/api/fingerprint')

@fingerprint_bp.route('/enroll/<emp_id>/<int:finger_index>', methods=['POST'])
def start_enrollment(emp_id, finger_index):
    # Insert an enrollment task into tblenrollment_tasks.
    # The local app will poll this task and execute it.
    try:
        with db_cursor(commit=True) as (conn, cur):
            # Force cancel any stuck pending task to avoid 409 locked scanner error
            cur.execute("UPDATE tblenrollment_tasks SET status='cancelled' WHERE status='pending'")
            
            cur.execute("""
                INSERT INTO tblenrollment_tasks (employee_id, finger_index, status, step, message) 
                VALUES (%s, %s, 'pending', 1, 'Scanner ready. Please touch finger to sensor (Press 1 of 3)...')
            """, (emp_id, finger_index))
            task_id = cur.lastrowid
            
        return jsonify({'message': 'Enrollment task queued.', 'task_id': task_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fingerprint_bp.route('/enroll_step', methods=['POST'])
def update_enrollment_step():
    data = request.json or {}
    task_id = data.get('task_id')
    step = int(data.get('step') or 1)
    message = data.get('message', '')
    error_msg = data.get('error', '')
    status = data.get('status', 'pending')

    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE tblenrollment_tasks
                SET step=%s, message=%s, error_message=%s, status=%s
                WHERE id=%s
            """, (step, message, error_msg, status, task_id))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fingerprint_bp.route('/enroll_status', methods=['GET'])
def get_status():
    # The frontend polls this to see if enrollment succeeded or failed
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id, status, finger_index, employee_id, step, message, error_message FROM tblenrollment_tasks ORDER BY id DESC LIMIT 1")
            task = cur.fetchone()
            if not task:
                return jsonify({'status': 'idle', 'message': '', 'error': '', 'step': 0})
                
            status = task['status']
            step = task.get('step') or 1
            msg = task.get('message') or 'Please scan finger...'
            err = task.get('error_message') or ''

            if status == 'pending':
                return jsonify({'status': 'enrolling', 'message': msg, 'error': '', 'step': step})
            elif status == 'success':
                return jsonify({'status': 'success', 'message': msg or 'Enrolled successfully!', 'error': '', 'step': 3})
            elif status == 'error':
                return jsonify({'status': 'error', 'message': '', 'error': err or 'Enrollment failed.', 'step': 0})
            elif status == 'cancelled':
                return jsonify({'status': 'error', 'message': '', 'error': 'Enrollment cancelled.', 'step': 0})
            else:
                return jsonify({'status': 'idle', 'message': '', 'error': '', 'step': 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@fingerprint_bp.route('/enroll_cancel', methods=['POST'])
def cancel_enrollment():
    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE tblenrollment_tasks SET status='cancelled' WHERE status='pending'")
        return jsonify({'message': 'Cancelled'}), 200
    except Exception:
        return jsonify({'error': 'Failed to cancel'}), 500


# --- Endpoints for Local App to consume ---

@fingerprint_bp.route('/kiosk_sync', methods=['GET'])
def kiosk_sync():
    """Returns all enrolled fingerprint templates."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id, employee_id, user_name, fingerprint_template FROM fingerprints")
            rows = cur.fetchall()
            return jsonify({'fingerprints': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fingerprint_bp.route('/poll_tasks', methods=['GET'])
def poll_tasks():
    """Returns the oldest pending enrollment task."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id, employee_id, finger_index FROM tblenrollment_tasks WHERE status='pending' ORDER BY id ASC LIMIT 1")
            task = cur.fetchone()
            if task:
                return jsonify({'task': task})
            return jsonify({'task': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fingerprint_bp.route('/enroll_complete', methods=['POST'])
def enroll_complete():
    """Receives the successfully merged template from the local app."""
    data = request.json
    task_id = data.get('task_id')
    emp_id = data.get('employee_id')
    finger_index = data.get('finger_index')
    template_b64 = data.get('template')
    error = data.get('error')

    try:
        with db_cursor(commit=True) as (conn, cur):
            if error:
                cur.execute("UPDATE tblenrollment_tasks SET status='error' WHERE id=%s", (task_id,))
                return jsonify({'message': 'Error logged'})
                
            # Upsert into fingerprints
            cur.execute("SELECT first_name, last_name FROM tblemployee WHERE employee_id=%s", (emp_id,))
            emp = cur.fetchone()
            user_name = f"{emp['first_name']} {emp['last_name']}" if emp else str(emp_id)

            cur.execute("""
                INSERT INTO fingerprints (employee_id, user_name, fingerprint_template, finger_index)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    fingerprint_template = VALUES(fingerprint_template),
                    user_name = VALUES(user_name)
            """, (emp_id, user_name, template_b64, finger_index))

            # Mark task success
            cur.execute("UPDATE tblenrollment_tasks SET status='success' WHERE id=%s", (task_id,))
            
        return jsonify({'message': 'Enrollment complete recorded'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fingerprint_bp.route('/verify_admin', methods=['POST'])
def verify_admin():
    """Verify Admin/HR credentials for Kiosk authorization."""
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required'}), 400

    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT u.employee_id, u.username, u.name AS fallback_name, u.role, e.first_name, e.last_name
                FROM tblusers u
                LEFT JOIN tblemployee e ON u.employee_id = e.employee_id
                WHERE u.username=%s AND u.password=%s
            """, (username, password))
            emp = cur.fetchone()
            if emp:
                if emp['role'] not in ['Admin', 'HR', 'HR Officer']:
                    return jsonify({'success': False, 'error': 'Access Denied: Admin or HR credentials required.'}), 403

                display_name = emp['fallback_name']
                if emp['first_name'] and emp['last_name']:
                    display_name = f"{emp['first_name']} {emp['last_name']}"

                return jsonify({
                    'success': True,
                    'user': {
                        'email': emp['username'],
                        'name': display_name,
                        'role': emp['role'],
                        'employee_id': emp['employee_id']
                    }
                })
            else:
                return jsonify({'success': False, 'error': 'Invalid admin credentials.'}), 401
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

