import subprocess
import mysql.connector

passwords = [
    '', 'root', '123456', 'password', 'admin', 'pnchs', 'root1234', '1234', 'mysql',
    'YourSecurePassword123!', 'Password123!', '12345678', 'rootroot', 'p@ssword',
    'pnchs123', 'Passi123', 'passi', 'cloud'
]

found = False
print("--- Testing Local MySQL Passwords ---")
for pw in passwords:
    try:
        conn = mysql.connector.connect(host="localhost", user="root", password=pw, connect_timeout=2)
        if conn.is_connected():
            print(f"\n [✓] SUCCESS! Local MySQL root password is: '{pw}'")
            conn.close()
            found = True
            break
    except Exception as e:
        print(f" Tried '{pw}': {str(e)[:50]}")

if not found:
    print("\n [!] None of the common passwords matched. Testing Windows Service auth...")
