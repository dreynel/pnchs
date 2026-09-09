import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db import db_cursor

def clean_payroll_data():
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        
        cur.execute("DELETE FROM tblpayroll_details")
        print("[CLEANED] Cleared table tblpayroll_details")
        
        cur.execute("DELETE FROM tblpayroll")
        print("[CLEANED] Cleared table tblpayroll")
        
        cur.execute("DELETE FROM tblapprovals WHERE LOWER(DocType) LIKE '%payroll%'")
        print("[CLEANED] Cleared payroll entries from tblapprovals")
        
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        
    print("\nPayroll data cleaned successfully!")

if __name__ == '__main__':
    clean_payroll_data()
