"""
Seed Attendance Logs using execute_values for rapid batch insertion.
Generates realistic attendance for August and September 2026:
- On time
- Late arrivals
- Undertime (leaving early)
- Half day (morning only or afternoon only)
- Absences (no logs)
"""
import random
from datetime import date, datetime, timedelta
from psycopg2.extras import execute_values
from db import db_cursor

HOLIDAYS = {
    date(2026, 8, 21): "Ninoy Aquino Day",
    date(2026, 8, 31): "National Heroes Day",
}

def seed_logs():
    random.seed(42)

    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT employee_id, first_name, last_name, designation, employee_type FROM tblemployee ORDER BY employee_id")
        employees = cur.fetchall()
        print(f"Generating sample logs for {len(employees)} employees...")

        # Clear existing logs for Aug and Sep 2026
        cur.execute("DELETE FROM tbltime_logs WHERE work_date >= '2026-08-01' AND work_date <= '2026-09-30'")
        cur.execute("DELETE FROM tblbiometric_logs WHERE log_time >= '2026-08-01 00:00:00' AND log_time <= '2026-09-30 23:59:59'")
        print("[OK] Cleared previous Aug-Sep 2026 logs.")

        start_date = date(2026, 8, 1)
        end_date = date(2026, 9, 30)

        work_dates = []
        cur_d = start_date
        while cur_d <= end_date:
            if cur_d.weekday() < 5 and cur_d not in HOLIDAYS:
                work_dates.append(cur_d)
            cur_d += timedelta(days=1)

        print(f"Total work dates: {len(work_dates)}")

        time_rows = []
        bio_rows = []

        # Distinct profiles:
        # Chronic absent: 14, 15, 24 (absent ~85% of days -> clearly negative net pay with statutory deductions)
        # Heavy tardy / undertime / moderate absent: 4, 8, 13, 20
        # Regular: on time with minor variations
        chronic_absent_indexes = [14, 15, 24]
        heavy_deduction_indexes = [4, 8, 13, 20]

        # First clean out existing Aug & Sep 2026 logs
        cur.execute("DELETE FROM tbltime_logs WHERE work_date BETWEEN '2026-08-01' AND '2026-09-30'")
        cur.execute("DELETE FROM tblbiometric_logs WHERE log_time >= '2026-08-01' AND log_time < '2026-10-01'")
        print("Cleaned prior Aug & Sep time and biometric logs.")

        for idx, emp in enumerate(employees):
            emp_id = emp['employee_id']
            is_teaching = (emp.get('employee_type') == 'TEACHING') or ('teacher' in (emp.get('designation') or '').lower())
            is_chronic = idx in chronic_absent_indexes
            is_heavy = idx in heavy_deduction_indexes

            am_start_h, am_start_m = (7, 30) if is_teaching else (8, 0)
            am_end_h, am_end_m = (11, 30) if is_teaching else (12, 0)

            for d in work_dates:
                roll = random.random()

                if is_chronic:
                    # EMP-000-015 and EMP-000-016: 100% absent (unpaid days with 0 leave credits)
                    # EMP-000-025: absent 90% of the time
                    if idx in [14, 15]:
                        continue # 100% Absent
                    elif roll < 0.90:
                        continue # 90% Absent
                    else:
                        condition = 'halfday_am'
                elif is_heavy:
                    if roll < 0.35:
                        continue # Absent (unpaid day)
                    elif roll < 0.55:
                        condition = 'halfday_am' # Half day absence
                    elif roll < 0.80:
                        condition = 'late_heavy' # 45-90 min tardy
                    elif roll < 0.90:
                        condition = 'undertime'
                    else:
                        condition = 'ontime'
                else:
                    if roll < 0.05:
                        continue # Absent
                    elif roll < 0.20:
                        condition = 'late_moderate' # 15-35 min late
                    elif roll < 0.30:
                        condition = 'undertime' # 20-50 min undertime
                    elif roll < 0.35:
                        condition = 'halfday_am'
                    elif roll < 0.40:
                        condition = 'late_light' # 3-10 min late
                    else:
                        condition = 'ontime'

                am_in = am_out = pm_in = pm_out = None

                if condition == 'ontime':
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=random.randint(5, 18))
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m) + timedelta(minutes=random.randint(0, 5))
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) - timedelta(minutes=random.randint(2, 10))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) + timedelta(minutes=random.randint(1, 15))
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')
                    pm_in, pm_out = pm_in_dt.strftime('%H:%M:%S'), pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_light':
                    late = random.randint(3, 12)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) - timedelta(minutes=5)
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0)
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')
                    pm_in, pm_out = pm_in_dt.strftime('%H:%M:%S'), pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_moderate':
                    late = random.randint(16, 38)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) + timedelta(minutes=random.randint(0, 10))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0)
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')
                    pm_in, pm_out = pm_in_dt.strftime('%H:%M:%S'), pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_heavy':
                    late = random.randint(45, 95)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) + timedelta(minutes=random.randint(10, 30))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0)
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')
                    pm_in, pm_out = pm_in_dt.strftime('%H:%M:%S'), pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'undertime':
                    early = random.randint(25, 60)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=5)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0)
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) - timedelta(minutes=early)
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')
                    pm_in, pm_out = pm_in_dt.strftime('%H:%M:%S'), pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'halfday_am':
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=5)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    am_in, am_out = am_in_dt.strftime('%H:%M:%S'), am_out_dt.strftime('%H:%M:%S')

                time_rows.append((emp_id, d, am_in, am_out, pm_in, pm_out))

                if am_in:
                    bio_rows.append((emp_id, 'am_time_in', f"{d} {am_in}"))
                if am_out:
                    bio_rows.append((emp_id, 'am_time_out', f"{d} {am_out}"))
                if pm_in:
                    bio_rows.append((emp_id, 'pm_time_in', f"{d} {pm_in}"))
                if pm_out:
                    bio_rows.append((emp_id, 'pm_time_out', f"{d} {pm_out}"))

        print(f"Batch inserting {len(time_rows)} time logs...")
        execute_values(
            cur,
            """
            INSERT INTO tbltime_logs (employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out)
            VALUES %s
            ON CONFLICT (employee_id, work_date) DO UPDATE
            SET am_time_in = EXCLUDED.am_time_in,
                am_time_out = EXCLUDED.am_time_out,
                pm_time_in = EXCLUDED.pm_time_in,
                pm_time_out = EXCLUDED.pm_time_out
            """,
            time_rows,
            page_size=500
        )

        print(f"Batch inserting {len(bio_rows)} biometric punches...")
        execute_values(
            cur,
            """
            INSERT INTO tblbiometric_logs (employee_id, log_type, log_time)
            VALUES %s
            """,
            bio_rows,
            page_size=1000
        )

        print(f"[OK] Successfully seeded {len(time_rows)} daily time logs and {len(bio_rows)} biometric punches for August and September 2026!")

if __name__ == '__main__':
    seed_logs()
