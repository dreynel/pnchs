import mysql.connector

def sync_users(host, user, password, database):
    print(f"Syncing tblusers with tblemployee on {host} ({database})...")
    conn = mysql.connector.connect(
        host=host, user=user, password=password, database=database
    )
    cur = conn.cursor(dictionary=True)

    # 1. Delete users whose employee_id is NOT NULL and NOT in tblemployee
    cur.execute("""
        DELETE FROM tblusers 
        WHERE employee_id IS NOT NULL 
          AND employee_id NOT IN (SELECT employee_id FROM tblemployee)
    """)
    removed_orphans = cur.rowcount
    print(f" - Deleted {removed_orphans} orphaned users with missing employee_id.")

    # 2. Check if tblemployee is empty
    cur.execute("SELECT COUNT(*) as cnt FROM tblemployee")
    emp_cnt = cur.fetchone()['cnt']

    if emp_cnt == 0:
        # If no employees exist at all, clear ALL users from tblusers so if no employee no users
        cur.execute("DELETE FROM tblusers")
        all_removed = cur.rowcount
        print(f" - Since tblemployee has 0 employees, cleared all {all_removed} user records from tblusers.")
    
    conn.commit()

    cur.execute("SELECT COUNT(*) as u_cnt FROM tblusers")
    u_cnt = cur.fetchone()['u_cnt']
    print(f"Current count in tblemployee: {emp_cnt}, in tblusers: {u_cnt}")

    cur.close()
    conn.close()

if __name__ == '__main__':
    # Remote
    sync_users("187.52.121.22", "pnchs_user", "YourSecurePassword123!", "dbpnchs")
