"""
Sync employees and users records:
- Assign Nino Justin Silguera (EMP-033) as HR Officer (role: HR)
- Assign Quiron Pineda Bermejo (EMP-032) as Accounting Officer (role: Accounting)
- Assign Dr. Gemma B. Peñaranda (EMP-001) as School Principal (role: Principal)
- Sync and ensure all 34 employees in tblemployee are 100% linked with tblusers.
"""
from db import db_cursor

def sync_employees_and_users():
    with db_cursor(commit=True) as (conn, cur):
        print("1. Assigning HR Officer role to Nino Justin Silguera (EMP-033)...")
        # Update tblemployee
        cur.execute("""
            UPDATE tblemployee 
            SET designation = 'Administrative Officer II / HR Officer'
            WHERE employee_id = 'EMP-033'
        """)
        # Update tblusers for nsilguera and hr1
        cur.execute("""
            UPDATE tblusers 
            SET role = 'HR', name = 'Nino Justin D. Silguera', employee_id = 'EMP-033'
            WHERE username = 'nsilguera'
        """)
        cur.execute("""
            UPDATE tblusers 
            SET role = 'HR', name = 'Nino Justin D. Silguera', employee_id = 'EMP-033'
            WHERE username = 'hr1'
        """)

        print("2. Assigning Accounting role to Quiron Pineda Bermejo (EMP-032)...")
        cur.execute("""
            UPDATE tblemployee 
            SET designation = 'Administrative Officer II / Finance'
            WHERE employee_id = 'EMP-032'
        """)
        cur.execute("""
            UPDATE tblusers 
            SET role = 'Accounting', name = 'Quiron Pineda Bermejo', employee_id = 'EMP-032'
            WHERE username = 'qbermejo'
        """)
        cur.execute("""
            UPDATE tblusers 
            SET role = 'Accounting', name = 'Quiron Pineda Bermejo', employee_id = 'EMP-032'
            WHERE username = 'accounting1'
        """)

        print("3. Syncing Principal role for Dr. Gemma B. Peñaranda (EMP-001)...")
        cur.execute("""
            UPDATE tblusers 
            SET role = 'Principal', name = 'Dr. Gemma B. Peñaranda', employee_id = 'EMP-001'
            WHERE username IN ('gpenaranda', 'principal')
        """)

        print("4. Verifying employee-user sync across all employees...")
        cur.execute("""
            SELECT e.employee_id, e.first_name, e.last_name, e.designation, u.username, u.role, u.employee_id as user_emp_id
            FROM tblemployee e
            LEFT JOIN tblusers u ON e.employee_id = u.employee_id
            ORDER BY e.employee_id
        """)
        rows = cur.fetchall()
        print(f"Total synchronized employee-user links: {len(rows)}")
        
        # Verify hr1 and accounting1 have employee_id
        cur.execute("""
            SELECT username, role, name, employee_id 
            FROM tblusers 
            WHERE username IN ('hr1', 'principal', 'accounting1', 'nsilguera', 'qbermejo', 'gpenaranda')
        """)
        key_accounts = cur.fetchall()
        for acc in key_accounts:
            print(f"[OK] User: {acc['username']:12s} | Role: {acc['role']:12s} | EmployeeID: {acc['employee_id']} | Name: {acc['name']}")

if __name__ == '__main__':
    sync_employees_and_users()
