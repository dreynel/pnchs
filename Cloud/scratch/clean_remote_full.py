import mysql.connector

def clean_remote_database():
    host = "187.52.121.22"
    user = "pnchs_user"
    password = "YourSecurePassword123!"
    database = "dbpnchs"

    print(f"Connecting to MySQL '{database}' on {host} for full database cleanup...")
    conn = mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        connect_timeout=15
    )
    cur = conn.cursor(dictionary=True)

    tables_to_truncate = [
        "tblpayroll_details",
        "tblpayroll",
        "tblleave_transactions",
        "tblleave_balances",
        "tblleaves",
        "tblapprovals",
        "tbltime_logs",
        "tblbiometric_logs",
        "fingerprints",
        "tblenrollment_tasks",
        "tblpayhead",
        "tblglobal_payheads",
        "tblemployee",
        "tblaudit_logs",
        "logs",
        "schedules",
        "device_state"
    ]

    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for tbl in tables_to_truncate:
        cur.execute(f"DELETE FROM {tbl}")
        print(f"[CLEANED] Cleared table {tbl}")

    # Clean tblusers except core system roles (admin, hr, finance, auditor)
    cur.execute("DELETE FROM tblusers WHERE username NOT IN ('admin', 'hr', 'finance', 'auditor')")
    print("[CLEANED] Cleared employee users from tblusers (retained admin, hr, finance, auditor)")

    # Ensure employee_id pointers for retained system users are set to NULL since employees were purged
    cur.execute("UPDATE tblusers SET employee_id = NULL WHERE username IN ('admin', 'hr', 'finance', 'auditor')")

    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()

    print("\nVerifying remaining table counts:")
    cur.execute("SHOW TABLES")
    tables = cur.fetchall()
    tbl_key = f"Tables_in_{database}"
    for row in tables:
        tbl_name = row[tbl_key]
        cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl_name}")
        cnt = cur.fetchone()['cnt']
        print(f" - {tbl_name}: {cnt} rows")

    cur.close()
    conn.close()
    print("\nRemote database cleanup completed successfully!")

if __name__ == '__main__':
    clean_remote_database()
