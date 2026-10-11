"""
Regenerate Attendance Logs (Jan 1, 2026 - Oct 10, 2026) for 7:00 AM - 12:00 PM and 1:00 PM - 5:00 PM Schedule.
Also cleans all payroll data (tblpayroll, tblpayroll_details, tblapprovals) to allow fresh calculations.
"""
import random
from datetime import date, datetime, timedelta
from db import db_cursor

def regenerate_logs():
    random.seed(2026)

    with db_cursor(commit=True) as (conn, cur):
        print("1. Cleaning payroll calculation data and existing attendance logs...")
        cur.execute("DELETE FROM tblpayroll_details")
        cur.execute("DELETE FROM tblpayroll")
        cur.execute("DELETE FROM tblapprovals WHERE DocType = 'Payroll'")
        cur.execute("DELETE FROM tbltime_logs")
        cur.execute("DELETE FROM tblbiometric_logs")
        print("[OK] Payroll data and attendance logs purged.")

        # Fetch all active employees
        cur.execute("SELECT employee_id, first_name, last_name, designation FROM tblemployee WHERE LOWER(COALESCE(employment_status, 'active')) = 'active' ORDER BY id")
        employees = cur.fetchall()
        print(f"Loaded {len(employees)} active employees.")

        # Fetch holidays in 2026
        cur.execute("SELECT holiday_date FROM tblholidays WHERE holiday_date BETWEEN '2026-01-01' AND '2026-10-10'")
        holiday_set = {r['holiday_date'] for r in cur.fetchall()}

        start_date = date(2026, 1, 1)
        end_date = date(2026, 10, 10)

        work_dates = []
        cur_d = start_date
        while cur_d <= end_date:
            if cur_d.weekday() < 5 and cur_d not in holiday_set:
                work_dates.append(cur_d)
            cur_d += timedelta(days=1)

        print(f"Total eligible work dates: {len(work_dates)}")

        time_batch = []
        bio_batch = []

        # Standard Minimum Hours:
        # Morning:   07:00 AM - 12:00 PM (AM in before 07:00 is on-time)
        # Afternoon: 01:00 PM - 05:00 PM (PM out at/after 17:00 is on-time)
        for emp in employees:
            emp_id = emp["employee_id"]

            for d in work_dates:
                roll = random.random()

                # Attendance distribution:
                # 88% on time
                # 6% slight morning tardiness (7:04 - 7:25 AM)
                # 3% undertime in afternoon (leave 4:30 - 4:50 PM)
                # 2% half-day AM only
                # 1% absent
                if roll < 0.01:
                    continue  # Absent
                elif roll < 0.03:
                    # Half-day AM
                    am_in = f"06:{random.randint(45, 58):02d}:00"
                    am_out = f"12:{random.randint(0, 6):02d}:00"
                    pm_in = None
                    pm_out = None
                elif roll < 0.09:
                    # Tardy morning arrival (after 7:00 AM)
                    late_min = random.randint(4, 25)
                    am_in = f"07:{late_min:02d}:00"
                    am_out = f"12:{random.randint(0, 6):02d}:00"
                    pm_in = f"12:{random.randint(50, 58):02d}:00"
                    pm_out = f"17:{random.randint(0, 12):02d}:00"
                elif roll < 0.12:
                    # Undertime in afternoon (before 5:00 PM)
                    am_in = f"06:{random.randint(45, 58):02d}:00"
                    am_out = f"12:{random.randint(0, 6):02d}:00"
                    pm_in = f"12:{random.randint(50, 58):02d}:00"
                    pm_out = f"16:{random.randint(32, 52):02d}:00"
                else:
                    # On time (Punched before 7:00 AM, out 12:00 PM+, in before 1:00 PM, out 5:00 PM+)
                    am_in = f"06:{random.randint(45, 58):02d}:00"
                    am_out = f"12:{random.randint(0, 8):02d}:00"
                    pm_in = f"12:{random.randint(48, 58):02d}:00"
                    pm_out = f"17:{random.randint(0, 15):02d}:00"

                time_batch.append((emp_id, d, am_in, am_out, pm_in, pm_out))

                if am_in:
                    bio_batch.append((emp_id, 'am_time_in', f"{d} {am_in}"))
                if am_out:
                    bio_batch.append((emp_id, 'am_time_out', f"{d} {am_out}"))
                if pm_in:
                    bio_batch.append((emp_id, 'pm_time_in', f"{d} {pm_in}"))
                if pm_out:
                    bio_batch.append((emp_id, 'pm_time_out', f"{d} {pm_out}"))

        print(f"2. Batch inserting {len(time_batch)} daily time logs...")
        chunk_size = 1000
        for i in range(0, len(time_batch), chunk_size):
            chunk = time_batch[i:i + chunk_size]
            cur.executemany("""
                INSERT INTO tbltime_logs (employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, chunk)

        print(f"3. Batch inserting {len(bio_batch)} biometric punch logs...")
        for i in range(0, len(bio_batch), chunk_size):
            chunk = bio_batch[i:i + chunk_size]
            cur.executemany("""
                INSERT INTO tblbiometric_logs (employee_id, log_type, log_time)
                VALUES (%s, %s, %s)
            """, chunk)

        # Verification check
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll")
        rem_payroll = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll_details")
        rem_details = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tblapprovals WHERE DocType = 'Payroll'")
        rem_approvals = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tbltime_logs")
        total_time_logs = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tblbiometric_logs")
        total_bio_logs = cur.fetchone()['c']

        print(f"[SUCCESS] Regeneration complete:")
        print(f"  - tblpayroll: {rem_payroll} (cleaned)")
        print(f"  - tblpayroll_details: {rem_details} (cleaned)")
        print(f"  - tblapprovals (Payroll): {rem_approvals} (cleaned)")
        print(f"  - tbltime_logs: {total_time_logs} records (7:00 AM - 12:00 PM & 1:00 PM - 5:00 PM)")
        print(f"  - tblbiometric_logs: {total_bio_logs} punches")

if __name__ == '__main__':
    regenerate_logs()
