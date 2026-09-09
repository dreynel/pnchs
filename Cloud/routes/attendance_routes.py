import datetime
import calendar
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



def _parse_attendance_date_range(args):
    mode = args.get('date_mode')
    today = datetime.date.today()
    if not mode:
        if args.get('date'):
            mode = 'daily'
        elif args.get('month'):
            mode = 'month'
        elif args.get('year') and not (args.get('date_from') or args.get('date_to')):
            mode = 'year'
        elif args.get('date_from') or args.get('date_to'):
            mode = 'range'
        else:
            mode = 'daily'

    if mode == 'daily':
        d = args.get('date') or today.strftime('%Y-%m-%d')
        return 'daily', d, d, f"Daily ({d})", True
    elif mode == 'month':
        y = int(args.get('year') or today.year)
        m = int(args.get('month') or today.month)
        last_day = calendar.monthrange(y, m)[1]
        m_name = calendar.month_name[m]
        return 'month', f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}", f"{m_name} {y}", False
    elif mode == 'year':
        y = int(args.get('year') or today.year)
        return 'year', f"{y:04d}-01-01", f"{y:04d}-12-31", f"Year {y}", False
    elif mode == 'range':
        d_from = args.get('date_from') or today.strftime('%Y-%m-%d')
        d_to = args.get('date_to') or d_from
        return 'range', d_from, d_to, f"{d_from} to {d_to}", (d_from == d_to)
    return 'daily', today.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'), 'Today', True


@attendance_bp.route('/logs/data', methods=['GET'])
def get_biometric_logs():
    try:
        mode, start_date, end_date, label, is_single_day = _parse_attendance_date_range(request.args)
        
        query = """
            SELECT 
                b.id, 
                b.employee_id, 
                CONCAT(e.first_name, ' ', e.last_name) as name,
                b.log_type, 
                b.log_time
            FROM tblbiometric_logs b
            JOIN tblemployee e ON b.employee_id = e.employee_id
            WHERE DATE(b.log_time) >= %s AND DATE(b.log_time) <= %s
            ORDER BY b.log_time DESC
        """
        params = [start_date, end_date]

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


@attendance_bp.route('/today_categorized', methods=['GET'])
def get_today_categorized():
    """Returns categorized attendance records for Daily, Month, Year, or Date Range."""
    try:
        mode, start_date, end_date, label, is_single_day = _parse_attendance_date_range(request.args)
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT employee_id, first_name, last_name, designation, employee_type
                FROM tblemployee
                ORDER BY last_name ASC, first_name ASC
            """)
            employees = cur.fetchall()

            cur.execute("""
                SELECT b.id, b.employee_id, CONCAT(e.first_name, ' ', e.last_name) as name,
                       b.log_type, b.log_time
                FROM tblbiometric_logs b
                JOIN tblemployee e ON b.employee_id = e.employee_id
                WHERE DATE(b.log_time) >= %s AND DATE(b.log_time) <= %s
                ORDER BY b.log_time DESC
            """, (start_date, end_date))
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

            if is_single_day:
                cur.execute("""
                    SELECT employee_id, am_time_in, am_time_out, pm_time_in, pm_time_out
                    FROM tbltime_logs
                    WHERE work_date = %s
                """, (start_date,))
                time_logs = {row['employee_id']: row for row in cur.fetchall()}

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

                    f_am_in  = _format_time_12h(am_in)
                    f_am_out = _format_time_12h(am_out)
                    f_pm_in  = _format_time_12h(pm_in)
                    f_pm_out = _format_time_12h(pm_out)

                    matrix.append({
                        'employee_id': emp_id,
                        'name': f"{emp['first_name']} {emp['last_name']}",
                        'department': emp.get('employee_type') or 'Faculty',
                        'designation': emp.get('designation') or 'Staff',
                        'employee_type': emp.get('employee_type') or 'Faculty',
                        'am_time_in': f_am_in,
                        'am_time_out': f_am_out,
                        'pm_time_in': f_pm_in,
                        'pm_time_out': f_pm_out,
                        'am_in': f_am_in,
                        'am_out': f_am_out,
                        'pm_in': f_pm_in,
                        'pm_out': f_pm_out,
                        'has_activity': bool(am_in or am_out or pm_in or pm_out)
                    })
            else:
                cur.execute("""
                    SELECT employee_id,
                           COUNT(am_time_in) as am_in_c,
                           COUNT(am_time_out) as am_out_c,
                           COUNT(pm_time_in) as pm_in_c,
                           COUNT(pm_time_out) as pm_out_c,
                           COUNT(DISTINCT work_date) as active_days
                    FROM tbltime_logs
                    WHERE work_date >= %s AND work_date <= %s
                    GROUP BY employee_id
                """, (start_date, end_date))
                agg_logs = {row['employee_id']: row for row in cur.fetchall()}

                for emp in employees:
                    emp_id = emp['employee_id']
                    agg = agg_logs.get(emp_id, {})
                    c_am_in = agg.get('am_in_c', 0)
                    c_am_out = agg.get('am_out_c', 0)
                    c_pm_in = agg.get('pm_in_c', 0)
                    c_pm_out = agg.get('pm_out_c', 0)
                    days_active = agg.get('active_days', 0)

                    am_in_count += c_am_in
                    am_out_count += c_am_out
                    pm_in_count += c_pm_in
                    pm_out_count += c_pm_out

                    matrix.append({
                        'employee_id': emp_id,
                        'name': f"{emp['first_name']} {emp['last_name']}",
                        'department': emp.get('employee_type') or 'Faculty',
                        'designation': emp.get('designation') or 'Staff',
                        'employee_type': emp.get('employee_type') or 'Faculty',
                        'am_time_in': f"{c_am_in} scan{'s' if c_am_in!=1 else ''}" if c_am_in else "—",
                        'am_time_out': f"{c_am_out} scan{'s' if c_am_out!=1 else ''}" if c_am_out else "—",
                        'pm_time_in': f"{c_pm_in} scan{'s' if c_pm_in!=1 else ''}" if c_pm_in else "—",
                        'pm_time_out': f"{c_pm_out} scan{'s' if c_pm_out!=1 else ''}" if c_pm_out else "—",
                        'am_in': f"{c_am_in} scan{'s' if c_am_in!=1 else ''}" if c_am_in else "—",
                        'am_out': f"{c_am_out} scan{'s' if c_am_out!=1 else ''}" if c_am_out else "—",
                        'pm_in': f"{c_pm_in} scan{'s' if c_pm_in!=1 else ''}" if c_pm_in else "—",
                        'pm_out': f"{c_pm_out} scan{'s' if c_pm_out!=1 else ''}" if c_pm_out else "—",
                        'days_active': days_active,
                        'has_activity': bool(days_active > 0)
                    })

            return jsonify({
                'date': start_date if is_single_day else f"{start_date} to {end_date}",
                'date_mode': mode,
                'start_date': start_date,
                'end_date': end_date,
                'period_label': label,
                'is_single_day': is_single_day,
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
