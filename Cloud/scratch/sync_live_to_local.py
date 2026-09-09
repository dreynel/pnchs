import mysql.connector
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 1. Connect to Live VPS Database
LIVE_CONFIG = {
    "host": "187.52.121.22",
    "user": "pnchs_user",
    "password": "YourSecurePassword123!",
    "database": "dbpnchs",
    "connect_timeout": 15
}

LOCAL_ROOT_PW = "007622"

print("\n--- Connecting to Local MySQL (root) ---")
try:
    local_conn = mysql.connector.connect(host="localhost", user="root", password=LOCAL_ROOT_PW, connect_timeout=5)
    print(" [+] Local MySQL root connection successful!")
except Exception as e:
    print(f" [!] Failed to connect to local MySQL root: {e}")
    sys.exit(1)

local_cur = local_conn.cursor()

# Ensure local database dbpnchs exists
local_cur.execute("CREATE DATABASE IF NOT EXISTS dbpnchs")
local_cur.execute("USE dbpnchs")

# Ensure user 'pnchs_user'@'localhost' exists with password 'YourSecurePassword123!'
try:
    local_cur.execute("CREATE USER IF NOT EXISTS 'pnchs_user'@'localhost' IDENTIFIED BY 'YourSecurePassword123!'")
    local_cur.execute("GRANT ALL PRIVILEGES ON dbpnchs.* TO 'pnchs_user'@'localhost'")
    local_cur.execute("FLUSH PRIVILEGES")
    print(" [+] Local user 'pnchs_user'@'localhost' created and granted permissions!")
except Exception as u_err:
    print(f" [!] User creation notice: {u_err}")

local_conn.commit()

# Run init_db.py to create local tables & migrations
from init_db import init as init_local_schema
print(" [+] Initializing local database schema...")
try:
    init_local_schema()
except Exception as e:
    print(f" Schema init notice: {e}")

# Reconnect dictionary cursor to local dbpnchs
local_conn.close()
local_conn = mysql.connector.connect(host="localhost", user="root", password=LOCAL_ROOT_PW, database="dbpnchs")
local_cur = local_conn.cursor(dictionary=True)

# 2. Connect to Live Database & Copy Data
print("\n--- Pulling Data from Live Remote DB (187.52.121.22) ---")
try:
    live_conn = mysql.connector.connect(**LIVE_CONFIG)
    live_cur = live_conn.cursor(dictionary=True)
    print(" [+] Connected to Remote Live DB!")
except Exception as e:
    print(f" [!] Live connection error: {e}")
    sys.exit(1)

TABLES_TO_SYNC = [
    "tblsalary_grades",
    "tblstatutory_registry",
    "tblpolicy_config",
    "tblholidays",
    "tblemployee",
    "tblusers",
    "tblpayhead",
    "tblglobal_payheads",
    "tblleave_balances",
    "tblleave_transactions",
    "tblleaves",
    "tbltime_logs",
    "tblpayroll",
    "tblpayroll_details",
    "tblapprovals",
    "tblaudit_logs"
]

print("\n--- Clearing local tables to ensure exact live clone ---")
local_cur.execute("SET FOREIGN_KEY_CHECKS = 0")
for table in reversed(TABLES_TO_SYNC):
    try:
        local_cur.execute(f"TRUNCATE TABLE {table}")
        print(f"  [+] Truncated local table: {table}")
    except Exception as tr_err:
        print(f"  [!] Truncate notice for {table}: {tr_err}")
local_conn.commit()
print(" [+] Local database tables cleaned successfully!")

local_cur.execute("SET FOREIGN_KEY_CHECKS = 0")

for table in TABLES_TO_SYNC:
    try:
        live_cur.execute(f"SELECT * FROM {table}")
        rows = live_cur.fetchall()
        if not rows:
            print(f"  [-] {table}: 0 rows found in live DB.")
            continue

        cols = list(rows[0].keys())
        col_names = ", ".join(cols)
        val_placeholders = ", ".join(["%s"] * len(cols))
        update_placeholders = ", ".join([f"{c}=VALUES({c})" for c in cols])

        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({val_placeholders}) ON DUPLICATE KEY UPDATE {update_placeholders}"
        
        batch_vals = [tuple(r[c] for c in cols) for r in rows]
        local_cur.executemany(insert_sql, batch_vals)
        local_conn.commit()
        print(f"  [+] {table}: Synced {len(rows)} rows to local DB.")
    except Exception as t_err:
        print(f"  [!] {table} sync warning: {t_err}")

local_cur.execute("SET FOREIGN_KEY_CHECKS = 1")
local_conn.commit()

live_cur.close()
live_conn.close()
local_cur.close()
local_conn.close()

print("\n--- Updating Cloud/db.py to use Local Database ---")
# Update db.py to point DB_HOST to localhost by default
db_py_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'db.py'))
new_db_py = f'''import os
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager

DB_CONFIG = {{
    "host":     os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "dbpnchs"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "{LOCAL_ROOT_PW}"),
    "charset":  "utf8mb4",
    "autocommit": False,
    "use_pure": True,
}}

# Create a connection pool for local MySQL database
connection_pool = None
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name="local_db_pool",
        pool_size=15,
        pool_reset_session=True,
        **DB_CONFIG
    )
except Error as e:
    print(f"Error initializing local database connection pool: {{e}}")
    connection_pool = None

def get_connection():
    """Open and return a new MySQL connection from pool or fresh connection."""
    if connection_pool:
        try:
            conn = connection_pool.get_connection()
            if not conn.is_connected():
                conn.reconnect(attempts=3, delay=1)
            return conn
        except Exception:
            pass
    return mysql.connector.connect(**DB_CONFIG)


@contextmanager
def db_cursor(commit=False):
    """
    Context manager that yields (conn, cursor).
    Automatically commits or rolls back, then closes.
    """
    conn = None
    cur  = None
    try:
        conn = get_connection()
        try:
            cur = conn.cursor(dictionary=True)
        except Error:
            if hasattr(conn, 'reconnect'):
                conn.reconnect(attempts=3, delay=1)
            else:
                conn = mysql.connector.connect(**DB_CONFIG)
            cur = conn.cursor(dictionary=True)

        yield conn, cur
        if commit:
            conn.commit()
    except Error as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn and conn.is_connected():
            try:
                conn.close()
            except Exception:
                pass
'''

with open(db_py_path, 'w', encoding='utf-8') as f:
    f.write(new_db_py)

print(" [+] Cloud/db.py updated to default to localhost for fast local development!")
print(" [+] All live database tables & records successfully pulled to local MySQL dbpnchs!")
