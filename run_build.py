#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build ChatMemoir.exe via PyInstaller.

Wraps `pyinstaller ChatMemoir.spec --noconfirm`, streams output to build.log.
Triggered via .wxbuild-trigger sentinel + admin task (no UAC).

Why sentinel-based: PyInstaller needs the project on a local disk for reliable
binary patching (UPX, icon embedding). When the project lives on \\wsl.localhost\
UNC paths, the build can fail with permission errors. Running via the
ChatMemoirAdmin task at least gives us admin rights + a clean process tree.
If UNC build fails, the runner copies the source tree to %TEMP%\chatmemoir-src
first and builds from there.
"""
import os
import shutil
import subprocess
import sys
import threading
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'build.log')
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
        f.write(f"build started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"PROJ={PROJ}")
    _log(f"python={sys.executable}")
    _log(f"version={sys.version.split()[0]}")

    # Check if PROJ is on a UNC path — PyInstaller struggles with UNC cwd
    is_unc = PROJ.startswith('\\\\') or PROJ.lower().startswith('//')
    work_dir = PROJ
    if is_unc:
        # Copy the project to %TEMP%\chatmemoir-src for a stable local build.
        # Exclude heavy / disposable dirs to keep the copy fast.
        import tempfile
        local_root = tempfile.mkdtemp(prefix='chatmemoir_build_')
        local_src = os.path.join(local_root, 'src')
        _log(f"UNC path detected — copying source to local: {local_src}")
        ignore = shutil.ignore_patterns(
            '.git', '__pycache__', '*.pyc',
            'data', 'decrypted', 'wxid_*', 'build', 'dist',
            'wechat-decrypt-tool', '.planning', 'doc',
            'node_modules', 'mind', 'xiaoyiClaw',
        )
        shutil.copytree(PROJ, local_src, ignore=ignore)
        _log(f"Copy complete: {os.listdir(local_src)}")
        work_dir = local_src

    _log("--- running pyinstaller ---")
    cmd = [sys.executable, '-m', 'PyInstaller', 'ChatMemoir.spec', '--noconfirm', '--clean']
    _log(f"cmd: {' '.join(cmd)}")
    _log(f"cwd: {work_dir}")
    proc = subprocess.Popen(
        cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
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

    # If we built in temp, copy dist/ back to PROJ so we can find it
    if is_unc and os.path.isdir(os.path.join(work_dir, 'dist')):
        dist_src = os.path.join(work_dir, 'dist')
        dist_dst = os.path.join(PROJ, 'dist')
        if os.path.isdir(dist_dst):
            shutil.rmtree(dist_dst, ignore_errors=True)
        shutil.copytree(dist_src, dist_dst)
        _log(f"copied dist back to {dist_dst}")

    # Verify exe exists
    exe_path = os.path.join(PROJ, 'dist', 'ChatMemoir', 'ChatMemoir.exe')
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        _log(f"SUCCESS — exe at {exe_path} ({size_mb:.1f} MB)")
    else:
        _log(f"ERROR — exe not found at {exe_path}")
        return proc.returncode

    # ponytail: PyInstaller 6.21 sometimes drops tcl/tk data files even when
    # the spec lists them as datas (lib/tcl8 becomes an empty dir, init.tcl
    # missing → 'Can't find a usable init.tcl' on launch). Patch dist directly
    # by copying Python's bundled tcl8.6/tk8.6 into _internal/_tcl_data and
    # _internal/_tk_data. Skip if init.tcl already present.
    internal_dir = os.path.join(PROJ, 'dist', 'ChatMemoir', '_internal')
    target_tcl = os.path.join(internal_dir, '_tcl_data', 'init.tcl')
    if not os.path.isfile(target_tcl):
        src_tcl = os.path.join(sys.base_prefix, 'tcl', 'tcl8.6')
        src_tk = os.path.join(sys.base_prefix, 'tcl', 'tk8.6')
        if os.path.isdir(src_tcl):
            dst_tcl = os.path.join(internal_dir, '_tcl_data')
            if os.path.isdir(dst_tcl):
                shutil.rmtree(dst_tcl)
            shutil.copytree(src_tcl, dst_tcl)
            _log(f"patched tcl: {src_tcl} → {dst_tcl}")
        if os.path.isdir(src_tk):
            dst_tk = os.path.join(internal_dir, '_tk_data')
            if os.path.isdir(dst_tk):
                shutil.rmtree(dst_tk)
            shutil.copytree(src_tk, dst_tk)
            _log(f"patched tk: {src_tk} → {dst_tk}")
    else:
        _log("tcl init.tcl already present, skipping patch")

    return proc.returncode


if __name__ == '__main__':
    sys.exit(main())
