#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Native decrypt runner — uses the project's own 1-decrypt.py
(session_v4.py Method 3 with ±4096 YARA-widened scan), NOT the external
ylytdeng tool. The ylytdeng/cdb/wx_key paths were all confirmed dead on
WeChat 4.1.11.24 (see checkpoint 20260711-154955).

Logs everything to wxdecrypt.log so the WSL side can monitor progress.
Triggered via .wxdecrypt-native-trigger sentinel + admin task (no UAC).
"""
import os
import subprocess
import sys
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'wxdecrypt.log')


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    print(line, end='', flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"native decrypt run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"PROJ={PROJ}")
    _log(f"python={sys.executable}")
    _log("--- step 1: 1-decrypt.py (native, ±4096 YARA scan) ---")
    # 1-decrypt.py uses print() — capture stdout/stderr live so wxdecrypt.log
    # shows progress (YARA hits, candidate counts) instead of going silent.
    proc = subprocess.run(
        [sys.executable, '1-decrypt.py'],
        cwd=PROJ,
        capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )
    _log(f"exit code: {proc.returncode}")
    if proc.stdout:
        _log(f"--- stdout ---\n{proc.stdout[-10000:]}")
    if proc.stderr:
        _log(f"--- stderr ---\n{proc.stderr[-5000:]}")

    # Check whether decryption succeeded: 1-decrypt.py writes info.json + db_storage/
    # under the uid-named output directory.
    info_jsons = []
    for entry in os.listdir(PROJ):
        candidate = os.path.join(PROJ, entry, 'db_storage', 'info.json')
        if os.path.exists(candidate):
            info_jsons.append(candidate)
    if info_jsons:
        _log(f"SUCCESS — found {len(info_jsons)} decrypted info.json: {info_jsons}")
    else:
        _log("STEP 1 FAILED — no decrypted info.json found")
    return proc.returncode


if __name__ == '__main__':
    sys.exit(main())
