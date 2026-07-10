#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Direct cdb.exe capture: bypass wcdb_key_tool_windows.py's buggy parser.
Uses -cf script file (avoids shell-quoting echo issues) and strict hit
detection (requires 'Breakpoint' marker, not just WCDB_HIT_BEGIN which can
appear in bp-action echo during setup).

User flow: trigger via .wcdb-direct-trigger sentinel → attach cdb to Weixin
→ user re-logs WeChat → bp fires → dump @rdx → parse → save passphrase.
"""
import os
import re
import subprocess
import sys
import time

PROJ = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(PROJ, 'wcdb-direct.log')
PASSPHRASE_FILE = os.path.join(PROJ, 'wcdb.passphrase')
CDB = r"C:\Program Files\WindowsApps\Microsoft.WinDbg_1.2606.22001.0_x64__8wekyb3d8bbwe\amd64\cdb.exe"
SCRIPT = os.path.join(PROJ, 'wcdb_capture.cdb')
DB_DIR = r"C:\Users\lenovo\xwechat_files\wxid_ttlo1sb5pyh811_760e\db_storage"


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    print(line, end='', flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass


def find_weixin_pid():
    r = subprocess.run(
        ['tasklist.exe', '/FI', 'IMAGENAME eq Weixin.exe', '/FO', 'CSV', '/NH'],
        capture_output=True, text=True)
    pids = []
    for line in r.stdout.splitlines():
        p = [x.strip('" ') for x in line.split('","')]
        if len(p) >= 5 and p[0].lower() == 'weixin.exe':
            try:
                mem = int(p[4].replace(',', '').replace(' K', '').strip())
            except ValueError:
                mem = 0
            pids.append((int(p[1]), mem))
    pids.sort(key=lambda x: x[1], reverse=True)
    return pids[0][0] if pids else None


def parse_passphrase(cdb_output):
    """Parse cdb `db @rdx L20` output. Looks for lines like:
    00000000`12345678  ab cd ef 01 23 45 67 89-01 23 45 67 89 ab cd ef  ................
    Stricter than wcdb_key_tool: requires 'Breakpoint' marker first."""
    if 'Breakpoint' not in cdb_output and 'breakpoint' not in cdb_output.lower():
        return None, "no 'Breakpoint' marker — bp never hit"
    if 'WCDB_HIT_BEGIN' not in cdb_output:
        return None, "no WCDB_HIT_BEGIN after bp hit"
    seg = cdb_output.split('WCDB_HIT_BEGIN', 1)[1].split('WCDB_HIT_END', 1)[0]
    hex_bytes = []
    for line in seg.splitlines():
        # cdb db format: addr`addr  HH HH HH HH HH HH HH HH-HH HH HH HH HH HH HH HH  ................
        m = re.match(r"^[0-9a-f`]+\s+((?:[0-9a-fA-F]{2}[\s\-]+){15}[0-9a-fA-F]{2})", line)
        if m:
            hex_bytes += re.findall(r"[0-9a-fA-F]{2}", m.group(1))
    if len(hex_bytes) < 32:
        return None, f"only {len(hex_bytes)} hex bytes parsed (need 32)"
    return ''.join(hex_bytes[:32]).lower(), None


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"wcdb direct capture {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log(f"CDB={CDB} exists={os.path.exists(CDB)}")
    _log(f"SCRIPT={SCRIPT} exists={os.path.exists(SCRIPT)}")

    pid = find_weixin_pid()
    if not pid:
        _log("ERROR: Weixin.exe not running. User must start WeChat and login first.")
        return 1
    _log(f"Weixin.exe PID={pid}")

    # Build cdb command: attach, set bp with action from script, go.
    # bp action reads script file content to avoid echo-during-setup.
    with open(SCRIPT, 'r') as f:
        bp_action = f.read().strip()
    # Replace newlines with semicolons for inline bp action, or use $><file to run script
    # Use $><scriptfile which runs commands from file without echoing each
    bp_cmd = f'bp bcrypt!BCryptDeriveKeyPBKDF2 "$><{SCRIPT}"'
    cdb_args = [CDB, '-p', str(pid), '-c', f'{bp_cmd}; g']

    _log("=" * 60)
    _log("ATTACHED cdb to Weixin. USER: re-login WeChat now (设置→退出登录→重新扫码)")
    _log(f"capture timeout: 600s")
    _log("=" * 60)
    _log(f"cdb args: {' '.join(cdb_args)}")

    try:
        proc = subprocess.run(cdb_args, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=650)
    except subprocess.TimeoutExpired as e:
        _log(f"TIMEOUT after 650s")
        out = (e.stdout or '') + (e.stderr or '')
    else:
        _log(f"cdb exit: {proc.returncode}")
        out = (proc.stdout or '') + (proc.stderr or '')

    # Save full cdb output for debugging
    with open(os.path.join(PROJ, 'wcdb-cdb-output.txt'), 'w', encoding='utf-8') as f:
        f.write(out)
    _log(f"full cdb output ({len(out)} chars) → wcdb-cdb-output.txt")
    _log(f"output tail: ...{out[-400:]}")

    passphrase, err = parse_passphrase(out)
    if not passphrase:
        _log(f"PARSE FAILED: {err}")
        return 2
    _log(f"PASSPHRASE CAPTURED: {passphrase[:16]}...{passphrase[-8:]}")
    with open(PASSPHRASE_FILE, 'w') as f:
        f.write(passphrase)
    _log(f"saved to {PASSPHRASE_FILE}")

    # Now run extract --decrypt to derive per-DB keys and decrypt
    _log("running wcdb_key_tool_windows.py extract --decrypt...")
    rc = subprocess.run(
        [sys.executable, os.path.join(PROJ, 'wcdb_key_tool_windows.py'),
         '-v', 'extract', '--decrypt', '--db-dir', DB_DIR,
         '--output', 'wcdb_all_keys.json'],
        cwd=PROJ, capture_output=True, text=True,
        encoding='utf-8', errors='replace').returncode
    _log(f"extract rc={rc}")
    return rc


if __name__ == '__main__':
    sys.exit(main())
