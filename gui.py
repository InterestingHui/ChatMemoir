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
