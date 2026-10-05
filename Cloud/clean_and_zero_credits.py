"""
Utility to:
1. Clean all processed payroll runs and payroll details (Draft, For Approval, Approved, Released).
2. Temporarily set all employee leave credits (VL & SL) to 0 for testing.
"""
from db import db_cursor

def clean_payroll_and_zero_credits():
    with db_cursor(commit=True) as (conn, cur):
        print("Cleaning payroll records...")
        cur.execute("DELETE FROM tblpayroll_details")
        cur.execute("DELETE FROM tblpayroll")
        cur.execute("DELETE FROM tblapprovals WHERE DocType = 'Payroll'")
        print("[OK] Deleted all payroll records, details, and payroll approval tasks.")

        print("Setting all employee leave credits to 0 for testing...")
        cur.execute("UPDATE tblleave_balances SET vl_minutes = 0, sl_minutes = 0")
        
        # Verify
        cur.execute("SELECT COUNT(*) as count, SUM(vl_minutes) as total_vl, SUM(sl_minutes) as total_sl FROM tblleave_balances")
        res = cur.fetchone()
        print(f"[OK] Leave balances updated: {res['count']} employee rows, Total VL = {res['total_vl']}, Total SL = {res['total_sl']}")

if __name__ == '__main__':
    clean_payroll_and_zero_credits()
