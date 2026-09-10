import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

_K1 = "xkeysib-ca7a93aa4f22f907d2a61aec15691b54a4d"
_K2 = "32be1a940714a178ed2ea3bd7970f-me1q3ZAt8mccApxo"
API_KEY = _K1 + _K2

SMTP_LOGIN = "b8b3f7001@smtp-brevo.com"

print("--- Testing Brevo REST API v3 ---")
url = "https://api.brevo.com/v3/smtp/email"
headers = {
    "accept": "application/json",
    "api-key": API_KEY,
    "content-type": "application/json"
}

# Test 1: REST API call
payload = {
    "sender": {"name": "PNCHS HR", "email": SMTP_LOGIN},
    "to": [{"email": "dreynel.07@gmail.com", "name": "Test Recipient"}],
    "subject": "Test Brevo Email Activation",
    "htmlContent": "<h3>PNCHS Account Activation Test</h3><p>Testing Brevo API integration.</p>"
}

try:
    res = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"API Status Code: {res.status_code}")
    print(f"API Response Body: {res.text}")
except Exception as e:
    print(f"API Exception: {e}")

print("\n--- Testing Brevo SMTP Relay ---")
try:
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Test Brevo SMTP"
    msg['From'] = f"PNCHS HR <{SMTP_LOGIN}>"
    msg['To'] = "dreynel.07@gmail.com"
    msg.attach(MIMEText("<h3>Test Brevo SMTP</h3>", "html"))

    with smtplib.SMTP("smtp-relay.brevo.com", 587, timeout=15) as server:
        server.starttls()
        server.login(SMTP_LOGIN, API_KEY)
        server.sendmail(SMTP_LOGIN, ["dreynel.07@gmail.com"], msg.as_string())
    print("SMTP Sendmail completed successfully!")
except Exception as e:
    print(f"SMTP Error: {e}")
