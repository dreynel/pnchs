from flask import Blueprint, request, session, jsonify, Response
from db import db_cursor
import os, json, csv, io
from datetime import datetime, timedelta

audit_bp = Blueprint('audit', __name__)

def check_access():
    user = session.get('user', {})
    if user.get('role') not in ['Auditor', 'Admin', 'Principal']:
        return False
    return True

def _build_date_filter(args):
    where = []
    params = []
    mode = args.get('date_mode')
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
            mode = 'all'

    if mode == 'daily':
        d = args.get('date') or args.get('date_from')
        if d:
            where.append("DATE(created_at) = %s")
            params.append(d)
    elif mode == 'month':
        m = args.get('month')
        y = args.get('year')
        if y and str(y).isdigit():
            where.append("YEAR(created_at) = %s")
            params.append(int(y))
        if m and str(m).isdigit():
            where.append("MONTH(created_at) = %s")
            params.append(int(m))
    elif mode == 'year':
        y = args.get('year')
        if y and str(y).isdigit():
            where.append("YEAR(created_at) = %s")
            params.append(int(y))
    elif mode == 'range':
        d_from = args.get('date_from')
        d_to = args.get('date_to')
        if d_from:
            where.append("DATE(created_at) >= %s")
            params.append(d_from)
        if d_to:
            where.append("DATE(created_at) <= %s")
            params.append(d_to)
    return where, params

@audit_bp.route('/api/audit/logs', methods=['GET'])
def get_logs():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    offset = (page - 1) * per_page
    
    action = request.args.get('action')
    user_name = request.args.get('user_name')
    target_table = request.args.get('target_table')
    search = request.args.get('search')
    
    where_clauses = ["1=1"]
    params = []
    
    d_where, d_params = _build_date_filter(request.args)
    where_clauses.extend(d_where)
    params.extend(d_params)
    if action:
        where_clauses.append("action LIKE %s")
        params.append(f"%{action}%")
    if user_name:
        where_clauses.append("user_name LIKE %s")
        params.append(f"%{user_name}%")
    if target_table:
        where_clauses.append("target_table = %s")
        params.append(target_table)
    if search:
        where_clauses.append("(action LIKE %s OR user_name LIKE %s OR target_table LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    where_sql = " AND ".join(where_clauses)
    
    with db_cursor() as (conn, cur):
        # Get total
        cur.execute(f"SELECT COUNT(*) as total FROM tblaudit_logs WHERE {where_sql}", tuple(params))
        total = cur.fetchone()['total']
        
        # Get rows with actual employee/user full names
        query_params = list(params) + [per_page, offset]
        cur.execute(f"""
            SELECT a.*, 
                   COALESCE(
                       NULLIF(TRIM(CONCAT(COALESCE(e.first_name,''), ' ', COALESCE(e.last_name,''))), ''),
                       NULLIF(u.name, ''),
                       a.user_name
                   ) AS actual_name
            FROM tblaudit_logs a
            LEFT JOIN tblusers u ON (a.user_name = u.username OR a.user_name = u.name)
            LEFT JOIN tblemployee e ON (u.employee_id = e.employee_id OR a.employee_id = e.employee_id)
            WHERE {where_sql} 
            ORDER BY a.created_at DESC 
            LIMIT %s OFFSET %s
        """, tuple(query_params))
        rows = cur.fetchall()
    
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    
    # Format datetimes & override user_name with actual full name
    for row in rows:
        if row.get('actual_name'):
            row['user_name'] = row['actual_name']
        created = row.get('created_at')
        if isinstance(created, datetime):
            row['timestamp'] = created.isoformat()
            row['created_at'] = created.isoformat()
        else:
            row['timestamp'] = str(created) if created else ''
            
    return jsonify({
        'logs': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })

@audit_bp.route('/api/audit/summary', methods=['GET'])
def get_summary():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    with db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) as count FROM tblaudit_logs WHERE DATE(created_at) = %s", (today,))
        today_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM tblaudit_logs WHERE DATE(created_at) >= %s", (start_of_week,))
        week_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM tblaudit_logs WHERE DATE(created_at) >= %s", (start_of_month,))
        month_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM tblaudit_logs")
        total_count = cur.fetchone()['count']
        
        # by category roughly based on actions
        cur.execute("SELECT action, COUNT(*) as count FROM tblaudit_logs GROUP BY action")
        action_counts = cur.fetchall()
        
        # recent users with actual full names
        cur.execute("""
            SELECT COALESCE(
                       NULLIF(TRIM(CONCAT(COALESCE(e.first_name,''), ' ', COALESCE(e.last_name,''))), ''),
                       NULLIF(u.name, ''),
                       a.user_name
                   ) AS user_name, 
                   COUNT(*) as count 
            FROM tblaudit_logs a
            LEFT JOIN tblusers u ON (a.user_name = u.username OR a.user_name = u.name)
            LEFT JOIN tblemployee e ON (u.employee_id = e.employee_id OR a.employee_id = e.employee_id)
            WHERE DATE(a.created_at) >= %s 
            GROUP BY user_name 
            ORDER BY count DESC LIMIT 5
        """, (start_of_week,))
        recent_users = cur.fetchall()
    
    by_category = {
        'login': 0, 'employee': 0, 'payroll': 0, 'leave': 0, 'attendance': 0, 'settings': 0
    }
    
    for row in action_counts:
        act = (row['action'] or '').upper()
        cnt = row['count']
        if 'LOGIN' in act or 'LOGOUT' in act:
            by_category['login'] += cnt
        elif 'EMPLOYEE' in act:
            by_category['employee'] += cnt
        elif 'PAYROLL' in act:
            by_category['payroll'] += cnt
        elif 'LEAVE' in act:
            by_category['leave'] += cnt
        elif 'ATTENDANCE' in act:
            by_category['attendance'] += cnt
        else:
            by_category['settings'] += cnt
            
    return jsonify({
        'today': today_count,
        'this_week': week_count,
        'this_month': month_count,
        'total': total_count,
        'by_category': by_category,
        'recent_users': recent_users
    })

@audit_bp.route('/api/audit/export', methods=['GET'])
def export_csv():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    action = request.args.get('action')
    user_name = request.args.get('user_name')
    target_table = request.args.get('target_table')
    search = request.args.get('search')
    
    where_clauses = ["1=1"]
    params = []
    
    d_where, d_params = _build_date_filter(request.args)
    where_clauses.extend(d_where)
    params.extend(d_params)
    if action:
        where_clauses.append("action LIKE %s")
        params.append(f"%{action}%")
    if user_name:
        where_clauses.append("user_name LIKE %s")
        params.append(f"%{user_name}%")
    if target_table:
        where_clauses.append("target_table = %s")
        params.append(target_table)
    if search:
        where_clauses.append("(action LIKE %s OR user_name LIKE %s OR target_table LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    where_sql = " AND ".join(where_clauses)
    
    with db_cursor() as (conn, cur):
        cur.execute(f"""
            SELECT a.*, 
                   COALESCE(
                       NULLIF(TRIM(CONCAT(COALESCE(e.first_name,''), ' ', COALESCE(e.last_name,''))), ''),
                       NULLIF(u.name, ''),
                       a.user_name
                   ) AS actual_name
            FROM tblaudit_logs a
            LEFT JOIN tblusers u ON (a.user_name = u.username OR a.user_name = u.name)
            LEFT JOIN tblemployee e ON (u.employee_id = e.employee_id OR a.employee_id = e.employee_id)
            WHERE {where_sql} 
            ORDER BY a.created_at DESC
        """, tuple(params))
        rows = cur.fetchall()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Timestamp', 'User', 'Action', 'Target Table', 'Target ID', 'Employee ID', 'Old Value', 'New Value', 'Reason', 'IP Address'])
    
    for r in rows:
        created = r.get('created_at')
        time_str = created.isoformat() if isinstance(created, datetime) else str(created or '')
        user_display = r.get('actual_name') or r.get('user_name')
        cw.writerow([
            r.get('id'),
            time_str,
            user_display,
            r.get('action'),
            r.get('target_table'),
            r.get('target_id'),
            r.get('employee_id'),
            r.get('old_value'),
            r.get('new_value'),
            r.get('reason'),
            r.get('ip_address')
        ])
        
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=audit_logs.csv"}
    )

@audit_bp.route('/api/audit/payroll-periods', methods=['GET'])
def get_audit_payroll_periods():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    with db_cursor() as (conn, cur):
        cur.execute("""
            SELECT p.period_key, p.period_name, p.status, p.total_gross, p.total_net, p.created_at,
                   COUNT(d.id) as employee_count
            FROM tblpayroll p
            LEFT JOIN tblpayroll_details d ON p.period_key = d.period_key
            GROUP BY p.period_key, p.period_name, p.status, p.total_gross, p.total_net, p.created_at
            ORDER BY p.created_at DESC
        """)
        rows = cur.fetchall()

    for r in rows:
        r['total_gross'] = float(r.get('total_gross') or 0)
        r['total_net'] = float(r.get('total_net') or 0)
        created = r.get('created_at')
        if isinstance(created, datetime):
            r['created_at'] = created.strftime('%Y-%m-%d %H:%M')

    return jsonify({'periods': rows})

@audit_bp.route('/api/audit/payroll-verification', methods=['GET'])
def get_payroll_verification():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    period_key = request.args.get('period_key')
    with db_cursor() as (conn, cur):
        if not period_key:
            cur.execute("SELECT period_key FROM tblpayroll ORDER BY created_at DESC LIMIT 1")
            latest = cur.fetchone()
            if latest:
                period_key = latest['period_key']
            else:
                return jsonify({
                    'period_key': '',
                    'summary': {'total_employees': 0, 'total_gross': 0, 'total_deductions': 0, 'total_net': 0, 'accurate_count': 0, 'discrepancy_count': 0, 'compliance_rate': 100},
                    'details': []
                })

        cur.execute("""
            SELECT d.*, 
                   e.first_name, e.last_name, e.designation, e.employment_status
            FROM tblpayroll_details d
            LEFT JOIN tblemployee e ON d.employee_id = e.employee_id
            WHERE d.period_key = %s
            ORDER BY e.last_name, e.first_name
        """, (period_key,))
        rows = cur.fetchall()

    verified_list = []
    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0
    accurate_count = 0
    discrepancy_count = 0

    for r in rows:
        emp_name = f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip() or r.get('employee_id')
        basic_pay = float(r.get('half_basic') or r.get('basic_salary') or 0)
        monthly_salary = float(r.get('basic_salary') or (basic_pay * 2))
        daily_rate = float(r.get('daily_rate') or round(monthly_salary / 22.0, 2)) if monthly_salary > 0 else 0.0
        
        overtime_pay = 0.0  # OT if applicable
        holiday_pay = float(r.get('holiday_pay') or 0)
        other_earnings = float(r.get('other_earnings') or 0)

        # Parse custom payheads
        ph_earnings = 0.0
        ph_deductions = 0.0
        payheads_raw = r.get('payheads_json')
        if payheads_raw:
            try:
                ph_data = json.loads(payheads_raw) if isinstance(payheads_raw, str) else payheads_raw
                if isinstance(ph_data, dict):
                    if 'earnings' in ph_data and isinstance(ph_data['earnings'], list):
                        for item in ph_data['earnings']:
                            if isinstance(item, dict):
                                ph_earnings += float(item.get('amount') or 0)
                    if 'deductions' in ph_data and isinstance(ph_data['deductions'], list):
                        for item in ph_data['deductions']:
                            if isinstance(item, dict):
                                ph_deductions += float(item.get('amount') or 0)
            except Exception:
                pass

        stored_gross = float(r.get('total_gross') or 0)
        # Gross computation math
        audited_gross = round(basic_pay + holiday_pay + other_earnings, 2)
        if abs(audited_gross - stored_gross) > 0.01 and abs((audited_gross + ph_earnings) - stored_gross) <= 0.01:
            audited_gross = round(audited_gross + ph_earnings, 2)

        gross_var = round(audited_gross - stored_gross, 2)

        # Deductions computation math
        absent_ded = float(r.get('absent_deduction') or 0)
        tardiness_ded = float(r.get('tardiness_deduction') or 0)
        undertime_ded = float(r.get('undertime_deduction') or 0)
        sss_ee = float(r.get('sss_ee') or 0)
        philhealth_ee = float(r.get('philhealth_ee') or 0)
        pagibig_ee = float(r.get('pagibig_ee') or 0)
        withholding_tax = float(r.get('withholding_tax') or 0)
        other_deductions = float(r.get('other_deductions') or 0)

        stored_deductions = float(r.get('total_deduct') or 0)
        audited_deductions = round(absent_ded + tardiness_ded + undertime_ded + sss_ee + philhealth_ee + pagibig_ee + withholding_tax + other_deductions + ph_deductions, 2)
        deduction_var = round(audited_deductions - stored_deductions, 2)

        stored_net = float(r.get('net_pay') or 0)
        audited_net = max(0.0, round(audited_gross - audited_deductions, 2))
        net_var = round(audited_net - stored_net, 2)

        # Audit verdict
        is_accurate = (abs(gross_var) <= 0.01 and abs(deduction_var) <= 0.01 and abs(net_var) <= 0.01)
        if is_accurate:
            accurate_count += 1
            status = 'ACCURATE'
        else:
            discrepancy_count += 1
            status = 'DISCREPANCY'

        warnings = []
        if stored_net <= 0 or r.get('is_negative'):
            warnings.append("Zero/Negative Net Pay (Deductions exceed gross salary)")

        total_gross += stored_gross
        total_deductions += stored_deductions
        total_net += stored_net

        verified_list.append({
            'employee_id': r.get('employee_id'),
            'employee_name': emp_name,
            'designation': r.get('designation') or 'Staff',
            'employment_status': r.get('employment_status') or 'Permanent',
            'monthly_salary': monthly_salary,
            'daily_rate': daily_rate,
            'basic_pay': basic_pay,
            'overtime_pay': overtime_pay,
            'holiday_pay': holiday_pay,
            'other_earnings': other_earnings,
            'ph_earnings': ph_earnings,
            'stored_gross': stored_gross,
            'audited_gross': audited_gross,
            'gross_variance': gross_var,
            'absent_days': r.get('absent_days') or 0,
            'absent_deduction': absent_ded,
            'tardiness_minutes': r.get('late_minutes') or 0,
            'tardiness_deduction': tardiness_ded,
            'undertime_minutes': r.get('undertime_minutes') or 0,
            'undertime_deduction': undertime_ded,
            'sss_ee': sss_ee,
            'philhealth_ee': philhealth_ee,
            'pagibig_ee': pagibig_ee,
            'withholding_tax': withholding_tax,
            'other_deductions': other_deductions + ph_deductions,
            'stored_deductions': stored_deductions,
            'audited_deductions': audited_deductions,
            'deduction_variance': deduction_var,
            'stored_net': stored_net,
            'audited_net': audited_net,
            'net_variance': net_var,
            'status': status,
            'warnings': warnings,
            'formulas': {
                'daily_rate': f"₱{monthly_salary:,.2f} / 22 = ₱{daily_rate:,.2f}/day",
                'basic_pay': f"Half-month basic rate = ₱{basic_pay:,.2f}",
                'tardiness': f"{r.get('late_minutes') or 0} mins × (₱{daily_rate:,.2f} / 480) = ₱{tardiness_ded:,.2f}",
                'undertime': f"{r.get('undertime_minutes') or 0} mins × (₱{daily_rate:,.2f} / 480) = ₱{undertime_ded:,.2f}",
                'absence': f"{r.get('absent_days') or 0} days × ₱{daily_rate:,.2f} = ₱{absent_ded:,.2f}",
                'gross_sum': f"Basic (₱{basic_pay:,.2f}) + Hol (₱{holiday_pay:,.2f}) + Allow (₱{other_earnings + ph_earnings:,.2f}) = ₱{audited_gross:,.2f}",
                'ded_sum': f"Absence (₱{absent_ded:,.2f}) + Late (₱{tardiness_ded:,.2f}) + Under (₱{undertime_ded:,.2f}) + PHIC (₱{philhealth_ee:,.2f}) + Tax (₱{withholding_tax:,.2f}) + Custom (₱{other_deductions + ph_deductions:,.2f}) = ₱{audited_deductions:,.2f}",
                'net_sum': f"Gross (₱{audited_gross:,.2f}) - Deductions (₱{audited_deductions:,.2f}) = ₱{audited_net:,.2f}"
            }
        })

    total_count = len(verified_list)
    compliance_rate = round((accurate_count / total_count * 100), 1) if total_count > 0 else 100.0

    return jsonify({
        'period_key': period_key,
        'summary': {
            'total_employees': total_count,
            'total_gross': round(total_gross, 2),
            'total_deductions': round(total_deductions, 2),
            'total_net': round(total_net, 2),
            'accurate_count': accurate_count,
            'discrepancy_count': discrepancy_count,
            'compliance_rate': compliance_rate
        },
        'details': verified_list
    })

@audit_bp.route('/api/audit/export-payroll-verification', methods=['GET'])
def export_payroll_verification():
    if not check_access():
        return jsonify({'error': 'Forbidden'}), 403

    period_key = request.args.get('period_key')
    if not period_key:
        return jsonify({'error': 'Missing period_key'}), 400

    # Fetch verification response directly
    res = get_payroll_verification()
    data = res.get_json()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow([
        'Period Key', 'Employee ID', 'Employee Name', 'Designation',
        'Monthly Salary', 'Basic Pay', 'Daily Rate',
        'Overtime Pay', 'Holiday Pay', 'Other Earnings', 'Stored Gross', 'Audited Gross', 'Gross Variance',
        'Absent Ded', 'Tardiness Ded', 'Undertime Ded', 'PhilHealth', 'Pag-IBIG', 'SSS', 'Withholding Tax', 'Other Deds',
        'Stored Total Deductions', 'Audited Total Deductions', 'Deduction Variance',
        'Stored Net Pay', 'Audited Net Pay', 'Net Variance', 'Audit Status'
    ])

    for d in data.get('details', []):
        cw.writerow([
            period_key,
            d['employee_id'],
            d['employee_name'],
            d['designation'],
            f"{d['monthly_salary']:.2f}",
            f"{d['basic_pay']:.2f}",
            f"{d['daily_rate']:.2f}",
            f"{d['overtime_pay']:.2f}",
            f"{d['holiday_pay']:.2f}",
            f"{(d['other_earnings'] + d['ph_earnings']):.2f}",
            f"{d['stored_gross']:.2f}",
            f"{d['audited_gross']:.2f}",
            f"{d['gross_variance']:.2f}",
            f"{d['absent_deduction']:.2f}",
            f"{d['tardiness_deduction']:.2f}",
            f"{d['undertime_deduction']:.2f}",
            f"{d['philhealth_ee']:.2f}",
            f"{d['pagibig_ee']:.2f}",
            f"{d['sss_ee']:.2f}",
            f"{d['withholding_tax']:.2f}",
            f"{d['ph_deductions']:.2f}",
            f"{d['stored_deductions']:.2f}",
            f"{d['audited_deductions']:.2f}",
            f"{d['deduction_variance']:.2f}",
            f"{d['stored_net']:.2f}",
            f"{d['audited_net']:.2f}",
            f"{d['net_variance']:.2f}",
            d['status']
        ])

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=payroll_audit_verification_{period_key}.csv"}
    )

