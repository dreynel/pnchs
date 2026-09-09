import mysql.connector

def check_users_and_configs():
    conn = mysql.connector.connect(
        host="187.52.121.22",
        user="pnchs_user",
        password="YourSecurePassword123!",
        database="dbpnchs"
    )
    cur = conn.cursor(dictionary=True)
    
    cur.execute("SELECT id, username, role, employee_id FROM tblusers")
    print("tblusers rows:")
    for u in cur.fetchall():
        print(f"  {u}")
        
    cur.execute("SELECT * FROM tblpolicy_config")
    print("\ntblpolicy_config rows:")
    for p in cur.fetchall():
        print(f"  {p}")

    cur.execute("SELECT * FROM tblholidays")
    print("\ntblholidays rows:")
    for h in cur.fetchall():
        print(f"  {h}")

    cur.close()
    conn.close()

if __name__ == '__main__':
    check_users_and_configs()
