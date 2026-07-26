#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Patch existing dist/ with tcl/tk data and verify _socket.pyd.

Standalone runner: doesn't rebuild, just patches what's already in
PROJ/dist/ChatMemoir/. Used after a build that completed but didn't run
the post-build patch step (e.g. admin process exited unexpectedly).

Trigger: .wxpatch-trigger sentinel + admin task.
"""
import os
import shutil
import sys
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'patch.log')


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
        f.write(f"patch run {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    internal = os.path.join(PROJ, 'dist', 'ChatMemoir', '_internal')
    if not os.path.isdir(internal):
        _log(f"ERROR: no dist/ChatMemoir/_internal at {internal}")
        return 1
    _log(f"internal: {internal}")

    # 1. Patch Tcl/Tk
    src_tcl = os.path.join(sys.base_prefix, 'tcl', 'tcl8.6')
    src_tk = os.path.join(sys.base_prefix, 'tcl', 'tk8.6')
    target_tcl_init = os.path.join(internal, '_tcl_data', 'init.tcl')
    if os.path.isfile(target_tcl_init):
        _log("tcl init.tcl already present, skipping")
    elif not os.path.isdir(src_tcl):
        _log(f"ERROR: source tcl not found at {src_tcl}")
    else:
        for src, name in [(src_tcl, '_tcl_data'), (src_tk, '_tk_data')]:
            if not os.path.isdir(src):
                continue
            dst = os.path.join(internal, name)
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
            _log(f"copied {src} → {dst}")
        _log("tcl/tk patch complete")

    # 2. Verify _socket.pyd present (force PyInstaller to keep it)
    socket_pyd = os.path.join(internal, '_socket.pyd')
    if not os.path.isfile(socket_pyd):
        # Copy from Python install if missing
        src_socket = os.path.join(sys.base_prefix, 'DLLs', '_socket.pyd')
        if os.path.isfile(src_socket):
            shutil.copy2(src_socket, socket_pyd)
            _log(f"copied _socket.pyd from {src_socket}")
        else:
            _log(f"ERROR: _socket.pyd missing and not in {src_socket}")
    else:
        _log(f"_socket.pyd present ({os.path.getsize(socket_pyd)} bytes)")

    # 3. Find the latest build temp dir and copy fresh dist back if needed
    import tempfile
    temp_dir = tempfile.gettempdir()
    candidates = []
    for entry in os.listdir(temp_dir):
        if entry.startswith('chatmemoir_build_'):
            full = os.path.join(temp_dir, entry)
            if os.path.isdir(full):
                candidates.append((os.path.getmtime(full), full))
    if candidates:
        candidates.sort(reverse=True)
        latest_temp_dist = os.path.join(candidates[0][1], 'src', 'dist', 'ChatMemoir')
        if os.path.isdir(latest_temp_dist):
            _log(f"latest build temp: {latest_temp_dist}")
            # If temp dist is newer than PROJ/dist, copy it back
            temp_exe = os.path.join(latest_temp_dist, 'ChatMemoir.exe')
            proj_exe = os.path.join(PROJ, 'dist', 'ChatMemoir', 'ChatMemoir.exe')
            if os.path.isfile(temp_exe) and os.path.isfile(proj_exe):
                if os.path.getmtime(temp_exe) > os.path.getmtime(proj_exe):
                    _log("temp dist newer than PROJ/dist — copying back")
                    dist_dst = os.path.join(PROJ, 'dist', 'ChatMemoir')
                    if os.path.isdir(dist_dst):
                        shutil.rmtree(dist_dst, ignore_errors=True)
                    shutil.copytree(latest_temp_dist, dist_dst)
                    _log(f"copied → {dist_dst}")
                    # Re-patch tcl/tk on the freshly copied dist
                    for src, name in [(src_tcl, '_tcl_data'), (src_tk, '_tk_data')]:
                        if not os.path.isdir(src):
                            continue
                        dst = os.path.join(dist_dst, '_internal', name)
                        if os.path.isdir(dst):
                            shutil.rmtree(dst, ignore_errors=True)
                        shutil.copytree(src, dst)
                    _log("re-patched tcl/tk on copied dist")

    exe = os.path.join(PROJ, 'dist', 'ChatMemoir', 'ChatMemoir.exe')
    if os.path.isfile(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        _log(f"FINAL exe: {exe} ({size_mb:.1f} MB)")
    else:
        _log(f"ERROR: exe still missing")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
