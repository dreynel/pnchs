from flask import Blueprint, jsonify, request, session
from mysql.connector import Error
from db import db_cursor
import calendar
from datetime import date, datetime
from services.policy_engine import (
    AttendancePolicyService,
    LeavePolicyService,
    RateCalculationService,
    PayrollPolicyService,
    AuditService
)

dtr_bp = Blueprint('dtr', __name__, url_prefix='/api/dtr')

MONTHS = ['January','February','March','April','May','June',
          'July','August','September','October','November','December']




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

def _compute_hours(row, employee_type, designation):
    sch = AttendancePolicyService.get_schedule(employee_type, designation)
    am_in  = AttendancePolicyService.td_to_minutes(row.get('am_time_in'))
    am_out = AttendancePolicyService.td_to_minutes(row.get('am_time_out'))
    pm_in  = AttendancePolicyService.td_to_minutes(row.get('pm_time_in'))
    pm_out = AttendancePolicyService.td_to_minutes(row.get('pm_time_out'))

    hours = 0.0
    am_duration = sch['am_end'] - sch['am_start']
    pm_duration = sch['pm_end'] - sch['pm_start']

    if am_in is not None and am_out is not None:
        worked = am_out - am_in
        hours += min(worked, am_duration) / 60
    elif am_in is not None:
        worked = sch['am_end'] - max(am_in, sch['am_start'])
        hours += max(worked, 0) / 60

    if pm_in is not None and pm_out is not None:
        worked = pm_out - pm_in
        hours += min(worked, pm_duration) / 60
    elif pm_in is not None:
        worked = sch['pm_end'] - max(pm_in, sch['pm_start'])
        hours += max(worked, 0) / 60

    return round(hours, 2)


# ── GET /api/dtr/employees ─────────────────────────────────────────────────────
@dtr_bp.route('/employees', methods=['GET'])
def get_employees():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT employee_id, first_name, last_name, designation, employee_type
                FROM tblemployee
                ORDER BY last_name, first_name
            """)
            rows = cur.fetchall()
        return jsonify([{
            'id':            r['employee_id'],
            'first_name':    r['first_name'],
            'last_name':     r['last_name'],
            'designation':   r['designation'],
            'employee_type': r.get('employee_type', 'NON_TEACHING'),
            'full_name':     f"{r['first_name']} {r['last_name']}",
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
                SELECT employee_id, first_name, last_name, designation, employee_type
                FROM tblemployee WHERE employee_id = %s
            """, (emp_id,))
            emp = cur.fetchone()
            if not emp:
                return jsonify({'error': 'Employee not found'}), 404

            emp_type = emp.get('employee_type', 'NON_TEACHING')
            desig    = emp['designation']
            sch      = AttendancePolicyService.get_schedule(emp_type, desig)

            # Get basic salary & per minute rate for deduction estimation
            cur.execute("SELECT amount FROM tblpayhead WHERE employee_id=%s AND (LOWER(pay_head) LIKE %s OR LOWER(pay_head) LIKE %s)", (emp_id, '%salary%', '%basic%'))
            sal_row = cur.fetchone()
            basic_salary = float(sal_row['amount']) if sal_row else 0.0
            
            # Fetch month working days
            month_start_date = date(year_int, month_int, 1)
            days_in_m = calendar.monthrange(year_int, month_int)[1]
            month_end_date   = date(year_int, month_int, days_in_m)
            
            work_days_count = 0
            curr_d = month_start_date
            while curr_d <= month_end_date:
                if curr_d.weekday() < 5:
                    work_days_count += 1
                curr_d += calendar.timedelta(days=1) if hasattr(calendar, 'timedelta') else __import__('datetime').timedelta(days=1)
                
            rates = RateCalculationService.compute_rates(basic_salary, work_days_count or 22)
            per_min_rate = rates['per_min_rate']

            # Get leave balance
            bal = LeavePolicyService.get_balance(cur, emp_id)
            vl_balance_min = bal['vl_minutes']

            cur.execute("""
                SELECT log_id, employee_id, work_date,
                       am_time_in, am_time_out,
                       pm_time_in, pm_time_out,
                       actual_classroom_teaching_minutes,
                       teaching_related_minutes,
                       teaching_related_approved,
                       tardiness_minutes,
                       undertime_minutes,
                       vl_minutes_charged,
                       unpaid_minutes,
                       remarks
                FROM tbltime_logs
                WHERE employee_id = %s
                  AND YEAR(work_date)  = %s
                  AND MONTH(work_date) = %s
                ORDER BY work_date
            """, (emp_id, year_int, month_int))
            log_rows = cur.fetchall()

        logs_by_day = {r['work_date'].day: r for r in log_rows}

        days = []
        total_present = total_halfday = total_absent = 0
        total_late_min = total_undertime_min = 0
        total_vl_charged_min = total_unpaid_min = 0

        h1 = {'present': 0, 'halfday': 0, 'absent': 0, 'late_min': 0, 'undertime_min': 0, 'vl_charged': 0, 'unpaid': 0, 'hours': 0.0}
        h2 = {'present': 0, 'halfday': 0, 'absent': 0, 'late_min': 0, 'undertime_min': 0, 'vl_charged': 0, 'unpaid': 0, 'hours': 0.0}

        for d in range(1, days_in_m + 1):
            work_date  = date(year_int, month_int, d)
            weekday    = work_date.strftime('%a')
            is_weekend = work_date.weekday() >= 5
            half       = h1 if d <= 15 else h2

            if d in logs_by_day:
                r      = logs_by_day[d]
                status = _compute_status(r)

                res = AttendancePolicyService.calculate_tardiness_and_undertime(
                    emp_type, desig,
                    r['am_time_in'], r['am_time_out'],
                    r['pm_time_in'], r['pm_time_out'],
                    actual_classroom_minutes=r.get('actual_classroom_teaching_minutes') or 0,
                    teaching_related_minutes=r.get('teaching_related_minutes') or 0,
                    teaching_related_approved=bool(r.get('teaching_related_approved', 1))
                )
                late  = res['tardiness_minutes']
                under = res['undertime_minutes']
                hours_today = _compute_hours(r, emp_type, desig)

                # Simulated charging if not already saved
                total_deficiency = late + under
                vl_charged = min(total_deficiency, vl_balance_min)
                unpaid     = total_deficiency - vl_charged
                deduction_amount = round(unpaid * per_min_rate, 2)

                entry = {
                    'log_id':        r['log_id'],
                    'day':           d,
                    'date_str':      work_date.strftime('%b %d, %Y'),
                    'weekday':       weekday,
                    'is_weekend':    is_weekend,
                    'am_in':         _time_str(r['am_time_in']),
                    'am_out':        _time_str(r['am_time_out']),
                    'pm_in':         _time_str(r['pm_time_in']),
                    'pm_out':        _time_str(r['pm_time_out']),
                    'status':        status,
                    'late_min':      late,
                    'undertime_min': under,
                    'vl_charged_min': vl_charged,
                    'unpaid_min':    unpaid,
                    'payroll_deduction': deduction_amount,
                    'has_log':       True,
                    'hours':         hours_today,
                    'remarks':       r.get('remarks') or ''
                }
            else:
                status = 'weekend' if is_weekend else 'absent'
                entry = {
                    'log_id':        None,
                    'day':           d,
                    'date_str':      work_date.strftime('%b %d, %Y'),
                    'weekday':       weekday,
                    'is_weekend':    is_weekend,
                    'am_in':         None, 'am_out': None,
                    'pm_in':         None, 'pm_out': None,
                    'status':        status,
                    'late_min':      0,
                    'undertime_min': 0,
                    'vl_charged_min': 0,
                    'unpaid_min':    0,
                    'payroll_deduction': 0.0,
                    'has_log':       False,
                    'hours':         0.0,
                    'remarks':       ''
                }

            if not is_weekend:
                if status == 'present':
                    total_present  += 1; half['present'] += 1; half['hours'] += entry['hours']
                elif status == 'half-day':
                    total_halfday  += 1; half['halfday'] += 1; half['hours'] += entry['hours']
                    total_present  += 0.5
                elif status == 'absent':
                    total_absent   += 1; half['absent'] += 1

                total_late_min       += entry['late_min'];       half['late_min']       += entry['late_min']
                total_undertime_min  += entry['undertime_min'];  half['undertime_min']  += entry['undertime_min']
                total_vl_charged_min += entry['vl_charged_min']; half['vl_charged']    += entry['vl_charged_min']
                total_unpaid_min     += entry['unpaid_min'];     half['unpaid']        += entry['unpaid_min']

            days.append(entry)

        total_hours = round(h1['hours'] + h2['hours'], 2)
        month_name  = MONTHS[month_int - 1]
        total_payroll_deduction = round(total_unpaid_min * per_min_rate, 2)

        return jsonify({
            'employee': {
                'id':            emp['employee_id'],
                'first_name':    emp['first_name'],
                'last_name':     emp['last_name'],
                'designation':   emp['designation'],
                'employee_type': emp_type,
                'full_name':     f"{emp['first_name']} {emp['last_name']}",
                'schedule':      sch['label'],
                'vl_balance_minutes': vl_balance_min,
                'vl_balance_formatted': LeavePolicyService.format_minutes_to_dhm(vl_balance_min),
            },
            'period': {
                'year': year_int, 'month': month_int,
                'month_name': month_name, 'label': f"{month_name} {year_int}",
            },
            'summary': {
                'total_present':          total_present,
                'total_halfday':          total_halfday,
                'total_absent':           total_absent,
                'total_late_min':         total_late_min,
                'total_undertime_min':    total_undertime_min,
                'total_vl_charged_min':   total_vl_charged_min,
                'total_unpaid_min':       total_unpaid_min,
                'total_payroll_deduction': total_payroll_deduction,
                'total_hours_dutied':     total_hours,
                'working_days':           total_present + total_halfday + total_absent,
            },
            'summary_h1': {
                'label': '1st Half (Days 1–15)',
                'present': h1['present'], 'halfday': h1['halfday'],
                'absent': h1['absent'], 'late_min': h1['late_min'],
                'undertime_min': h1['undertime_min'],
                'vl_charged_min': h1['vl_charged'],
                'unpaid_min': h1['unpaid'],
                'payroll_deduction': round(h1['unpaid'] * per_min_rate, 2),
                'hours_dutied': round(h1['hours'], 2),
            },
            'summary_h2': {
                'label': '2nd Half (Days 16–End)',
                'present': h2['present'], 'halfday': h2['halfday'],
                'absent': h2['absent'], 'late_min': h2['late_min'],
                'undertime_min': h2['undertime_min'],
                'vl_charged_min': h2['vl_charged'],
                'unpaid_min': h2['unpaid'],
                'payroll_deduction': round(h2['unpaid'] * per_min_rate, 2),
                'hours_dutied': round(h2['hours'], 2),
            },
            'days': days,
        })
    except Error as e:
        return jsonify({'error': str(e)}), 500


# ── POST /api/dtr/correct ──────────────────────────────────────────────────────
@dtr_bp.route('/correct', methods=['POST'])
def correct_attendance():
    """
    Correct an attendance log record with automatic reversal of previous VL deduction
    and application of the corrected VL deduction without orphaned entries.
    """
    user = session.get('user', {})
    if user.get('role') not in ['Admin', 'HR']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json(force=True)
    emp_id    = data.get('employee_id')
    work_date = data.get('work_date')
    am_in     = data.get('am_time_in')
    am_out    = data.get('am_time_out')
    pm_in     = data.get('pm_time_in')
    pm_out    = data.get('pm_time_out')
    reason    = data.get('reason', 'Manual DTR Correction').strip()

    if not emp_id or not work_date:
        return jsonify({'error': 'employee_id and work_date are required'}), 400

    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT employee_type, designation FROM tblemployee WHERE employee_id=%s", (emp_id,))
            emp = cur.fetchone()
            if not emp:
                return jsonify({'error': 'Employee not found'}), 404

            # Check existing time log
            cur.execute("SELECT log_id, am_time_in, am_time_out, pm_time_in, pm_time_out FROM tbltime_logs WHERE employee_id=%s AND work_date=%s", (emp_id, work_date))
            log_row = cur.fetchone()

            log_id = log_row['log_id'] if log_row else None
            ref_id = f"LOG-{log_id}" if log_id else f"DTR-{emp_id}-{work_date}"

            # Step 1: Reversal of existing leave deduction for this attendance record
            if log_id:
                LeavePolicyService.reverse_attendance_leave_deductions(cur, emp_id, ref_id, user_name=user.get('name', 'HR'), reason=reason)

            # Step 2: Compute corrected tardiness and undertime
            res = AttendancePolicyService.calculate_tardiness_and_undertime(
                emp.get('employee_type', 'NON_TEACHING'), emp['designation'],
                am_in, am_out, pm_in, pm_out
            )
            late_min  = res['tardiness_minutes']
            under_min = res['undertime_minutes']

            # Step 3: Process new leave credit deduction
            processed = LeavePolicyService.process_tardiness_and_undertime(
                cur, emp_id, work_date, late_min, under_min, reference_id=ref_id, user_name=user.get('name', 'HR')
            )

            vl_charged = processed['total_vl_charged']
            unpaid_min = processed['total_lwop_minutes']

            # Step 4: Upsert time log
            if log_id:
                cur.execute("""
                    UPDATE tbltime_logs
                    SET am_time_in=%s, am_time_out=%s, pm_time_in=%s, pm_time_out=%s,
                        tardiness_minutes=%s, undertime_minutes=%s, vl_minutes_charged=%s, unpaid_minutes=%s, remarks=%s
                    WHERE log_id=%s
                """, (am_in, am_out, pm_in, pm_out, late_min, under_min, vl_charged, unpaid_min, reason, log_id))
            else:
                cur.execute("""
                    INSERT INTO tbltime_logs
                    (employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out,
                     tardiness_minutes, undertime_minutes, vl_minutes_charged, unpaid_minutes, remarks)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (emp_id, work_date, am_in, am_out, pm_in, pm_out, late_min, under_min, vl_charged, unpaid_min, reason))
                log_id = cur.lastrowid

            # Step 5: Audit log entry
            AuditService.log_action(
                cur, action='ATTENDANCE_CORRECTED', employee_id=emp_id, user_name=user.get('name', 'HR'),
                target_table='tbltime_logs', target_id=log_id,
                old_value=f"Original Log ID {log_id}", new_value=f"Late: {late_min}m, Under: {under_min}m, VL Charged: {vl_charged}m, Unpaid: {unpaid_min}m",
                reason=reason
            )

        return jsonify({'success': True, 'message': 'Attendance corrected successfully', 'result': processed})
    except Exception as e:
        return jsonify({'error': str(e)}), 500