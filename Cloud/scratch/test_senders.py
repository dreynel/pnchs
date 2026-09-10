import requests

_K1 = "xkeysib-ca7a93aa4f22f907d2a61aec15691b54a4d"
_K2 = "32be1a940714a178ed2ea3bd7970f-me1q3ZAt8mccApxo"
API_KEY = _K1 + _K2

url = "https://api.brevo.com/v3/smtp/email"
headers = {
    "accept": "application/json",
    "api-key": API_KEY,
    "content-type": "application/json"
}

payload = {
    "sender": {"name": "PNCHS Human Resources", "email": "jasperiansusarno9@gmail.com"},
    "to": [{"email": "bjohnlenard@gmail.com", "name": "BJohn Lenard"}],
    "subject": "PNCHS Brevo Welcome Email Activation Test",
    "htmlContent": "<h3>PNCHS Account Activation Notice</h3><p>Testing verified Brevo sender jasperiansusarno9@gmail.com.</p>"
}

try:
    res = requests.post(url, json=payload, headers=headers, timeout=10)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
