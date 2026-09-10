import mysql.connector

def check(name, config):
    print(f"=== {name} ===")
    try:
        conn = mysql.connector.connect(**config)
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT u.id, u.username, u.name, u.role, u.employee_id FROM tblusers u")
        for r in cur.fetchall():
            print(f"User: {r['username']:<15} Name: {r['name']:<20} Role: {r['role']:<12} EmpID: {r['employee_id']}")
        cur.close()
        conn.close()
    except Exception as e:
        print("Error:", e)

check("VPS DB", {"host": "187.52.121.22", "user": "pnchs_user", "password": "YourSecurePassword123!", "database": "dbpnchs", "connect_timeout": 10})
check("Local DB", {"host": "localhost", "user": "root", "password": "007622", "database": "dbpnchs", "connect_timeout": 5})
