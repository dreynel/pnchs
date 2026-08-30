import os
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "dbpnchs"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "007622"),
    "charset":  "utf8mb4",
    "autocommit": False,
    "use_pure": True,
}

# Create connection pool gracefully if local MySQL is reachable
db_pool = None
try:
    db_pool = pooling.MySQLConnectionPool(
        pool_name="local_scanner_pool",
        pool_size=10,
        pool_reset_session=True,
        **DB_CONFIG
    )
    print("[OK] Connected to local MySQL connection pool.")
except Exception as e:
    print(f"[INFO] Local MySQL not active or unreachable ({e}). Running in Cloud Mode.")
    db_pool = None

def get_connection():
    """Returns a MySQL connection from pool or direct connect."""
    if db_pool:
        return db_pool.get_connection()
    return mysql.connector.connect(**DB_CONFIG)

@contextmanager
def db_cursor(commit=False):
    """
    Context manager that yields (conn, cursor).
    Automatically commits or rolls back, then closes.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        yield conn, cur
        if commit:
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cur:
            cur.close()
        if conn and hasattr(conn, 'is_connected') and conn.is_connected():
            conn.close()