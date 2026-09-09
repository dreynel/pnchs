import mysql.connector

def clean_payroll_data():
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
        print(f"Cleaning ONLY Payroll Data on {env_name}...")
        print(f"==================================================")

        try:
            conn = mysql.connector.connect(**config)
            cur = conn.cursor(dictionary=True)

            cur.execute("SET FOREIGN_KEY_CHECKS = 0")

            # 1. Truncate tblpayroll_details
            cur.execute("DELETE FROM tblpayroll_details")
            print("  [OK] Deleted all records from tblpayroll_details")

            # 2. Truncate tblpayroll
            cur.execute("DELETE FROM tblpayroll")
            print("  [OK] Deleted all records from tblpayroll")

            # 3. Clean tblapprovals for DocType = 'Payroll' only
            cur.execute("DELETE FROM tblapprovals WHERE DocType = 'Payroll'")
            print("  [OK] Deleted all Payroll approvals from tblapprovals (Leave approvals preserved)")

            # 4. Clean tblaudit_logs for Payroll actions
            cur.execute("DELETE FROM tblaudit_logs WHERE target_table = 'tblpayroll' OR action LIKE '%PAYROLL%'")
            print("  [OK] Cleaned payroll audit logs from tblaudit_logs")

            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            conn.commit()

            # Verification
            cur.execute("SELECT COUNT(*) AS cnt FROM tblpayroll")
            pr_cnt = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) AS cnt FROM tblpayroll_details")
            prd_cnt = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) AS cnt FROM tblapprovals WHERE DocType = 'Payroll'")
            app_cnt = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) AS cnt FROM tblemployee")
            emp_cnt = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) AS cnt FROM tblleave_balances")
            lb_cnt = cur.fetchone()['cnt']

            print(f"\nVerification Results for {env_name}:")
            print(f"  - tblpayroll count: {pr_cnt}")
            print(f"  - tblpayroll_details count: {prd_cnt}")
            print(f"  - tblapprovals (Payroll) count: {app_cnt}")
            print(f"  - tblemployee count (PRESERVED): {emp_cnt}")
            print(f"  - tblleave_balances count (PRESERVED): {lb_cnt}")

            cur.close()
            conn.close()

        except Exception as e:
            print(f"  [ERROR] Failed to clean {env_name}: {e}")

if __name__ == '__main__':
    clean_payroll_data()
