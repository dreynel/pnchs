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
    print(f"Error initializing local database connection pool: {e}")
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
