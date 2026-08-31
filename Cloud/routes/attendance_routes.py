import datetime
from flask import Blueprint, jsonify, request
from db import db_cursor

attendance_bp = Blueprint('attendance', __name__, url_prefix='/api/attendance')

def _format_time_12h(time_val):
    if not time_val:
        return None
    if isinstance(time_val, datetime.timedelta):
        tot_sec = int(time_val.total_seconds())
        h = tot_sec // 3600
        m = (tot_sec % 3600) // 60
        s = tot_sec % 60
        t = datetime.time(h, m, s)
        return t.strftime('%I:%M %p').lstrip('0')
    if isinstance(time_val, str):
        try:
            parts = time_val.split(':')
            t = datetime.time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
            return t.strftime('%I:%M %p').lstrip('0')
        except Exception:
            return time_val
    if isinstance(time_val, datetime.time):
        return time_val.strftime('%I:%M %p').lstrip('0')
    return str(time_val)


def resolve_log_slot(row, now_time=None):
    if now_time is None:
        now_time = datetime.datetime.now().time()
    now_m = now_time.hour * 60 + now_time.minute
    
    # Morning: before 11:00 AM (660 mins)
    if now_m < 11 * 60:
        if not row or row.get('am_time_in') is None:
            return 'am_time_in'
        if row.get('am_time_out') is None and now_m >= 10 * 60:
            return 'am_time_out'
        return 'am_time_in'
        
    # Lunch break: 11:00 AM to 12:45 PM (765 mins)
    elif now_m < 12 * 60 + 45:
        if not row or row.get('am_time_out') is None:
            return 'am_time_out'
        if row.get('pm_time_in') is None and now_m >= 12 * 60 + 15:
            return 'pm_time_in'
        return 'am_time_out'
        
    # Afternoon Return: 12:45 PM to 02:30 PM (870 mins)
    elif now_m < 14 * 60 + 30:
        if not row or row.get('pm_time_in') is None:
            return 'pm_time_in'
        if row.get('pm_time_out') is None and now_m >= 14 * 60:
            return 'pm_time_out'
        return 'pm_time_in'
        
    # Afternoon Dismissal: 02:30 PM onwards
    else:
        if not row or row.get('pm_time_out') is None:
            return 'pm_time_out'
        return 'pm_time_out'


@attendance_bp.route('/log', methods=['POST'])
def log_attendance():
    data = request.get_json(force=True)
    employee_id = data.get('employee_id')
    log_type = data.get('log_type') # 'am_time_in', 'am_time_out', 'pm_time_in', 'pm_time_out', or 'auto'
    
    if not employee_id:
        return jsonify({'error': 'Missing employee_id'}), 400

    type_labels = {
        'am_time_in': 'AM Time In',
        'am_time_out': 'AM Time Out',
        'pm_time_in': 'PM Time In',
        'pm_time_out': 'PM Time Out'
    }

    try:
        with db_cursor(commit=True) as (conn, cur):
            today = datetime.date.today()
            now_dt = datetime.datetime.now()
            current_time = now_dt.strftime('%H:%M:%S')
            
            # Check existing time log for today
            cur.execute("""
                SELECT log_id, am_time_in, am_time_out, pm_time_in, pm_time_out 
                FROM tbltime_logs 
                WHERE employee_id=%s AND work_date=%s
            """, (employee_id, today))
            row = cur.fetchone()
            
            # Auto-determine slot if 'auto' or not explicitly provided
            if not log_type or log_type == 'auto':
                log_type = resolve_log_slot(row, now_dt.time())
                
            label = type_labels.get(log_type, log_type)
            
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
    except Exception as e:
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
                    
                # Beautify log_type
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
