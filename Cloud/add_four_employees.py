"""
Add 4 employees:
- Jasper Ian Susarno
- Quiron Bermejo
- Nino Justin Silguera
- Alfred Treyes

Includes:
1. tblemployee records
2. tblleave_balances (4,800 mins each)
3. tblpayhead (Basic Salary = 36,125.00, SG 13 Step 1)
4. tblusers portal logins (Password123!)
5. tbltime_logs & tblbiometric_logs (Jan 1, 2026 to Oct 10, 2026)
"""
import random
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from db import db_cursor

NEW_EMPLOYEES = [
    {
        "id": "EMP-031",
        "first_name": "Jasper Ian",
        "middle_name": "P.",
        "last_name": "Susarno",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "jsusarno",
        "email": "jasperiansusarno9@gmail.com",
        "contact": "+63 960 311 0618",
        "bday": "1994-03-31"
    },
    {
        "id": "EMP-032",
        "first_name": "Quiron",
        "middle_name": "Pineda",
        "last_name": "Bermejo",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "qbermejo",
        "email": "quironbermejo246888@gmail.com",
        "contact": "+63 917 482 1934",
        "bday": "1992-07-15"
    },
    {
        "id": "EMP-033",
        "first_name": "Nino Justin",
        "middle_name": "D.",
        "last_name": "Silguera",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "nsilguera",
        "email": "ninojustin.silguera@pnchs.edu.ph",
        "contact": "+63 928 554 9021",
        "bday": "1995-11-22"
    },
    {
        "id": "EMP-034",
        "first_name": "Alfred",
        "middle_name": "",
        "last_name": "Treyes",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "atreyes",
        "email": "alfedtreyes192021@gmail.com",
        "contact": "+63 919 723 4589",
        "bday": "1991-05-18"
    }
]

def add_employees():
    random.seed(34)
    hashed_pwd = generate_password_hash("Password123!")
    assert check_password_hash(hashed_pwd, "Password123!")

    with db_cursor(commit=True) as (conn, cur):
        print("1. Inserting 4 employees into tblemployee, tblleave_balances, tblpayhead, tblusers...")
        for emp in NEW_EMPLOYEES:
            emp_id = emp["id"]
            fn = emp["first_name"]
            mn = emp["middle_name"]
            ln = emp["last_name"]
            desig = emp["designation"]
            sg = emp["salary_grade"]
            step = emp["step"]
            email = emp["email"]
            contact = emp["contact"]
            bday = emp["bday"]
            username = emp["username"]
            full_name = f"{fn} {mn} {ln}".strip() if mn else f"{fn} {ln}".strip()

            # Insert / Upsert Employee
            cur.execute("""
                INSERT INTO tblemployee (
                    employee_id, first_name, middle_name, last_name,
                    designation, employee_type, salary_grade, step,
                    employment_status, birthday, email, contact, address
                ) VALUES (%s, %s, %s, %s, %s, 'TEACHING', %s, %s, 'Active', %s, %s, %s, 'Pototan, Iloilo')
                ON DUPLICATE KEY UPDATE
                    first_name=VALUES(first_name),
                    middle_name=VALUES(middle_name),
                    last_name=VALUES(last_name),
                    designation=VALUES(designation),
                    salary_grade=VALUES(salary_grade),
                    step=VALUES(step),
                    email=VALUES(email),
                    contact=VALUES(contact)
            """, (emp_id, fn, mn, ln, desig, sg, step, bday, email, contact))

            # Leave Balance
            cur.execute("""
                INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes)
                VALUES (%s, 4800, 4800)
                ON DUPLICATE KEY UPDATE vl_minutes=4800, sl_minutes=4800
            """, (emp_id,))

            # Basic Salary Payhead
            cur.execute("""
                DELETE FROM tblpayhead WHERE employee_id = %s
            """, (emp_id,))
            cur.execute("""
                INSERT INTO tblpayhead (employee_id, pay_head, description, amount, category, mode, percentage_value)
                VALUES (%s, 'Basic Salary', 'Monthly Basic Salary (SSL VI / EO 64)', %s, 'Earning', 'Amount', 0.00)
            """, (emp_id, emp["base_salary"]))

            # User Portal Account
            cur.execute("""
                INSERT INTO tblusers (username, password, name, role, employee_id)
                VALUES (%s, %s, %s, 'Employee', %s)
                ON DUPLICATE KEY UPDATE password=VALUES(password), name=VALUES(name), employee_id=VALUES(employee_id)
            """, (username, hashed_pwd, full_name, emp_id))

            print(f"[OK] Added/Updated: {emp_id} - {full_name} ({username})")

        print("2. Generating Realistic Time Logs from Jan 1, 2026 to Oct 10, 2026...")
        # Get holidays
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

        print(f"Eligible work dates: {len(work_dates)}")

        time_batch = []
        bio_batch = []

        for emp in NEW_EMPLOYEES:
            emp_id = emp["id"]
            # Clean old logs if any
            cur.execute("DELETE FROM tbltime_logs WHERE employee_id = %s", (emp_id,))
            cur.execute("DELETE FROM tblbiometric_logs WHERE employee_id = %s", (emp_id,))

            for d in work_dates:
                roll = random.random()

                if roll < 0.01:
                    continue  # Absent
                elif roll < 0.03:
                    # Half day AM
                    in_m = random.randint(12, 28)
                    am_in = f"07:{in_m:02d}:00"
                    am_out = f"11:{random.randint(30, 35):02d}:00"
                    pm_in = None
                    pm_out = None
                elif roll < 0.09:
                    # Late morning
                    late_min = random.randint(35, 52)
                    am_in = f"07:{late_min:02d}:00"
                    am_out = f"11:{random.randint(30, 35):02d}:00"
                    pm_in = f"12:{random.randint(50, 58):02d}:00"
                    pm_out = f"17:{random.randint(0, 12):02d}:00"
                elif roll < 0.12:
                    # Undertime in afternoon
                    in_m = random.randint(15, 27)
                    am_in = f"07:{in_m:02d}:00"
                    am_out = f"11:{random.randint(30, 35):02d}:00"
                    pm_in = f"12:{random.randint(50, 58):02d}:00"
                    pm_out = f"16:{random.randint(32, 50):02d}:00"
                else:
                    # On time
                    in_m = random.randint(12, 27)
                    am_in = f"07:{in_m:02d}:00"
                    am_out = f"11:{random.randint(30, 35):02d}:00"
                    pm_in = f"12:{random.randint(50, 58):02d}:00"
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

        print(f"Batch inserting {len(time_batch)} daily time logs...")
        chunk_size = 500
        for i in range(0, len(time_batch), chunk_size):
            chunk = time_batch[i:i + chunk_size]
            cur.executemany("""
                INSERT INTO tbltime_logs (employee_id, work_date, am_time_in, am_time_out, pm_time_in, pm_time_out)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, chunk)

        print(f"Batch inserting {len(bio_batch)} biometric punch logs...")
        for i in range(0, len(bio_batch), chunk_size):
            chunk = bio_batch[i:i + chunk_size]
            cur.executemany("""
                INSERT INTO tblbiometric_logs (employee_id, log_type, log_time)
                VALUES (%s, %s, %s)
            """, chunk)

        print(f"[SUCCESS] Finished adding 4 employees with {len(time_batch)} time logs and {len(bio_batch)} biometric punches!")

if __name__ == '__main__':
    add_employees()
