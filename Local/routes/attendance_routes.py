import datetime
import time
import os
import requests
from flask import Blueprint, jsonify, request
from db import db_cursor

attendance_bp = Blueprint('attendance', __name__, url_prefix='/api/attendance')

try:
    from scanner_manager import KIOSK_STATE, state_lock, start_device_thread, stop_device_thread
except ImportError:
    import sys
    _base = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    if _base not in sys.path:
        sys.path.insert(0, _base)
    from scanner_manager import KIOSK_STATE, state_lock, start_device_thread, stop_device_thread

@attendance_bp.route('/start', methods=['POST'])
def start_kiosk():
    with state_lock:
        KIOSK_STATE['last_scan'] = None
        KIOSK_STATE['last_error'] = None
    start_device_thread()
    return jsonify({
        'message': 'Kiosk/Scanner background thread started',
        'status': KIOSK_STATE.get('status', 'disconnected'),
        'device_connected': (KIOSK_STATE.get('status') == 'running')
    })

@attendance_bp.route('/stop', methods=['POST'])
def stop_kiosk():
    return jsonify({'message': 'Kiosk stopping instruction noted.'})

@attendance_bp.route('/poll', methods=['GET'])
def poll_kiosk():
    return jsonify({
        'status': KIOSK_STATE.get('status', 'disconnected'),
        'last_scan': KIOSK_STATE.get('last_scan'),
        'last_error': KIOSK_STATE.get('last_error'),
        'server_time': time.time()
    })

@attendance_bp.route('/log', methods=['POST'])
def log_attendance():
    if KIOSK_STATE.get('status') != 'running':
        return jsonify({'error': 'Fingerprint Scanner device not connected. Please connect USB reader.'}), 503

    data = request.get_json(force=True)

    employee_id = data.get('employee_id')
    log_type = data.get('log_type') # 'am_time_in', 'am_time_out', 'pm_time_in', 'pm_time_out'
    
    if not employee_id or not log_type:
        return jsonify({'error': 'Missing data'}), 400
        
    valid_types = ['am_time_in', 'am_time_out', 'pm_time_in', 'pm_time_out']
    if log_type not in valid_types:
        return jsonify({'error': 'Invalid log_type'}), 400

    type_labels = {
        'am_time_in': 'AM Time In',
        'am_time_out': 'AM Time Out',
        'pm_time_in': 'PM Time In',
        'pm_time_out': 'PM Time Out'
    }
    label = type_labels.get(log_type, log_type)

    try:
        with db_cursor(commit=True) as (conn, cur):
            today = datetime.date.today()
            current_time = datetime.datetime.now().strftime('%H:%M:%S')
            
            # Check existing time log for today
            cur.execute("""
                SELECT log_id, am_time_in, am_time_out, pm_time_in, pm_time_out 
                FROM tbltime_logs 
                WHERE employee_id=%s AND work_date=%s
            """, (employee_id, today))
            row = cur.fetchone()
            
            # Trap duplication: only once per slot per day (max 4 entries/day)
            if row and row.get(log_type) is not None:
                existing_time = _format_time_12h(row.get(log_type))
                return jsonify({
                    'error': f"{label} already recorded for today at {existing_time}.",
                    'duplicate': True,
                    'log_type': log_type,
                    'existing_time': existing_time
                }), 400
            
            # Record raw punch in tblbiometric_logs
            cur.execute("""
                INSERT INTO tblbiometric_logs (employee_id, log_type) 
                VALUES (%s, %s)
            """, (employee_id, log_type))
            
            if row:
                cur.execute(f"UPDATE tbltime_logs SET {log_type} = %s WHERE log_id=%s", (current_time, row['log_id']))
            else:
                cur.execute(f"""
                    INSERT INTO tbltime_logs (employee_id, work_date, {log_type}) 
                    VALUES (%s, %s, %s)
                """, (employee_id, today, current_time))
                
        return jsonify({
            'message': f"Logged {label} for {employee_id}",
            'log_type': log_type,
            'time': _format_time_12h(current_time)
        })
    except Exception as db_err:
        print(f"[DB ERROR] Attendance log write notice: {db_err}")
        return jsonify({'error': str(db_err)}), 500


def _format_time_12h(val):
    """Format any time/timedelta/datetime/string into 12-hour format (e.g. 7:30 AM or 3:13:08 PM)."""
    if not val:
        return None
    if isinstance(val, datetime.timedelta):
        total_seconds = int(val.total_seconds())
        h = (total_seconds // 3600) % 24
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        suffix = 'AM' if h < 12 else 'PM'
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12}:{m:02d}:{s:02d} {suffix}" if s > 0 else f"{h12}:{m:02d} {suffix}"
    if isinstance(val, (datetime.time, datetime.datetime)):
        h = val.hour
        m = val.minute
        s = getattr(val, 'second', 0)
        suffix = 'AM' if h < 12 else 'PM'
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12}:{m:02d}:{s:02d} {suffix}" if s > 0 else f"{h12}:{m:02d} {suffix}"
    s_val = str(val).strip()
    for fmt in ['%H:%M:%S', '%H:%M', '%I:%M:%S %p', '%I:%M %p']:
        try:
            dt = datetime.datetime.strptime(s_val, fmt)
            h = dt.hour
            m = dt.minute
            sec = dt.second
            suffix = 'AM' if h < 12 else 'PM'
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            return f"{h12}:{m:02d}:{sec:02d} {suffix}" if sec > 0 else f"{h12}:{m:02d} {suffix}"
        except ValueError:
            pass
    return s_val


@attendance_bp.route('/logs/data', methods=['GET'])
def get_biometric_logs():
    try:
        date_filter = request.args.get('date')
        
        query = """
            SELECT 
                b.id, 
                b.employee_id, 
                CONCAT(e.first_name, ' ', e.last_name) as name,
                b.log_type, 
                b.log_time
            FROM tblbiometric_logs b
            JOIN tblemployee e ON b.employee_id = e.employee_id
        """
        params = []
        
        if date_filter:
            query += " WHERE DATE(b.log_time) = %s"
            params.append(date_filter)
            
        query += " ORDER BY b.log_time DESC"

        with db_cursor() as (conn, cur):
            cur.execute(query, tuple(params))
            logs = cur.fetchall()
            type_map = {
                'am_time_in': 'AM Time In',
                'am_time_out': 'AM Time Out',
                'pm_time_in': 'PM Time In',
                'pm_time_out': 'PM Time Out'
            }
            for log in logs:
                if log['log_time']:
                    log['time_str'] = log['log_time'].strftime('%I:%M:%S %p').lstrip('0')
                    log['date_str'] = log['log_time'].strftime('%b %d, %Y')
                    log['log_time'] = log['log_time'].strftime('%b %d, %Y %I:%M:%S %p').lstrip('0')
                log['log_type_label'] = type_map.get(log['log_type'], log['log_type'])
                
            return jsonify(logs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@attendance_bp.route('/today_categorized', methods=['GET'])
def get_today_categorized():
    """Returns categorized attendance records (AM In, AM Out, PM In, PM Out) for the selected date."""
    target_date = request.args.get('date') or datetime.date.today().strftime('%Y-%m-%d')
    try:
        with db_cursor() as (conn, cur):
            # Fetch all active employees
            cur.execute("""
                SELECT employee_id, first_name, last_name, designation, employee_type
                FROM tblemployee
                ORDER BY last_name ASC, first_name ASC
            """)
            employees = cur.fetchall()

            # Fetch time logs for target date
            cur.execute("""
                SELECT employee_id, am_time_in, am_time_out, pm_time_in, pm_time_out
                FROM tbltime_logs
                WHERE work_date = %s
            """, (target_date,))
            time_logs = {row['employee_id']: row for row in cur.fetchall()}

            # Fetch raw biometric punches for target date
            cur.execute("""
                SELECT b.id, b.employee_id, CONCAT(e.first_name, ' ', e.last_name) as name,
                       b.log_type, b.log_time
                FROM tblbiometric_logs b
                JOIN tblemployee e ON b.employee_id = e.employee_id
                WHERE DATE(b.log_time) = %s
                ORDER BY b.log_time DESC
            """, (target_date,))
            raw_punches = cur.fetchall()
            type_map = {
                'am_time_in': 'AM Time In',
                'am_time_out': 'AM Time Out',
                'pm_time_in': 'PM Time In',
                'pm_time_out': 'PM Time Out'
            }
            for p in raw_punches:
                if p.get('log_time'):
                    p['log_time_fmt'] = p['log_time'].strftime('%I:%M:%S %p').lstrip('0')
                    p['time_str'] = p['log_time'].strftime('%I:%M:%S %p').lstrip('0')
                    p['date_str'] = p['log_time'].strftime('%b %d, %Y')
                    p['log_time'] = p['log_time'].strftime('%b %d, %Y %I:%M:%S %p').lstrip('0')
                p['log_type_label'] = type_map.get(p.get('log_type'), p.get('log_type'))

            matrix = []
            am_in_count = 0
            am_out_count = 0
            pm_in_count = 0
            pm_out_count = 0

            for emp in employees:
                emp_id = emp['employee_id']
                log = time_logs.get(emp_id, {})
                
                am_in = log.get('am_time_in')
                am_out = log.get('am_time_out')
                pm_in = log.get('pm_time_in')
                pm_out = log.get('pm_time_out')

                if am_in: am_in_count += 1
                if am_out: am_out_count += 1
                if pm_in: pm_in_count += 1
                if pm_out: pm_out_count += 1

                formatted_am_in  = _format_time_12h(am_in)
                formatted_am_out = _format_time_12h(am_out)
                formatted_pm_in  = _format_time_12h(pm_in)
                formatted_pm_out = _format_time_12h(pm_out)

                matrix.append({
                    'employee_id': emp_id,
                    'name': f"{emp['first_name']} {emp['last_name']}",
                    'department': emp.get('employee_type') or 'Faculty',
                    'designation': emp.get('designation') or 'Staff',
                    'employee_type': emp.get('employee_type') or 'Faculty',
                    'am_time_in': formatted_am_in,
                    'am_time_out': formatted_am_out,
                    'pm_time_in': formatted_pm_in,
                    'pm_time_out': formatted_pm_out,
                    'am_in': formatted_am_in,
                    'am_out': formatted_am_out,
                    'pm_in': formatted_pm_in,
                    'pm_out': formatted_pm_out,
                    'has_activity': bool(am_in or am_out or pm_in or pm_out)
                })

            return jsonify({
                'date': target_date,
                'summary': {
                    'total_employees': len(employees),
                    'am_in': am_in_count,
                    'am_out': am_out_count,
                    'pm_in': pm_in_count,
                    'pm_out': pm_out_count,
                    'am_time_in': am_in_count,
                    'am_time_out': am_out_count,
                    'pm_time_in': pm_in_count,
                    'pm_time_out': pm_out_count
                },
                'records': matrix,
                'matrix': matrix,
                'raw_punches': raw_punches
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
