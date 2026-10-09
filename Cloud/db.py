import os
import re
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager

# ── Hostinger VPS MySQL Configuration ──────────────────────────────────────────

DB_HOST = os.getenv("DB_HOST", "187.52.121.22")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "dbpnchs")
DB_USER = os.getenv("DB_USER", "pnchs_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "YourSecurePassword123!")

DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "charset": "utf8mb4",
    "autocommit": False,
    "use_pure": True,
}

# ── Case-Insensitive Dict Row ────────────────────────────────────────────────

class CaseInsensitiveDict(dict):
    """
    Subclass of dict providing case-insensitive key lookup.
    Enables lookups like row['ApprovalID'] to transparently
    match lowercase column names ('approvalid').
    """
    def __getitem__(self, key):
        if super().__contains__(key):
            return super().__getitem__(key)
        if isinstance(key, str):
            lk = key.lower()
            for k in self:
                if isinstance(k, str) and k.lower() == lk:
                    return super().__getitem__(k)
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            lk = key.lower()
            return any(isinstance(k, str) and k.lower() == lk for k in self)
        return False


# ── MySQL Cursor with Query Translation & Case-Insensitive Dict ──────────────

class CaseInsensitiveMySQLCursor(mysql.connector.cursor.MySQLCursorDict):
    """
    Cursor that:
    1. Returns CaseInsensitiveDict instances for dict-like row access.
    2. Rewrites PostgreSQL constructs seamlessly to MySQL:
       - ON CONFLICT (...) DO UPDATE SET ... -> ON DUPLICATE KEY UPDATE ...
       - ON CONFLICT (...) DO NOTHING -> ON DUPLICATE KEY UPDATE id=id
       - EXCLUDED.column -> VALUES(column)
       - INTERVAL '30 days' -> INTERVAL 30 DAY
    """
    def execute(self, query, vars=None, **kwargs):
        if isinstance(query, str):
            # 1. Translate INTERVAL '30 days' / INTERVAL '1 month'
            if 'INTERVAL' in query.upper():
                def _norm_interval(m):
                    num = m.group(1)
                    unit = m.group(2).rstrip('sS').upper()
                    return f"INTERVAL {num} {unit}"
                query = re.sub(
                    r"INTERVAL\s+'(\d+)\s+([A-Za-z]+)'",
                    _norm_interval,
                    query,
                    flags=re.IGNORECASE
                )


            # 2. Translate PostgreSQL ON CONFLICT to MySQL ON DUPLICATE KEY UPDATE
            u_query = query.upper()
            if 'ON CONFLICT' in u_query:
                # Replace EXCLUDED.col with VALUES(col)
                query = re.sub(r'EXCLUDED\.(\w+)', r'VALUES(\1)', query, flags=re.IGNORECASE)
                
                # ON CONFLICT (...) DO NOTHING
                if 'DO NOTHING' in u_query:
                    query = re.sub(
                        r'ON\s+CONFLICT\s*\([^)]*\)\s*DO\s+NOTHING',
                        r'ON DUPLICATE KEY UPDATE id=id',
                        query,
                        flags=re.IGNORECASE
                    )
                # ON CONFLICT (...) DO UPDATE SET ...
                elif 'DO UPDATE SET' in u_query:
                    query = re.sub(
                        r'ON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET\s+(.*)$',
                        r'ON DUPLICATE KEY UPDATE \1',
                        query,
                        flags=re.IGNORECASE | re.DOTALL
                    )

        return super().execute(query, vars, **kwargs)

    def fetchone(self):
        row = super().fetchone()
        return CaseInsensitiveDict(row) if row is not None else None

    def fetchall(self):
        rows = super().fetchall()
        return [CaseInsensitiveDict(r) for r in rows] if rows else []


# ── Connection Pool ──────────────────────────────────────────────────────────

_connection_pool = None

def _init_pool():
    global _connection_pool
    try:
        _connection_pool = pooling.MySQLConnectionPool(
            pool_name="hostinger_vps_pool",
            pool_size=15,
            pool_reset_session=True,
            **DB_CONFIG
        )
        print(f"[OK] Connected to Hostinger VPS MySQL pool ({DB_HOST}:{DB_PORT}/{DB_NAME})")
    except Error as e:
        print(f"[WARN] Error initializing database connection pool: {e}. Using direct connections.")
        _connection_pool = None

_init_pool()

def get_connection():
    """Open and return a new MySQL connection from pool or fresh direct connection."""
    global _connection_pool
    if _connection_pool:
        try:
            conn = _connection_pool.get_connection()
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
    Uses buffered=True to prevent 'Unread result found' errors in pooled connections.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        try:
            cur = conn.cursor(cursor_class=CaseInsensitiveMySQLCursor, buffered=True)
        except Error:
            if hasattr(conn, 'reconnect'):
                conn.reconnect(attempts=3, delay=1)
            else:
                conn = mysql.connector.connect(**DB_CONFIG)
            cur = conn.cursor(cursor_class=CaseInsensitiveMySQLCursor, buffered=True)

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
        if conn and hasattr(conn, 'is_connected') and conn.is_connected():
            try:
                conn.close()
            except Exception:
                pass
