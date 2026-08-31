from flask import Blueprint, jsonify
from db import db_cursor
from datetime import datetime, timedelta
import calendar

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')

@dashboard_bp.route('/stats')
def get_dashboard_stats():
    try:
        with db_cursor() as (conn, cur):
            # 1. Basic Summary
            cur.execute("SELECT COUNT(*) as total FROM tblemployee")
            total_emps = cur.fetchone()['total']
            
            # New hires (created in last 30 days)
            cur.execute("SELECT COUNT(*) as total FROM tblemployee WHERE created_at >= CURDATE() - INTERVAL 30 DAY")
            new_hires = cur.fetchone()['total']

            # 2. Latest Payroll KPI
            # Find the most recent period with data
            cur.execute("""
                SELECT p.period_key, p.month, p.year, p.half,
                       SUM(d.total_gross) as gross, 
                       SUM(d.total_deduct) as deduct, 
                       SUM(d.net_pay) as net,
                       COUNT(d.id) as processed
                FROM tblpayroll p
                JOIN tblpayroll_details d ON p.period_key = d.period_key
                GROUP BY p.period_key, p.month, p.year, p.half
                ORDER BY p.year DESC, p.month DESC, p.half DESC
                LIMIT 1
            """)
            latest_run = cur.fetchone()
            
            # 3. Last 6 Periods Trend
            cur.execute("""
                SELECT p.month, p.half, SUM(d.total_gross) as gross, SUM(d.net_pay) as net
                FROM tblpayroll p
                JOIN tblpayroll_details d ON p.period_key = d.period_key
                GROUP BY p.period_key, p.month, p.year, p.half
                ORDER BY p.year DESC, p.month DESC, p.half DESC
                LIMIT 6
            """)
            trends = cur.fetchall()
            trends.reverse() # Show chronological
            
            # 4. Recent Activity (Combined: Attendance + New Hires)
            # Biometric logs
            cur.execute("""
                SELECT b.log_time as activity_time, 'attendance' as act_type, b.log_type, e.first_name, e.last_name
                FROM tblbiometric_logs b
                JOIN tblemployee e ON b.employee_id = e.employee_id
                ORDER BY b.log_time DESC
                LIMIT 10
            """)
            attendance_acts = cur.fetchall()
            
            # New employees
            cur.execute("""
                SELECT created_at as activity_time, 'registration' as act_type, '' as log_type, first_name, last_name
                FROM tblemployee
                ORDER BY created_at DESC
                LIMIT 5
            """)
            reg_acts = cur.fetchall()
            
            # Combine and sort
            all_acts = []
            for a in attendance_acts:
                all_acts.append({
                    'name': f"{a['first_name']} {a['last_name']}",
                    'type': a['log_type'].replace('_', ' ').title(),
                    'act_type': 'Biometric',
                    'time': a['activity_time']
                })
            for r in reg_acts:
                all_acts.append({
                    'name': f"{r['first_name']} {r['last_name']}",
                    'type': 'Registered',
                    'act_type': 'New Employee',
                    'time': r['activity_time']
                })
            
            all_acts.sort(key=lambda x: x['time'], reverse=True)
            display_acts = all_acts[:6]
            
            # 5. Days Left in Period
            now = datetime.now()
            if now.day <= 15:
                # 1st half: Ends on 15th
                end_date = datetime(now.year, now.month, 15)
            else:
                # 2nd half: Ends on last day of month
                last_day = calendar.monthrange(now.year, now.month)[1]
                end_date = datetime(now.year, now.month, last_day)
            
            days_left = (end_date - now).days
            if days_left < 0: days_left = 0
            
            # Format results
            data = {
                'summary': {
                    'total_employees': total_emps,
                    'new_hires': new_hires,
                    'days_left': days_left,
                    'current_period_gross': float(latest_run['gross']) if latest_run else 0,
                    'period_label': f"{calendar.month_name[latest_run['month']][:3]} {latest_run['year']} - {'1st' if latest_run['half']==1 else '2nd'} Half" if latest_run else "N/A"
                },
                'kpis': {
                    'total_gross': float(latest_run['gross']) if latest_run else 0,
                    'total_deduct': float(latest_run['deduct']) if latest_run else 0,
                    'net_pay': float(latest_run['net']) if latest_run else 0,
                    'processed_count': latest_run['processed'] if latest_run else 0
                },
                'trends': [
                    {
                        'label': f"{calendar.month_name[t['month']][:3]} {'H1' if t['half']==1 else 'H2'}",
                        'gross': float(t['gross']),
                        'net': float(t['net'])
                    } for t in trends
                ],
                'activity': [
                    {
                        'name': act['name'],
                        'type': act['type'],
                        'tag': act['act_type'],
                        'time_label': act['time'].strftime('%I:%M %p'),
                        'date_label': 'Today' if act['time'].date() == now.date() else act['time'].strftime('%b %d')
                    } for act in display_acts
                ]
            }
            
            return jsonify(data)
            
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500
