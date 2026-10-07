import os
import re
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
from datetime import datetime
_cloud_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_cloud_dir, '.env')
_root_dir = os.path.dirname(_cloud_dir)
_candidate_envs = [
    os.path.join(_cloud_dir, '.env'),
    os.path.join(_root_dir, '.env')
]

try:
    from dotenv import load_dotenv
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        load_dotenv()
    for _p in _candidate_envs:
        if os.path.exists(_p):
            load_dotenv(_p)
    load_dotenv()
except ImportError:
    pass

# Always guarantee fallback parsing of .env if file exists and keys aren't in os.environ
if os.path.exists(_env_path):
    try:
        with open(_env_path, 'r', encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass
# Fallback parser for .env if python-dotenv is not installed
for _p in _candidate_envs:
    if os.path.exists(_p):
        try:
            with open(_p, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith('#') and '=' in _line:
                        _k, _v = _line.split('=', 1)
                        _k = _k.strip()
                        _v = _v.strip().strip('"').strip("'")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v
        except Exception:
            pass

# All credentials must come strictly from .env / environment variables
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")

# SMTP Configuration (Brevo default or custom SMTP like Gmail/Hostinger/cPanel)
SMTP_HOST = os.getenv("SMTP_HOST", os.getenv("BREVO_SMTP_HOST", "smtp-relay.brevo.com"))
SMTP_PORT = int(os.getenv("SMTP_PORT", os.getenv("BREVO_SMTP_PORT", 587)))
SMTP_USER = os.getenv("SMTP_USER", os.getenv("BREVO_SMTP_LOGIN", ""))
SMTP_PASS = os.getenv("SMTP_PASS", os.getenv("BREVO_SMTP_KEY", ""))

BREVO_SMTP_HOST = SMTP_HOST
BREVO_SMTP_PORT = SMTP_PORT
BREVO_SMTP_USER = SMTP_USER
BREVO_SMTP_PASS = SMTP_PASS

SENDER_NAME = os.getenv("SENDER_NAME", "Pototan National Comprehensive High School (PNCHS)")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')

def is_valid_email(email):
    """Checks whether an email address has a valid syntactic structure."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def validate_email_service():
    """
    Validates Brevo API connectivity, SMTP relay status, sender configuration, and credentials.
    Returns a comprehensive diagnostic dictionary.
    """
    report = {
        "configured": bool(BREVO_API_KEY),
        "api_valid": False,
        "smtp_valid": False,
        "sender_email": SENDER_EMAIL,
        "sender_name": SENDER_NAME,
        "api_message": "",
        "smtp_message": "",
        "overall_status": "error"
    }

    if not BREVO_API_KEY:
        report["api_message"] = "Brevo API key is missing or not configured."
        return report

    # 1. Test Brevo API endpoint /v3/account
    try:
        url = "https://api.brevo.com/v3/account"
        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json() if resp.text else {}
            report["api_valid"] = True
            report["api_message"] = f"Brevo API authenticated successfully (Account: {data.get('email', 'OK')})."
        elif resp.status_code == 401:
            err_data = resp.json() if resp.text else {}
            raw_msg = err_data.get('message', 'Unauthorized API key')
            if 'unrecognised IP' in raw_msg or 'authorised_ips' in raw_msg:
                report["api_message"] = f"Brevo API requires IP authorization: {raw_msg}"
            else:
                report["api_message"] = f"Brevo API Unauthorized (401): {raw_msg}"
        else:
            report["api_message"] = f"Brevo API returned status code {resp.status_code}."
    except Exception as api_err:
        report["api_message"] = f"Brevo API request failed: {str(api_err)}"

    # 2. Test Brevo SMTP Relay connection
    try:
        with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT, timeout=8) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(BREVO_SMTP_USER, BREVO_SMTP_PASS)
            report["smtp_valid"] = True
            report["smtp_message"] = f"Brevo SMTP relay ({BREVO_SMTP_HOST}:{BREVO_SMTP_PORT}) authenticated successfully."
    except Exception as smtp_err:
        report["smtp_message"] = f"Brevo SMTP connection/auth error: {str(smtp_err)}"

    if report["api_valid"] or report["smtp_valid"]:
        report["overall_status"] = "healthy"
    else:
        report["overall_status"] = "attention_needed"

    report["status"] = report["overall_status"]

    return report


def send_welcome_email(employee_data, username, password, async_send=True):
    """
    Sends account activation welcome email to newly created employee via Brevo API / SMTP.
    If async_send is True, runs in a background thread to prevent UI response delay.
    """
    def _do_send():
        email = (employee_data.get('email') or '').strip()
        if not email or not is_valid_email(email):
            print(f"[EmailService] Invalid or missing recipient email address: '{email}'.")
            return {"success": False, "error": f"Invalid or missing email address: '{email}'"}

        emp_id = employee_data.get('employee_id') or employee_data.get('id', 'N/A')
        first_name = employee_data.get('first_name', '').strip()
        middle_name = employee_data.get('middle_name', '').strip()
        last_name = employee_data.get('last_name', '').strip()
        full_name = f"{first_name} {middle_name} {last_name}".strip() if middle_name else f"{first_name} {last_name}".strip()
        if not full_name:
            full_name = "Employee"
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
              <h1>Pototan National Comprehensive High School</h1>
              <p>Employee Account Activation Notice (PNCHS)</p>
            </div>
            <div class="body">
              <p>Dear <strong>{full_name}</strong>,</p>
              <p>Welcome to the Pototan National Comprehensive High School (PNCHS) Workforce Management System! Your official employee account has been created and verified as <span class="badge">{status}</span>.</p>
              
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
              &copy; 2026 Pototan National Comprehensive High School (PNCHS) • Confidential Notification
            </div>
          </div>
        </body>
        </html>
        """

        last_api_error = ""
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
            resp = requests.post(url, json=payload, headers=headers, timeout=6)
            if resp.status_code in [200, 201, 202]:
                data = resp.json() if resp.text else {}
                msg_id = data.get("messageId", "")
                print(f"[Brevo API] Welcome email sent successfully to {email} ({resp.status_code}) ID: {msg_id}")
                return {"success": True, "method": "Brevo REST API", "status_code": resp.status_code, "messageId": msg_id, "message": "Email sent successfully via Brevo API"}
            else:
                raw_err = resp.text
                try:
                    err_json = resp.json()
                    raw_err = err_json.get('message', resp.text)
                except Exception:
                    pass
                last_api_error = f"Brevo API ({resp.status_code}): {raw_err}"
                print(f"[Brevo API] {last_api_error}. Trying SMTP fallback...")
        except Exception as api_err:
            last_api_error = f"Brevo API error: {str(api_err)}"
            print(f"[Brevo API Error] {last_api_error}. Trying SMTP fallback...")

        # Method 2: Fallback to SMTP Relay
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
            msg['To'] = email
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=6) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SENDER_EMAIL, [email], msg.as_string())
            print(f"[SMTP] Welcome email sent successfully to {email} via {SMTP_HOST}")
            return {"success": True, "method": f"SMTP ({SMTP_HOST})", "message": "Email sent successfully via SMTP"}
        except Exception as smtp_err:
            print(f"[SMTP Error] Failed to send email to {email}: {smtp_err}")
            err_details = str(smtp_err)
            if 'unrecognised IP' in last_api_error or 'authorised_ips' in last_api_error:
                err_details = last_api_error
            elif last_api_error:
                err_details = f"{last_api_error} | SMTP Error: {smtp_err}"
            return {"success": False, "error": err_details}

    if async_send:
        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
        return {"success": True, "queued": True}
    else:
        return _do_send()


def send_login_notification_email(user_info, ip_address):
    """
    Sends a security notification email via Brevo when a user logs in successfully.
    Executed in a background thread to avoid delaying page load.
    """
    def _do_send():
        email = (user_info.get('email') or '').strip()
        if not email or '@' not in email:
            return

        name = user_info.get('name') or user_info.get('username') or 'User'
        role = user_info.get('role') or 'Staff'
        login_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S PST')

        subject = f"Security Alert: Successful Login to PNCHS Portal ({role})"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; color: #333; }}
            .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .header {{ background: #1e3a5f; color: #ffffff; padding: 22px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
            .header p {{ margin: 4px 0 0 0; font-size: 12px; opacity: 0.85; }}
            .body {{ padding: 25px; line-height: 1.6; font-size: 13.5px; }}
            .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin: 15px 0; }}
            .info-row {{ display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #e2e8f0; }}
            .info-row:last-child {{ border-bottom: none; }}
            .lbl {{ font-weight: 600; color: #475569; }}
            .val {{ font-weight: 700; color: #0f172a; }}
            .footer {{ background: #f1f5f9; padding: 12px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>Pototan National Comprehensive High School</h1>
              <p>Security Alert: Successful Login Notification (PNCHS)</p>
            </div>
            <div class="body">
              <p>Hello <strong>{name}</strong>,</p>
              <p>We detected a successful login to your account at Pototan National Comprehensive High School (PNCHS).</p>
              <div class="info-box">
                <div class="info-row"><span class="lbl">User Name:</span><span class="val">{name}</span></div>
                <div class="info-row"><span class="lbl">Account Role:</span><span class="val">{role}</span></div>
                <div class="info-row"><span class="lbl">Timestamp:</span><span class="val">{login_time}</span></div>
                <div class="info-row"><span class="lbl">IP Address:</span><span class="val">{ip_address or '127.0.0.1'}</span></div>
              </div>
              <p style="font-size: 12px; color: #64748b;">If this was you, no further action is required. If you did not authorize this login, please contact your administrator immediately.</p>
            </div>
            <div class="footer">&copy; 2026 Pototan National Comprehensive High School (PNCHS) • Security Service</div>
          </div>
        </body>
        </html>
        """

        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            }
            payload = {
                "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
                "to": [{"email": email, "name": name}],
                "subject": subject,
                "htmlContent": html_content
            }
            res = requests.post(url, json=payload, headers=headers, timeout=8)
            print(f"[LoginNotif Email] Sent to {email} ({res.status_code})")
        except Exception as e:
            print(f"[LoginNotif Email Error] {e}")

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()
