"""
Seed New 30-Employee Roster and Complete Attendance Logs (Jan 1, 2026 - Oct 10, 2026)
for Pototan National Comprehensive High School (PNCHS).
"""
import random
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash
from db import db_cursor

# 30-Personnel Verified Directory from DepEd SSL VI / EO 64
ROSTER = [
    {
        "id": "EMP-001",
        "first_name": "Gemma",
        "middle_name": "B.",
        "last_name": "Peñaranda",
        "title": "Dr.",
        "designation": "Principal IV",
        "salary_grade": 22,
        "step": 4,
        "base_salary": 85431.00,
        "username": "gpenaranda",
        "email": "gemma.penaranda@pnchs.edu.ph"
    },
    {
        "id": "EMP-002",
        "first_name": "Marites",
        "middle_name": "",
        "last_name": "Torres",
        "title": "",
        "designation": "Assistant School Principal II",
        "salary_grade": 19,
        "step": 4,
        "base_salary": 61916.00,
        "username": "mtorres",
        "email": "marites.torres@pnchs.edu.ph"
    },
    {
        "id": "EMP-003",
        "first_name": "Resty",
        "middle_name": "T.",
        "last_name": "Margarse",
        "title": "",
        "designation": "Assistant School Principal II",
        "salary_grade": 19,
        "step": 4,
        "base_salary": 61916.00,
        "username": "rmargarse",
        "email": "resty.margarse@pnchs.edu.ph"
    },
    {
        "id": "EMP-004",
        "first_name": "Arlene",
        "middle_name": "",
        "last_name": "Castañeda II",
        "title": "",
        "designation": "Assistant School Head / Master Teacher",
        "salary_grade": 19,
        "step": 1,
        "base_salary": 59153.00,
        "username": "acastaneda",
        "email": "arlene.castaneda@pnchs.edu.ph"
    },
    {
        "id": "EMP-005",
        "first_name": "Tesa Joy",
        "middle_name": "B.",
        "last_name": "Pachica",
        "title": "Dr.",
        "designation": "Principal In-Charge (District I)",
        "salary_grade": 20,
        "step": 1,
        "base_salary": 66052.00,
        "username": "tpachica",
        "email": "tesajoy.pachica@pnchs.edu.ph"
    },
    {
        "id": "EMP-006",
        "first_name": "Elma",
        "middle_name": "Operio",
        "last_name": "Provido",
        "title": "Dr.",
        "designation": "Head Teacher VI (Dept. Head)",
        "salary_grade": 19,
        "step": 1,
        "base_salary": 51357.00,
        "username": "eprovido",
        "email": "elma.provido@pnchs.edu.ph"
    },
    {
        "id": "EMP-007",
        "first_name": "Brigida",
        "middle_name": "Dacayan",
        "last_name": "Beronilla",
        "title": "",
        "designation": "Master Teacher I",
        "salary_grade": 18,
        "step": 1,
        "base_salary": 53818.00,
        "username": "bberonilla",
        "email": "brigida.beronilla@pnchs.edu.ph"
    },
    {
        "id": "EMP-008",
        "first_name": "Liezl",
        "middle_name": "",
        "last_name": "Pondevida",
        "title": "",
        "designation": "Teacher Department Head",
        "salary_grade": 16,
        "step": 1,
        "base_salary": 45694.00,
        "username": "lpondevida",
        "email": "liezl.pondevida@pnchs.edu.ph"
    },
    {
        "id": "EMP-009",
        "first_name": "Judyline",
        "middle_name": "",
        "last_name": "Gayap",
        "title": "",
        "designation": "Mathematics Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "jgayap",
        "email": "judyline.gayap@pnchs.edu.ph"
    },
    {
        "id": "EMP-010",
        "first_name": "Andrea Hana",
        "middle_name": "B.",
        "last_name": "Deveza",
        "title": "",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "adeveza",
        "email": "andreahana.deveza@pnchs.edu.ph"
    },
    {
        "id": "EMP-011",
        "first_name": "Michelle",
        "middle_name": "M.",
        "last_name": "Linatoc",
        "title": "",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "mlinatoc",
        "email": "michelle.linatoc@pnchs.edu.ph"
    },
    {
        "id": "EMP-012",
        "first_name": "Josephine",
        "middle_name": "Tuazon",
        "last_name": "Peñafiel",
        "title": "",
        "designation": "Senior Research Adviser / Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "jpenafiel",
        "email": "josephine.penafiel@pnchs.edu.ph"
    },
    {
        "id": "EMP-013",
        "first_name": "Lovely Kaye",
        "middle_name": "",
        "last_name": "Villanueva",
        "title": "",
        "designation": "Subject Group Head / Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "lvillanueva",
        "email": "lovelykaye.villanueva@pnchs.edu.ph"
    },
    {
        "id": "EMP-014",
        "first_name": "Arnaldo",
        "middle_name": "Q.",
        "last_name": "Perualila",
        "title": "",
        "designation": "Senior High School Coordinator",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "aperualila",
        "email": "arnaldo.perualila@pnchs.edu.ph"
    },
    {
        "id": "EMP-015",
        "first_name": "Catherine",
        "middle_name": "M.",
        "last_name": "Margarse",
        "title": "",
        "designation": "Research Adviser / Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "cmargarse",
        "email": "catherine.margarse@pnchs.edu.ph"
    },
    {
        "id": "EMP-016",
        "first_name": "Glenda",
        "middle_name": "S.",
        "last_name": "Magallon",
        "title": "",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "gmagallon",
        "email": "glenda.magallon@pnchs.edu.ph"
    },
    {
        "id": "EMP-017",
        "first_name": "Mega Lou Margarett",
        "middle_name": "G.",
        "last_name": "Parcon",
        "title": "",
        "designation": "Sports Coordinator / Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "mparcon",
        "email": "megalou.parcon@pnchs.edu.ph"
    },
    {
        "id": "EMP-018",
        "first_name": "Christy",
        "middle_name": "O.",
        "last_name": "Prosperoso",
        "title": "",
        "designation": "Journalism Coach / Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "cprosperoso",
        "email": "christy.prosperoso@pnchs.edu.ph"
    },
    {
        "id": "EMP-019",
        "first_name": "Maricel",
        "middle_name": "Figueroa",
        "last_name": "Cabale",
        "title": "",
        "designation": "Teacher III",
        "salary_grade": 13,
        "step": 1,
        "base_salary": 36125.00,
        "username": "mcabale",
        "email": "maricel.cabale@pnchs.edu.ph"
    },
    {
        "id": "EMP-020",
        "first_name": "Alma",
        "middle_name": "",
        "last_name": "Peña",
        "title": "",
        "designation": "Math Faculty / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "apena",
        "email": "alma.pena@pnchs.edu.ph"
    },
    {
        "id": "EMP-021",
        "first_name": "Roselyn",
        "middle_name": "Panila",
        "last_name": "Porras",
        "title": "",
        "designation": "Math Faculty / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "rporras",
        "email": "roselyn.porras@pnchs.edu.ph"
    },
    {
        "id": "EMP-022",
        "first_name": "Melanie",
        "middle_name": "",
        "last_name": "Juego",
        "title": "",
        "designation": "Math Faculty / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "mjuego",
        "email": "melanie.juego@pnchs.edu.ph"
    },
    {
        "id": "EMP-023",
        "first_name": "Rogelio",
        "middle_name": "P.",
        "last_name": "Segura",
        "title": "",
        "designation": "Classroom Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "rsegura",
        "email": "rogelio.segura@pnchs.edu.ph"
    },
    {
        "id": "EMP-024",
        "first_name": "Mary Grace",
        "middle_name": "B.",
        "last_name": "Jover",
        "title": "",
        "designation": "Classroom Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "mjover",
        "email": "marygrace.jover@pnchs.edu.ph"
    },
    {
        "id": "EMP-025",
        "first_name": "Joseph",
        "middle_name": "",
        "last_name": "Evangelio",
        "title": "",
        "designation": "Media Coordinator / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "jevangelio",
        "email": "joseph.evangelio@pnchs.edu.ph"
    },
    {
        "id": "EMP-026",
        "first_name": "Venus",
        "middle_name": "P.",
        "last_name": "Pasadilla",
        "title": "",
        "designation": "Assistant Sports Coach / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "vpasadilla",
        "email": "venus.pasadilla@pnchs.edu.ph"
    },
    {
        "id": "EMP-027",
        "first_name": "Doren",
        "middle_name": "",
        "last_name": "Dutchilla",
        "title": "",
        "designation": "Head Swimming Coach / Teacher II",
        "salary_grade": 12,
        "step": 1,
        "base_salary": 33947.00,
        "username": "ddutchilla",
        "email": "doren.dutchilla@pnchs.edu.ph"
    },
    {
        "id": "EMP-028",
        "first_name": "Janice",
        "middle_name": "A.",
        "last_name": "Cordero",
        "title": "",
        "designation": "Classroom Teacher I",
        "salary_grade": 11,
        "step": 1,
        "base_salary": 31705.00,
        "username": "jcordero",
        "email": "janice.cordero@pnchs.edu.ph"
    },
    {
        "id": "EMP-029",
        "first_name": "Mark Anthony",
        "middle_name": "L.",
        "last_name": "Solis",
        "title": "",
        "designation": "Classroom Teacher I",
        "salary_grade": 11,
        "step": 1,
        "base_salary": 31705.00,
        "username": "msolis",
        "email": "markanthony.solis@pnchs.edu.ph"
    },
    {
        "id": "EMP-030",
        "first_name": "Elena",
        "middle_name": "M.",
        "last_name": "Villanueva",
        "title": "",
        "designation": "Classroom Teacher I",
        "salary_grade": 11,
        "step": 1,
        "base_salary": 31705.00,
        "username": "evillanueva",
        "email": "elena.villanueva@pnchs.edu.ph"
    }
]

def seed_roster_and_logs():
    random.seed(2026)
    default_hashed_pwd = generate_password_hash("Password123!")

    with db_cursor(commit=True) as (conn, cur):
        print("1. Cleaning old operational and employee data...")
        cur.execute("DELETE FROM tblpayroll_details")
        cur.execute("DELETE FROM tblpayroll")
        cur.execute("DELETE FROM tblapprovals")
        cur.execute("DELETE FROM tblleaves")
        cur.execute("DELETE FROM tblleave_transactions")
        cur.execute("DELETE FROM tblleave_balances")
        cur.execute("DELETE FROM tbltime_logs")
        cur.execute("DELETE FROM tblbiometric_logs")
        cur.execute("DELETE FROM tblpayhead")
        cur.execute("DELETE FROM fingerprints")
        cur.execute("DELETE FROM tblenrollment_tasks")
        
        # Clean employee-role accounts in tblusers (retain principal, hr, accounting)
        cur.execute("DELETE FROM tblusers WHERE role = 'Employee' OR (employee_id IS NOT NULL AND role NOT IN ('Principal', 'HR', 'Accounting'))")
        
        # Now clean tblemployee
        cur.execute("DELETE FROM tblemployee")
        print("[OK] Prior records purged.")

        print("2. Inserting 30 Verified Faculty & Administrators...")
        for idx, emp in enumerate(ROSTER, start=1):
            emp_id = emp["id"]
            fn = emp["first_name"]
            mn = emp["middle_name"]
            ln = emp["last_name"]
            desig = emp["designation"]
            sg = emp["salary_grade"]
            step = emp["step"]
            email = emp["email"]
            contact = f"+63 917 {random.randint(100, 999)} {random.randint(1000, 9999)}"
            bday = f"{random.randint(1975, 1998)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
            
            cur.execute("""
                INSERT INTO tblemployee (
                    employee_id, first_name, middle_name, last_name,
                    designation, employee_type, salary_grade, step,
                    employment_status, birthday, email, contact, address
                ) VALUES (%s, %s, %s, %s, %s, 'TEACHING', %s, %s, 'Active', %s, %s, %s, 'Pototan, Iloilo')
            """, (emp_id, fn, mn, ln, desig, sg, step, bday, email, contact))

            # Initial Leave Balance (10 days VL, 10 days SL = 4800 mins each)
            cur.execute("""
                INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes)
                VALUES (%s, 4800, 4800)
            """, (emp_id,))

            # Monthly Basic Salary in tblpayhead
            cur.execute("""
                INSERT INTO tblpayhead (employee_id, pay_head, description, amount, category, mode, percentage_value)
                VALUES (%s, 'Basic Salary', 'Monthly Basic Salary (SSL VI / EO 64)', %s, 'Earning', 'Amount', 0.00)
            """, (emp_id, emp["base_salary"]))

            # Employee user portal login
            full_name = f"{emp['title']} {fn} {mn} {ln}".strip() if emp['title'] else f"{fn} {mn} {ln}".strip()
            cur.execute("""
                INSERT INTO tblusers (username, password, name, role, employee_id)
                VALUES (%s, %s, %s, 'Employee', %s)
            """, (emp["username"], default_hashed_pwd, full_name, emp_id))

        # Update or recreate system admin/HR/accounting accounts
        admin_users = [
            ('principal', default_hashed_pwd, 'Dr. Gemma B. Peñaranda', 'Principal', 'EMP-001'),
            ('hr1', default_hashed_pwd, 'HR Officer', 'HR', None),
            ('accounting1', default_hashed_pwd, 'Accounting Officer', 'Accounting', None)
        ]
        for u in admin_users:
            cur.execute("""
                INSERT INTO tblusers (username, password, name, role, employee_id)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE name=VALUES(name), role=VALUES(role), employee_id=VALUES(employee_id)
            """, u)
        print(f"[OK] Successfully registered 30 employees, leave balances, salary heads, and user accounts.")

        print("3. Generating Realistic Attendance & Biometrics from Jan 1, 2026 to Oct 10, 2026...")
        # Fetch holidays in the range
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

        # Standard Teaching schedule:
        # AM: 07:30 - 11:30 | PM: 13:00 - 17:00
        for emp in ROSTER:
            emp_id = emp["id"]
            for d in work_dates:
                roll = random.random()

                # Attendance distribution:
                # 88% on time
                # 6% slight tardiness (5-20 mins)
                # 3% undertime (10-30 mins early leave in PM)
                # 2% half-day AM only
                # 1% absent (no punches)
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
        # Insert in chunks of 1000
        chunk_size = 1000
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

        print(f"[SUCCESS] Complete setup finished!")
        print(f"[OK] 30 Employees registered")
        print(f"[OK] {len(time_batch)} Daily time logs seeded (Jan 2026 - Oct 2026)")
        print(f"[OK] {len(bio_batch)} Biometric punches recorded")

if __name__ == '__main__':
    seed_roster_and_logs()
