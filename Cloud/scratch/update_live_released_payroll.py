import mysql.connector
import sys

LIVE_CONFIG = {
    "host": "187.52.121.22",
    "user": "pnchs_user",
    "password": "YourSecurePassword123!",
    "database": "dbpnchs",
    "connect_timeout": 15
}

def update_live_database():
    print("\n--- Updating Existing Released Payroll Records on Live Database ---")
    try:
        conn = mysql.connector.connect(**LIVE_CONFIG)
        cur = conn.cursor(dictionary=True)
        print(f" [+] Connected to Live MySQL database '{LIVE_CONFIG['database']}' at {LIVE_CONFIG['host']}")

        # Ensure is_released column exists
        cur.execute(
            "SELECT COUNT(*) as cnt FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tblpayroll' AND COLUMN_NAME='is_released'"
        )
        row = cur.fetchone()
        cnt = row['cnt'] if isinstance(row, dict) else row[0]
        if cnt == 0:
            cur.execute("ALTER TABLE tblpayroll ADD COLUMN is_released TINYINT(1) NOT NULL DEFAULT 0 AFTER status")
            print(" [+] Added 'is_released' column to tblpayroll")

        # Update tblpayroll records where status = 'Released' -> is_released = 1, status = 'Approved'
        cur.execute("UPDATE tblpayroll SET is_released = 1, status = 'Approved' WHERE status = 'Released'")
        payroll_affected = cur.rowcount
        print(f" [+] Updated {payroll_affected} payroll records in tblpayroll (status='Released' -> status='Approved', is_released=1)")

        # Update tblapprovals records where ApprovalStatus = 'Released' -> 'Approved'
        cur.execute("UPDATE tblapprovals SET ApprovalStatus = 'Approved' WHERE ApprovalStatus = 'Released'")
        approvals_affected = cur.rowcount
        print(f" [+] Updated {approvals_affected} approval records in tblapprovals (ApprovalStatus='Released' -> ApprovalStatus='Approved')")

        conn.commit()

        # Display updated live payroll summary
        cur.execute("SELECT period_key, year, month, half, status, is_released, released_by, released_at FROM tblpayroll ORDER BY year DESC, month DESC, half DESC")
        runs = cur.fetchall()
        print("\n--- Current Live Payroll Runs Summary ---")
        for r in runs:
            rel_str = f"Released by {r['released_by']} on {r['released_at']}" if r['is_released'] else "Not Released"
            print(f" • Period: {r['period_key']} | Status: {r['status']} | Released: {r['is_released']} ({rel_str})")

        cur.close()
        conn.close()
        print("\n [SUCCESS] Live database updated successfully!")
    except Exception as e:
        print(f" [!] Live database connection/update notice: {e}")

if __name__ == '__main__':
    update_live_database()
