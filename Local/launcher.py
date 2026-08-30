import os
import sys

# Ensure PyInstaller extraction path is top priority in sys.path
_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if _dir not in sys.path:
    sys.path.insert(0, _dir)
os.chdir(_dir)

import threading
import time

try:
    import scanner_manager
    from scanner_manager import start_device_thread, stop_device_thread
except Exception as e:
    print(f"[WARN] scanner_manager import notice: {e}")
    def start_device_thread(): pass
    def stop_device_thread(): pass

from app import app


def run_flask():
    """Run Flask server in a background thread."""
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)


def on_window_closing():
    """Gracefully stop scanner thread when the desktop window is closed."""
    print("[INFO] Desktop window closing — shutting down scanner thread...")
    try:
        stop_device_thread()
    except Exception:
        pass
    os._exit(0)


if __name__ == '__main__':
    print("=" * 65)
    print("   PNCHS Biometric Attendance — Native Desktop Kiosk")
    print("   Live Cloud Server: http://187.52.121.22:8080")
    print("=" * 65)

    # 1. Start USB Scanner listener thread
    print("\n[INFO] Starting USB Scanner listener thread...")
    try:
        start_device_thread()
    except Exception as ex:
        print(f"[WARN] Scanner hardware thread startup notice: {ex}")

    # 2. Start Flask server in a background daemon thread
    print("[INFO] Starting local API server on http://127.0.0.1:5000 ...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 3. Wait briefly for Flask to boot up
    time.sleep(1.5)

    # 4. Open native desktop window (pywebview)
    import webview

    print("[INFO] Launching native desktop kiosk window...")
    window = webview.create_window(
        title='PNCHS Biometric Attendance',
        url='http://127.0.0.1:5000/kiosk',
        width=1280,
        height=800,
        resizable=True,
        maximized=True,
        frameless=False,
        easy_drag=False,
        text_select=False,
        zoomable=False,
    )
    window.events.closing += on_window_closing

    webview.start()
