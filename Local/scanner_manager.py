import threading
import time
import base64
import requests
import os
try:
    from pyzkfp import ZKFP2
except ImportError:
    ZKFP2 = None

CLOUD_API_URL = os.environ.get('CLOUD_API_URL', 'http://187.52.121.22:8080')
MATCH_THRESHOLD = 55

state_lock = threading.RLock()

KIOSK_STATE = {
    'status': 'stopped',     # stopped, running, error
    'last_scan': None,
    'last_error': None,
    'cooldowns': {},          # employee_id -> last_log_time
    'enroll_step': 0,
    'enroll_error': None
}

_thread_handle = None
_running = False

def sync_fingerprints_from_cloud():
    """Fetch all fingerprints directly from the live Hostinger database."""
    users_dict = {}
    try:
        from db import db_cursor
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id, employee_id, user_name, fingerprint_template, finger_index FROM fingerprints")
            data = cur.fetchall()
            for r in data:
                try:
                    template_bytes = base64.b64decode(r['fingerprint_template'])
                    key = (r['employee_id'], r.get('finger_index', 1))
                    users_dict[key] = (r['id'], r['employee_id'], r['user_name'], template_bytes)
                except Exception:
                    pass
            print(f"[SYNC] Loaded {len(users_dict)} templates directly from live database.")
    except Exception as e:
        print(f"[SYNC] Direct DB sync notice: {e}")

    return list(users_dict.values())



def _scanner_loop():
    global _running

    if ZKFP2 is None:
        print("[INFO] PyZKFP SDK native libraries not available.")
        with state_lock:
            KIOSK_STATE['status'] = 'disconnected'
            _running = False
        return

    zkfp = None
    device_open = False
    
    enroll_task = None
    enroll_step = 0
    enroll_timeout = 0
    last_db_check = time.time()
    last_task_poll = 0
    last_hw_check = 0

    print("[INFO] Starting real-time USB Biometric Scanner monitor...")

    while _running:
        # ── 1. Device Reconnection / Initialization Loop ──────────────────────
        if not device_open:
            with state_lock:
                KIOSK_STATE['status'] = 'disconnected'
            try:
                zkfp = ZKFP2()
                zkfp.Init()
                dev_count = zkfp.GetDeviceCount()
                if dev_count > 0:
                    zkfp.OpenDevice(0)
                    device_open = True
                    with state_lock:
                        KIOSK_STATE['status'] = 'running'
                    print("[SUCCESS] Physical USB Biometric Fingerprint Reader connected & active!")
                    
                    # Sync fingerprints from Database into reader RAM
                    id_map = {}
                    users = sync_fingerprints_from_cloud()
                    for row_id, emp_id, user_name, template in users:
                        try:
                            zkfp.DBAdd(row_id, template)
                            id_map[row_id] = {'employee_id': emp_id, 'name': user_name}
                        except Exception as ex:
                            pass
                else:
                    try:
                        zkfp.Terminate()
                    except Exception: pass
                    zkfp = None
                    time.sleep(2.0)
                    continue
            except Exception as e:
                device_open = False
                try:
                    if zkfp:
                        zkfp.CloseDevice()
                        zkfp.Terminate()
                except Exception: pass
                zkfp = None
                with state_lock:
                    KIOSK_STATE['status'] = 'disconnected'
                time.sleep(2.0)
                continue


        # ── 2. Active Scanner Operation Loop ──────────────────────────────────
        try:
            now = time.time()

            if not enroll_task and (now - last_task_poll >= 1.0):
                last_task_poll = now
                try:
                    from db import db_cursor
                    with db_cursor() as (conn, cur):
                        cur.execute("SELECT * FROM tblenrollment_tasks WHERE status='pending' ORDER BY id ASC LIMIT 1")
                        task = cur.fetchone()
                        if task:
                            enroll_task = task
                            enroll_templates = []
                            enroll_timeout = 0
                            last_db_check = time.time()
                            with state_lock:
                                KIOSK_STATE['enroll_step'] = 1
                                KIOSK_STATE['enroll_error'] = None
                            print(f"Discovered new enrollment task: {enroll_task}")
                except Exception:
                    pass

            if enroll_task:
                # Check DB for cancellation every 1.5 seconds
                now = time.time()
                if now - last_db_check >= 1.5:
                    last_db_check = now
                    try:
                        from db import db_cursor
                        with db_cursor() as (conn, cur):
                            cur.execute("SELECT status FROM tblenrollment_tasks WHERE id=%s", (enroll_task['id'],))
                            chk = cur.fetchone()
                            if not chk or chk['status'] != 'pending':
                                print(f"Enroll task {enroll_task['id']} was cancelled or modified. Dropping.")
                                enroll_task = None
                                continue
                    except Exception:
                        pass
                
                if enroll_step <= 3:
                    if enroll_timeout > 600:  # 60s timeout
                        print("Enrollment timeout: 60s elapsed without input.")
                        try:
                            from db import db_cursor
                            with db_cursor(commit=True) as (conn, cur):
                                cur.execute("UPDATE tblenrollment_tasks SET status='error', error_message='Enrollment timed out.' WHERE id=%s", (enroll_task['id'],))
                        except Exception: pass
                        enroll_task = None
                        with state_lock:
                            KIOSK_STATE['enroll_step'] = 0
                            KIOSK_STATE['enroll_error'] = 'Enrollment timed out.'
                        continue

                    res = zkfp.AcquireFingerprint()
                    if res:
                        tmp, img = res
                        if not tmp or len(tmp) == 0:
                            enroll_timeout += 1
                            time.sleep(0.1)
                            continue

                        enroll_timeout = 0

                        # Check for duplicate fingerprints against other registered employees
                        if len(id_map) > 0:
                            try:
                                fid, score = zkfp.DBIdentify(tmp)
                                if score >= MATCH_THRESHOLD:
                                    matched_emp = id_map.get(fid, {})
                                    matched_emp_id = matched_emp.get('employee_id')
                                    if matched_emp_id and matched_emp_id != enroll_task['employee_id']:
                                        is_ghost = False
                                        try:
                                            with db_cursor() as (conn, cur):
                                                cur.execute("SELECT id FROM tblemployee WHERE employee_id=%s", (matched_emp_id,))
                                                if not cur.fetchone():
                                                    is_ghost = True
                                        except Exception: pass
                                        
                                        if is_ghost:
                                            try:
                                                zkfp.DBDel(fid)
                                                if fid in id_map: del id_map[fid]
                                            except Exception: pass
                                        else:
                                            matched_name = matched_emp.get('name', 'Unknown')
                                            err_msg = f"Fingerprint already assigned to {matched_name} ({matched_emp_id})."
                                            try:
                                                from db import db_cursor
                                                with db_cursor(commit=True) as (conn, cur):
                                                    cur.execute("UPDATE tblenrollment_tasks SET status='error', error_message=%s WHERE id=%s", (err_msg, enroll_task['id']))
                                            except Exception: pass
                                            enroll_task = None
                                            with state_lock:
                                                KIOSK_STATE['enroll_step'] = 0
                                                KIOSK_STATE['enroll_error'] = err_msg
                                            time.sleep(1.5)
                                            continue
                            except Exception as dup_err:
                                print(f"[ENROLL] Duplicate check notice: {dup_err}")

                        enroll_templates.append(tmp)
                        enroll_step += 1
                        scanned_count = enroll_step - 1
                        step_msg = f"Scan {scanned_count} of 3 recorded! Lift finger and touch sensor again..." if scanned_count < 3 else "Merging fingerprint templates..."

                        try:
                            from db import db_cursor
                            with db_cursor(commit=True) as (conn, cur):
                                cur.execute("UPDATE tblenrollment_tasks SET step=%s, message=%s WHERE id=%s", (min(enroll_step, 3), step_msg, enroll_task['id']))
                        except Exception: pass

                        with state_lock:
                            KIOSK_STATE['enroll_step'] = min(enroll_step, 3)
                        print(f"Enroll scan {scanned_count} of 3 successful.")
                        time.sleep(1.2)  # Sensor recalibration pause between scans
                else:
                    # DBMerge templates from the 3 valid scans
                    try:
                        print(f"[ENROLL] Merging {len(enroll_templates)} scans for {enroll_task['employee_id']}...")
                        merged_template, merged_len = zkfp.DBMerge(enroll_templates[0], enroll_templates[1], enroll_templates[2])
                    except Exception as merge_err:
                        print(f"[ENROLL] DBMerge call failed: {merge_err}")
                        merged_template, merged_len = None, 0

                    if merged_template is None or merged_len == 0:
                        err_msg = "Could not combine the 3 scans. Please place the same finger firmly and try again."
                        print(f"[ENROLL ERROR] {err_msg}")
                        try:
                            from db import db_cursor
                            with db_cursor(commit=True) as (conn, cur):
                                cur.execute("UPDATE tblenrollment_tasks SET status='error', error_message=%s WHERE id=%s", (err_msg, enroll_task['id']))
                        except Exception: pass
                        with state_lock:
                            KIOSK_STATE['enroll_step'] = 0
                            KIOSK_STATE['enroll_error'] = err_msg
                    else:
                        template_bytes = bytes(merged_template)
                        if 0 < merged_len < len(template_bytes):
                            template_bytes = template_bytes[:merged_len]

                        template_b64 = base64.b64encode(template_bytes).decode('utf-8')
                        
                        try:
                            from db import db_cursor
                            with db_cursor(commit=True) as (conn, cur):
                                cur.execute("SELECT first_name, last_name FROM tblemployee WHERE employee_id=%s", (enroll_task['employee_id'],))
                                emp = cur.fetchone()
                                user_name = f"{emp['first_name']} {emp['last_name']}" if emp else str(enroll_task['employee_id'])

                                cur.execute("""
                                    INSERT INTO fingerprints (employee_id, user_name, fingerprint_template, finger_index)
                                    VALUES (%s, %s, %s, %s)
                                    ON DUPLICATE KEY UPDATE 
                                        fingerprint_template = VALUES(fingerprint_template),
                                        user_name = VALUES(user_name)
                                """, (enroll_task['employee_id'], user_name, template_b64, enroll_task['finger_index']))

                                cur.execute("UPDATE tblenrollment_tasks SET status='success', step=3, message='Fingerprint registered successfully!' WHERE id=%s", (enroll_task['id'],))

                            new_local_id = max(list(id_map.keys()) + [0]) + 1
                            try:
                                zkfp.DBAdd(new_local_id, template_bytes)
                            except Exception: pass
                            id_map[new_local_id] = {'employee_id': enroll_task['employee_id'], 'name': user_name}
                            print(f"[ENROLL SUCCESS] Fingerprint enrolled for {user_name} ({enroll_task['employee_id']}).")
                            with state_lock:
                                KIOSK_STATE['enroll_step'] = 3
                                KIOSK_STATE['enroll_error'] = None
                        except Exception as e:
                            print(f"[ENROLL ERROR] Error saving enrollment to database: {e}")
                            with state_lock:
                                KIOSK_STATE['enroll_error'] = f"Database error: {e}"

                    enroll_task = None
                    enroll_templates = []
                    enroll_step = 0

            else:
                # Normal Kiosk Attendance Scanning Mode
                # Periodic sync fingerprints from DB every 30 seconds
                if now - last_db_check >= 30.0:
                    last_db_check = now
                    try:
                        fresh_users = sync_fingerprints_from_cloud()
                        if len(fresh_users) != len(id_map):
                            print(f"[SYNC] Database fingerprint count changed ({len(id_map)} -> {len(fresh_users)}). Reloading RAM cache.")
                            try:
                                zkfp.DBClear()
                            except Exception: pass
                            id_map.clear()
                            for row_id, emp_id, user_name, template in fresh_users:
                                try:
                                    zkfp.DBAdd(row_id, template)
                                    id_map[row_id] = {'employee_id': emp_id, 'name': user_name}
                                except Exception: pass
                    except Exception as sync_err:
                        print(f"[SYNC] Periodic sync notice: {sync_err}")

                res = zkfp.AcquireFingerprint()
                if res:
                    tmp, img = res
                    if len(id_map) > 0:
                        try:
                            fid, score = zkfp.DBIdentify(tmp)
                            if score >= MATCH_THRESHOLD:
                                user_info = id_map.get(fid)
                                if user_info:
                                    emp_id = user_info['employee_id']
                                    now = time.time()
                                    with state_lock:
                                        last_log = KIOSK_STATE['cooldowns'].get(emp_id, 0)
                                        if now - last_log < 7:
                                            # Same person double-tap cooldown
                                            time.sleep(0.3)
                                            continue
                                            
                                        print(f"[SCAN MATCH] Identified: {user_info['name']} (score: {score})")
                                        KIOSK_STATE['last_scan'] = {
                                            'employee_id': emp_id,
                                            'name': user_info['name'],
                                            'timestamp': now
                                        }
                                        KIOSK_STATE['cooldowns'][emp_id] = now
                                    # Brief sensor recalibration pause before next finger touch
                                    time.sleep(0.8)
                            else:
                                with state_lock:
                                    KIOSK_STATE['last_error'] = {
                                        'message': 'Fingerprint not recognized.',
                                        'timestamp': time.time()
                                    }
                                time.sleep(0.5)
                        except Exception as ex:
                            err_msg = str(ex).lower()
                            if any(k in err_msg for k in ['object reference', 'null', 'device', 'handle', 'interrupted', 'pointer']):
                                print(f"[INFO] Hardware disconnection caught in DBIdentify: {ex}")
                                raise ex
                            with state_lock:
                                KIOSK_STATE['last_error'] = {
                                    'message': 'Fingerprint not recognized.',
                                    'timestamp': time.time()
                                }
                            time.sleep(0.5)

                    else:
                        with state_lock:
                            KIOSK_STATE['last_error'] = {
                                'message': 'Scanner active, but no fingerprints registered in system.',
                                'timestamp': time.time()
                            }
                        time.sleep(1.0)

            time.sleep(0.08)

        except Exception as e:
            print(f"[WARNING] USB Fingerprint Scanner communication interrupted: {e}")
            device_open = False
            try:
                if zkfp:
                    zkfp.CloseDevice()
                    zkfp.Terminate()
            except Exception: pass
            zkfp = None
            with state_lock:
                KIOSK_STATE['status'] = 'disconnected'
            time.sleep(2.0)

    # Clean shutdown when thread stopped
    if zkfp and device_open:
        try:
            zkfp.CloseDevice()
            zkfp.Terminate()
        except Exception: pass

    with state_lock:
        KIOSK_STATE['status'] = 'stopped'
    print("Scanner background thread shut down.")



def start_device_thread():
    """Starts the scanner thread if not running."""
    global _running, _thread_handle
    with state_lock:
        if _running:
            return
        _running = True
    _thread_handle = threading.Thread(target=_scanner_loop)
    _thread_handle.daemon = True
    _thread_handle.start()

def stop_device_thread():
    """Signals the scanner thread to shut down."""
    global _running
    with state_lock:
        _running = False
