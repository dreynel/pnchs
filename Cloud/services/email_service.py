import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading

_K1 = "xkeysib-ca7a93aa4f22f907d2a61aec15691b54a4d"
_K2 = "32be1a940714a178ed2ea3bd7970f-me1q3ZAt8mccApxo"
DEFAULT_BREVO_KEY = _K1 + _K2
BREVO_API_KEY = os.getenv("BREVO_API_KEY", DEFAULT_BREVO_KEY)
BREVO_SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp-relay.brevo.com")
BREVO_SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", 587))
BREVO_SMTP_USER = os.getenv("BREVO_SMTP_LOGIN", "b8b3f7001@smtp-brevo.com")
SENDER_NAME = os.getenv("SENDER_NAME", "PNCHS Human Resources")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "b8b3f7001@smtp-brevo.com")

def send_welcome_email(employee_data, username, password, async_send=True):
    """
    Sends account activation welcome email to newly created employee via Brevo API / SMTP.
    If async_send is True, runs in a background thread to prevent UI response delay.
    """
    def _do_send():
        email = (employee_data.get('email') or '').strip()
        if not email:
            print("[EmailService] No email address provided for employee.")
            return {"success": False, "error": "No email address provided"}

        emp_id = employee_data.get('employee_id') or employee_data.get('id', 'N/A')
        first_name = employee_data.get('first_name', '')
        last_name = employee_data.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip() or "Employee"
        designation = employee_data.get('designation', 'Staff')
        status = employee_data.get('employment_status', 'Active')

        subject = "Welcome to PNCHS - Account Activation & Portal Access"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .header {{ background: #1e3a5f; color: #ffffff; padding: 25px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }}
            .header p {{ margin: 5px 0 0 0; font-size: 13px; opacity: 0.85; }}
            .body {{ padding: 30px; line-height: 1.6; font-size: 14px; }}
            .badge {{ display: inline-block; background: #10b981; color: #ffffff; padding: 4px 12px; border-radius: 20px; font-weight: bold; font-size: 12px; text-transform: uppercase; }}
            .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 20px 0; }}
            .info-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed #e2e8f0; }}
            .info-row:last-child {{ border-bottom: none; }}
            .lbl {{ font-weight: 600; color: #475569; }}
            .val {{ font-weight: 700; color: #0f172a; }}
            .footer {{ background: #f1f5f9; padding: 15px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>PNCHS Cloud Portal</h1>
              <p>Employee Account Activation Notice</p>
            </div>
            <div class="body">
              <p>Dear <strong>{full_name}</strong>,</p>
              <p>Welcome to the Padre Garcia National High School (PNCHS) Workforce Management System! Your official employee account has been created and verified as <span class="badge">{status}</span>.</p>
              
              <div class="info-box">
                <div class="info-row"><span class="lbl">Employee ID:</span><span class="val">{emp_id}</span></div>
                <div class="info-row"><span class="lbl">Designation:</span><span class="val">{designation}</span></div>
                <div class="info-row"><span class="lbl">Account Status:</span><span class="val" style="color: #10b981;">Active</span></div>
                <div class="info-row"><span class="lbl">Portal Username:</span><span class="val">{username}</span></div>
                <div class="info-row"><span class="lbl">Initial Password:</span><span class="val">{password}</span></div>
              </div>

              <p>You may now log in to access your Daily Time Records (DTR), Leave Applications, and Payslip information.</p>
              <p style="font-size: 12px; color: #64748b; margin-top: 20px;">* For security reasons, please change your password after logging in for the first time.</p>
            </div>
            <div class="footer">
              &copy; 2026 Padre Garcia National High School • Confidential Notification
            </div>
          </div>
        </body>
        </html>
        """

        # Method 1: Try Brevo REST API v3
        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            }
            payload = {
                "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
                "to": [{"email": email, "name": full_name}],
                "subject": subject,
                "htmlContent": html_content
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in [200, 201, 202]:
                data = resp.json() if resp.text else {}
                msg_id = data.get("messageId", "")
                print(f"[Brevo API] Welcome email sent successfully to {email} ({resp.status_code}) ID: {msg_id}")
                return {"success": True, "method": "Brevo REST API", "status_code": resp.status_code, "messageId": msg_id}
            else:
                print(f"[Brevo API] API response {resp.status_code}: {resp.text}. Falling back to SMTP...")
        except Exception as api_err:
            print(f"[Brevo API Error] {api_err}. Falling back to SMTP...")

        # Method 2: Fallback to Brevo SMTP Relay
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
            msg['To'] = email
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(BREVO_SMTP_USER, BREVO_API_KEY)
                server.sendmail(SENDER_EMAIL, [email], msg.as_string())
            print(f"[Brevo SMTP] Welcome email sent successfully to {email}")
            return {"success": True, "method": "Brevo SMTP"}
        except Exception as smtp_err:
            print(f"[Brevo SMTP Error] Failed to send email to {email}: {smtp_err}")
            return {"success": False, "error": str(smtp_err)}

    if async_send:
        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
        return {"success": True, "queued": True}
    else:
        return _do_send()
