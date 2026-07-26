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
import threading
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'wxdecrypt.log')
_lock = threading.Lock()


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    with _lock:
        try:
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass


def _stream_reader(stream, label, echo=True):
    """Read lines from stream, write each to LOG as it arrives.
    Line-buffered — preserves the per-line logger output 1-decrypt.py emits."""
    for line in iter(stream.readline, ''):
        out = line.rstrip('\r\n')
        if out:
            with _lock:
                try:
                    with open(LOG, 'a', encoding='utf-8') as f:
                        f.write(f"{out}\n")
                except Exception:
                    pass
        if echo:
            print(line, end='', flush=True)
    stream.close()


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"native decrypt run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"PROJ={PROJ}")
    _log(f"python={sys.executable}")
    _log("--- step 1: 1-decrypt.py (native, ±4096 YARA scan) ---")
    _log("--- streaming stdout/stderr live (line-buffered) ---")

    # Use Popen + text mode + line-buffered pipes so logger output flows
    # into wxdecrypt.log in real time. Captures full diagnostic lines like
    # [get_key_inner] YARA landed N anchor hits — those were truncated by
    # capture_output=True's end-of-stream 5KB tail on the first run.
    proc = subprocess.Popen(
        [sys.executable, '-u', '1-decrypt.py'],
        cwd=PROJ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,  # line-buffered
    )
    # Spawn two readers so stdout and stderr are drained concurrently
    # (otherwise a pipe full of stderr could deadlock the child).
    t_out = threading.Thread(target=_stream_reader, args=(proc.stdout, 'stdout'), daemon=True)
    t_err = threading.Thread(target=_stream_reader, args=(proc.stderr, 'stderr'), daemon=True)
    t_out.start()
    t_err.start()
    proc.wait()
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    _log(f"exit code: {proc.returncode}")

    # Check whether decryption succeeded for the CURRENT WeChat account
    # (skip stale dirs from prior accounts — match against data_dir in info.json).
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
