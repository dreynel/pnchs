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

    # 1. Try local database first
    try:
        with db_cursor(commit=True) as (conn, cur):
            # Insert into biometric logs
            cur.execute("""
                INSERT INTO tblbiometric_logs (employee_id, log_type) 
                VALUES (%s, %s)
            """, (employee_id, log_type))
            
            # Upsert daily time log
            today = datetime.date.today()
            current_time = datetime.datetime.now().strftime('%H:%M:%S')
            
            cur.execute("SELECT log_id FROM tbltime_logs WHERE employee_id=%s AND work_date=%s", (employee_id, today))
            row = cur.fetchone()
            
            if row:
                cur.execute(f"UPDATE tbltime_logs SET {log_type} = %s WHERE log_id=%s", (current_time, row['log_id']))
            else:
                cur.execute(f"""
                    INSERT INTO tbltime_logs (employee_id, work_date, {log_type}) 
                    VALUES (%s, %s, %s)
                """, (employee_id, today, current_time))
                
        return jsonify({'message': f"Logged {log_type} for {employee_id}"})
    except Exception as db_err:
        print(f"[SYNC] Direct DB log failed ({db_err}), forwarding to Cloud API...")
        # 2. Forward to Cloud API
        cloud_url = os.environ.get('CLOUD_API_URL', 'http://187.52.121.22:8080')
        try:
            resp = requests.post(f"{cloud_url}/api/attendance/log", json=data, timeout=6)
            return (resp.content, resp.status_code, resp.headers.items())
        except Exception as cloud_err:
            return jsonify({'error': f"Failed to record attendance: {cloud_err}"}), 500


@attendance_bp.route('/today_categorized', methods=['GET'])
def get_today_categorized_logs():
    """
    Returns categorized attendance logs for the day (AM IN, AM OUT, PM IN, PM OUT)
    and summary count metrics.
    """
    from datetime import date, datetime
    req_date = request.args.get('date') or date.today().strftime('%Y-%m-%d')

    try:
        with db_cursor() as (conn, cur):
            # 1. Fetch today's aggregated time logs with employee info
            cur.execute("""
                SELECT 
                    t.id,
                    t.employee_id,
                    CONCAT(e.first_name, ' ', e.last_name) as name,
                    e.department,
                    e.designation,
                    t.work_date,
                    t.am_time_in,
                    t.am_time_out,
                    t.pm_time_in,
                    t.pm_time_out
                FROM tbltime_logs t
                JOIN tblemployee e ON t.employee_id = e.employee_id
                WHERE t.work_date = %s
                ORDER BY t.id DESC
            """, (req_date,))
            time_rows = cur.fetchall()

            # 2. Fetch raw punch logs for today
            cur.execute("""
                SELECT 
                    b.id, 
                    b.employee_id, 
                    CONCAT(e.first_name, ' ', e.last_name) as name,
                    b.log_type, 
                    b.log_time
                FROM tblbiometric_logs b
                JOIN tblemployee e ON b.employee_id = e.employee_id
                WHERE DATE(b.log_time) = %s
                ORDER BY b.log_time DESC
            """, (req_date,))
            raw_punches = cur.fetchall()

            def fmt_time(t):
                if t is None:
                    return None
                if isinstance(t, str):
                    return t
                try:
                    total_sec = int(t.total_seconds())
                    h = total_sec // 3600
                    m = (total_sec % 3600) // 60
                    dt = datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M")
                    return dt.strftime("%I:%M %p")
                except Exception:
                    return str(t)

            am_in_count = 0
            am_out_count = 0
            pm_in_count = 0
            pm_out_count = 0

            categorized_records = []
            for r in time_rows:
                am_in_str = fmt_time(r.get('am_time_in'))
                am_out_str = fmt_time(r.get('am_time_out'))
                pm_in_str = fmt_time(r.get('pm_time_in'))
                pm_out_str = fmt_time(r.get('pm_time_out'))

                if am_in_str: am_in_count += 1
                if am_out_str: am_out_count += 1
                if pm_in_str: pm_in_count += 1
                if pm_out_str: pm_out_count += 1

                categorized_records.append({
                    'id': r['id'],
                    'employee_id': r['employee_id'],
                    'name': r['name'],
                    'department': r.get('department') or '—',
                    'designation': r.get('designation') or 'Staff',
                    'am_time_in': am_in_str,
                    'am_time_out': am_out_str,
                    'pm_time_in': pm_in_str,
                    'pm_time_out': pm_out_str
                })

            type_labels = {
                'am_time_in': 'AM Time In',
                'am_time_out': 'AM Time Out',
                'pm_time_in': 'PM Time In',
                'pm_time_out': 'PM Time Out'
            }
            formatted_punches = []
            for p in raw_punches:
                p_time = p['log_time'].strftime('%I:%M:%S %p') if p.get('log_time') else '—'
                p_date = p['log_time'].strftime('%b %d, %Y') if p.get('log_time') else ''
                formatted_punches.append({
                    'id': p['id'],
                    'employee_id': p['employee_id'],
                    'name': p['name'],
                    'log_type': p['log_type'],
                    'log_type_label': type_labels.get(p['log_type'], p['log_type']),
                    'time_str': p_time,
                    'date_str': p_date
                })

            return jsonify({
                'date': req_date,
                'summary': {
                    'total_scans': len(raw_punches),
                    'total_employees': len(time_rows),
                    'am_time_in': am_in_count,
                    'am_time_out': am_out_count,
                    'pm_time_in': pm_in_count,
                    'pm_time_out': pm_out_count
                },
                'records': categorized_records,
                'raw_punches': formatted_punches
            })
    except Exception as e:
        print(f"[LOGS] Local DB query notice ({e}), attempting Cloud API...")
        cloud_url = os.environ.get('CLOUD_API_URL', 'http://187.52.121.22:8080')
        try:
            resp = requests.get(f"{cloud_url}/api/attendance/logs/data?date={req_date}", timeout=6)
            if resp.status_code == 200:
                raw_data = resp.json()
                return jsonify({
                    'date': req_date,
                    'summary': {
                        'total_scans': len(raw_data),
                        'total_employees': len(set(x.get('employee_id') for x in raw_data)),
                        'am_time_in': sum(1 for x in raw_data if x.get('log_type') == 'am_time_in'),
                        'am_time_out': sum(1 for x in raw_data if x.get('log_type') == 'am_time_out'),
                        'pm_time_in': sum(1 for x in raw_data if x.get('log_type') == 'pm_time_in'),
                        'pm_time_out': sum(1 for x in raw_data if x.get('log_type') == 'pm_time_out')
                    },
                    'records': [],
                    'raw_punches': raw_data
                })
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


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
            for log in logs:
                if log['log_time']:
                    log['log_time'] = log['log_time'].strftime('%b %d, %Y %I:%M:%S %p')
                    
                type_map = {
                    'am_time_in': 'AM Time In',
                    'am_time_out': 'AM Time Out',
                    'pm_time_in': 'PM Time In',
                    'pm_time_out': 'PM Time Out'
                }
                log['log_type_label'] = type_map.get(log['log_type'], log['log_type'])
                
            return jsonify(logs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
