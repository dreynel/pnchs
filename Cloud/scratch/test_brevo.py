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

senders_to_test = [
    "bjohnlenard@gmail.com",
    "b8b3f7001@smtp-brevo.com",
    "noreply@pnchs.edu.ph"
]

recipient = "bjohnlenard@gmail.com"

for s in senders_to_test:
    print(f"\n--- Testing Sender: {s} ---> {recipient} ---")
    payload = {
        "sender": {"name": "PNCHS Human Resources", "email": s},
        "to": [{"email": recipient, "name": "BJohn Lenard"}],
        "subject": f"PNCHS Account Activation Notice (Sender Test {s})",
        "htmlContent": f"<h3>PNCHS Account Activation Test</h3><p>Testing Brevo API sender <strong>{s}</strong>.</p>"
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(f"Error: {e}")
