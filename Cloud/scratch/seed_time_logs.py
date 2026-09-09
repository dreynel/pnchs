import mysql.connector
import sys
import os
import random
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db import db_cursor
from services.policy_engine import AttendancePolicyService

# Holidays in July - Sept 2026
HOLIDAYS_2026 = {
    date(2026, 8, 21),  # Ninoy Aquino Day
    date(2026, 8, 31),  # National Heroes Day
}

def generate_work_dates(start_date, end_date):
    curr = start_date
    work_dates = []
    while curr <= end_date:
        if curr.weekday() < 5 and curr not in HOLIDAYS_2026:
            work_dates.append(curr)
        curr += timedelta(days=1)
    return work_dates

def build_time_log(emp, work_date):
    emp_type = emp.get('employee_type', 'NON_TEACHING').upper()
    desig = emp.get('designation', '')
    is_teaching = (emp_type == 'TEACHING')

    roll = random.randint(1, 100)
    if roll <= 70:
        scenario = 'ON_TIME'
    elif roll <= 82:
        scenario = 'LATE'
    elif roll <= 90:
        scenario = 'UNDERTIME'
    elif roll <= 94:
        scenario = 'LATE_UNDERTIME'
    elif roll <= 97:
        scenario = 'HALF_DAY'
    else:
        scenario = 'ABSENT'

    if scenario == 'ABSENT':
        return None

    if is_teaching:
        base_am_in = "07:25:00"
        base_am_out = "11:30:00"
        base_pm_in = "12:55:00"
        base_pm_out = "17:00:00"
    else:
        base_am_in = "07:55:00"
        base_am_out = "12:00:00"
        base_pm_in = "12:55:00"
        base_pm_out = "17:00:00"

    am_in_str = base_am_in
    am_out_str = base_am_out
    pm_in_str = base_pm_in
    pm_out_str = base_pm_out

    if scenario == 'LATE':
        late_mins = random.choice([15, 20, 25, 30, 40, 45])
        if is_teaching:
            am_in_str = (datetime.strptime("07:30:00", "%H:%M:%S") + timedelta(minutes=late_mins)).strftime("%H:%M:%S")
        else:
            am_in_str = (datetime.strptime("08:00:00", "%H:%M:%S") + timedelta(minutes=late_mins)).strftime("%H:%M:%S")

    elif scenario == 'UNDERTIME':
        ut_mins = random.choice([15, 25, 30, 45, 60])
        pm_out_str = (datetime.strptime("17:00:00", "%H:%M:%S") - timedelta(minutes=ut_mins)).strftime("%H:%M:%S")

    elif scenario == 'LATE_UNDERTIME':
        late_mins = random.choice([15, 30])
        ut_mins = random.choice([20, 40])
        if is_teaching:
            am_in_str = (datetime.strptime("07:30:00", "%H:%M:%S") + timedelta(minutes=late_mins)).strftime("%H:%M:%S")
        else:
            am_in_str = (datetime.strptime("08:00:00", "%H:%M:%S") + timedelta(minutes=late_mins)).strftime("%H:%M:%S")
        pm_out_str = (datetime.strptime("17:00:00", "%H:%M:%S") - timedelta(minutes=ut_mins)).strftime("%H:%M:%S")

    elif scenario == 'HALF_DAY':
        pm_in_str = None
        pm_out_str = None

    actual_classroom = 360 if is_teaching else 0
    teaching_related = 120 if is_teaching else 0
    teaching_approved = 1 if is_teaching else 0

    metrics = AttendancePolicyService.calculate_tardiness_and_undertime(
        employee_type=emp_type,
        designation=desig,
        am_in=am_in_str,
        am_out=am_out_str,
        pm_in=pm_in_str,
        pm_out=pm_out_str,
        actual_classroom_minutes=actual_classroom,
        teaching_related_minutes=teaching_related,
        teaching_related_approved=bool(teaching_approved)
    )

    tardiness_mins = metrics['tardiness_minutes']
    undertime_mins = metrics['undertime_minutes']

    if scenario == 'ON_TIME':
        remarks = "On Time"
    elif scenario == 'HALF_DAY':
        remarks = "Half-Day AM Only"
    else:
        parts = []
        if tardiness_mins > 0:
            parts.append(f"Tardy ({tardiness_mins}m)")
        if undertime_mins > 0:
            parts.append(f"Undertime ({undertime_mins}m)")
        remarks = ", ".join(parts) if parts else "Present"

    return (
        emp['employee_id'], work_date, am_in_str, am_out_str,
        pm_in_str, pm_out_str, actual_classroom,
        teaching_related, teaching_approved,
        tardiness_mins, undertime_mins,
        0, 0, remarks
    )

def seed_time_logs_for_db(conn, db_name="Local"):
    print(f"\n--- Batch Seeding Time Logs for {db_name} Database ---")
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT employee_id, first_name, last_name, designation, employee_type FROM tblemployee")
    employees = cur.fetchall()

    if not employees:
        print(" [!] No employees found in database.")
        cur.close()
        return

    cur.execute("DELETE FROM tbltime_logs WHERE work_date BETWEEN '2026-07-01' AND '2026-09-09'")

    start_date = date(2026, 7, 1)
    end_date = date(2026, 9, 9)
    work_dates = generate_work_dates(start_date, end_date)

    batch_data = []
    tardy_count = 0
    undertime_count = 0

    for emp in employees:
        for wdate in work_dates:
            row = build_time_log(emp, wdate)
            if row:
                batch_data.append(row)
                if row[9] > 0: # tardiness_minutes
                    tardy_count += 1
                if row[10] > 0: # undertime_minutes
                    undertime_count += 1

    insert_sql = """
        INSERT INTO tbltime_logs (
            employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out,
            actual_classroom_teaching_minutes, teaching_related_minutes, teaching_related_approved,
            tardiness_minutes, undertime_minutes, vl_minutes_charged, unpaid_minutes, remarks
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) ON DUPLICATE KEY UPDATE
            am_time_in=VALUES(am_time_in), am_time_out=VALUES(am_time_out),
            pm_time_in=VALUES(pm_time_in), pm_time_out=VALUES(pm_time_out),
            tardiness_minutes=VALUES(tardiness_minutes), undertime_minutes=VALUES(undertime_minutes),
            remarks=VALUES(remarks)
    """

    cur.executemany(insert_sql, batch_data)
    conn.commit()
    print(f" [+] {db_name} Batch Seeding Complete: {len(batch_data)} total logs created (Tardy: {tardy_count}, Undertime: {undertime_count})")
    cur.close()

def main():
    # 1. Local Database
    try:
        with db_cursor(commit=True) as (local_conn, cur):
            seed_time_logs_for_db(local_conn, "Local")
    except Exception as e:
        print(f"Local time log seed error: {e}")

    # 2. Remote Database (187.52.121.22)
    try:
        remote_conn = mysql.connector.connect(
            host="187.52.121.22",
            user="pnchs_user",
            password="YourSecurePassword123!",
            database="dbpnchs",
            connect_timeout=15
        )
        seed_time_logs_for_db(remote_conn, "Remote (187.52.121.22)")
        remote_conn.close()
    except Exception as e:
        print(f"Remote time log seed error: {e}")

if __name__ == '__main__':
    main()
