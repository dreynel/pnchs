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

            cur.execute("SELECT COUNT(*) as total FROM tblemployee WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'")
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

            # 7. Recent Activity Feed (Biometric punches + DTR logs + Leaves + Staff registrations)
            activities = []

            # 7a. Real-time biometric device punches (tblbiometric_logs)
            try:
                cur.execute("""
                    SELECT b.id, b.employee_id, b.log_type, b.log_time, e.first_name, e.last_name
                    FROM tblbiometric_logs b
                    JOIN tblemployee e ON b.employee_id = e.employee_id
                    ORDER BY b.log_time DESC
                    LIMIT 10
                """)
                bio_rows = cur.fetchall()
                type_map = {
                    'am_time_in': 'AM Time In',
                    'am_time_out': 'AM Time Out',
                    'pm_time_in': 'PM Time In',
                    'pm_time_out': 'PM Time Out',
                    'IN': 'Time In',
                    'OUT': 'Time Out'
                }
                for b in bio_rows:
                    b_time = b['log_time']
                    t_label = type_map.get(b['log_type'], b['log_type'] or 'Biometric Punch')
                    activities.append({
                        'name': f"{b['first_name']} {b['last_name']}",
                        'type': f"{t_label} biometric verified",
                        'tag': 'Biometric',
                        'date_label': b_time.strftime('%b %d, %Y') if b_time else 'Today',
                        'time_label': b_time.strftime('%I:%M %p') if b_time else '',
                        'sort_time': b_time or datetime.min
                    })
            except Exception:
                pass

            # 7b. Time logs (tbltime_logs)
            try:
                cur.execute("""
                    SELECT t.work_date, t.am_time_in, t.pm_time_out, e.first_name, e.last_name, e.employee_id
                    FROM tbltime_logs t
                    JOIN tblemployee e ON t.employee_id = e.employee_id
                    ORDER BY t.work_date DESC, t.log_id DESC
                    LIMIT 10
                """)
                attendance_rows = cur.fetchall()
                for a in attendance_rows:
                    w_date = a['work_date']
                    punch = a['pm_time_out'] or a['am_time_in']
                    sort_dt = datetime.min
                    if w_date:
                        try:
                            if punch and hasattr(punch, 'hour'):
                                sort_dt = datetime.combine(w_date, punch)
                            elif punch and isinstance(punch, str) and ':' in punch:
                                parts = punch.split(':')
                                sort_dt = datetime(w_date.year, w_date.month, w_date.day, int(parts[0]), int(parts[1]))
                            elif hasattr(w_date, 'year'):
                                sort_dt = datetime(w_date.year, w_date.month, w_date.day, 17 if a['pm_time_out'] else 8, 0)
                        except Exception:
                            sort_dt = datetime.min

                    time_display = ''
                    if punch:
                        try:
                            if hasattr(punch, 'strftime'):
                                time_display = punch.strftime('%I:%M %p')
                            elif isinstance(punch, str) and ':' in punch:
                                p_obj = datetime.strptime(punch[:8], '%H:%M:%S').time() if len(punch) >= 8 else datetime.strptime(punch[:5], '%H:%M').time()
                                time_display = p_obj.strftime('%I:%M %p')
                            else:
                                time_display = str(punch)[:5]
                        except Exception:
                            time_display = str(punch)[:5]

                    action_desc = "PM Time Out" if a['pm_time_out'] else ("AM Time In" if a['am_time_in'] else "DTR Attendance Log")
                    activities.append({
                        'name': f"{a['first_name']} {a['last_name']}",
                        'type': f"{action_desc} ({time_display or 'Present'})",
                        'tag': 'Biometric',
                        'date_label': w_date.strftime('%b %d, %Y') if hasattr(w_date, 'strftime') else str(w_date),
                        'time_label': time_display or 'Biometric',
                        'sort_time': sort_dt
                    })
            except Exception:
                pass

            # 7c. Leave Applications (tblleaves)
            try:
                cur.execute("""
                    SELECT l.leave_date, l.leave_type, l.status, l.filed_at, e.first_name, e.last_name
                    FROM tblleaves l
                    JOIN tblemployee e ON l.employee_id = e.employee_id
                    ORDER BY l.filed_at DESC
                    LIMIT 6
                """)
                leave_rows = cur.fetchall()
                for l in leave_rows:
                    f_time = l['filed_at']
                    activities.append({
                        'name': f"{l['first_name']} {l['last_name']}",
                        'type': f"{l['status']} {l['leave_type']} Leave application",
                        'tag': 'Leave',
                        'date_label': f_time.strftime('%b %d, %Y') if f_time else 'Recent',
                        'time_label': f_time.strftime('%I:%M %p') if f_time else '',
                        'sort_time': f_time or datetime.min
                    })
            except Exception:
                pass

            # 7d. Employee Registrations (tblemployee)
            try:
                cur.execute("""
                    SELECT created_at, first_name, last_name, employee_id, designation
                    FROM tblemployee
                    ORDER BY created_at DESC
                    LIMIT 6
                """)
                reg_rows = cur.fetchall()
                for r in reg_rows:
                    r_time = r['created_at']
                    desig = f" ({r['designation']})" if r.get('designation') else ""
                    activities.append({
                        'name': f"{r['first_name']} {r['last_name']}",
                        'type': f"New staff enrolled{desig}",
                        'tag': 'Staff',
                        'date_label': r_time.strftime('%b %d, %Y') if r_time else 'Recent',
                        'time_label': r_time.strftime('%I:%M %p') if r_time else '',
                        'sort_time': r_time or datetime.min
                    })
            except Exception:
                pass

            # Deduplicate by (name, tag, date_label, time_label) & sort chronologically descending
            seen = set()
            unique_activities = []
            for act in activities:
                key = (act['name'], act['tag'], act['date_label'], act['time_label'])
                if key not in seen:
                    seen.add(key)
                    unique_activities.append(act)

            unique_activities.sort(key=lambda x: x.get('sort_time') or datetime.min, reverse=True)
            display_activities = unique_activities[:8]

            for d in display_activities:
                d.pop('sort_time', None)

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

