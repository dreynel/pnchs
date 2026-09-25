import psycopg2

NEON_URI = "postgresql://neondb_owner:npg_ZX56pOIfsgqo@ep-restless-pond-avdmjozs-pooler.c-11.us-east-1.aws.neon.tech/pnchs?sslmode=require&channel_binding=require"

def verify():
    conn = psycopg2.connect(NEON_URI)
    cur = conn.cursor()

    # Clean up IFNULL function
    cur.execute("DROP FUNCTION IF EXISTS IFNULL(anyelement, anyelement);")
    cur.execute("""
    CREATE OR REPLACE FUNCTION IFNULL(a anycompatible, b anycompatible) RETURNS anycompatible AS $$
    BEGIN
        RETURN COALESCE(a, b);
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    """)
    conn.commit()

    # Query public tables
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Total tables: {len(tables)}")
    
    print("\nTable Row Counts:")
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}";')
        cnt = cur.fetchone()[0]
        print(f"  - {t:25}: {cnt}")

    # Test compatibility functions
    cur.execute("SELECT YEAR(CURRENT_DATE), MONTH(CURRENT_DATE), IFNULL(NULL, 'test_fallback'), CURDATE();")
    print("\nCompatibility functions check:")
    print("  YEAR(CURRENT_DATE):", cur.fetchone())

    conn.close()

if __name__ == '__main__':
    verify()
