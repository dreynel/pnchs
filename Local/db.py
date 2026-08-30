import os
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "194.59.164.63"),
    "database": os.getenv("DB_NAME", "u534933225_dbpwms"),
    "user":     os.getenv("DB_USER", "u534933225_pwms"),
    "password": os.getenv("DB_PASSWORD", "QIr0lbg5*"),
    "charset":  "utf8mb4",
    "autocommit": False,
    "use_pure": True,
}

# Create connection pool gracefully for live Hostinger MySQL database
db_pool = None
try:
    db_pool = pooling.MySQLConnectionPool(
        pool_name="live_hostinger_pool",
        pool_size=10,
        pool_reset_session=True,
        **DB_CONFIG
    )
    print("[OK] Connected directly to live Hostinger MySQL database pool.")
except Exception as e:
    print(f"[INFO] Direct live MySQL pool notice ({e}). Falling back to direct connection.")
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