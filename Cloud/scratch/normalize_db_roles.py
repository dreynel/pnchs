import mysql.connector

def normalize_roles():
    vps_config = {
        "host": "187.52.121.22",
        "user": "pnchs_user",
        "password": "YourSecurePassword123!",
        "database": "dbpnchs",
        "connect_timeout": 15
    }

    local_config = {
        "host": "localhost",
        "user": "root",
        "password": "007622",
        "database": "dbpnchs",
        "connect_timeout": 5
    }

    for env_name, config in [("Live VPS Database (187.52.121.22)", vps_config), ("Local Database (localhost)", local_config)]:
        print(f"\n==================================================")
        print(f"Normalizing tblusers roles on {env_name}...")
        print(f"==================================================")

        try:
            conn = mysql.connector.connect(**config)
            cur = conn.cursor(dictionary=True)

            cur.execute("SELECT id, username, role FROM tblusers")
            users = cur.fetchall()

            for u in users:
                uid = u['id']
                raw_role = str(u['role'] or '').strip().upper()
                if raw_role in ['ADMIN', 'PRINCIPAL', 'ADMINISTRATOR']:
                    norm_role = 'Admin'
                elif raw_role in ['HR', 'HR OFFICER', 'HUMAN RESOURCES']:
                    norm_role = 'HR'
                elif raw_role in ['FINANCE', 'FINANCE OFFICER', 'PAYROLL OFFICER']:
                    norm_role = 'Finance'
                elif raw_role in ['AUDITOR', 'AUDIT']:
                    norm_role = 'Auditor'
                else:
                    norm_role = 'Employee'

                if u['role'] != norm_role:
                    cur.execute("UPDATE tblusers SET role=%s WHERE id=%s", (norm_role, uid))
                    print(f"  [UPDATED] User '{u['username']}' (ID {uid}): '{u['role']}' -> '{norm_role}'")

            conn.commit()

            print(f"\nVerification Results for {env_name}:")
            cur.execute("SELECT id, username, role, employee_id FROM tblusers ORDER BY id")
            for r in cur.fetchall():
                print(f"  - User '{r['username']}': Role = {r['role']}")

            cur.close()
            conn.close()

        except Exception as e:
            print(f"  [ERROR] Failed to normalize roles on {env_name}: {e}")

if __name__ == '__main__':
    normalize_roles()
