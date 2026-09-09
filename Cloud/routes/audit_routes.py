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
        
        # Get rows
        query_params = list(params) + [per_page, offset]
        cur.execute(f"SELECT * FROM tblaudit_logs WHERE {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s", tuple(query_params))
        rows = cur.fetchall()
    
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    
    # Format datetimes
    for row in rows:
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
        
        # recent users
        cur.execute("""
            SELECT user_name, COUNT(*) as count 
            FROM tblaudit_logs 
            WHERE DATE(created_at) >= %s 
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
        cur.execute(f"SELECT * FROM tblaudit_logs WHERE {where_sql} ORDER BY created_at DESC", tuple(params))
        rows = cur.fetchall()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Timestamp', 'User', 'Action', 'Target Table', 'Target ID', 'Employee ID', 'Old Value', 'New Value', 'Reason', 'IP Address'])
    
    for r in rows:
        created = r.get('created_at')
        time_str = created.isoformat() if isinstance(created, datetime) else str(created or '')
        cw.writerow([
            r.get('id'),
            time_str,
            r.get('user_name'),
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
