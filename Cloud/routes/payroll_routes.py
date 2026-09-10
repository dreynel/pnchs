from flask import Blueprint, jsonify, request, session, current_app
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
            
            AuditService.log_action(cur, 'PAYROLL_CREATED', user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblpayroll', new_value=period_key)

            # Load holidays, employees, global payheads, and statutory configs
            holidays = get_holidays_in_period(cur, start_date, end_date)
            holiday_dates = set(holidays.keys())

            cur.execute("SELECT * FROM tblglobal_payheads")
            global_payheads = cur.fetchall()

            configs = _get_statutory_configs(cur)

            cur.execute("SELECT employee_id, first_name, last_name, designation, employee_type FROM tblemployee WHERE LOWER(COALESCE(employment_status, 'active')) = 'active'")
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

                # ── Approved leaves & absence evaluation cutoff (only up to yesterday) ───────────────
                approved_leave_dates = get_approved_leave_dates(cur, emp_id, start_date, end_date)
                yesterday = date.today() - timedelta(days=1)
                eval_end_date = min(end_date, yesterday)

                if eval_end_date >= start_date:
                    eval_work_days = count_work_days_in_period(start_date, eval_end_date)
                    eval_logged = {d for d in logged_dates if d <= eval_end_date}
                    eval_leaves = len([d for d in approved_leave_dates if d.weekday() < 5 and d <= eval_end_date])
                    effective_present = len(eval_logged) + eval_leaves
                    absent_days = max(0, eval_work_days - effective_present)
                else:
                    absent_days = 0

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


# ── GET /api/payroll/process & /api/payroll/report ──────────────────────────
@payroll_bp.route('/report', methods=['GET'])
@payroll_bp.route('/process', methods=['GET'])
def process_payroll():
    if request.path.endswith('/process') and session.get('user', {}).get('role') == 'Admin':
        return jsonify({'error': 'Unauthorized: Admin does not have access to Payroll Processing'}), 403

    mode = request.args.get('date_mode', '').strip().lower()
    year = request.args.get('year', '').strip()
    month = request.args.get('month', '').strip()
    half = request.args.get('half', '').strip()
    period_key = request.args.get('period_key', '').strip()

    today = date.today()

    # Determine filter mode if not explicitly provided
    if not mode:
        if period_key or (year and month and half):
            mode = 'run'
        elif request.args.get('date'):
            mode = 'daily'
        elif request.args.get('date_from') or request.args.get('date_to'):
            mode = 'range'
        elif year and month and not half:
            mode = 'month'
        elif year and not month and not half:
            mode = 'year'
        else:
            mode = 'run' if (year and month and half) else 'month'

    try:
        with db_cursor() as (conn, cur):
            # ── 1. Single Run Mode ───────────────────────────────────────────
            if mode == 'run':
                if not period_key:
                    if not (year and month and half):
                        return jsonify({'error': 'year, month, and half or period_key are required for single run'}), 400
                    period_key = f"{int(year)}-{int(month)}-{int(half)}"

                cur.execute("""
                    SELECT d.*, e.first_name, e.last_name, e.designation,
                           COALESCE(b.vl_minutes, 4800) AS vl_minutes,
                           COALESCE(b.sl_minutes, 4800) AS sl_minutes
                    FROM tblpayroll_details d
                    JOIN tblemployee e ON d.employee_id = e.employee_id
                    LEFT JOIN tblleave_balances b ON d.employee_id = b.employee_id
                    WHERE d.period_key = %s
                    ORDER BY e.last_name, e.first_name
                """, (period_key,))
                records = cur.fetchall()

                cur.execute("SELECT year, month, half, created_at, approved_by, approved_at FROM tblpayroll WHERE period_key=%s", (period_key,))
                hdr = cur.fetchone()
                created_at_str = hdr['created_at'].strftime('%b %d, %Y') if hdr and hdr.get('created_at') else '—'
                approved_by    = hdr['approved_by'] if hdr else None
                approved_at    = hdr['approved_at'].strftime('%b %d, %Y %I:%M %p') if hdr and hdr.get('approved_at') else None

                p_parts = period_key.split('-')
                p_year = hdr['year'] if hdr else (p_parts[0] if len(p_parts)>0 else '')
                p_month = hdr['month'] if hdr else (int(p_parts[1]) if len(p_parts)>1 else 1)
                p_half = hdr['half'] if hdr else (int(p_parts[2]) if len(p_parts)>2 else 1)
                m_name = calendar.month_name[int(p_month)] if str(p_month).isdigit() and 1 <= int(p_month) <= 12 else ''
                period_label = f"{m_name} {p_year} - {'1st' if int(p_half)==1 else '2nd'} Half"

                results = []
                gGross = gDeduct = gNet = 0.0
                for rec in records:
                    def f(k): return float(rec.get(k) or 0)
                    vl_m = int(rec.get('vl_minutes') or 4800)
                    sl_m = int(rec.get('sl_minutes') or 4800)
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
                        'vl_tardiness_minutes': rec.get('vl_tardiness_minutes', 0),
                        'vl_undertime_minutes': rec.get('vl_undertime_minutes', 0),
                        'lwop_tardiness_minutes': rec.get('lwop_tardiness_minutes', 0),
                        'lwop_undertime_minutes': rec.get('lwop_undertime_minutes', 0),
                        'tardiness_deduction': f('tardiness_deduction'),
                        'undertime_deduction': f('undertime_deduction'),
                        'vl_minutes':          vl_m,
                        'sl_minutes':          sl_m,
                        'vl_formatted':        LeavePolicyService.format_minutes_to_dhm(vl_m),
                        'sl_formatted':        LeavePolicyService.format_minutes_to_dhm(sl_m),
                        'gsis_ee':             f('sss_ee'),
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
                    'period':      period_label,
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

            # ── 2. Multi-Run / Aggregation Modes (Month, Year, Range, Daily) ─
            where_clauses = []
            params = []
            period_label = ""

            if mode == 'daily':
                target = request.args.get('date') or today.strftime('%Y-%m-%d')
                if isinstance(target, str):
                    sp = [int(x) for x in target.split('-')]
                    d_obj = date(sp[0], sp[1], sp[2])
                else:
                    d_obj = target
                y_i, m_i, d_i = d_obj.year, d_obj.month, d_obj.day
                h_i = 1 if d_i <= 15 else 2
                where_clauses.append("p.year = %s AND p.month = %s AND p.half = %s")
                params.extend([y_i, m_i, h_i])
                period_label = f"Daily ({d_obj.strftime('%b %d, %Y')} - {calendar.month_name[m_i]} {'1st' if h_i==1 else '2nd'} Half)"

            elif mode == 'month':
                y_i = int(year or today.year)
                m_i = int(month or today.month)
                where_clauses.append("p.year = %s AND p.month = %s")
                params.extend([y_i, m_i])
                period_label = f"{calendar.month_name[m_i]} {y_i}"

            elif mode == 'year':
                y_i = int(year or today.year)
                where_clauses.append("p.year = %s")
                params.append(y_i)
                period_label = f"Year {y_i}"

            elif mode == 'range':
                s_str = request.args.get('date_from') or today.strftime('%Y-%m-%d')
                e_str = request.args.get('date_to') or s_str
                sp = [int(x) for x in s_str.split('-')]
                ep = [int(x) for x in e_str.split('-')]
                s_date = date(sp[0], sp[1], sp[2])
                e_date = date(ep[0], ep[1], ep[2])
                s_int = s_date.year * 10000 + s_date.month * 100 + s_date.day
                e_int = e_date.year * 10000 + e_date.month * 100 + e_date.day

                where_clauses.append("""
                    (p.year * 10000 + p.month * 100 + IF(p.half = 1, 1, 16)) <= %s
                    AND
                    (p.year * 10000 + p.month * 100 + IF(p.half = 1, 15, 31)) >= %s
                """)
                params.extend([e_int, s_int])
                period_label = f"{s_date.strftime('%b %d, %Y')} – {e_date.strftime('%b %d, %Y')}"

            # Query matching payroll runs
            where_sql = " AND ".join(where_clauses)
            cur.execute(f"""
                SELECT period_key, year, month, half, status, approved_by, approved_at, created_at
                FROM tblpayroll p
                WHERE {where_sql}
                ORDER BY year ASC, month ASC, half ASC
            """, tuple(params))
            hdrs = cur.fetchall()

            # Prefer approved / posted runs, but fallback to any found if none approved yet
            approved_hdrs = [h for h in hdrs if h['status'] in ['Approved', 'Posted']]
            active_hdrs = approved_hdrs if approved_hdrs else hdrs

            if not active_hdrs:
                return jsonify({
                    'period':      period_label,
                    'created_at':  '—',
                    'approved_by': None,
                    'approved_at': None,
                    'employees':   [],
                    'summary': {
                        'total_employees':    0,
                        'grand_total_gross':  0.0,
                        'grand_total_deduct': 0.0,
                        'grand_total_net':    0.0,
                        'runs_count':         0
                    }
                })

            # If exactly 1 run was found, delegate to single run display for full detail
            if len(active_hdrs) == 1:
                single_hdr = active_hdrs[0]
                return jsonify(json.loads(process_payroll_single_run(cur, single_hdr['period_key'], period_label)))

            # Multiple runs: Aggregate across all matched periods
            keys = [h['period_key'] for h in active_hdrs]
            in_clause = ','.join(['%s'] * len(keys))
            cur.execute(f"""
                SELECT 
                    d.employee_id,
                    e.first_name,
                    e.last_name,
                    e.designation,
                    MAX(d.basic_salary) AS basic_salary,
                    SUM(COALESCE(d.half_basic, 0)) AS half_basic,
                    SUM(COALESCE(d.other_earnings, 0)) AS other_earnings,
                    SUM(COALESCE(d.holiday_pay, 0)) AS holiday_pay,
                    SUM(COALESCE(d.other_deductions, 0)) AS other_deductions,
                    AVG(COALESCE(d.daily_rate, 0)) AS daily_rate,
                    SUM(COALESCE(d.absent_days, 0)) AS absent_days,
                    SUM(COALESCE(d.absent_deduction, 0)) AS absent_deduction,
                    SUM(COALESCE(d.late_minutes, 0)) AS late_minutes,
                    SUM(COALESCE(d.undertime_minutes, 0)) AS undertime_minutes,
                    SUM(COALESCE(d.tardiness_deduction, 0)) AS tardiness_deduction,
                    SUM(COALESCE(d.undertime_deduction, 0)) AS undertime_deduction,
                    SUM(COALESCE(d.sss_ee, 0)) AS sss_ee,
                    SUM(COALESCE(d.philhealth_ee, 0)) AS philhealth_ee,
                    SUM(COALESCE(d.pagibig_ee, 0)) AS pagibig_ee,
                    SUM(COALESCE(d.withholding_tax, 0)) AS withholding_tax,
                    SUM(COALESCE(d.total_gross, 0)) AS total_gross,
                    SUM(COALESCE(d.total_deduct, 0)) AS total_deduct,
                    SUM(COALESCE(d.net_pay, 0)) AS net_pay,
                    COUNT(DISTINCT d.period_key) AS runs_count
                FROM tblpayroll_details d
                JOIN tblemployee e ON d.employee_id = e.employee_id
                WHERE d.period_key IN ({in_clause})
                GROUP BY d.employee_id, e.first_name, e.last_name, e.designation
                ORDER BY e.last_name, e.first_name
            """, tuple(keys))
            records = cur.fetchall()

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
                    'vl_tardiness_minutes': rec.get('vl_tardiness_minutes', 0),
                    'vl_undertime_minutes': rec.get('vl_undertime_minutes', 0),
                    'lwop_tardiness_minutes': rec.get('lwop_tardiness_minutes', 0),
                    'lwop_undertime_minutes': rec.get('lwop_undertime_minutes', 0),
                    'tardiness_deduction': f('tardiness_deduction'),
                    'undertime_deduction': f('undertime_deduction'),
                    'gsis_ee':             f('sss_ee'),
                    'philhealth_ee':      f('philhealth_ee'),
                    'pagibig_ee':         f('pagibig_ee'),
                    'withholding_tax':    f('withholding_tax'),
                    'statutory_json':      None,
                    'payheads_json':       None,
                    'total_gross':        f('total_gross'),
                    'total_deduct':       f('total_deduct'),
                    'net_pay':            f('net_pay'),
                    'is_negative':        bool(f('net_pay') < 0),
                    'below_net_floor':    bool(f('net_pay') < 2500.0 and f('basic_salary') > 0),
                    'dtr_filed':          True,
                    'runs_count':         rec.get('runs_count', len(active_hdrs)),
                })
                gGross  += f('total_gross')
                gDeduct += f('total_deduct')
                gNet    += f('net_pay')

            approvers = list({h['approved_by'] for h in active_hdrs if h.get('approved_by')})
            approver_str = ", ".join(approvers) if approvers else "Multiple Runs"

            return jsonify({
                'period':      f"{period_label} ({len(active_hdrs)} Runs Aggregated)",
                'created_at':  f"{len(active_hdrs)} runs",
                'approved_by': approver_str,
                'approved_at': active_hdrs[-1]['approved_at'].strftime('%b %d, %Y') if active_hdrs[-1].get('approved_at') else None,
                'employees':   results,
                'summary': {
                    'total_employees':    len(results),
                    'grand_total_gross':  round(gGross,  2),
                    'grand_total_deduct': round(gDeduct, 2),
                    'grand_total_net':    round(gNet,    2),
                    'runs_count':         len(active_hdrs)
                }
            })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


def process_payroll_single_run(cur, period_key, label_override=None):
    """Helper to format a single run payload as JSON string."""
    cur.execute("""
        SELECT d.*, e.first_name, e.last_name, e.designation,
               COALESCE(b.vl_minutes, 4800) AS vl_minutes,
               COALESCE(b.sl_minutes, 4800) AS sl_minutes
        FROM tblpayroll_details d
        JOIN tblemployee e ON d.employee_id = e.employee_id
        LEFT JOIN tblleave_balances b ON d.employee_id = b.employee_id
        WHERE d.period_key = %s
        ORDER BY e.last_name, e.first_name
    """, (period_key,))
    records = cur.fetchall()

    cur.execute("SELECT year, month, half, created_at, approved_by, approved_at FROM tblpayroll WHERE period_key=%s", (period_key,))
    hdr = cur.fetchone()
    created_at_str = hdr['created_at'].strftime('%b %d, %Y') if hdr and hdr.get('created_at') else '—'
    approved_by    = hdr['approved_by'] if hdr else None
    approved_at    = hdr['approved_at'].strftime('%b %d, %Y %I:%M %p') if hdr and hdr.get('approved_at') else None

    p_parts = period_key.split('-')
    p_year = hdr['year'] if hdr else (p_parts[0] if len(p_parts)>0 else '')
    p_month = hdr['month'] if hdr else (int(p_parts[1]) if len(p_parts)>1 else 1)
    p_half = hdr['half'] if hdr else (int(p_parts[2]) if len(p_parts)>2 else 1)
    m_name = calendar.month_name[int(p_month)] if str(p_month).isdigit() and 1 <= int(p_month) <= 12 else ''
    period_label = label_override or f"{m_name} {p_year} - {'1st' if int(p_half)==1 else '2nd'} Half"

    results = []
    gGross = gDeduct = gNet = 0.0
    for rec in records:
        def f(k): return float(rec.get(k) or 0)
        vl_m = int(rec.get('vl_minutes') or 4800)
        sl_m = int(rec.get('sl_minutes') or 4800)
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
            'vl_tardiness_minutes': rec.get('vl_tardiness_minutes', 0),
            'vl_undertime_minutes': rec.get('vl_undertime_minutes', 0),
            'lwop_tardiness_minutes': rec.get('lwop_tardiness_minutes', 0),
            'lwop_undertime_minutes': rec.get('lwop_undertime_minutes', 0),
            'tardiness_deduction': f('tardiness_deduction'),
            'undertime_deduction': f('undertime_deduction'),
            'vl_minutes':          vl_m,
            'sl_minutes':          sl_m,
            'vl_formatted':        LeavePolicyService.format_minutes_to_dhm(vl_m),
            'sl_formatted':        LeavePolicyService.format_minutes_to_dhm(sl_m),
            'gsis_ee':             f('sss_ee'),
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
            'runs_count':         1
        })
        gGross  += f('total_gross')
        gDeduct += f('total_deduct')
        gNet    += f('net_pay')

    return json.dumps({
        'period':      period_label,
        'created_at':  created_at_str,
        'approved_by': approved_by,
        'approved_at': approved_at,
        'employees':   results,
        'summary': {
            'total_employees':    len(results),
            'grand_total_gross':  round(gGross,  2),
            'grand_total_deduct': round(gDeduct, 2),
            'grand_total_net':    round(gNet,    2),
            'runs_count':         1
        }
    })


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
            cur.execute("SELECT status, is_released, released_at, created_at FROM tblpayroll WHERE period_key=%s", (period_key,))
            pr = cur.fetchone()
            if not pr:
                return jsonify({'error': 'Payslip for this period has not been generated.'}), 404
            if not pr.get('is_released') and not pr.get('released_at'):
                return jsonify({'error': 'Payslip for this period has not been released yet. Payslips are accessible only after releasing by Finance.'}), 403

            cur.execute("""
                SELECT d.*, e.first_name, e.last_name, e.designation,
                       COALESCE(b.vl_minutes, 4800) AS vl_minutes,
                       COALESCE(b.sl_minutes, 4800) AS sl_minutes
                FROM tblpayroll_details d
                JOIN tblemployee e ON d.employee_id = e.employee_id
                LEFT JOIN tblleave_balances b ON d.employee_id = b.employee_id
                WHERE d.period_key = %s AND d.employee_id = %s
            """, (period_key, emp_id))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Employee payslip record not found.'}), 404

            def f(k): return float(rec.get(k) or 0)
            vl_m = int(rec.get('vl_minutes') or 4800)
            sl_m = int(rec.get('sl_minutes') or 4800)
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
                'undertime_minutes':  rec.get('undertime_minutes', 0),
                'vl_tardiness_minutes': rec.get('vl_tardiness_minutes', 0),
                'vl_undertime_minutes': rec.get('vl_undertime_minutes', 0),
                'lwop_tardiness_minutes': rec.get('lwop_tardiness_minutes', 0),
                'lwop_undertime_minutes': rec.get('lwop_undertime_minutes', 0),
                'tardiness_deduction':f('tardiness_deduction'),
                'undertime_deduction':f('undertime_deduction'),
                'vl_minutes':          vl_m,
                'sl_minutes':          sl_m,
                'vl_formatted':        LeavePolicyService.format_minutes_to_dhm(vl_m),
                'sl_formatted':        LeavePolicyService.format_minutes_to_dhm(sl_m),
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
            cur.execute("SELECT period_key, year, month, half, status, is_released, remarks, approved_by, approved_at, released_by, released_at, created_at FROM tblpayroll ORDER BY year DESC, month DESC, half DESC")
            records = cur.fetchall()
            return jsonify([{
                'key':         r['period_key'],
                'period':      f"{calendar.month_name[r['month']]} {r['year']} - {'1st' if r['half']==1 else '2nd'} Half",
                'year':        r['year'],
                'month':       r['month'],
                'half':        r['half'],
                'status':      r['status'],
                'is_released': bool(r.get('is_released') or r.get('released_at')),
                'remarks':     r['remarks'],
                'approved_by': r['approved_by'],
                'approved_at': r['approved_at'].strftime('%b %d, %Y %I:%M %p') if r['approved_at'] else None,
                'released_by': r.get('released_by'),
                'released_at': r['released_at'].strftime('%b %d, %Y %I:%M %p') if r.get('released_at') else None,
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
            cur.execute("DELETE FROM tblapprovals WHERE DocType='Payroll' AND DocNumber=%s", (period_key,))
            AuditService.log_action(cur, 'PAYROLL_DELETED', user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblpayroll', old_value=period_key)
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── PUT /api/payroll/runs/<period_key>/details/<employee_id> ─────────────────
@payroll_bp.route('/runs/<period_key>/details/<employee_id>', methods=['PUT'])
def update_payroll_detail(period_key, employee_id):
    return jsonify({'error': 'Manual payroll adjustments are currently disabled.'}), 403


# ── POST /api/payroll/runs/<period_key>/status ───────────────────────────────
@payroll_bp.route('/runs/<period_key>/status', methods=['POST'])
def update_status(period_key):
    from flask import session
    role = session.get('user', {}).get('role')
    user_name = session.get('user', {}).get('name', 'Unknown')
    data = request.json or {}
    new_status = data.get('status')
    remarks    = data.get('remarks', None)

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM tblpayroll WHERE period_key=%s", (period_key,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Not found'}), 404

            curr_status = rec['status']

            if role in ['Finance', 'Finance Officer']:
                if new_status == 'For Approval' and curr_status in ['Draft', 'Rejected']:
                    cur.execute("UPDATE tblpayroll SET status='For Approval', remarks=NULL WHERE period_key=%s", (period_key,))
                    cur.execute("""
                        INSERT INTO tblapprovals (DocType, DocNumber, ApprovalStatus, ApproverRole, RequesterID, Title)
                        VALUES ('Payroll', %s, 'Pending', 'Principal', %s, %s)
                        ON DUPLICATE KEY UPDATE ApprovalStatus='Pending', RequesterID=%s
                    """, (period_key, user_name, f"Payroll Run - {period_key}", user_name))
                    AuditService.log_action(cur, 'PAYROLL_SUBMITTED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
                elif new_status == 'Released' and curr_status == 'Approved':
                    cur.execute("UPDATE tblpayroll SET is_released=1, released_by=%s, released_at=NOW() WHERE period_key=%s", (user_name, period_key))
                    AuditService.log_action(cur, 'PAYROLL_RELEASED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
                else:
                    return jsonify({'error': 'Invalid status transition for Finance'}), 400
            elif role in ['Administrator', 'Admin', 'Principal']:
                if new_status == 'Released' and curr_status == 'Approved':
                    cur.execute("UPDATE tblpayroll SET is_released=1, released_by=%s, released_at=NOW() WHERE period_key=%s", (user_name, period_key))
                    AuditService.log_action(cur, 'PAYROLL_RELEASED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
                elif new_status in ['Approved', 'Rejected'] and curr_status == 'For Approval':
                    if new_status == 'Approved':
                        cur.execute(
                            "UPDATE tblpayroll SET status=%s, remarks=%s, approved_by=%s, approved_at=NOW() WHERE period_key=%s",
                            (new_status, remarks, user_name, period_key)
                        )
                        cur.execute("""
                            UPDATE tblapprovals
                            SET ApprovalStatus='Approved', ApproverID=%s, Remarks=%s, ApprovedAt=NOW()
                            WHERE DocType='Payroll' AND DocNumber=%s
                        """, (user_name, remarks, period_key))
                        AuditService.log_action(cur, 'PAYROLL_APPROVED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
                    else:
                        cur.execute(
                            "UPDATE tblpayroll SET status=%s, remarks=%s WHERE period_key=%s",
                            (new_status, remarks, period_key)
                        )
                        cur.execute("""
                            UPDATE tblapprovals
                            SET ApprovalStatus='Rejected', ApproverID=%s, Remarks=%s, ApprovedAt=NOW()
                            WHERE DocType='Payroll' AND DocNumber=%s
                        """, (user_name, remarks, period_key))
                        AuditService.log_action(cur, 'PAYROLL_REJECTED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
                else:
                    return jsonify({'error': 'Invalid status transition for Approver'}), 400
            else:
                return jsonify({'error': 'Unauthorized'}), 403

            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/payroll/releasing_list ──────────────────────────────────────────
@payroll_bp.route('/releasing_list', methods=['GET'])
def releasing_list():
    from flask import session
    role = session.get('user', {}).get('role')
    if role not in ['Finance', 'Finance Officer', 'Admin', 'Administrator', 'Principal', 'Auditor']:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT p.period_key, p.year, p.month, p.half, p.status, p.is_released, p.remarks,
                       p.approved_by, p.approved_at, p.released_by, p.released_at, p.created_at,
                       COUNT(d.id) AS total_employees,
                       COALESCE(SUM(d.total_gross), 0) AS total_gross,
                       COALESCE(SUM(d.total_deduct), 0) AS total_deductions,
                       COALESCE(SUM(d.net_pay), 0) AS total_net_pay
                FROM tblpayroll p
                LEFT JOIN tblpayroll_details d ON p.period_key = d.period_key
                WHERE p.status = 'Approved'
                GROUP BY p.id, p.period_key, p.year, p.month, p.half, p.status, p.is_released, p.remarks,
                         p.approved_by, p.approved_at, p.released_by, p.released_at, p.created_at
                ORDER BY p.year DESC, p.month DESC, p.half DESC
            """)
            records = cur.fetchall()
            return jsonify([{
                'key':              r['period_key'],
                'period':           f"{calendar.month_name[r['month']]} {r['year']} - {'1st' if r['half']==1 else '2nd'} Half",
                'year':             r['year'],
                'month':            r['month'],
                'half':             r['half'],
                'status':           r['status'],
                'is_released':      bool(r.get('is_released') or r.get('released_at')),
                'remarks':          r['remarks'],
                'total_employees':  int(r['total_employees']),
                'total_gross':      float(r['total_gross']),
                'total_deductions': float(r['total_deductions']),
                'total_net_pay':    float(r['total_net_pay']),
                'approved_by':      r['approved_by'],
                'approved_at':      r['approved_at'].strftime('%b %d, %Y %I:%M %p') if r['approved_at'] else None,
                'released_by':      r.get('released_by'),
                'released_at':      r['released_at'].strftime('%b %d, %Y %I:%M %p') if r.get('released_at') else None,
                'created_at':       r['created_at'].strftime('%b %d, %Y') if r['created_at'] else None,
            } for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── POST /api/payroll/release ────────────────────────────────────────────────
@payroll_bp.route('/release', methods=['POST'])
def release_payroll():
    from flask import session
    role = session.get('user', {}).get('role')
    user_name = session.get('user', {}).get('name', 'Unknown')

    if role not in ['Finance', 'Finance Officer', 'Admin', 'Administrator', 'Principal']:
        return jsonify({'error': 'Unauthorized. Only Finance or Admin can release payroll.'}), 403

    data = request.json or {}
    period_key = data.get('period_key')
    if not period_key:
        return jsonify({'error': 'Missing period_key parameter'}), 400

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM tblpayroll WHERE period_key=%s", (period_key,))
            rec = cur.fetchone()
            if not rec:
                return jsonify({'error': 'Payroll run not found'}), 404

            if rec['status'] != 'Approved':
                return jsonify({'error': f"Cannot release payroll in '{rec['status']}' status. Payroll must be 'Approved' before releasing."}), 400

            cur.execute(
                "UPDATE tblpayroll SET is_released=1, released_by=%s, released_at=NOW() WHERE period_key=%s",
                (user_name, period_key)
            )
            AuditService.log_action(cur, 'PAYROLL_RELEASED', user_name=user_name, target_table='tblpayroll', new_value=period_key)
            conn.commit()

            return jsonify({'success': True, 'message': f'Payroll period {period_key} released successfully. Employee payslips are now available.'})
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

# ══════════════════════════════════════════════════════════════════════════════
# LEAVE MANAGEMENT API
# ══════════════════════════════════════════════════════════════════════════════

@payroll_bp.route('/leaves', methods=['GET'])
def get_leaves():
    from flask import session
    user = session.get('user', {})
    role = user.get('role')
    emp_id_param = request.args.get('employee_id', '').strip()
    status_param = request.args.get('status', '').strip()

    try:
        with db_cursor() as (conn, cur):
            query = """
                SELECT l.id, l.employee_id, CONCAT(e.first_name,' ',e.last_name) as emp_name,
                       l.leave_date, l.leave_type, l.status, l.reason, l.reviewed_by, l.reviewed_at, l.filed_at
                FROM tblleaves l JOIN tblemployee e ON l.employee_id=e.employee_id
            """
            params = []
            conditions = []

            if role not in ['HR', 'HR Officer']:
                emp_id = user.get('employee_id')
                conditions.append("l.employee_id = %s")
                params.append(emp_id)
            elif emp_id_param:
                conditions.append("l.employee_id = %s")
                params.append(emp_id_param)

            if status_param and status_param != 'all':
                conditions.append("l.status = %s")
                params.append(status_param)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY l.leave_date DESC, l.filed_at DESC"

            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            return jsonify([{
                'id':          r['id'],
                'employee_id': r['employee_id'],
                'emp_name':    r['emp_name'],
                'leave_date':  r['leave_date'].strftime('%Y-%m-%d'),
                'leave_type':  r['leave_type'],
                'status':      r['status'],
                'reason':      r['reason'] or '',
                'reviewed_by': r['reviewed_by'] or '',
                'reviewed_at': r['reviewed_at'].strftime('%b %d, %Y %I:%M %p') if r['reviewed_at'] else None,
                'filed_at':    r['filed_at'].strftime('%b %d, %Y %I:%M %p') if r['filed_at'] else None,
            } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leaves', methods=['POST'])
def file_leave():
    from flask import session, current_app
    from services.policy_engine import LeavePolicyService
    from werkzeug.utils import secure_filename
    import os

    user = session.get('user', {})
    role = user.get('role')

    if request.files or request.form:
        data = request.form
        file_obj = request.files.get('attachment')
    else:
        data = request.json or {}
        file_obj = None

    emp_id     = user.get('employee_id') if role not in ['HR', 'HR Officer'] else (data.get('employee_id') or user.get('employee_id'))
    leave_date = data.get('leave_date')
    leave_type = (data.get('leave_type') or 'VL').upper()
    reason     = data.get('reason', '').strip()

    if not emp_id:
        return jsonify({'error': 'Employee ID is required.'}), 400
    if not leave_date:
        return jsonify({'error': 'Leave date is required.'}), 400
    try:
        parsed_date = datetime.strptime(leave_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid leave date format. Use YYYY-MM-DD.'}), 400

    if role == 'Employee' and parsed_date <= date.today():
        return jsonify({'error': 'Leave applications must be filed at least 1 day in advance (starting tomorrow).'}), 400

    import json

    files_list = []
    if request.files:
        files_list = request.files.getlist('attachment') or request.files.getlist('attachments')

    saved_paths = []
    if files_list:
        target_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'leaves')
        os.makedirs(target_dir, exist_ok=True)
        allowed = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.doc', '.docx', '.txt']

        for idx, fobj in enumerate(files_list):
            if fobj and fobj.filename:
                fname = secure_filename(fobj.filename)
                if fname:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in allowed:
                        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                        saved_filename = f"{timestamp_str}_{idx}_{fname}"
                        full_path = os.path.join(target_dir, saved_filename)
                        fobj.save(full_path)
                        saved_paths.append(f"uploads/leaves/{saved_filename}")

    attachment_path = json.dumps(saved_paths) if saved_paths else None

    try:
        with db_cursor(commit=True) as (conn, cur):
            # Check for duplicate leave on the same date
            cur.execute("""
                SELECT id, status FROM tblleaves
                WHERE employee_id=%s AND leave_date=%s AND status IN ('Pending', 'Approved')
            """, (emp_id, leave_date))
            dup = cur.fetchone()
            if dup:
                return jsonify({'error': f"A {dup['status']} leave request already exists for this date."}), 400

            cur.execute("""
                INSERT INTO tblleaves (employee_id, leave_date, leave_type, reason, attachment, status)
                VALUES (%s, %s, %s, %s, %s, 'Pending')
            """, (emp_id, leave_date, leave_type, reason, attachment_path))
            leave_id = cur.lastrowid

            cur.execute("SELECT CONCAT(first_name, ' ', last_name) AS fullname FROM tblemployee WHERE employee_id=%s", (emp_id,))
            emp_rec = cur.fetchone()
            emp_name = emp_rec['fullname'] if emp_rec and emp_rec['fullname'] else emp_id

            cur.execute("""
                INSERT INTO tblapprovals (DocType, DocNumber, ApprovalStatus, ApproverRole, RequesterID, Title, Remarks)
                VALUES ('Leave', %s, 'Pending', 'HR', %s, %s, %s)
                ON DUPLICATE KEY UPDATE ApprovalStatus='Pending', RequesterID=%s, Title=%s, Remarks=%s
            """, (str(leave_id), emp_name, f"{leave_type} Leave - {emp_name} ({leave_date})", reason, emp_name, f"{leave_type} Leave - {emp_name} ({leave_date})", reason))

            return jsonify({
                'success': True,
                'id': leave_id,
                'message': f"Leave request for {leave_date} submitted successfully!"
            }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leaves/<int:lid>/status', methods=['PUT'])
def review_leave(lid):
    from flask import session
    from services.policy_engine import AuditService, LeavePolicyService
    user = session.get('user', {})
    role = user.get('role')

    if role not in ['Admin', 'Principal', 'HR', 'HR Officer', 'Finance', 'Finance Officer']:
        return jsonify({'error': 'Unauthorized'}), 403

    data       = request.json or {}
    new_status = data.get('status')
    if new_status not in ['Approved', 'Rejected']:
        return jsonify({'error': 'Status must be Approved or Rejected.'}), 400

    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT * FROM tblleaves WHERE id=%s", (lid,))
            leave = cur.fetchone()
            if not leave:
                return jsonify({'error': 'Leave record not found'}), 404

            old_status = leave['status']
            emp_id     = leave['employee_id']
            leave_type = leave['leave_type']
            leave_date_str = leave['leave_date'].strftime('%Y-%m-%d')
            reviewer_name = user.get('name', 'HR Admin')

            if old_status == new_status:
                return jsonify({'success': True, 'message': f'Leave is already {new_status}.'})

            # Handle transitions
            if new_status == 'Approved' and old_status != 'Approved':
                # Deduct 1 day (480 mins) from balance
                bal = LeavePolicyService.get_balance(cur, emp_id)
                target_key = 'vl_minutes' if leave_type == 'VL' else 'sl_minutes'
                curr_mins = bal[target_key]
                new_mins = max(0, curr_mins - 480)

                cur.execute(f"UPDATE tblleave_balances SET {target_key}=%s WHERE employee_id=%s", (new_mins, emp_id))

                # Log transaction
                cur.execute("""
                    INSERT INTO tblleave_transactions
                    (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                    VALUES (%s, %s, %s, 480, 'DEDUCTION', 'LEAVE_APPLICATION', %s, %s, %s)
                """, (emp_id, leave_date_str, leave_type, f"LEAVE-{lid}", f"Approved {leave_type} leave on {leave_date_str}", reviewer_name))

                AuditService.log_action(
                    cur, action='LEAVE_APPROVED', employee_id=emp_id, user_name=reviewer_name,
                    target_table='tblleaves', target_id=str(lid),
                    old_value=f"Status: {old_status}", new_value=f"Status: Approved (-480m {leave_type})",
                    reason=leave.get('reason') or 'Leave Approved'
                )

            elif old_status == 'Approved' and new_status in ['Rejected', 'Pending']:
                # Reverse deduction (+480 mins back)
                bal = LeavePolicyService.get_balance(cur, emp_id)
                target_key = 'vl_minutes' if leave_type == 'VL' else 'sl_minutes'
                curr_mins = bal[target_key]
                new_mins = curr_mins + 480

                cur.execute(f"UPDATE tblleave_balances SET {target_key}=%s WHERE employee_id=%s", (new_mins, emp_id))

                # Log reversal transaction
                cur.execute("""
                    INSERT INTO tblleave_transactions
                    (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                    VALUES (%s, %s, %s, 480, 'ACCRUAL', 'LEAVE_REVERSAL', %s, %s, %s)
                """, (emp_id, leave_date_str, leave_type, f"REV-LEAVE-{lid}", f"Reversed {leave_type} leave (marked {new_status})", reviewer_name))

                AuditService.log_action(
                    cur, action='LEAVE_REVERSED', employee_id=emp_id, user_name=reviewer_name,
                    target_table='tblleaves', target_id=str(lid),
                    old_value="Status: Approved", new_value=f"Status: {new_status} (+480m refunded)",
                    reason=f"Status changed to {new_status}"
                )

            cur.execute("""
                UPDATE tblleaves 
                SET status=%s, reviewed_by=%s, reviewed_at=NOW()
                WHERE id=%s
            """, (new_status, reviewer_name, lid))

            cur.execute("""
                UPDATE tblapprovals
                SET ApprovalStatus=%s, ApproverID=%s, ApprovedAt=NOW()
                WHERE DocType='Leave' AND DocNumber=%s
            """, (new_status, reviewer_name, str(lid)))

            return jsonify({'success': True, 'message': f'Leave request marked as {new_status}.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@payroll_bp.route('/leaves/<int:lid>', methods=['DELETE'])
def delete_leave(lid):
    from flask import session
    from services.policy_engine import AuditService, LeavePolicyService
    user = session.get('user', {})
    role = user.get('role')
    emp_id = user.get('employee_id')

    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT * FROM tblleaves WHERE id=%s", (lid,))
            leave = cur.fetchone()
            if not leave:
                return jsonify({'error': 'Leave record not found'}), 404

            # Permission check: Employee can cancel their OWN Pending leave
            if role == 'Employee':
                if leave['employee_id'] != emp_id:
                    return jsonify({'error': 'Unauthorized'}), 403
                if leave['status'] != 'Pending':
                    return jsonify({'error': 'Only pending leave requests can be cancelled.'}), 400
            elif role not in ['Admin', 'Principal', 'HR', 'HR Officer']:
                return jsonify({'error': 'Unauthorized'}), 403

            # If it was Approved, reverse deduction first
            if leave['status'] == 'Approved':
                target_key = 'vl_minutes' if leave['leave_type'] == 'VL' else 'sl_minutes'
                bal = LeavePolicyService.get_balance(cur, leave['employee_id'])
                new_mins = bal[target_key] + 480
                cur.execute(f"UPDATE tblleave_balances SET {target_key}=%s WHERE employee_id=%s", (new_mins, leave['employee_id']))

                cur.execute("""
                    INSERT INTO tblleave_transactions
                    (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                    VALUES (%s, %s, %s, 480, 'ACCRUAL', 'LEAVE_CANCEL', %s, 'Cancelled approved leave', %s)
                """, (leave['employee_id'], leave['leave_date'].strftime('%Y-%m-%d'), leave['leave_type'], f"CAN-LEAVE-{lid}", user.get('name', 'User')))

            cur.execute("DELETE FROM tblleaves WHERE id=%s", (lid,))
            cur.execute("DELETE FROM tblapprovals WHERE DocType='Leave' AND DocNumber=%s", (str(lid),))
            return jsonify({'success': True, 'message': 'Leave request cancelled successfully.'})
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
            if role not in ['HR', 'HR Officer']:
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
    if user.get('role') not in ['HR', 'HR Officer']:
        return jsonify({'error': 'Unauthorized: Only HR can adjust leave credit balances.'}), 403

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
            if role not in ['HR', 'HR Officer']:
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
            AuditService.log_action(cur, 'POLICY_UPDATED', user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblpolicy_config')
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

