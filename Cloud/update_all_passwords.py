"""
Update all user accounts in tblusers to have correctly hashed password 'Password123!'
and verify each account with check_password_hash.
"""
from db import db_cursor
from werkzeug.security import generate_password_hash, check_password_hash

def update_all_passwords():
    raw_password = "Password123!"
    hashed_password = generate_password_hash(raw_password)
    
    print(f"Generated hash: {hashed_password[:35]}... (len: {len(hashed_password)})")
    assert check_password_hash(hashed_password, raw_password), "Hash verification failed!"
    
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT COUNT(*) AS total FROM tblusers")
        total = cur.fetchone()['total']
        print(f"Updating passwords for all {total} users in tblusers...")
        
        cur.execute("UPDATE tblusers SET password = %s", (hashed_password,))
        
        # Verify every user
        cur.execute("SELECT id, username, role, name, password FROM tblusers ORDER BY role, username")
        users = cur.fetchall()
        
        all_ok = True
        for u in users:
            stored = u['password']
            valid = check_password_hash(stored, raw_password)
            if not valid:
                print(f"[FAIL] User {u['username']} password check failed!")
                all_ok = False
        
        if all_ok:
            print(f"[SUCCESS] All {len(users)} user accounts in tblusers successfully updated and verified for '{raw_password}'!")
        else:
            print("[ERROR] Some user accounts could not be verified.")

if __name__ == '__main__':
    update_all_passwords()
