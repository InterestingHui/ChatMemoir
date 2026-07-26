#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir 聊天记录导出工具
一键解密微信数据库，浏览联系人，导出聊天记录
"""
import os
import sys

# Headless verifier dispatch: if a sentinel file exists in the project root,
# run verify_pipeline.py instead of the GUI. Lets us trigger E2E verification
# via the existing admin scheduled task (schtasks /run /tn ChatMemoirAdmin)
# without a separate UAC step — same elevation path as a normal GUI launch.
_proj_dir = os.path.dirname(os.path.abspath(__file__))
_sentinel = os.path.join(_proj_dir, '.verify-trigger')
if os.path.exists(_sentinel):
    try:
        os.remove(_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from verify_pipeline import main as _verify_main
    sys.exit(_verify_main())

# Self-test dispatch: drives the real ChatMemoirApp + _on_start via Tk
# mainloop, teeing every set_loading_progress / log callback to selftest.log.
# Same sentinel pattern as .verify-trigger — reuses the admin scheduled task
# so no extra UAC. Trigger: `touch .selftest-trigger && schtasks /Run /TN ChatMemoirAdmin`
_selftest_sentinel = os.path.join(_proj_dir, '.selftest-trigger')
if os.path.exists(_selftest_sentinel):
    try:
        os.remove(_selftest_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from selftest_auto import main as _selftest_main
    sys.exit(_selftest_main())

# wcdb direct cdb capture: bypass wcdb_key_tool's buggy parser, use -cf
# script + strict "Breakpoint" marker detection. Trigger: .wcdb-direct-trigger
_wcdb_direct_sentinel = os.path.join(_proj_dir, '.wcdb-direct-trigger')
if os.path.exists(_wcdb_direct_sentinel):
    try:
        os.remove(_wcdb_direct_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from run_wcdb_direct import main as _wcdb_direct_main
    sys.exit(_wcdb_direct_main())

# wcdb cdb.exe capture dispatch: attach cdb to Weixin.exe, breakpoint
# bcrypt!BCryptDeriveKeyPBKDF2, capture passphrase when user re-logs in.
# Triggered by .wcdb-trigger sentinel. Output → wcdb-capture.log.
# Trigger: `touch .wcdb-trigger && schtasks /Run /TN ChatMemoirAdmin`
_wcdb_sentinel = os.path.join(_proj_dir, '.wcdb-trigger')
if os.path.exists(_wcdb_sentinel):
    try:
        os.remove(_wcdb_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from run_wcdb_capture import main as _wcdb_main
    sys.exit(_wcdb_main())

# wxdecrypt (ylytdeng/wechat-decrypt) dispatch: extract keys via memory scan,
# decrypt all DBs, export chats. Triggered by .wxdecrypt-trigger sentinel.
# Reuses admin task for elevation. Output → wxdecrypt.log.
# Trigger: `touch .wxdecrypt-trigger && schtasks /Run /TN ChatMemoirAdmin`
_wxdecrypt_sentinel = os.path.join(_proj_dir, '.wxdecrypt-trigger')
if os.path.exists(_wxdecrypt_sentinel):
    try:
        os.remove(_wxdecrypt_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from run_wxdecrypt import main as _wxdecrypt_main
    sys.exit(_wxdecrypt_main())

# Native decrypt dispatch: uses the project's own 1-decrypt.py
# (session_v4.py Method 3, ±4096 YARA-widened scan). Replaces the dead
# ylytdeng/cdb/wx_key paths on WeChat 4.1.11.24.
# Trigger: `touch .wxdecrypt-native-trigger && schtasks /Run /TN ChatMemoirAdmin`
_native_sentinel = os.path.join(_proj_dir, '.wxdecrypt-native-trigger')
if os.path.exists(_native_sentinel):
    try:
        os.remove(_native_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from run_native_decrypt import main as _native_main
    sys.exit(_native_main())

# wx_key refresh dispatch: launch tools/wx_key/wx_key.exe (elevated via the
# admin task — no UAC) and poll the wx_key cache file until its timestamp
# changes, then kill wx_key.exe and exit. Lets us refresh a stale passphrase
# via the existing admin task without a separate UAC step. User still needs
# to click "extract" inside the wx_key.exe GUI window once.
# Trigger: `touch .wxkey-trigger && schtasks /Run /TN ChatMemoirAdmin`
_wxkey_sentinel = os.path.join(_proj_dir, '.wxkey-trigger')
if os.path.exists(_wxkey_sentinel):
    try:
        os.remove(_wxkey_sentinel)
    except OSError:
        pass
    import subprocess
    import time
    import json as _json_wx
    _wx_log = os.path.join(_proj_dir, 'wxkey.log')
    def _wxlog(msg):
        with open(_wx_log, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    _wxlog(f"wxkey refresh starting, pid={os.getpid()}")
    _wx_key_exe = os.path.join(_proj_dir, 'tools', 'wx_key', 'wx_key.exe')
    _wx_key_wd = os.path.dirname(_wx_key_exe)
    _cache_path = os.path.join(os.environ.get('APPDATA', ''), 'com.example', 'wx_key', 'shared_preferences.json')
    _old_ts = ''
    if os.path.exists(_cache_path):
        try:
            with open(_cache_path, 'r', encoding='utf-8') as f:
                _old_ts = _json_wx.load(f).get('flutter.key_timestamp', '')
        except Exception as _e:
            _wxlog(f"cache read error: {_e!r}")
    _wxlog(f"cache path: {_cache_path}")
    _wxlog(f"old timestamp: {_old_ts}")
    try:
        _proc = subprocess.Popen([_wx_key_exe], cwd=_wx_key_wd)
        _wxlog(f"launched wx_key.exe pid={_proc.pid} (NOT auto-killing — user closes manually)")
    except Exception as _e:
        _wxlog(f"launch failed: {_e!r}")
        sys.exit(1)
    # ponytail: don't poll-and-kill. The previous 180s timeout killed wx_key.exe
    # before the user noticed the window. Just launch and exit; the WSL side
    # polls the cache file separately and the user closes wx_key.exe themselves.
    _wxlog("sentinel exiting, wx_key.exe still running")
    sys.exit(0)

# Kill-other-pythonw dispatch: scheduled-task elevation can't be terminated
# from a non-admin WSL shell ('Access Denied'), so to clean up stuck admin
# pythonw processes we use the same sentinel trick. The task launches us
# elevated; we enumerate other pythonw PIDs and taskkill them, then exit.
_kill_sentinel = os.path.join(_proj_dir, '.kill-pythonw-trigger')
if os.path.exists(_kill_sentinel):
    try:
        os.remove(_kill_sentinel)
    except OSError:
        pass
    import subprocess
    my_pid = os.getpid()
    r = subprocess.run(
        ['tasklist.exe', '/FI', 'IMAGENAME eq pythonw.exe', '/FO', 'CSV', '/NH'],
        capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if not parts or parts[0].lower() != 'pythonw.exe' or len(parts) < 2:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if pid != my_pid:
            subprocess.run(['taskkill.exe', '/F', '/PID', str(pid)], capture_output=True)
    sys.exit(0)

from gui import main

if __name__ == "__main__":
    main()
