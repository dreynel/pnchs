# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

base_path = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(base_path, 'templates'), 'templates'),
    (os.path.join(base_path, 'static'), 'static'),
    (os.path.join(base_path, 'pages'), 'pages'),
    (os.path.join(base_path, 'routes'), 'routes'),
    (os.path.join(base_path, 'scanner_manager.py'), '.'),
    (os.path.join(base_path, 'db.py'), '.'),
    (os.path.join(base_path, 'app.py'), '.'),
]
binaries = []
hiddenimports = [
    'scanner_manager',
    'db',
    'app',
    'mysql.connector.plugins.mysql_native_password',
    'mysql.connector.plugins.caching_sha2_password',
    'routes',
    'routes.attendance_routes',
    'routes.employee_routes',
    'routes.dtr_routes',
    'routes.payroll_routes',
    'routes.fingerprint_routes',
    'routes.registry_routes',
    'routes.dashboard_routes',
    # pywebview native desktop window
    'webview',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'clr_loader',
    'pythonnet',
    'bottle',
    'proxy_tools',
]

tmp_ret = collect_all('pyzkfp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('flask')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('jinja2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('werkzeug')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mysql')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('bottle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['launcher.py'],
    pathex=[base_path],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PNCHS_Scanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
