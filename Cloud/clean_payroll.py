"""
Utility to safely clean/purge all payroll data:
- tblpayroll_details (payroll breakdown lines)
- tblpayroll (payroll periods / headers)
- tblapprovals (where DocType = 'Payroll')

Leaves employee master data, leave credits, DTR logs, salary grades,
and global payheads completely untouched.
"""
from db import db_cursor

def clean_payroll_data():
    with db_cursor(commit=True) as (conn, cur):
        print("Checking existing records before cleanup...")
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll_details")
        details_cnt = cur.fetchone()['c']
        
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll")
        payroll_cnt = cur.fetchone()['c']
        
        cur.execute("SELECT COUNT(*) AS c FROM tblapprovals WHERE DocType = 'Payroll'")
        approvals_cnt = cur.fetchone()['c']
        
        print(f"Found: {payroll_cnt} payroll periods, {details_cnt} payroll details, {approvals_cnt} payroll approval requests.")
        
        print("Deleting payroll details...")
        cur.execute("DELETE FROM tblpayroll_details")
        
        print("Deleting payroll periods...")
        cur.execute("DELETE FROM tblpayroll")
        
        print("Deleting payroll approval entries...")
        cur.execute("DELETE FROM tblapprovals WHERE DocType = 'Payroll'")
        
        # Verify cleanup
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll_details")
        rem_details = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tblpayroll")
        rem_payroll = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM tblapprovals WHERE DocType = 'Payroll'")
        rem_approvals = cur.fetchone()['c']
        
        print(f"[SUCCESS] Cleanup completed successfully.")
        print(f"Remaining in tblpayroll: {rem_payroll}")
        print(f"Remaining in tblpayroll_details: {rem_details}")
        print(f"Remaining in tblapprovals (DocType='Payroll'): {rem_approvals}")

if __name__ == '__main__':
    clean_payroll_data()
