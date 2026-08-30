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

# Create a connection pool for live MySQL database
connection_pool = None
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name="live_hostinger_pool",
        pool_size=15,
        pool_reset_session=True,
        **DB_CONFIG
    )
    print("[OK] Connected to live Hostinger MySQL connection pool.")
except Error as e:
    print(f"Error initializing live database connection pool: {e}")
    connection_pool = None

def get_connection():
    """Open and return a new MySQL connection from the local pool."""
    if connection_pool:
        return connection_pool.get_connection()
    return mysql.connector.connect(**DB_CONFIG)


@contextmanager
def db_cursor(commit=False):
    """
    Context manager that yields (conn, cursor).
    Automatically commits or rolls back, then closes.

    Usage:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("INSERT ...")
    """
    conn = None
    cur  = None
    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)
        yield conn, cur
        if commit:
            conn.commit()
    except Error as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cur:
            cur.close()
        if conn and conn.is_connected():
            conn.close()