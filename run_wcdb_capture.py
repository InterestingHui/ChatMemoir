#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Runner for wcdb_key_tool_windows.py: capture passphrase via cdb.exe
breakpoint, then extract + decrypt all DBs. Triggered via .wcdb-trigger
sentinel + admin task. User MUST re-login WeChat during the capture window.

Logs everything to wcdb-capture.log.
"""
import os
import subprocess
import sys
import time
import glob

PROJ = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(PROJ, 'wcdb_key_tool_windows.py')
LOG = os.path.join(PROJ, 'wcdb-capture.log')
DB_DIR = r"C:\Users\lenovo\xwechat_files\wxid_ttlo1sb5pyh811_760e\db_storage"

# WinDbg MSIX install location — cdb.exe lives here
CDB_DIR = r"C:\Program Files\WindowsApps\Microsoft.WinDbg_1.2606.22001.0_x64__8wekyb3d8bbwe\amd64"


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    print(line, end='', flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass


def _run(cmd, label, timeout=None):
    _log(f"--- {label} ---")
    _log(f"cmd: {' '.join(cmd)}")
    env = os.environ.copy()
    env['PATH'] = CDB_DIR + os.pathsep + env.get('PATH', '')
    try:
        proc = subprocess.run(
            cmd, cwd=PROJ, env=env,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        _log(f"TIMEOUT after {timeout}s")
        _log(f"stdout: {e.stdout[-2000:] if e.stdout else ''}")
        _log(f"stderr: {e.stderr[-1000:] if e.stderr else ''}")
        return -1
    _log(f"exit: {proc.returncode}")
    if proc.stdout:
        _log(f"--- stdout ---\n{proc.stdout[-8000:]}")
    if proc.stderr:
        _log(f"--- stderr ---\n{proc.stderr[-4000:]}")
    return proc.returncode


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"wcdb capture run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"TOOL={TOOL}")
    _log(f"DB_DIR={DB_DIR}")
    _log(f"CDB_DIR={CDB_DIR}")
    _log(f"cdb.exe exists: {os.path.exists(os.path.join(CDB_DIR, 'cdb.exe'))}")

    # Kill stale wx_key.exe so it doesn't hold WeChat process handles
    _log("killing stale wx_key.exe if any...")
    subprocess.run(['taskkill.exe', '/F', '/IM', 'wx_key.exe'],
                   capture_output=True, text=True)

    # Step 1: capture passphrase (user must re-login WeChat during this window)
    _log("=" * 60)
    _log("STEP 1: capture-experimental (timeout 600s = 10min)")
    _log("*** USER ACTION REQUIRED: in WeChat, go to 设置 → 退出登录 → 重新扫码登录 ***")
    _log("*** This triggers BCryptDeriveKeyPBKDF2 → breakpoint hits → passphrase captured ***")
    _log("=" * 60)
    rc = _run(
        [sys.executable, TOOL, '-v', 'capture-experimental', '--timeout', '600'],
        'capture-experimental',
        timeout=650,
    )

    # Step 2: if capture succeeded, extract + decrypt
    passphrase_file = os.path.join(PROJ, 'wcdb.passphrase')
    if not os.path.exists(passphrase_file):
        _log("NO PASSPHRASE FILE — capture failed, aborting extract")
        return rc or 1

    _log(f"passphrase file exists, running extract --decrypt")
    rc2 = _run(
        [sys.executable, TOOL, '-v', 'extract', '--decrypt',
         '--db-dir', DB_DIR, '--output', 'wcdb_all_keys.json'],
        'extract + decrypt',
        timeout=300,
    )

    # Count decrypted DBs
    dec_dir = os.path.join(PROJ, 'decrypted')
    if os.path.isdir(dec_dir):
        dbs = glob.glob(os.path.join(dec_dir, '**', '*.db'), recursive=True)
        _log(f"decrypted DBs: {len(dbs)}")
    _log(f"DONE rc={rc2}")
    return rc2


if __name__ == '__main__':
    sys.exit(main())
