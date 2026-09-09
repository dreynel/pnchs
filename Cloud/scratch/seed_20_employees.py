import mysql.connector
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db import db_cursor

EMPLOYEES_DATA = [
    # 1 Principal (Admin)
    {
        "id": "EMP-001", "first_name": "Maria Fe", "last_name": "Santos", "designation": "Principal I",
        "employee_type": "TEACHING", "salary_grade": 19, "step": 1, "basic": 59153.00,
        "role": "Admin", "username": "santos", "birthday": "1978-05-14", "email": "principal@pnchs.edu.ph"
    },
    # 3 HR (HR)
    {
        "id": "EMP-002", "first_name": "Juan", "last_name": "Cruz", "designation": "Administrative Officer IV (HRMO II)",
        "employee_type": "NON_TEACHING", "salary_grade": 14, "step": 1, "basic": 38764.00,
        "role": "HR", "username": "cruz", "birthday": "1985-08-20", "email": "hr1@pnchs.edu.ph"
    },
    {
        "id": "EMP-003", "first_name": "Clara", "last_name": "Reyes", "designation": "Administrative Officer I (HR Aide)",
        "employee_type": "NON_TEACHING", "salary_grade": 11, "step": 1, "basic": 31705.00,
        "role": "HR", "username": "reyes", "birthday": "1990-03-12", "email": "hr2@pnchs.edu.ph"
    },
    {
        "id": "EMP-004", "first_name": "Elena", "last_name": "Mendoza", "designation": "Administrative Assistant I (HR Assistant)",
        "employee_type": "NON_TEACHING", "salary_grade": 7, "step": 1, "basic": 20914.00,
        "role": "HR", "username": "mendoza", "birthday": "1993-11-05", "email": "hr3@pnchs.edu.ph"
    },
    # 2 Finance (Finance)
    {
        "id": "EMP-005", "first_name": "Roberto", "last_name": "Garcia", "designation": "Accountant III",
        "employee_type": "NON_TEACHING", "salary_grade": 19, "step": 1, "basic": 59153.00,
        "role": "Finance", "username": "garcia", "birthday": "1982-01-25", "email": "finance1@pnchs.edu.ph"
    },
    {
        "id": "EMP-006", "first_name": "Teresa", "last_name": "Del Rosario", "designation": "Administrative Assistant II (Bookkeeper)",
        "employee_type": "NON_TEACHING", "salary_grade": 8, "step": 1, "basic": 22423.00,
        "role": "Finance", "username": "delrosario", "birthday": "1988-06-18", "email": "finance2@pnchs.edu.ph"
    },
    # 1 Auditor (Auditor)
    {
        "id": "EMP-007", "first_name": "Gabriel", "last_name": "Aquino", "designation": "State Auditor II",
        "employee_type": "NON_TEACHING", "salary_grade": 18, "step": 1, "basic": 53818.00,
        "role": "Auditor", "username": "aquino", "birthday": "1984-09-30", "email": "auditor@pnchs.edu.ph"
    },
    # 2 Security Guards
    {
        "id": "EMP-008", "first_name": "Ramon", "last_name": "Dela Cruz", "designation": "Security Guard I",
        "employee_type": "NON_TEACHING", "salary_grade": 3, "step": 1, "basic": 16486.00,
        "role": "Employee", "username": "delacruz", "birthday": "1986-04-15", "email": "rdelacruz@pnchs.edu.ph"
    },
    {
        "id": "EMP-009", "first_name": "Juancho", "last_name": "Dizon", "designation": "Security Guard II",
        "employee_type": "NON_TEACHING", "salary_grade": 5, "step": 1, "basic": 18581.00,
        "role": "Employee", "username": "dizon", "birthday": "1989-09-22", "email": "jdizon@pnchs.edu.ph"
    },
    # 11 Staff & Faculty Employees
    {
        "id": "EMP-010", "first_name": "Jose", "last_name": "Rizal", "designation": "Teacher I",
        "employee_type": "TEACHING", "salary_grade": 11, "step": 1, "basic": 31705.00,
        "role": "Employee", "username": "rizal", "birthday": "1991-06-19", "email": "jrizal@pnchs.edu.ph"
    },
    {
        "id": "EMP-011", "first_name": "Andres", "last_name": "Bonifacio", "designation": "Teacher I",
        "employee_type": "TEACHING", "salary_grade": 11, "step": 1, "basic": 31705.00,
        "role": "Employee", "username": "bonifacio", "birthday": "1992-11-30", "email": "abonifacio@pnchs.edu.ph"
    },
    {
        "id": "EMP-012", "first_name": "Melchora", "last_name": "Ramos", "designation": "Teacher II",
        "employee_type": "TEACHING", "salary_grade": 12, "step": 1, "basic": 33947.00,
        "role": "Employee", "username": "ramos", "birthday": "1987-01-06", "email": "mramos@pnchs.edu.ph"
    },
    {
        "id": "EMP-013", "first_name": "Apolinario", "last_name": "Mabini", "designation": "Teacher II",
        "employee_type": "TEACHING", "salary_grade": 12, "step": 1, "basic": 33947.00,
        "role": "Employee", "username": "mabini", "birthday": "1988-07-23", "email": "amabini@pnchs.edu.ph"
    },
    {
        "id": "EMP-014", "first_name": "Marcelo", "last_name": "Del Pilar", "designation": "Teacher III",
        "employee_type": "TEACHING", "salary_grade": 13, "step": 1, "basic": 36125.00,
        "role": "Employee", "username": "delpilar", "birthday": "1985-08-30", "email": "mdelpilar@pnchs.edu.ph"
    },
    {
        "id": "EMP-015", "first_name": "Emilio", "last_name": "Jacinto", "designation": "Teacher III",
        "employee_type": "TEACHING", "salary_grade": 13, "step": 1, "basic": 36125.00,
        "role": "Employee", "username": "jacinto", "birthday": "1993-12-15", "email": "ejacinto@pnchs.edu.ph"
    },
    {
        "id": "EMP-016", "first_name": "Graciano", "last_name": "Jaena", "designation": "Master Teacher I",
        "employee_type": "TEACHING", "salary_grade": 18, "step": 1, "basic": 53818.00,
        "role": "Employee", "username": "jaena", "birthday": "1980-12-18", "email": "gjaena@pnchs.edu.ph"
    },
    {
        "id": "EMP-017", "first_name": "Teresa", "last_name": "Magbanua", "designation": "Master Teacher II",
        "employee_type": "TEACHING", "salary_grade": 19, "step": 1, "basic": 59153.00,
        "role": "Employee", "username": "magbanua", "birthday": "1981-10-13", "email": "tmagbanua@pnchs.edu.ph"
    },
    {
        "id": "EMP-018", "first_name": "Francisco", "last_name": "Baltazar", "designation": "Administrative Aide IV (Clerk I)",
        "employee_type": "NON_TEACHING", "salary_grade": 4, "step": 1, "basic": 17506.00,
        "role": "Employee", "username": "baltazar", "birthday": "1994-04-02", "email": "fbaltazar@pnchs.edu.ph"
    },
    {
        "id": "EMP-019", "first_name": "Gregorio", "last_name": "Agoncillo", "designation": "Nurse I",
        "employee_type": "NON_TEACHING", "salary_grade": 10, "step": 1, "basic": 26917.00,
        "role": "Employee", "username": "agoncillo", "birthday": "1990-11-14", "email": "gagoncillo@pnchs.edu.ph"
    },
    {
        "id": "EMP-020", "first_name": "Trinidad", "last_name": "Tecson", "designation": "Guidance Counselor I",
        "employee_type": "NON_TEACHING", "salary_grade": 11, "step": 1, "basic": 31705.00,
        "role": "Employee", "username": "tecson", "birthday": "1988-11-18", "email": "ttecson@pnchs.edu.ph"
    }
]

DEFAULT_PASSWORD = "Password123!"

def seed_db(conn, db_name="Local"):
    print(f"\n--- Seeding {db_name} Database ---")
    cur = conn.cursor(dictionary=True)

    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    cur.execute("DELETE FROM tblusers")
    cur.execute("DELETE FROM tblemployee")
    cur.execute("DELETE FROM tblpayhead")
    cur.execute("DELETE FROM tblleave_balances")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")

    for emp in EMPLOYEES_DATA:
        # Insert tblemployee
        cur.execute("""
            INSERT INTO tblemployee 
            (employee_id, first_name, last_name, designation, employee_type, salary_grade, step, employment_status, birthday, email, contact, address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Active', %s, %s, '+63 917 123 4567', 'Passi City, Iloilo')
        """, (
            emp['id'], emp['first_name'], emp['last_name'], emp['designation'],
            emp['employee_type'], emp['salary_grade'], emp['step'],
            emp['birthday'], emp['email']
        ))

        # Insert Basic Salary Payhead
        cur.execute("""
            INSERT INTO tblpayhead (employee_id, pay_head, description, amount, category, mode, percentage_value)
            VALUES (%s, 'Basic Salary', 'Base Monthly Salary Rate', %s, 'Earning', 'Amount', 0.00)
        """, (emp['id'], emp['basic']))

        # Insert User account with password = Password123! and username = emp['username']
        fullname = f"{emp['first_name']} {emp['last_name']}"
        cur.execute("""
            INSERT INTO tblusers (username, password, name, role, employee_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (emp['username'], DEFAULT_PASSWORD, fullname, emp['role'], emp['id']))

        # Insert Leave Balances (4800 mins = 10 days default)
        cur.execute("""
            INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes)
            VALUES (%s, 4800, 4800)
        """, (emp['id'],))

        print(f" [+] Created {emp['id']} | Username: {emp['username']} | {fullname} | Role: {emp['role']} | Desig: {emp['designation']}")

    conn.commit()

    # Verification counts
    cur.execute("SELECT COUNT(*) as emp_cnt FROM tblemployee")
    e_cnt = cur.fetchone()['emp_cnt']
    cur.execute("SELECT COUNT(*) as usr_cnt FROM tblusers")
    u_cnt = cur.fetchone()['usr_cnt']

    print(f"\nVerification {db_name}: tblemployee={e_cnt}, tblusers={u_cnt}")
    cur.close()

def main():
    # 1. Local Database
    try:
        with db_cursor(commit=True) as (local_conn, cur):
            seed_db(local_conn, "Local")
    except Exception as e:
        print(f"Local seed error: {e}")

    # 2. Remote Database (187.52.121.22)
    try:
        remote_conn = mysql.connector.connect(
            host="187.52.121.22",
            user="pnchs_user",
            password="YourSecurePassword123!",
            database="dbpnchs",
            connect_timeout=15
        )
        seed_db(remote_conn, "Remote (187.52.121.22)")
        remote_conn.close()
    except Exception as e:
        print(f"Remote seed error: {e}")

if __name__ == '__main__':
    main()
