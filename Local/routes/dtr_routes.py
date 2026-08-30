from flask import Blueprint, jsonify, request
from mysql.connector import Error
from db import db_cursor
import calendar
from datetime import date

dtr_bp = Blueprint('dtr', __name__, url_prefix='/api/dtr')

MONTHS = ['January','February','March','April','May','June',
          'July','August','September','October','November','December']

# ── Schedule Definitions ───────────────────────────────────────────────────────
# All times in minutes since midnight for easy arithmetic
def _get_schedule(designation):
    """
    Returns schedule dict based on designation keyword.
    Faculty:  AM 7:30–11:30 | PM 13:00–17:00  (8h total)
    Staff:    AM 8:00–12:00  | PM 13:00–17:00  (8h total)
    Default to Staff if unrecognised.
    """
    desig = (designation or '').lower()
    if 'faculty' in desig:
        return {
            'am_start': 7 * 60 + 30,   # 07:30
            'am_end':   11 * 60 + 30,  # 11:30
            'pm_start': 13 * 60,        # 13:00
            'pm_end':   17 * 60,        # 17:00
            'label': 'Faculty (7:30–11:30 / 13:00–17:00)'
        }
    else:  # Staff or Admin/others
        return {
            'am_start': 8 * 60,         # 08:00
            'am_end':   12 * 60,        # 12:00
            'pm_start': 13 * 60,        # 13:00
            'pm_end':   17 * 60,        # 17:00
            'label': 'Staff (8:00–12:00 / 13:00–17:00)'
        }

def _td_to_minutes(td):
    """Convert timedelta (MySQL TIME) to total minutes."""
    if td is None:
        return None
    return int(td.total_seconds()) // 60

def _time_str(t):
    """Convert timedelta (MySQL TIME), string, or None to 12-hour string (e.g. 7:30 AM)."""
    if t is None:
        return None
    if isinstance(t, str):
        s = t.strip()
        for fmt in ['%H:%M:%S', '%H:%M', '%I:%M:%S %p', '%I:%M %p']:
            try:
                dt = datetime.strptime(s, fmt)
                h = dt.hour
                m = dt.minute
                suffix = 'AM' if h < 12 else 'PM'
                h12 = h % 12
                if h12 == 0:
                    h12 = 12
                return f"{h12}:{m:02d} {suffix}"
            except ValueError:
                pass
        return s
    total_seconds = int(t.total_seconds())
    h = (total_seconds // 3600) % 24
    m = (total_seconds % 3600) // 60

def _compute_status(row):
    """Derive attendance status from a log row."""
    sessions = sum([
        row.get('am_time_in')  is not None,
        row.get('am_time_out') is not None,
        row.get('pm_time_in')  is not None,
        row.get('pm_time_out') is not None,
    ])
    if sessions == 0:
        return 'absent'
    if sessions <= 2:
        return 'half-day'
    return 'present'

def _compute_late_and_undertime(row, schedule):
    """
    Compute late minutes and undertime minutes based on employee schedule.

    Late:      arrived after scheduled start (AM or PM)
    Undertime: left before scheduled end (AM or PM)

    Returns (late_minutes, undertime_minutes)
    """
    late_min = 0
    undertime_min = 0

    am_in  = _td_to_minutes(row.get('am_time_in'))
    am_out = _td_to_minutes(row.get('am_time_out'))
    pm_in  = _td_to_minutes(row.get('pm_time_in'))
    pm_out = _td_to_minutes(row.get('pm_time_out'))

    # AM tardiness: arrived after AM start
    if am_in is not None:
        if am_in > schedule['am_start']:
            late_min += am_in - schedule['am_start']

    # AM undertime: left before AM end
    if am_out is not None:
        if am_out < schedule['am_end']:
            undertime_min += schedule['am_end'] - am_out

    # PM tardiness: arrived after PM start
    if pm_in is not None:
        if pm_in > schedule['pm_start']:
            late_min += pm_in - schedule['pm_start']

    # PM undertime: left before PM end
    if pm_out is not None:
        if pm_out < schedule['pm_end']:
            undertime_min += schedule['pm_end'] - pm_out

    return late_min, undertime_min

def _compute_hours(row, schedule):
    """
    Compute actual hours dutied based on real time logs vs schedule.
    Caps at scheduled hours; minimum 0.
    """
    am_in  = _td_to_minutes(row.get('am_time_in'))
    am_out = _td_to_minutes(row.get('am_time_out'))
    pm_in  = _td_to_minutes(row.get('pm_time_in'))
    pm_out = _td_to_minutes(row.get('pm_time_out'))

    hours = 0.0
    am_duration = schedule['am_end'] - schedule['am_start']  # e.g. 240 min = 4h
    pm_duration = schedule['pm_end'] - schedule['pm_start']  # always 240 min = 4h

    if am_in is not None and am_out is not None:
        worked = am_out - am_in
        hours += min(worked, am_duration) / 60
    elif am_in is not None:
        # Only in recorded, assume worked AM session minus late
        worked = schedule['am_end'] - max(am_in, schedule['am_start'])
        hours += max(worked, 0) / 60

    if pm_in is not None and pm_out is not None:
        worked = pm_out - pm_in
        hours += min(worked, pm_duration) / 60
    elif pm_in is not None:
        worked = schedule['pm_end'] - max(pm_in, schedule['pm_start'])
        hours += max(worked, 0) / 60

    return round(hours, 2)


# ── GET /api/dtr/employees ─────────────────────────────────────────────────────
@dtr_bp.route('/employees', methods=['GET'])
def get_employees():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT employee_id, first_name, last_name, designation
                FROM tblemployee
                ORDER BY last_name, first_name
            """)
            rows = cur.fetchall()
        return jsonify([{
            'id':          r['employee_id'],
            'first_name':  r['first_name'],
            'last_name':   r['last_name'],
            'designation': r['designation'],
            'full_name':   f"{r['first_name']} {r['last_name']}",
        } for r in rows])
    except Error as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/dtr/report ────────────────────────────────────────────────────────
@dtr_bp.route('/report', methods=['GET'])
def get_dtr_report():
    emp_id = request.args.get('employee_id', '').strip()
    year   = request.args.get('year',  '').strip()
    month  = request.args.get('month', '').strip()

    if not emp_id or not year or not month:
        return jsonify({'error': 'employee_id, year, and month are required'}), 400
    try:
        year_int  = int(year)
        month_int = int(month)
    except ValueError:
        return jsonify({'error': 'year and month must be integers'}), 400

    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT employee_id, first_name, last_name, designation
                FROM tblemployee WHERE employee_id = %s
            """, (emp_id,))
            emp = cur.fetchone()
            if not emp:
                return jsonify({'error': 'Employee not found'}), 404

            schedule = _get_schedule(emp['designation'])

            cur.execute("""
                SELECT log_id, employee_id, work_date,
                       am_time_in, am_time_out,
                       pm_time_in, pm_time_out
                FROM tbltime_logs
                WHERE employee_id = %s
                  AND YEAR(work_date)  = %s
                  AND MONTH(work_date) = %s
                ORDER BY work_date
            """, (emp_id, year_int, month_int))
            log_rows = cur.fetchall()

        logs_by_day = {r['work_date'].day: r for r in log_rows}
        days_in_month = calendar.monthrange(year_int, month_int)[1]

        days = []
        total_present = total_halfday = total_absent = 0
        total_late_min = total_undertime_min = 0

        h1 = {'present': 0, 'halfday': 0, 'absent': 0, 'late_min': 0, 'undertime_min': 0, 'hours': 0.0}
        h2 = {'present': 0, 'halfday': 0, 'absent': 0, 'late_min': 0, 'undertime_min': 0, 'hours': 0.0}

        for d in range(1, days_in_month + 1):
            work_date  = date(year_int, month_int, d)
            weekday    = work_date.strftime('%a')
            is_weekend = work_date.weekday() >= 5
            half       = h1 if d <= 15 else h2

            if d in logs_by_day:
                r            = logs_by_day[d]
                status       = _compute_status(r)
                late, under  = _compute_late_and_undertime(r, schedule)
                hours_today  = _compute_hours(r, schedule)
                entry = {
                    'day':          d,
                    'date_str':     work_date.strftime('%b %d, %Y'),
                    'weekday':      weekday,
                    'is_weekend':   is_weekend,
                    'am_in':        _time_str(r['am_time_in']),
                    'am_out':       _time_str(r['am_time_out']),
                    'pm_in':        _time_str(r['pm_time_in']),
                    'pm_out':       _time_str(r['pm_time_out']),
                    'status':       status,
                    'late_min':     late,
                    'undertime_min': under,
                    'has_log':      True,
                    'hours':        hours_today,
                }
            else:
                status = 'weekend' if is_weekend else 'absent'
                entry = {
                    'day':          d,
                    'date_str':     work_date.strftime('%b %d, %Y'),
                    'weekday':      weekday,
                    'is_weekend':   is_weekend,
                    'am_in':        None, 'am_out': None,
                    'pm_in':        None, 'pm_out': None,
                    'status':       status,
                    'late_min':     0,
                    'undertime_min': 0,
                    'has_log':      False,
                    'hours':        0.0,
                }

            if not is_weekend:
                if status == 'present':
                    total_present  += 1; half['present'] += 1; half['hours'] += entry['hours']
                elif status == 'half-day':
                    total_halfday  += 1; half['halfday'] += 1; half['hours'] += entry['hours']
                    total_present  += 0.5
                elif status == 'absent':
                    total_absent   += 1; half['absent'] += 1
                total_late_min      += entry['late_min'];     half['late_min']      += entry['late_min']
                total_undertime_min += entry['undertime_min']; half['undertime_min'] += entry['undertime_min']

            days.append(entry)

        total_hours = round(h1['hours'] + h2['hours'], 2)
        month_name  = MONTHS[month_int - 1]

        return jsonify({
            'employee': {
                'id':          emp['employee_id'],
                'first_name':  emp['first_name'],
                'last_name':   emp['last_name'],
                'designation': emp['designation'],
                'full_name':   f"{emp['first_name']} {emp['last_name']}",
                'schedule':    schedule['label'],
            },
            'period': {
                'year': year_int, 'month': month_int,
                'month_name': month_name, 'label': f"{month_name} {year_int}",
            },
            'summary': {
                'total_present':        total_present,
                'total_halfday':        total_halfday,
                'total_absent':         total_absent,
                'total_late_min':       total_late_min,
                'total_undertime_min':  total_undertime_min,
                'total_hours_dutied':   total_hours,
                'working_days':         total_present + total_halfday + total_absent,
            },
            'summary_h1': {
                'label': '1st Half (Days 1–15)',
                'present': h1['present'], 'halfday': h1['halfday'],
                'absent': h1['absent'], 'late_min': h1['late_min'],
                'undertime_min': h1['undertime_min'],
                'hours_dutied': round(h1['hours'], 2),
            },
            'summary_h2': {
                'label': '2nd Half (Days 16–End)',
                'present': h2['present'], 'halfday': h2['halfday'],
                'absent': h2['absent'], 'late_min': h2['late_min'],
                'undertime_min': h2['undertime_min'],
                'hours_dutied': round(h2['hours'], 2),
            },
            'days': days,
        })
    except Error as e:
        return jsonify({'error': str(e)}), 500