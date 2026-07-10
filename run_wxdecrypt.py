#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Runner for the bundled ylytdeng/wechat-decrypt tool.
Extracts keys from WeChat memory, decrypts all DBs, exports chats.
Logs everything to wxdecrypt.log so the WSL side can monitor progress.

Triggered via .wxdecrypt-trigger sentinel + admin task (no UAC).
"""
import os
import subprocess
import sys
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.join(PROJ, 'wechat-decrypt-tool')
LOG = os.path.join(PROJ, 'wxdecrypt.log')


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    print(line, end='', flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass


def _run(cmd, label):
    _log(f"--- {label}: {' '.join(cmd)} ---")
    proc = subprocess.run(
        cmd, cwd=TOOL_DIR,
        capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )
    _log(f"exit code: {proc.returncode}")
    if proc.stdout:
        _log(f"--- stdout ---\n{proc.stdout[-8000:]}")
    if proc.stderr:
        _log(f"--- stderr ---\n{proc.stderr[-4000:]}")
    return proc.returncode


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"wxdecrypt run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"TOOL_DIR={TOOL_DIR}")
    _log(f"config.json exists: {os.path.exists(os.path.join(TOOL_DIR, 'config.json'))}")

    # Step 1: extract keys + decrypt all DBs
    rc = _run([sys.executable, 'main.py', 'decrypt'], 'step 1: key extract + decrypt')

    keys_file = os.path.join(TOOL_DIR, 'all_keys.json')
    decrypted_dir = os.path.join(TOOL_DIR, 'decrypted')
    _log(f"keys_file exists: {os.path.exists(keys_file)}")
    if os.path.isdir(decrypted_dir):
        import glob
        db_count = len(glob.glob(os.path.join(decrypted_dir, '**', '*.db'), recursive=True))
        _log(f"decrypted DBs: {db_count}")

    if rc != 0 or not os.path.exists(keys_file):
        _log("STEP 1 FAILED — no keys extracted, aborting before export")
        return rc or 1

    # Step 2: export all chats
    rc2 = _run([sys.executable, 'export_all_chats.py'], 'step 2: export all chats')
    _log(f"DONE. Overall rc={rc2}")
    return rc2


if __name__ == '__main__':
    sys.exit(main())
