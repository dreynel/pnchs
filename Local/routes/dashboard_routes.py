from flask import Blueprint, jsonify
from db import db_cursor
from datetime import datetime, date, timedelta
import calendar

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')

@dashboard_bp.route('/stats')
def get_dashboard_stats():
    try:
        with db_cursor() as (conn, cur):
            now = datetime.now()
            today_date = date.today()

            # 1. Total and category counts
            cur.execute("SELECT COUNT(*) as total FROM tblemployee")
            total_emps = cur.fetchone()['total'] or 0

            cur.execute("SELECT COUNT(*) as total FROM tblemployee WHERE employee_type='TEACHING' OR LOWER(designation) LIKE '%teacher%'")
            teaching_emps = cur.fetchone()['total'] or 0

            non_teaching_emps = max(0, total_emps - teaching_emps)

            cur.execute("SELECT COUNT(*) as total FROM tblemployee WHERE created_at >= CURDATE() - INTERVAL 30 DAY")
            new_hires = cur.fetchone()['total'] or 0

            # 2. Leaves count
            cur.execute("SELECT COUNT(*) as total FROM tblleaves WHERE status='Pending'")
            pending_leaves = cur.fetchone()['total'] or 0

            cur.execute("SELECT COUNT(*) as total FROM tblleaves WHERE status='Approved'")
            approved_leaves = cur.fetchone()['total'] or 0

            # 3. Attendance Today / Latest
            cur.execute("SELECT COUNT(DISTINCT employee_id) as total FROM tbltime_logs WHERE work_date = %s", (today_date,))
            today_attendance = cur.fetchone()['total'] or 0

            # 4. Latest Processed Payroll KPI
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

            if latest_run:
                kpi_gross = float(latest_run['gross'] or 0.0)
                kpi_deduct = float(latest_run['deduct'] or 0.0)
                kpi_net = float(latest_run['net'] or 0.0)
                kpi_processed = int(latest_run['processed'] or 0)
                p_label = f"{calendar.month_name[latest_run['month']][:3]} {latest_run['year']} - {'1st' if latest_run['half']==1 else '2nd'} Half"
            else:
                kpi_gross = 0.0
                kpi_deduct = 0.0
                kpi_net = 0.0
                kpi_processed = 0
                p_label = "Not Processed Yet"

            # 5. Trends (Last 6 Periods)
            cur.execute("""
                SELECT p.month, p.year, p.half, SUM(d.total_gross) as gross, SUM(d.net_pay) as net
                FROM tblpayroll p
                JOIN tblpayroll_details d ON p.period_key = d.period_key
                GROUP BY p.period_key, p.month, p.year, p.half
                ORDER BY p.year DESC, p.month DESC, p.half DESC
                LIMIT 6
            """)
            trends_rows = cur.fetchall()
            trends_rows.reverse()

            if trends_rows:
                trends = [{
                    'label': f"{calendar.month_name[t['month']][:3]} {'H1' if t['half']==1 else 'H2'}",
                    'gross': float(t['gross']),
                    'net': float(t['net'])
                } for t in trends_rows]
            else:
                trends = []

            # 7. Recent Activity Feed (Time Logs + Leaves + Employee Registrations)
            cur.execute("""
                SELECT t.work_date, t.am_time_in, t.pm_time_out, e.first_name, e.last_name, e.employee_id
                FROM tbltime_logs t
                JOIN tblemployee e ON t.employee_id = e.employee_id
                ORDER BY t.work_date DESC, t.log_id DESC
                LIMIT 8
            """)
            attendance_rows = cur.fetchall()

            cur.execute("""
                SELECT l.leave_date, l.leave_type, l.status, l.filed_at, e.first_name, e.last_name
                FROM tblleaves l
                JOIN tblemployee e ON l.employee_id = e.employee_id
                ORDER BY l.filed_at DESC
                LIMIT 5
            """)
            leave_rows = cur.fetchall()

            cur.execute("""
                SELECT created_at, first_name, last_name, employee_id
                FROM tblemployee
                ORDER BY created_at DESC
                LIMIT 5
            """)
            reg_rows = cur.fetchall()

            activities = []
            for a in attendance_rows:
                act_time = a['work_date']
                punch_str = a['pm_time_out'] or a['am_time_in'] or 'Present'
                activities.append({
                    'name': f"{a['first_name']} {a['last_name']}",
                    'type': f"DTR log ({punch_str})",
                    'tag': 'Biometric',
                    'date_label': a['work_date'].strftime('%b %d, %Y') if hasattr(a['work_date'], 'strftime') else str(a['work_date']),
                    'time_label': str(punch_str)[:5] if punch_str != 'Present' else 'Biometric'
                })

            for l in leave_rows:
                f_time = l['filed_at']
                activities.append({
                    'name': f"{l['first_name']} {l['last_name']}",
                    'type': f"{l['status']} {l['leave_type']} Leave",
                    'tag': 'Leave',
                    'date_label': f_time.strftime('%b %d') if f_time else 'Recent',
                    'time_label': f_time.strftime('%I:%M %p') if f_time else 'Leave'
                })

            for r in reg_rows:
                r_time = r['created_at']
                activities.append({
                    'name': f"{r['first_name']} {r['last_name']}",
                    'type': 'Registered staff profile',
                    'tag': 'Staff',
                    'date_label': r_time.strftime('%b %d') if r_time else 'Recent',
                    'time_label': r_time.strftime('%I:%M %p') if r_time else 'Profile'
                })

            display_activities = activities[:6]

            # 8. Days Left & Elapsed Percentage in Current Period
            if now.day <= 15:
                start_d = datetime(now.year, now.month, 1)
                end_d = datetime(now.year, now.month, 15)
                period_name = f"{calendar.month_name[now.month]} 1 – 15, {now.year}"
                cutoff_date_str = f"{calendar.month_name[now.month]} 15, {now.year}"
            else:
                start_d = datetime(now.year, now.month, 16)
                last_day = calendar.monthrange(now.year, now.month)[1]
                end_d = datetime(now.year, now.month, last_day)
                period_name = f"{calendar.month_name[now.month]} 16 – {last_day}, {now.year}"
                cutoff_date_str = f"{calendar.month_name[now.month]} {last_day}, {now.year}"

            total_period_days = max(1, (end_d - start_d).days + 1)
            elapsed_days = min(total_period_days, max(0, (now - start_d).days + 1))
            elapsed_pct = int((elapsed_days / total_period_days) * 100)
            days_left = max(0, (end_d - now).days)

            dtr_rate = 100 if total_emps > 0 else 0

            return jsonify({
                'summary': {
                    'total_employees': total_emps,
                    'teaching_employees': teaching_emps,
                    'non_teaching_employees': non_teaching_emps,
                    'new_hires': new_hires,
                    'pending_leaves': pending_leaves,
                    'approved_leaves': approved_leaves,
                    'today_attendance': today_attendance,
                    'days_left': days_left,
                    'elapsed_pct': elapsed_pct,
                    'period_name': period_name,
                    'cutoff_date_str': cutoff_date_str,
                    'current_period_gross': kpi_gross,
                    'period_label': p_label,
                    'dtr_rate': dtr_rate
                },
                'kpis': {
                    'total_gross': kpi_gross,
                    'total_deduct': kpi_deduct,
                    'net_pay': kpi_net,
                    'processed_count': kpi_processed
                },
                'trends': trends,
                'activity': display_activities
            })

    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

