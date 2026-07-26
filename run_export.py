#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch-export chats as HTML from the decrypted DBs.
Wraps 3-exporter.py batch_export(), streams output to wxexport.log.

Triggered via .wxexport-trigger sentinel + admin task (no UAC).
Note: needs Windows-only deps (pysilk via scribe); must run under Windows Python.
"""
import os
import subprocess
import sys
import threading
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'wxexport.log')
_lock = threading.Lock()


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    with _lock:
        try:
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass


def _stream_reader(stream):
    for line in iter(stream.readline, ''):
        out = line.rstrip('\r\n')
        if out:
            with _lock:
                try:
                    with open(LOG, 'a', encoding='utf-8') as f:
                        f.write(f"{out}\n")
                except Exception:
                    pass
    stream.close()


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"export run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"PROJ={PROJ}")
    _log(f"python={sys.executable}")

    # Find the most recently decrypted account under decrypted/
    decrypted_root = os.path.join(PROJ, 'decrypted')
    if not os.path.isdir(decrypted_root):
        _log(f"ERROR: no decrypted/ dir at {decrypted_root}")
        return 1
    candidates = sorted(
        [d for d in os.listdir(decrypted_root) if os.path.isdir(os.path.join(decrypted_root, d))],
        key=lambda d: os.path.getmtime(os.path.join(decrypted_root, d)),
        reverse=True,
    )
    if not candidates:
        _log("ERROR: no decrypted accounts found")
        return 1
    account = candidates[0]
    db_dir = os.path.join(decrypted_root, account, 'db_storage')
    _log(f"Using account={account} db_dir={db_dir}")

    proc = subprocess.Popen(
        [sys.executable, '-u', '3-exporter.py', 'batch', db_dir],
        cwd=PROJ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )
    t_out = threading.Thread(target=_stream_reader, args=(proc.stdout,), daemon=True)
    t_err = threading.Thread(target=_stream_reader, args=(proc.stderr,), daemon=True)
    t_out.start()
    t_err.start()
    proc.wait()
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    _log(f"exit code: {proc.returncode}")
    return proc.returncode


if __name__ == '__main__':
    sys.exit(main())
