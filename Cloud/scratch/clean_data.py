import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db import db_cursor

def clean_database():
    tables_to_clean = [
        "tblpayroll_details",
        "tblpayroll",
        "tblleave_transactions",
        "tblleave_balances",
        "tblleaves",
        "tblapprovals"
    ]
    
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for tbl in tables_to_clean:
            cur.execute(f"DELETE FROM {tbl}")
            print(f"[CLEANED] Cleared table {tbl}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    print("\nDatabase clean completed successfully!")

if __name__ == '__main__':
    clean_database()
