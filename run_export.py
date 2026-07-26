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

    # Find the most recently decrypted account under decrypted/.
    # Sort by info.json mtime (not the dir itself — directory mtime on
    # \\wsl.localhost\ UNC paths often doesn't update across re-decrypts).
    # Override via sentinel file content: write account name into
    # .wxexport-trigger to force a specific account.
    decrypted_root = os.path.join(PROJ, 'decrypted')
    if not os.path.isdir(decrypted_root):
        _log(f"ERROR: no decrypted/ dir at {decrypted_root}")
        return 1

    sentinel = os.path.join(PROJ, '.wxexport-trigger')
    forced_account = ''
    if os.path.exists(sentinel):
        # sentinel was already consumed by gui.py dispatch — read its
        # content via the sidecar .wxexport-account file instead.
        pass
    sidecar = os.path.join(PROJ, '.wxexport-account')
    if os.path.exists(sidecar):
        with open(sidecar, 'r', encoding='utf-8') as f:
            forced_account = f.read().strip()
        try:
            os.remove(sidecar)
        except OSError:
            pass

    def _info_mtime(d):
        p = os.path.join(decrypted_root, d, 'info.json')
        return os.path.getmtime(p) if os.path.exists(p) else 0

    if forced_account:
        account = forced_account
        _log(f"Using forced account={account} (from .wxexport-account sidecar)")
    else:
        candidates = sorted(
            [d for d in os.listdir(decrypted_root)
             if os.path.isdir(os.path.join(decrypted_root, d)) and os.path.exists(os.path.join(decrypted_root, d, 'info.json'))],
            key=_info_mtime,
            reverse=True,
        )
        if not candidates:
            _log("ERROR: no decrypted accounts with info.json found")
            return 1
        account = candidates[0]
        _log(f"Using account={account} (most recent info.json mtime)")
    db_dir = os.path.join(decrypted_root, account, 'db_storage')
    if not os.path.isdir(db_dir):
        _log(f"ERROR: db_dir does not exist: {db_dir}")
        return 1
    _log(f"db_dir={db_dir}")

    # ponytail: SQLite file locking via \\wsl.localhost\ UNC paths is flaky
    # on Windows ("database is locked" even with no other process holding
    # the file). Copy db_storage to a local %TEMP% dir for the export run,
    # then point 3-exporter.py at the local copy.
    import shutil
    import tempfile
    temp_root = tempfile.mkdtemp(prefix='chatmemoir_export_')
    local_db_dir = os.path.join(temp_root, 'db_storage')
    _log(f"Copying db_storage to local temp (avoids UNC SQLite lock): {local_db_dir}")
    shutil.copytree(db_dir, local_db_dir)
    _log("Copy complete")

    proc = subprocess.Popen(
        [sys.executable, '-u', '3-exporter.py', 'batch', local_db_dir],
        cwd=PROJ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        # ponytail: 3-exporter.py uses print() which encodes to the console
        # codepage. Windows default is GBK (cp936), which can't encode emoji
        # in contact remarks (e.g. 🐟) → UnicodeEncodeError mid-batch-export.
        # Force UTF-8 so emoji doesn't crash the whole batch.
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
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
