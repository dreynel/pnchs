import os
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager

def _get_working_db_config():
    """Try configured or candidate credentials until a working MySQL configuration is found."""
    candidates = []
    
    # 1. If explicit environment variables are set, try them first
    if os.getenv("DB_USER"):
        candidates.append({
            "host":     os.getenv("DB_HOST", "localhost"),
            "database": os.getenv("DB_NAME", "dbpnchs"),
            "user":     os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD", ""),
            "charset":  "utf8mb4",
            "autocommit": False,
            "use_pure": True,
        })

    # 2. Candidate credential pairs across environments
    host = os.getenv("DB_HOST", "localhost")
    dbname = os.getenv("DB_NAME", "dbpnchs")
    
    user_pass_pairs = [
        ("root", "007622"),
        ("pnchs_user", "YourSecurePassword123!"),
        ("root", ""),
        ("root", "root"),
        ("pnchs", "pnchs123"),
    ]

    for u, p in user_pass_pairs:
        candidates.append({
            "host":     host,
            "database": dbname,
            "user":     u,
            "password": p,
            "charset":  "utf8mb4",
            "autocommit": False,
            "use_pure": True,
        })

    for config in candidates:
        try:
            conn = mysql.connector.connect(**config)
            if conn.is_connected():
                conn.close()
                return config
        except Exception:
            continue

    return {
        "host":     host,
        "database": dbname,
        "user":     os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", "007622"),
        "charset":  "utf8mb4",
        "autocommit": False,
        "use_pure": True,
    }

DB_CONFIG = _get_working_db_config()

# Create a connection pool for database
connection_pool = None
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name="local_db_pool",
        pool_size=15,
        pool_reset_session=True,
        **DB_CONFIG
    )
except Error as e:
    print(f"Error initializing database connection pool: {e}")
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
