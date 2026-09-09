import mysql.connector
import sys

def inspect_remote():
    host = "187.52.121.22"
    user = "pnchs_user"
    password = "YourSecurePassword123!"
    database = "dbpnchs"

    print(f"Connecting to MySQL database '{database}' on {host}...")
    try:
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            connect_timeout=10
        )
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW TABLES")
        tables = cur.fetchall()
        print("\nTables found in remote database:")
        tbl_key = f"Tables_in_{database}"
        for row in tables:
            tbl_name = row[tbl_key]
            cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl_name}")
            cnt = cur.fetchone()['cnt']
            print(f" - {tbl_name}: {cnt} rows")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Direct MySQL connection error: {e}")

if __name__ == '__main__':
    inspect_remote()
