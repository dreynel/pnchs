"""
Seed Realistic Attendance Time Logs & Biometric Punches
for August and September 2026 across all 34 employees in PNCHS.
Includes:
- On-time logs
- Late arrivals (morning / afternoon tardiness)
- Undertime (leaving early)
- Half-day logs (morning only or afternoon only)
- Absences (0 logs)
- Official Philippine Holidays (Ninoy Aquino Day, National Heroes Day)
"""
import random
from datetime import date, datetime, timedelta
from db import db_cursor

# 2026 Holidays in August & September
HOLIDAYS = {
    date(2026, 8, 21): "Ninoy Aquino Day (Special Non-Working)",
    date(2026, 8, 31): "National Heroes Day (Regular Holiday)",
}

def generate_logs():
    random.seed(42) # Deterministic realistic seed

    with db_cursor(commit=True) as (conn, cur):
        # 1. Fetch all employees
        cur.execute("SELECT employee_id, first_name, last_name, designation, employee_type FROM tblemployee ORDER BY employee_id")
        employees = cur.fetchall()
        print(f"Generating sample logs for {len(employees)} employees...")

        # 2. Delete existing logs for August and September 2026
        cur.execute("DELETE FROM tbltime_logs WHERE work_date BETWEEN '2026-08-01' AND '2026-09-30'")
        cur.execute("DELETE FROM tblbiometric_logs WHERE log_time >= '2026-08-01 00:00:00' AND log_time <= '2026-09-30 23:59:59'")
        print("Cleared previous Aug-Sep 2026 logs.")

        # 3. Calendar dates for August and September 2026
        start_date = date(2026, 8, 1)
        end_date = date(2026, 9, 30)

        # Build list of weekdays (excluding weekends)
        work_dates = []
        cur_d = start_date
        while cur_d <= end_date:
            if cur_d.weekday() < 5 and cur_d not in HOLIDAYS:
                work_dates.append(cur_d)
            cur_d += timedelta(days=1)

        print(f"Total working days in Aug-Sep 2026 (excluding weekends & holidays): {len(work_dates)}")

        time_log_inserts = []
        bio_log_inserts = []

        # Distinct employee profiles for variety:
        # Profile A: Very punctual (95% on time, 5% slight late)
        # Profile B: Average (75% on time, 15% late, 5% undertime, 5% absent)
        # Profile C: Frequent tardy / undertime (50% on time, 35% late, 10% undertime, 5% absent)
        # Profile D: Habitual absentee / high LWOP (50% present, 20% half-day, 30% absent) -> triggers negative net pay!
        
        emp_profiles = {}
        for idx, emp in enumerate(employees):
            emp_id = emp['employee_id']
            if idx in [4, 8, 13]: # High absence / excessive tardy for negative net testing
                emp_profiles[emp_id] = 'D'
            elif idx % 4 == 1:
                emp_profiles[emp_id] = 'C'
            elif idx % 4 == 2:
                emp_profiles[emp_id] = 'A'
            else:
                emp_profiles[emp_id] = 'B'

        for emp in employees:
            emp_id = emp['employee_id']
            is_teaching = (emp.get('employee_type') == 'TEACHING') or ('teacher' in (emp.get('designation') or '').lower())
            prof = emp_profiles[emp_id]

            # Official standard schedule:
            # Teaching: AM 07:30 - 11:30 | PM 13:00 - 17:00
            # Non-Teaching: AM 08:00 - 12:00 | PM 13:00 - 17:00
            am_start_h, am_start_m = (7, 30) if is_teaching else (8, 0)
            am_end_h, am_end_m = (11, 30) if is_teaching else (12, 0)
            pm_start_h, pm_start_m = (13, 0), (13, 0)
            pm_end_h, pm_end_m = (17, 0), (17, 0)

            for d in work_dates:
                roll = random.random()

                # Determine attendance condition based on profile
                if prof == 'D':
                    # High absence / half-day
                    if roll < 0.35:
                        continue # Absent! No logs
                    elif roll < 0.55:
                        condition = 'halfday_am' # Only morning logged
                    elif roll < 0.75:
                        condition = 'late_heavy' # 30-75 mins late
                    else:
                        condition = 'ontime'
                elif prof == 'C':
                    # Frequent tardy & undertime
                    if roll < 0.08:
                        continue # Absent
                    elif roll < 0.35:
                        condition = 'late_moderate' # 15-40 mins late
                    elif roll < 0.50:
                        condition = 'undertime' # Leaves 20-50 mins early
                    elif roll < 0.60:
                        condition = 'late_and_undertime'
                    else:
                        condition = 'ontime'
                elif prof == 'A':
                    # Punctual
                    if roll < 0.02:
                        continue # Rare absent
                    elif roll < 0.10:
                        condition = 'late_light' # 2-8 mins late
                    else:
                        condition = 'ontime'
                else: # Profile B
                    if roll < 0.06:
                        continue # Absent
                    elif roll < 0.20:
                        condition = 'late_moderate'
                    elif roll < 0.28:
                        condition = 'undertime'
                    elif roll < 0.32:
                        condition = 'halfday_pm' # Only afternoon
                    else:
                        condition = 'ontime'

                # Now generate realistic timestamps
                am_in = None
                am_out = None
                pm_in = None
                pm_out = None

                if condition == 'ontime':
                    early_m = random.randint(5, 20)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=early_m)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m) + timedelta(minutes=random.randint(0, 8))
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) - timedelta(minutes=random.randint(3, 15))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) + timedelta(minutes=random.randint(2, 18))

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_light':
                    late_min = random.randint(3, 12)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late_min)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m) + timedelta(minutes=random.randint(0, 5))
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) - timedelta(minutes=random.randint(1, 10))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) + timedelta(minutes=random.randint(0, 10))

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_moderate':
                    late_min = random.randint(15, 38)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late_min)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_late = random.randint(0, 15)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) + timedelta(minutes=pm_late)
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) + timedelta(minutes=random.randint(0, 10))

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_heavy':
                    late_min = random.randint(45, 95)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late_min)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) + timedelta(minutes=random.randint(10, 35))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0)

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'undertime':
                    early_leave = random.randint(20, 65)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=5)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0)
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) - timedelta(minutes=early_leave)

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'late_and_undertime':
                    late_min = random.randint(20, 45)
                    under_min = random.randint(25, 55)
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) + timedelta(minutes=late_min)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0)
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0) - timedelta(minutes=under_min)

                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                elif condition == 'halfday_am':
                    am_in_dt = datetime(d.year, d.month, d.day, am_start_h, am_start_m) - timedelta(minutes=5)
                    am_out_dt = datetime(d.year, d.month, d.day, am_end_h, am_end_m)
                    am_in = am_in_dt.strftime('%H:%M:%S')
                    am_out = am_out_dt.strftime('%H:%M:%S')

                elif condition == 'halfday_pm':
                    pm_in_dt = datetime(d.year, d.month, d.day, 13, 0) + timedelta(minutes=random.randint(0, 10))
                    pm_out_dt = datetime(d.year, d.month, d.day, 17, 0)
                    pm_in = pm_in_dt.strftime('%H:%M:%S')
                    pm_out = pm_out_dt.strftime('%H:%M:%S')

                time_log_inserts.append((
                    emp_id, d, am_in, am_out, pm_in, pm_out
                ))

                if am_in:
                    bio_log_inserts.append((emp_id, 'am_time_in', f"{d} {am_in}"))
                if am_out:
                    bio_log_inserts.append((emp_id, 'am_time_out', f"{d} {am_out}"))
                if pm_in:
                    bio_log_inserts.append((emp_id, 'pm_time_in', f"{d} {pm_in}"))
                if pm_out:
                    bio_log_inserts.append((emp_id, 'pm_time_out', f"{d} {pm_out}"))

        print(f"Inserting {len(time_log_inserts)} time log records...")
        cur.executemany("""
            INSERT INTO tbltime_logs (employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, work_date) DO UPDATE
            SET am_time_in = EXCLUDED.am_time_in,
                am_time_out = EXCLUDED.am_time_out,
                pm_time_in = EXCLUDED.pm_time_in,
                pm_time_out = EXCLUDED.pm_time_out
        """, time_log_inserts)

        print(f"Inserting {len(bio_log_inserts)} biometric punch records...")
        cur.executemany("""
            INSERT INTO tblbiometric_logs (employee_id, log_type, log_time)
            VALUES (%s, %s, %s)
        """, bio_log_inserts)

        print("[SUCCESS] Sample attendance and biometric logs generated for August and September 2026!")

if __name__ == '__main__':
    generate_logs()
