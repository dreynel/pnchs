import os
import re
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2 import Error, DatabaseError, OperationalError, IntegrityError
import psycopg2.extras
import psycopg2.extensions

# ── Neon Database Configuration ───────────────────────────────────────────────

NEON_DEFAULT_URI = "postgresql://neondb_owner:npg_ZX56pOIfsgqo@ep-restless-pond-avdmjozs-pooler.c-11.us-east-1.aws.neon.tech/pnchs?sslmode=require&channel_binding=require"

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("NEON_DATABASE_URL")
    or os.getenv("DB_URI")
    or NEON_DEFAULT_URI
)

# ── Case-Insensitive Dict Row ────────────────────────────────────────────────

class CaseInsensitiveRow(psycopg2.extras.RealDictRow):
    """
    Subclass of RealDictRow providing case-insensitive key lookup.
    Enables legacy column lookups like row['ApprovalID'] to transparently
    match PostgreSQL lowercase column names ('approvalid').
    """
    def __getitem__(self, key):
        if super().__contains__(key):
            return super().__getitem__(key)
        if isinstance(key, str):
            lk = key.lower()
            for k in self.keys():
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
            return any(isinstance(k, str) and k.lower() == lk for k in self.keys())
        return False


# ── PostgreSQL Cursor with MySQL Compatibility & Lastrowid ───────────────────

class CaseInsensitiveRealDictCursor(psycopg2.extras.RealDictCursor):
    """
    Custom cursor that:
    1. Returns CaseInsensitiveRow instances for dict-like row access.
    2. Provides cur.lastrowid using LASTVAL() on INSERT queries.
    3. Preprocesses SQL queries to seamlessly handle MySQL constructs:
       - Strips backticks (`identifier` -> identifier).
       - Rewrites CAST(... AS CHAR) to CAST(... AS VARCHAR).
       - Translates ON DUPLICATE KEY UPDATE to PostgreSQL ON CONFLICT.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_factory = CaseInsensitiveRow
        self._lastrowid = None

    @property
    def lastrowid(self):
        return self._lastrowid

    def execute(self, query, vars=None):
        if isinstance(query, str):
            # 1. Strip backticks
            if '`' in query:
                query = query.replace('`', '')

            # 2. Rewrite CAST(... AS CHAR) -> CAST(... AS VARCHAR)
            if 'AS CHAR' in query.upper():
                query = re.sub(
                    r'CAST\s*\(\s*(.*?)\s+AS\s+CHAR\s*\)', 
                    r'CAST(\1 AS VARCHAR)', 
                    query, 
                    flags=re.IGNORECASE
                )

            # 3. Rewrite unquoted INTERVAL (e.g. INTERVAL 30 DAY -> INTERVAL '30 DAY')
            if 'INTERVAL' in query.upper():
                query = re.sub(
                    r'INTERVAL\s+(\d+)\s+([A-Za-z]+)',
                    r"INTERVAL '\1 \2'",
                    query,
                    flags=re.IGNORECASE
                )

            # 4. Translate SHOW TABLES [LIKE '...']
            if query.strip().upper().startswith("SHOW TABLES"):
                m = re.match(r'^\s*SHOW\s+TABLES\s+LIKE\s+(.+)$', query, flags=re.IGNORECASE)
                if m:
                    like_pat = m.group(1).rstrip(';')
                    query = f"SELECT tablename as Tables_in_database FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE {like_pat}"
                else:
                    query = "SELECT tablename as Tables_in_database FROM pg_tables WHERE schemaname = 'public'"

            # 5. Translate INSERT IGNORE INTO ... -> INSERT INTO ... ON CONFLICT DO NOTHING
            if 'INSERT IGNORE INTO' in query.upper():
                query = re.sub(r'INSERT\s+IGNORE\s+INTO', 'INSERT INTO', query, flags=re.IGNORECASE)
                if 'ON CONFLICT' not in query.upper():
                    clean_q = query.rstrip().rstrip(';')
                    query = f"{clean_q} ON CONFLICT DO NOTHING"

            # 6. Transparent translation of ON DUPLICATE KEY UPDATE
            u_query = query.upper()
            if 'ON DUPLICATE KEY UPDATE' in u_query:
                if 'TBLLEAVE_BALANCES' in u_query:
                    query = re.sub(r'ON\s+DUPLICATE\s+KEY\s+UPDATE.*$', 'ON CONFLICT (employee_id) DO NOTHING', query, flags=re.IGNORECASE | re.DOTALL)
                elif 'TBLPOLICY_CONFIG' in u_query:
                    query = re.sub(r'ON\s+DUPLICATE\s+KEY\s+UPDATE.*$', 'ON CONFLICT (config_key) DO UPDATE SET config_value=EXCLUDED.config_value', query, flags=re.IGNORECASE | re.DOTALL)
                elif 'FINGERPRINTS' in u_query:
                    query = re.sub(r'ON\s+DUPLICATE\s+KEY\s+UPDATE.*$', 'ON CONFLICT (employee_id, finger_index) DO UPDATE SET fingerprint_template=EXCLUDED.fingerprint_template, user_name=EXCLUDED.user_name', query, flags=re.IGNORECASE | re.DOTALL)
                elif 'TBLAPPROVALS' in u_query:
                    query = re.sub(r'ON\s+DUPLICATE\s+KEY\s+UPDATE.*$', 'ON CONFLICT (doctype, docnumber) DO UPDATE SET approvalstatus=\'Pending\', requesterid=EXCLUDED.requesterid', query, flags=re.IGNORECASE | re.DOTALL)
                elif 'TBLSALARY_GRADES' in u_query:
                    query = re.sub(
                        r'ON\s+DUPLICATE\s+KEY\s+UPDATE.*$', 
                        'ON CONFLICT (salary_grade) DO UPDATE SET position_title=EXCLUDED.position_title, step_1=EXCLUDED.step_1, step_2=EXCLUDED.step_2, step_3=EXCLUDED.step_3, step_4=EXCLUDED.step_4, step_5=EXCLUDED.step_5, step_6=EXCLUDED.step_6, step_7=EXCLUDED.step_7, step_8=EXCLUDED.step_8', 
                        query, 
                        flags=re.IGNORECASE | re.DOTALL
                    )

        res = super().execute(query, vars)

        # Sequence ID tracking for lastrowid
        self._lastrowid = None
        if isinstance(query, str) and query.strip().upper().startswith("INSERT "):
            try:
                super().execute("SAVEPOINT _sp_lastrowid;")
                with self.connection.cursor(cursor_factory=psycopg2.extensions.cursor) as id_cur:
                    id_cur.execute("SELECT LASTVAL();")
                    id_res = id_cur.fetchone()
                    if id_res:
                        self._lastrowid = id_res[0]
                super().execute("RELEASE SAVEPOINT _sp_lastrowid;")
            except Exception:
                try:
                    super().execute("ROLLBACK TO SAVEPOINT _sp_lastrowid;")
                except Exception:
                    pass
                self._lastrowid = None

        return res


# ── PostgreSQL Connection Wrapper ─────────────────────────────────────────────

class PostgresConnection(psycopg2.extensions.connection):
    """
    Subclass of psycopg2 connection that:
    - Automatically uses CaseInsensitiveRealDictCursor when dictionary=True or no factory specified.
    - Implements is_connected() and reconnect() for backwards compatibility with mysql.connector.
    """
    def cursor(self, *args, **kwargs):
        kwargs.pop('buffered', None)
        if kwargs.pop('dictionary', False) or 'cursor_factory' not in kwargs:
            kwargs['cursor_factory'] = CaseInsensitiveRealDictCursor
        return super().cursor(*args, **kwargs)

    def is_connected(self):
        return self.closed == 0

    def reconnect(self, attempts=3, delay=1):
        # psycopg2 connections handle pooling at pool level; no-op if alive
        pass


# ── Threaded Connection Pool ──────────────────────────────────────────────────

connection_pool = None

def _init_pool():
    global connection_pool
    try:
        connection_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=DATABASE_URL,
            connection_factory=PostgresConnection
        )
        print("[OK] Connected to PostgreSQL pool (Neon)")
    except Exception as e:
        print(f"[WARNING] Error initializing PostgreSQL pool: {e}")
        connection_pool = None

_init_pool()


def get_connection():
    """
    Obtain a verified healthy connection from the pool or a fresh connection.
    Recycles stale/idle connections automatically.
    """
    global connection_pool
    if connection_pool:
        try:
            conn = connection_pool.getconn()
            if conn and conn.closed == 0:
                # Test connection liveness
                try:
                    with conn.cursor() as test_cur:
                        test_cur.execute("SELECT 1;")
                    return conn
                except Exception:
                    # Connection dropped by Neon pooler, discard and retry
                    try:
                        connection_pool.putconn(conn, close=True)
                    except Exception:
                        pass
            else:
                try:
                    connection_pool.putconn(conn, close=True)
                except Exception:
                    pass
        except Exception:
            pass

    # Direct connection fallback
    return psycopg2.connect(DATABASE_URL, connection_factory=PostgresConnection)


def release_connection(conn, close=False):
    """Release a connection back to the pool or close it."""
    global connection_pool
    if connection_pool:
        try:
            connection_pool.putconn(conn, close=close)
            return
        except Exception:
            pass
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def db_cursor(commit=False):
    """
    Context manager that yields (conn, cur).
    Automatically commits or rolls back, then cleans up cursor and connection.
    """
    conn = None
    cur  = None
    try:
        conn = get_connection()
        cur  = conn.cursor(cursor_factory=CaseInsensitiveRealDictCursor)
        yield conn, cur
        if commit:
            conn.commit()
    except Exception as e:
        if conn and conn.closed == 0:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        if cur and not cur.closed:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            release_connection(conn)


def is_postgres():
    return True
