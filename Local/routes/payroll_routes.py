from flask import Blueprint, jsonify, request
import json
from mysql.connector import Error
from db import db_cursor
from datetime import date, timedelta, datetime
import calendar
from services.policy_engine import (
    RateCalculationService,
    AttendancePolicyService,
    LeavePolicyService,
    PayrollPolicyService,
    HabitualTardinessService,
    AuditService
)

payroll_bp = Blueprint('payroll', __name__, url_prefix='/api/payroll')

# ── Philippine Government Contribution Tables ────────────────────────────────

def _get_statutory_configs(cur):
    """Fetch statutory configuration from tblstatutory_registry."""
    cur.execute("SELECT config_key, config_value, config_mode FROM tblstatutory_registry")
    return {row['config_key']: {'value': row['config_value'], 'mode': row['config_mode']} for row in cur.fetchall()}


def compute_dynamic_statutory_deductions(monthly_basic, configs):
    """
    Processes official Philippine DepEd government statutory deductions.
    Returns MONTHLY employee contribution amounts.
    """
    # 1. GSIS Personal Share (9% of basic salary)
    gsis_cfg = configs.get('GSIS_EE_RATE', {})
    gsis_rate = float(gsis_cfg.get('value') or 0.09)
    gsis_ee = round(monthly_basic * gsis_rate, 2)

    # 2. PhilHealth Personal Share (2.5% of basic salary, capped at ₱100k salary / ₱2,500 EE share, floor ₱10k salary / ₱250 EE share)
    phic_cfg = configs.get('PHILHEALTH_EE_RATE', {})
    phic_rate = float(phic_cfg.get('value') or 0.025)
    effective_phic_salary = max(10000.0, min(monthly_basic, 100000.0))
    philhealth_ee = round(effective_phic_salary * phic_rate, 2)

    # 3. Pag-IBIG Personal Share (₱200.00 monthly cap)
    pagibig_cfg = configs.get('PAGIBIG_EE_AMOUNT', {})
    pagibig_ee = float(pagibig_cfg.get('value') or 200.00)

    return {
        'GSIS': gsis_ee,
        'PHILHEALTH': philhealth_ee,
        'PAGIBIG': pagibig_ee
    }

# BIR TRAIN Law — Semi-monthly withholding tax table (2023 onwards)
# (min_taxable_income_semi_monthly, base_tax, excess_over, marginal_rate)
_BIR_SEMI_MONTHLY = [
    (0,       0,        0,       0.00),
    (10417,   0,        10417,   0.20),
    (16667,   1250,     16667,   0.25),
    (33333,   5417,     33333,   0.30),
    (83333,   20417,    83333,   0.32),
    (333333,  100417,   333333,  0.35),
]

def compute_withholding_tax(taxable_semi_monthly, configs):
    """BIR withholding tax per semi-monthly period per TRAIN law."""
    # Run only if taxable income > 0. Activation is managed by the presence of a "WITHHOLDING_TAX" trigger or just default to ON.
    # The user wanted BIR_ENABLED removed, implying it should be more integrated or always-on when taxable.
    if taxable_semi_monthly <= 0:
        return 0.00
    bracket = _BIR_SEMI_MONTHLY[0]
    for b in _BIR_SEMI_MONTHLY:
        if taxable_semi_monthly >= b[0]:
            bracket = b
        else:
            break
    _, base_tax, excess_over, rate = bracket
    tax = base_tax + (taxable_semi_monthly - excess_over) * rate
    return round(max(tax, 0), 2)


# ── Date / Attendance Helpers ────────────────────────────────────────────────

def count_work_days_in_period(start_date, end_date):
    days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon-Fri
            days += 1
        current += timedelta(days=1)
    return days

# ── Schedule Definitions ─────────────────────────────────────────────────────
def _get_schedule(designation):
    """
    Returns schedule times in minutes-since-midnight.
    Faculty: AM 7:30–11:30  / PM 13:00–17:00
    Staff:   AM 8:00–12:00  / PM 13:00–17:00
    """
    desig = (designation or '').lower()
    if 'faculty' in desig:
        return {'am_start': 450, 'am_end': 690,  'pm_start': 780, 'pm_end': 1020}  # 7:30/11:30/13:00/17:00
    return     {'am_start': 480, 'am_end': 720,  'pm_start': 780, 'pm_end': 1020}  # 8:00/12:00/13:00/17:00


def _td_mins(td):
    """Convert MySQL TIME timedelta to total minutes, or None."""
    return None if td is None else int(td.total_seconds()) // 60


def _get_late_and_undertime(log, designation):
    """
    Returns (late_minutes, undertime_minutes) based on designation schedule.
    Late      = arrived after scheduled session start.
    Undertime = left before scheduled session end.
    """
    sch = _get_schedule(designation)
    late = 0
    under = 0

    am_in  = _td_mins(log.get('am_time_in'))
    am_out = _td_mins(log.get('am_time_out'))
    pm_in  = _td_mins(log.get('pm_time_in'))
    pm_out = _td_mins(log.get('pm_time_out'))

    if am_in  is not None: late  += max(0, am_in  - sch['am_start'])
    if am_out is not None: under += max(0, sch['am_end']  - am_out)
    if pm_in  is not None: late  += max(0, pm_in  - sch['pm_start'])
    if pm_out is not None: under += max(0, sch['pm_end']  - pm_out)

    return late, under

def get_holidays_in_period(cur, start_date, end_date):
    """Returns dict of {date: holiday_type} for holidays in the period."""
    cur.execute(
        "SELECT holiday_date, holiday_type FROM tblholidays WHERE holiday_date BETWEEN %s AND %s",
        (start_date, end_date)
    )
    return {row['holiday_date']: row['holiday_type'] for row in cur.fetchall()}

def get_approved_leave_dates(cur, emp_id, start_date, end_date):
    """Returns set of approved leave dates for an employee in period."""
    cur.execute(
        "SELECT leave_date FROM tblleaves WHERE employee_id=%s AND leave_date BETWEEN %s AND %s AND status='Approved'",
        (emp_id, start_date, end_date)
    )
    return {row['leave_date'] for row in cur.fetchall()}


# ── POST /api/payroll/runs ────────────────────────────────────────────────────
@payroll_bp.route('/runs', methods=['POST'])
def create_run():
    from flask import session
    if session.get('user', {}).get('role') not in ['Admin', 'Finance']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json
    year_str, month_str, half_str = data.get('year'), data.get('month'), data.get('half')
    if not year_str or not month_str or not half_str:
        return jsonify({'error': 'Missing parameters'}), 400

    try:
        year_int  = int(year_str)
        month_int = int(month_str)
        half_int  = int(half_str)
    except ValueError:
        return jsonify({'error': 'Invalid parameters'}), 400

    period_key = f"{year_int}-{month_int}-{half_int}"

    if half_int == 1:
        start_day, end_day = 1, 15
    else:
        start_day, end_day = 16, calendar.monthrange(year_int, month_int)[1]

    start_date = date(year_int, month_int, start_day)
    end_date   = date(year_int, month_int, end_day)
    expected_work_days  = count_work_days_in_period(start_date, end_date)

    month_start_date  = date(year_int, month_int, 1)
    month_end_date    = date(year_int, month_int, calendar.monthrange(year_int, month_int)[1])
    month_working_days = count_work_days_in_period(month_start_date, month_end_date)

    try:
        with db_cursor() as (conn, cur):
            # Duplicate check
            cur.execute("SELECT id FROM tblpayroll WHERE period_key=%s", (period_key,))
            if cur.fetchone():
                return jsonify({'error': 'Payroll record for this period already exists.'}), 400

            # Create header record
            cur.execute(
                "INSERT INTO tblpayroll (period_key, year, month, half, status) VALUES (%s, %s, %s, %s, 'Draft')",
                (period_key, year_int, month_int, half_int)
            )

            # Load holidays, employees, global payheads, and statutory configs
            holidays = get_holidays_in_period(cur, start_date, end_date)
            holiday_dates = set(holidays.keys())

            cur.execute("SELECT * FROM tblglobal_payheads")
            global_payheads = cur.fetchall()

            configs = _get_statutory_configs(cur)

            cur.execute("SELECT employee_id, first_name, last_name, designation FROM tblemployee")
            employees = cur.fetchall()

            # We'll calculate global payheads per employee due to potential percentages

            for emp in employees:
                emp_id = emp['employee_id']

                # ── Pay heads ─────────────────────────────────────────────────
                cur.execute("SELECT pay_head, amount, category, mode, percentage_value FROM tblpayhead WHERE employee_id = %s", (emp_id,))
                payheads = cur.fetchall()
                # Identify basic salary first for percentage calculations
                basic_salary = 0.0
                for ph in payheads:
                    if 'salary' in ph['pay_head'].lower() or 'basic' in ph['pay_head'].lower():
                        basic_salary += float(ph['amount'])

                other_earnings = other_deductions = 0.0
                holiday_pay = 0.0
                payhead_breakdown = {'earnings': [], 'deductions': []}
                # Process Individual Payheads
                for ph in payheads:
                    if 'salary' in ph['pay_head'].lower() or 'basic' in ph['pay_head'].lower():
                        continue
                    
                    amount = float(ph['amount'])
                    if ph.get('mode') == 'Percentage' and basic_salary > 0:
                        amount = basic_salary * (float(ph.get('percentage_value') or 0) / 100)
                    
                    if ph.get('category', 'Earning') == 'Earning':
                        other_earnings += amount
                        payhead_breakdown['earnings'].append({'name': ph['pay_head'], 'amount': round(amount / 2, 2)})
                    else:
                        other_deductions += amount
                        payhead_breakdown['deductions'].append({'name': ph['pay_head'], 'amount': round(amount / 2, 2)})

                # Process Global Payheads
                for g in global_payheads:
                    amount = float(g['amount'])
                    if g.get('mode') == 'Percentage' and basic_salary > 0:
                        amount = basic_salary * (float(g.get('percentage_value') or 0) / 100)
                    
                    if g.get('type') == 'Earning':
                        other_earnings += amount
                        payhead_breakdown['earnings'].append({'name': g['name'], 'amount': round(amount / 2, 2)})
                    else:
                        other_deductions += amount
                        payhead_breakdown['deductions'].append({'name': g['name'], 'amount': round(amount / 2, 2)})

                half_basic      = basic_salary / 2
                half_earnings   = other_earnings / 2
                half_deductions = other_deductions / 2

                # Daily & per-minute rate
                daily_rate   = (basic_salary / month_working_days) if basic_salary and month_working_days else 0
                per_min_rate = (daily_rate / 8 / 60) if daily_rate else 0

                # ── Attendance logs ───────────────────────────────────────────
                cur.execute("""
                    SELECT log_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out,
                           actual_classroom_teaching_minutes, teaching_related_minutes, teaching_related_approved
                    FROM tbltime_logs
                    WHERE employee_id = %s AND work_date BETWEEN %s AND %s
                """, (emp_id, start_date, end_date))
                logs = cur.fetchall()

                logged_dates     = {log['work_date'] for log in logs}
                total_late_min   = 0
                total_under_min  = 0
                vl_late_min      = 0
                vl_under_min     = 0
                lwop_late_min    = 0
                lwop_under_min   = 0

                # Check policy effective date
                apply_deped_policy = PayrollPolicyService.check_policy_effective_date(cur, end_date)

                emp_type = emp.get('employee_type', 'NON_TEACHING')
                desig    = emp.get('designation', '')

                for log in logs:
                    res = AttendancePolicyService.calculate_tardiness_and_undertime(
                        emp_type, desig,
                        log['am_time_in'], log['am_time_out'],
                        log['pm_time_in'], log['pm_time_out'],
                        actual_classroom_minutes=log.get('actual_classroom_teaching_minutes') or 0,
                        teaching_related_minutes=log.get('teaching_related_minutes') or 0,
                        teaching_related_approved=bool(log.get('teaching_related_approved', 1))
                    )
                    l = res['tardiness_minutes']
                    u = res['undertime_minutes']
                    total_late_min  += l
                    total_under_min += u

                    if apply_deped_policy:
                        ref_id = f"LOG-{log['log_id']}"
                        proc = LeavePolicyService.process_tardiness_and_undertime(
                            cur, emp_id, log['work_date'], l, u, reference_id=ref_id, user_name='PayrollEngine'
                        )
                        vl_late_min    += proc['vl_tardiness_minutes']
                        vl_under_min   += proc['vl_undertime_minutes']
                        lwop_late_min  += proc['lwop_tardiness_minutes']
                        lwop_under_min += proc['lwop_undertime_minutes']
                    else:
                        lwop_late_min  += l
                        lwop_under_min += u

                # ── Approved leaves (excluded from absent count) ───────────────
                approved_leave_dates = get_approved_leave_dates(cur, emp_id, start_date, end_date)
                # Only count leaves on working weekdays
                effective_leave_days = len([
                    d for d in approved_leave_dates
                    if d.weekday() < 5  # Mon-Fri
                ])

                # Effective present days = logged + approved leaves
                effective_present = len(logged_dates) + effective_leave_days

                absent_days      = max(0, expected_work_days - effective_present)
                absent_deduction = absent_days * daily_rate

                if apply_deped_policy:
                    # ONLY unpaid (LWOP) tardiness and undertime result in salary deduction!
                    tardiness_deduction  = round(lwop_late_min  * per_min_rate, 2)
                    undertime_deduction  = round(lwop_under_min * per_min_rate, 2)
                else:
                    tardiness_deduction  = round(total_late_min  * per_min_rate, 2)
                    undertime_deduction  = round(total_under_min * per_min_rate, 2)

                # ── Dynamic Statutory Deductions (monthly → semi-monthly split) ───────
                monthly_stat_deductions = compute_dynamic_statutory_deductions(basic_salary, configs)
                
                # Map primary rules to specific columns (halved for semi-monthly)
                gsis_ee = monthly_stat_deductions.get('GSIS', 0) / 2
                philhealth_ee = monthly_stat_deductions.get('PHILHEALTH', 0) / 2
                pagibig_ee = monthly_stat_deductions.get('PAGIBIG', 0) / 2
                
                # Add any other dynamic statutory rules to other_deductions pool
                for k, v in monthly_stat_deductions.items():
                    if k not in ['GSIS', 'PHILHEALTH', 'PAGIBIG']:
                        other_deductions += v
                
                # Re-calculate half-totals
                half_basic      = basic_salary / 2
                half_earnings   = other_earnings / 2
                half_deductions = other_deductions / 2

                # ── BIR Withholding Tax ───────────────────────────────────────
                # Taxable = semi-monthly gross earnings - mandatory deductions
                taxable = (half_basic + half_earnings) - gsis_ee - philhealth_ee - pagibig_ee - absent_deduction - tardiness_deduction - undertime_deduction
                withholding_tax = compute_withholding_tax(taxable, configs)

                # ── Totals ────────────────────────────────────────────────────
                total_gross  = half_basic + half_earnings
                total_deduct = (half_deductions + absent_deduction + tardiness_deduction
                                + undertime_deduction
                                + gsis_ee + philhealth_ee + pagibig_ee + withholding_tax)
                raw_net      = total_gross - total_deduct
                net_pay      = max(0.0, raw_net)
                is_negative  = 1 if raw_net < 0 else 0
                dtr_filed    = 1 if len(logs) > 0 else 0

                # ── Statutory Breakdown JSON ──────────────────────────────────
                # Create a breakdown of all individual deductions for the payslip
                breakdown = {}
                for k, v in monthly_stat_deductions.items():
                    breakdown[k] = round(v / 2, 2)
                
                # Add attendance and tax to breakdown as well for completeness
                breakdown['ABSENCE'] = round(absent_deduction, 2)
                breakdown['TARDINESS'] = round(tardiness_deduction, 2)
                breakdown['UNDERTIME'] = round(undertime_deduction, 2)
                breakdown['WTAX'] = round(withholding_tax, 2)
                
                stat_json = json.dumps(breakdown)

                cur.execute("""
                    INSERT INTO tblpayroll_details
                    (period_key, employee_id, basic_salary, half_basic, other_earnings, holiday_pay,
                     other_deductions, daily_rate, absent_days, absent_deduction,
                     late_minutes, undertime_minutes,
                     vl_tardiness_minutes, vl_undertime_minutes,
                     lwop_tardiness_minutes, lwop_undertime_minutes,
                     tardiness_deduction, undertime_deduction,
                     sss_ee, philhealth_ee, pagibig_ee, withholding_tax,
                     statutory_json, payheads_json,
                     total_gross, total_deduct, net_pay, is_negative, dtr_filed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (period_key, emp_id, basic_salary, half_basic, half_earnings, holiday_pay,
                      half_deductions, daily_rate, absent_days, absent_deduction,
                      total_late_min, total_under_min,
                      vl_late_min, vl_under_min,
                      lwop_late_min, lwop_under_min,
                      tardiness_deduction, undertime_deduction,
                      gsis_ee, philhealth_ee, pagibig_ee, withholding_tax,
                      stat_json, json.dumps(payhead_breakdown),
                      total_gross, total_deduct, net_pay, is_negative, dtr_filed))

            conn.commit()
            return jsonify({'success': True, 'key': period_key})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


def _workdays(start, end):
    """Generator of weekday dates between start and end (inclusive)."""
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


# ── GET /api/payroll/process ─────────────────────────────────────────────────
@payroll_bp.route('/process', methods=['GET'])
def process_payroll():
    year  = request.args.get('year',  '').strip()
    month = request.args.get('month', '').strip()
    half  = request.args.get('half',  '').strip()

    if not year or not month or not half:
        return jsonify({'error': 'year, month, and half are required'}), 400

    period_key = f"{int(year)}-{int(month)}-{int(half)}"

    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT d.*, e.first_name, e.last_name, e.designation
                FROM tblpayroll_details d
                JOIN tblemployee e ON d.employee_id = e.employee_id
                WHERE d.period_key = %s
            """, (period_key,))
            records = cur.fetchall()

            # Fetch payroll header for created_at
            cur.execute("SELECT created_at, approved_by, approved_at FROM tblpayroll WHERE period_key=%s", (period_key,))
            hdr = cur.fetchone()
            created_at_str = hdr['created_at'].strftime('%b %d, %Y') if hdr and hdr['created_at'] else '—'
            approved_by    = hdr['approved_by'] if hdr else None
            approved_at    = hdr['approved_at'].strftime('%b %d, %Y %I:%M %p') if hdr and hdr['approved_at'] else None

            results = []
            gGross = gDeduct = gNet = 0.0
            for rec in records:
                def f(k): return float(rec.get(k) or 0)
                results.append({
                    'id':                 rec['employee_id'],
                    'name':               f"{rec['first_name']} {rec['last_name']}",
                    'designation':        rec['designation'],
                    'basic_salary':       f('basic_salary'),
                    'half_basic':         f('half_basic'),
                    'other_earnings':     f('other_earnings'),
                    'holiday_pay':        f('holiday_pay'),
                    'other_deductions':   f('other_deductions'),
                    'daily_rate':         f('daily_rate'),
                    'absent_days':        rec.get('absent_days', 0),
                    'absent_deduction':   f('absent_deduction'),
                    'late_minutes':        rec.get('late_minutes', 0),
                    'undertime_minutes':   rec.get('undertime_minutes', 0),
                    'tardiness_deduction': f('tardiness_deduction'),
                    'undertime_deduction': f('undertime_deduction'),
                    'gsis_ee':             f('sss_ee'),  # Mapping sss_ee col to gsis_ee
                    'philhealth_ee':      f('philhealth_ee'),
                    'pagibig_ee':         f('pagibig_ee'),
                    'withholding_tax':    f('withholding_tax'),
                    'statutory_json':      rec.get('statutory_json'),
                    'payheads_json':       rec.get('payheads_json'),
                    'total_gross':        f('total_gross'),
                    'total_deduct':       f('total_deduct'),
                    'net_pay':            f('net_pay'),
                    'is_negative':        bool(rec.get('is_negative', 0)),
                    'below_net_floor':    bool(f('net_pay') < 2500.0 and f('basic_salary') > 0),
                    'dtr_filed':          bool(rec.get('dtr_filed', 0)),
                })

                gGross  += f('total_gross')
                gDeduct += f('total_deduct')
                gNet    += f('net_pay')

        return jsonify({
            'period':      f"{calendar.month_name[int(month)]} {year} - {'1st' if int(half)==1 else '2nd'} Half",
            'created_at':  created_at_str,
            'approved_by': approved_by,
            'approved_at': approved_at,
            'employees':   results,
            'summary': {
                'total_employees':    len(results),
                'grand_total_gross':  round(gGross,  2),
                'grand_total_deduct': round(gDeduct, 2),
                'grand_total_net':    round(gNet,    2),
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/payroll/my_payslip ──────────────────────────────────────────────
@payroll_bp.route('/my_payslip', methods=['GET'])
def my_payslip():
    from flask import session
    if 'user' not in session or not session['user'].get('employee_id'):
        return jsonify({'error': 'Unauthorized'}), 401

    year  = request.args.get('year',  '').strip()
    month = request.args.get('month', '').strip()
    half  = request.args.get('half',  '').strip()

    if not year or not month or not half:
        return jsonify({'error': 'Missing parameters'}), 400

    period_key = f"{int(year)}-{int(month)}-{int(half)}"
    emp_id = session['user']['employee_id']

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status, created_at FROM tblpayroll WHERE period_key=%s", (period_key,))
            pr = cur.fetchone()
            if not pr:
                return jsonify({'error': 'Payslip for this period has not been generated.'}), 404
            if pr['status'] not in ['Approved', 'Posted']:
                return jsonify({'error': 'Payslip is not yet approved and released.'}), 403

            cur.execute("""
                SELECT d.*, e.first_name, e.last_name, e.designation
                FROM tblpayroll_details d
                JOIN tblemployee e ON d.employee_id = e.employee_id
                WHERE d.period_key = %s AND d.employee_id = %s
            """, (period_key, emp_id))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Employee payslip record not found.'}), 404

            def f(k): return float(rec.get(k) or 0)
            payload = {
                'id':                 rec['employee_id'],
                'name':               f"{rec['first_name']} {rec['last_name']}",
                'designation':        rec['designation'],
                'basic_salary':       f('basic_salary'),
                'half_basic':         f('half_basic'),
                'other_earnings':     f('other_earnings'),
                'holiday_pay':        f('holiday_pay'),
                'other_deductions':   f('other_deductions'),
                'daily_rate':         f('daily_rate'),
                'absent_days':        rec.get('absent_days', 0),
                'absent_deduction':   f('absent_deduction'),
                'late_minutes':       rec.get('late_minutes', 0),
                'tardiness_deduction':f('tardiness_deduction'),
                'gsis_ee':             f('sss_ee'),  # DB col is sss_ee, mapped to gsis_ee in payload
                'philhealth_ee':      f('philhealth_ee'),
                'pagibig_ee':         f('pagibig_ee'),
                'withholding_tax':    f('withholding_tax'),
                'statutory_json':      rec.get('statutory_json'),
                'payheads_json':       rec.get('payheads_json'),
                'total_gross':        f('total_gross'),
                'total_deduct':       f('total_deduct'),
                'net_pay':            f('net_pay'),
                'is_negative':        bool(rec.get('is_negative', 0)),
                'dtr_filed':          bool(rec.get('dtr_filed', 0)),
            }
            return jsonify({
                'period':     f"{calendar.month_name[int(month)]} {year} - {'1st' if int(half)==1 else '2nd'} Half",
                'created_at': pr['created_at'].strftime('%b %d, %Y') if pr['created_at'] else '—',
                'data':       payload
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/payroll/runs ────────────────────────────────────────────────────
@payroll_bp.route('/runs', methods=['GET'])
def get_runs():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT period_key, year, month, half, status, remarks, approved_by, approved_at, created_at FROM tblpayroll ORDER BY year DESC, month DESC, half DESC")
            records = cur.fetchall()
            return jsonify([{
                'key':         r['period_key'],
                'period':      f"{calendar.month_name[r['month']]} {r['year']} - {'1st' if r['half']==1 else '2nd'} Half",
                'year':        r['year'],
                'month':       r['month'],
                'half':        r['half'],
                'status':      r['status'],
                'remarks':     r['remarks'],
                'approved_by': r['approved_by'],
                'approved_at': r['approved_at'].strftime('%b %d, %Y %I:%M %p') if r['approved_at'] else None,
                'created_at':  r['created_at'].strftime('%b %d, %Y') if r['created_at'] else None,
            } for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── DELETE /api/payroll/runs/<period_key> ────────────────────────────────────
@payroll_bp.route('/runs/<period_key>', methods=['DELETE'])
def delete_run(period_key):
    from flask import session
    if session.get('user', {}).get('role') not in ['Admin', 'Finance']:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM tblpayroll WHERE period_key=%s", (period_key,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Not found'}), 404
            if rec['status'] not in ['Draft', 'Rejected']:
                return jsonify({'error': 'Cannot delete an active or approved payroll.'}), 400
            cur.execute("DELETE FROM tblpayroll WHERE period_key=%s", (period_key,))
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── PUT /api/payroll/runs/<period_key>/details/<employee_id> ─────────────────
@payroll_bp.route('/runs/<period_key>/details/<employee_id>', methods=['PUT'])
def update_payroll_detail(period_key, employee_id):
    from flask import session
    if session.get('user', {}).get('role') not in ['Admin', 'Finance']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json
    try:
        half_basic          = float(data.get('half_basic', 0))
        other_earnings      = float(data.get('other_earnings', 0))
        holiday_pay         = float(data.get('holiday_pay', 0))
        other_deductions    = float(data.get('other_deductions', 0))
        absent_deduction    = float(data.get('absent_deduction', 0))
        tardiness_deduction = float(data.get('tardiness_deduction', 0))
        gsis_ee              = float(data.get('gsis_ee', data.get('sss_ee', 0)))
        philhealth_ee       = float(data.get('philhealth_ee', 0))
        pagibig_ee          = float(data.get('pagibig_ee', 0))
        withholding_tax     = float(data.get('withholding_tax', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid numeric data.'}), 400

    total_gross  = half_basic + other_earnings + holiday_pay
    total_deduct = other_deductions + absent_deduction + tardiness_deduction + gsis_ee + philhealth_ee + pagibig_ee + withholding_tax
    raw_net      = total_gross - total_deduct
    net_pay      = max(0.0, raw_net)
    is_negative  = 1 if raw_net < 0 else 0

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM tblpayroll WHERE period_key=%s", (period_key,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Not found'}), 404
            if rec['status'] != 'Draft':
                return jsonify({'error': 'Cannot edit details of a non-draft payroll.'}), 400

            cur.execute("""
                UPDATE tblpayroll_details
                SET half_basic=%s, other_earnings=%s, holiday_pay=%s, other_deductions=%s,
                    absent_deduction=%s, tardiness_deduction=%s,
                    sss_ee=%s, philhealth_ee=%s, pagibig_ee=%s, withholding_tax=%s,
                    total_gross=%s, total_deduct=%s, net_pay=%s, is_negative=%s
                WHERE period_key=%s AND employee_id=%s
            """, (half_basic, other_earnings, holiday_pay, other_deductions,
                  absent_deduction, tardiness_deduction,
                  gsis_ee, philhealth_ee, pagibig_ee, withholding_tax,
                  total_gross, total_deduct, net_pay, is_negative,
                  period_key, employee_id))
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── POST /api/payroll/runs/<period_key>/status ───────────────────────────────
@payroll_bp.route('/runs/<period_key>/status', methods=['POST'])
def update_status(period_key):
    from flask import session
    role = session.get('user', {}).get('role')
    user_name = session.get('user', {}).get('name', 'Unknown')
    data = request.json
    new_status = data.get('status')
    remarks    = data.get('remarks', None)

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM tblpayroll WHERE period_key=%s", (period_key,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Not found'}), 404

            curr_status = rec['status']

            if role == 'Finance':
                if new_status == 'For Approval' and curr_status in ['Draft', 'Rejected']:
                    cur.execute("UPDATE tblpayroll SET status='For Approval', remarks=NULL WHERE period_key=%s", (period_key,))
                else:
                    return jsonify({'error': 'Invalid status transition for Finance'}), 400
            elif role in ['Administrator', 'Admin']:
                if new_status in ['Approved', 'Rejected'] and curr_status == 'For Approval':
                    if new_status == 'Approved':
                        cur.execute(
                            "UPDATE tblpayroll SET status=%s, remarks=%s, approved_by=%s, approved_at=NOW() WHERE period_key=%s",
                            (new_status, remarks, user_name, period_key)
                        )
                    else:
                        cur.execute(
                            "UPDATE tblpayroll SET status=%s, remarks=%s WHERE period_key=%s",
                            (new_status, remarks, period_key)
                        )
                else:
                    return jsonify({'error': 'Invalid status transition for Admin'}), 400
            else:
                return jsonify({'error': 'Unauthorized'}), 403

            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# HOLIDAYS API
# ══════════════════════════════════════════════════════════════════════════════

@payroll_bp.route('/holidays', methods=['GET'])
def get_holidays():
    year = request.args.get('year')
    try:
        with db_cursor() as (conn, cur):
            if year:
                cur.execute("SELECT id, holiday_date, holiday_name, holiday_type FROM tblholidays WHERE YEAR(holiday_date)=%s ORDER BY holiday_date", (year,))
            else:
                cur.execute("SELECT id, holiday_date, holiday_name, holiday_type FROM tblholidays ORDER BY holiday_date DESC")
            rows = cur.fetchall()
            return jsonify([{
                'id':   r['id'],
                'date': r['holiday_date'].strftime('%Y-%m-%d'),
                'name': r['holiday_name'],
                'type': r['holiday_type'],
            } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/holidays', methods=['POST'])
def add_holiday():
    from flask import session
    if session.get('user', {}).get('role') not in ['Admin', 'Finance', 'HR']:
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    hdate = data.get('date')
    hname = data.get('name', '').strip()
    htype = data.get('type', 'Regular')
    if not hdate or not hname:
        return jsonify({'error': 'Date and name are required.'}), 400
    if htype not in ['Regular', 'Special']:
        return jsonify({'error': 'Type must be Regular or Special.'}), 400
    try:
        with db_cursor() as (conn, cur):
            cur.execute("INSERT INTO tblholidays (holiday_date, holiday_name, holiday_type) VALUES (%s, %s, %s)", (hdate, hname, htype))
            conn.commit()
            return jsonify({'success': True, 'id': cur.lastrowid})
    except Exception as e:
        if '1062' in str(e) or 'Duplicate' in str(e):
            return jsonify({'error': 'A holiday on this date already exists.'}), 400
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/holidays/<int:hid>', methods=['DELETE'])
def delete_holiday(hid):
    from flask import session
    if session.get('user', {}).get('role') not in ['Admin']:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM tblholidays WHERE id=%s", (hid,))
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# LEAVES API
# ══════════════════════════════════════════════════════════════════════════════

@payroll_bp.route('/leaves', methods=['GET'])
def get_leaves():
    from flask import session
    user = session.get('user', {})
    role = user.get('role')
    try:
        with db_cursor() as (conn, cur):
            if role == 'Employee':
                emp_id = user.get('employee_id')
                cur.execute("""
                    SELECT l.id, l.employee_id, CONCAT(e.first_name,' ',e.last_name) as emp_name,
                           l.leave_date, l.leave_type, l.status, l.reason, l.reviewed_by, l.reviewed_at, l.filed_at
                    FROM tblleaves l JOIN tblemployee e ON l.employee_id=e.employee_id
                    WHERE l.employee_id=%s ORDER BY l.leave_date DESC
                """, (emp_id,))
            else:
                cur.execute("""
                    SELECT l.id, l.employee_id, CONCAT(e.first_name,' ',e.last_name) as emp_name,
                           l.leave_date, l.leave_type, l.status, l.reason, l.reviewed_by, l.reviewed_at, l.filed_at
                    FROM tblleaves l JOIN tblemployee e ON l.employee_id=e.employee_id
                    ORDER BY l.filed_at DESC
                """)
            rows = cur.fetchall()
            return jsonify([{
                'id':          r['id'],
                'employee_id': r['employee_id'],
                'emp_name':    r['emp_name'],
                'leave_date':  r['leave_date'].strftime('%Y-%m-%d'),
                'leave_type':  r['leave_type'],
                'status':      r['status'],
                'reason':      r['reason'],
                'reviewed_by': r['reviewed_by'],
                'reviewed_at': r['reviewed_at'].strftime('%b %d, %Y') if r['reviewed_at'] else None,
                'filed_at':    r['filed_at'].strftime('%b %d, %Y') if r['filed_at'] else None,
            } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leaves', methods=['POST'])
def file_leave():
    from flask import session
    user = session.get('user', {})
    role = user.get('role')
    data = request.json
    emp_id     = user.get('employee_id') if role == 'Employee' else data.get('employee_id')
    leave_date = data.get('leave_date')
    leave_type = data.get('leave_type', 'VL')
    reason     = data.get('reason', '').strip()

    if not emp_id or not leave_date:
        return jsonify({'error': 'employee_id and leave_date are required.'}), 400
    if leave_type not in ['SL', 'VL']:
        return jsonify({'error': 'leave_type must be SL or VL.'}), 400
    try:
        with db_cursor() as (conn, cur):
            cur.execute("INSERT INTO tblleaves (employee_id, leave_date, leave_type, reason) VALUES (%s, %s, %s, %s)",
                        (emp_id, leave_date, leave_type, reason))
            conn.commit()
            return jsonify({'success': True, 'id': cur.lastrowid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leaves/<int:lid>/status', methods=['PUT'])
def review_leave(lid):
    from flask import session
    user = session.get('user', {})
    role = user.get('role')
    if role not in ['Admin', 'HR', 'Finance']:
        return jsonify({'error': 'Unauthorized'}), 403
    data       = request.json
    new_status = data.get('status')
    if new_status not in ['Approved', 'Rejected']:
        return jsonify({'error': 'Status must be Approved or Rejected.'}), 400
    try:
        with db_cursor() as (conn, cur):
            cur.execute("UPDATE tblleaves SET status=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
                        (new_status, user.get('name', 'HR'), lid))
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# LEAVE BALANCES & AUDIT TRANSACTIONS API
# ══════════════════════════════════════════════════════════════════════════════

@payroll_bp.route('/leave_balances', methods=['GET'])
def get_leave_balances():
    from flask import session
    from services.policy_engine import LeavePolicyService
    user = session.get('user', {})
    role = user.get('role')

    try:
        with db_cursor() as (conn, cur):
            if role == 'Employee':
                emp_id = user.get('employee_id')
                cur.execute("""
                    SELECT b.*, e.first_name, e.last_name
                    FROM tblleave_balances b
                    JOIN tblemployee e ON b.employee_id = e.employee_id
                    WHERE b.employee_id = %s
                """, (emp_id,))
            else:
                cur.execute("""
                    SELECT b.*, e.first_name, e.last_name
                    FROM tblleave_balances b
                    JOIN tblemployee e ON b.employee_id = e.employee_id
                    ORDER BY e.last_name, e.first_name
                """)
            rows = cur.fetchall()

            res = []
            for r in rows:
                vl = int(r['vl_minutes'])
                sl = int(r['sl_minutes'])
                res.append({
                    'employee_id':  r['employee_id'],
                    'emp_name':     f"{r['first_name']} {r['last_name']}",
                    'vl_minutes':   vl,
                    'sl_minutes':   sl,
                    'vl_formatted': LeavePolicyService.format_minutes_to_dhm(vl),
                    'sl_formatted': LeavePolicyService.format_minutes_to_dhm(sl),
                    'updated_at':   r['updated_at'].strftime('%Y-%m-%d %H:%M:%S') if r['updated_at'] else None
                })
            return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leave_balances/adjust', methods=['POST'])
def adjust_leave_balance():
    from flask import session
    from services.policy_engine import AuditService, LeavePolicyService
    user = session.get('user', {})
    if user.get('role') not in ['Admin', 'HR']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    emp_id     = data.get('employee_id')
    leave_type = data.get('leave_type', 'VL').upper()
    adj_mode   = data.get('mode', 'ADD')
    try:
        minutes = int(data.get('minutes', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid minutes value'}), 400
    reason     = data.get('reason', 'Manual Balance Adjustment').strip()

    if not emp_id or minutes < 0:
        return jsonify({'error': 'employee_id and non-negative minutes are required.'}), 400

    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT vl_minutes, sl_minutes FROM tblleave_balances WHERE employee_id=%s", (emp_id,))
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes) VALUES (%s, 4800, 4800)", (emp_id,))
                current_vl, current_sl = 4800, 4800
            else:
                current_vl, current_sl = row['vl_minutes'], row['sl_minutes']

            target_val = current_vl if leave_type == 'VL' else current_sl

            if adj_mode == 'ADD':
                new_val = target_val + minutes
                tx_type = 'ACCRUAL'
                tx_mins = minutes
            elif adj_mode == 'DEDUCT':
                new_val = max(0, target_val - minutes)
                tx_type = 'DEDUCTION'
                tx_mins = minutes
            else: # SET
                new_val = minutes
                diff = minutes - target_val
                tx_type = 'ADJUSTMENT'
                tx_mins = abs(diff)

            if leave_type == 'VL':
                cur.execute("UPDATE tblleave_balances SET vl_minutes=%s WHERE employee_id=%s", (new_val, emp_id))
            else:
                cur.execute("UPDATE tblleave_balances SET sl_minutes=%s WHERE employee_id=%s", (new_val, emp_id))

            today_str = date.today().strftime('%Y-%m-%d')
            cur.execute("""
                INSERT INTO tblleave_transactions
                (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                VALUES (%s, %s, %s, %s, %s, 'MANUAL_ADJUSTMENT', 'HR_ADJ', %s, %s)
            """, (emp_id, today_str, leave_type, tx_mins, tx_type, reason, user.get('name', 'HR')))

            AuditService.log_action(
                cur, action='LEAVE_BALANCE_ADJUSTED', employee_id=emp_id, user_name=user.get('name', 'HR'),
                target_table='tblleave_balances', target_id=emp_id,
                old_value=f"{leave_type}: {target_val} mins", new_value=f"{leave_type}: {new_val} mins", reason=reason
            )

        return jsonify({'success': True, 'new_balance': new_val, 'formatted': LeavePolicyService.format_minutes_to_dhm(new_val)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leave_transactions', methods=['GET'])
def get_leave_transactions():
    from flask import session
    user = session.get('user', {})
    role = user.get('role')
    emp_id_param = request.args.get('employee_id', '').strip()

    try:
        with db_cursor() as (conn, cur):
            if role == 'Employee':
                emp_id = user.get('employee_id')
                cur.execute("""
                    SELECT t.*, e.first_name, e.last_name
                    FROM tblleave_transactions t
                    JOIN tblemployee e ON t.employee_id = e.employee_id
                    WHERE t.employee_id = %s
                    ORDER BY t.created_at DESC
                """, (emp_id,))
            elif emp_id_param:
                cur.execute("""
                    SELECT t.*, e.first_name, e.last_name
                    FROM tblleave_transactions t
                    JOIN tblemployee e ON t.employee_id = e.employee_id
                    WHERE t.employee_id = %s
                    ORDER BY t.created_at DESC
                """, (emp_id_param,))
            else:
                cur.execute("""
                    SELECT t.*, e.first_name, e.last_name
                    FROM tblleave_transactions t
                    JOIN tblemployee e ON t.employee_id = e.employee_id
                    ORDER BY t.created_at DESC
                    LIMIT 200
                """)
            rows = cur.fetchall()
            return jsonify([{
                'id':               r['id'],
                'employee_id':      r['employee_id'],
                'emp_name':         f"{r['first_name']} {r['last_name']}",
                'date':             r['date'].strftime('%Y-%m-%d'),
                'leave_type':       r['leave_type'],
                'minutes':          r['minutes'],
                'transaction_type': r['transaction_type'],
                'source':           r['source'],
                'reference_id':     r['reference_id'],
                'remarks':          r['remarks'],
                'created_by':       r['created_by'],
                'created_at':       r['created_at'].strftime('%b %d, %Y %I:%M %p') if r['created_at'] else None
            } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POLICY CONFIGS & HABITUAL TARDINESS API
# ══════════════════════════════════════════════════════════════════════════════

@payroll_bp.route('/policy_configs', methods=['GET'])
def get_policy_configs():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT config_key, config_value, description, updated_at FROM tblpolicy_config ORDER BY config_key")
            rows = cur.fetchall()
            return jsonify([{
                'key':         r['config_key'],
                'value':       r['config_value'],
                'description': r['description'],
                'updated_at':  r['updated_at'].strftime('%Y-%m-%d %H:%M:%S') if r['updated_at'] else None
            } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/policy_configs', methods=['POST'])
def update_policy_configs():
    from flask import session
    user = session.get('user', {})
    if user.get('role') not in ['Admin', 'HR']:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json
    if not isinstance(data, list):
        return jsonify({'error': 'Expected list of config items'}), 400

    try:
        with db_cursor() as (conn, cur):
            for item in data:
                k = item.get('key')
                v = item.get('value')
                if k and v is not None:
                    cur.execute(
                        "INSERT INTO tblpolicy_config (config_key, config_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE config_value=%s",
                        (k, str(v), str(v))
                    )
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/habitual_tardiness', methods=['GET'])
def get_habitual_tardiness():
    from flask import session
    from services.policy_engine import HabitualTardinessService
    user = session.get('user', {})
    if user.get('role') not in ['Admin', 'HR', 'Finance']:
        return jsonify({'error': 'Unauthorized'}), 403

    today = date.today()
    target_year  = int(request.args.get('year', today.year))
    target_month = int(request.args.get('month', today.month))

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT employee_id, first_name, last_name, designation, employee_type FROM tblemployee ORDER BY last_name, first_name")
            employees = cur.fetchall()

            reports = []
            for emp in employees:
                rep = HabitualTardinessService.check_habitual_tardiness(cur, emp['employee_id'], target_year, target_month)
                rep['emp_name']     = f"{emp['first_name']} {emp['last_name']}"
                rep['designation']  = emp['designation']
                rep['employee_type'] = emp.get('employee_type', 'NON_TEACHING')
                reports.append(rep)

            flagged_count = len([r for r in reports if r['is_flagged']])
            return jsonify({
                'year': target_year,
                'month': target_month,
                'month_name': calendar.month_name[target_month],
                'flagged_count': flagged_count,
                'reports': reports
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

