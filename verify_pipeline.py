"""Headless E2E verifier for ChatMemoir decrypt -> contacts pipeline.

Bypasses the GUI; runs the same memoir calls _auto_decrypt makes, with full
logging at each step. Run via verify.bat (self-elevates via UAC), OR via the
existing admin scheduled task through gui.py's sentinel-file dispatch.

Output: verify_pipeline.log (readable from WSL for diagnosis).
"""

import ctypes
import json
import os
import sys
import time
import traceback
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(SCRIPT_DIR, 'verify_pipeline.log')


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"{ts}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception as e:
        print(f"  (log write failed: {e})", flush=True)


def reset_log():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(f"=== verify-pipeline started {datetime.now()} ===\n")


def step_admin():
    """Step 1: confirm admin privileges."""
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as e:
        log(f"  admin check threw: {e}")
        is_admin = False
    log(f"Admin: {is_admin}")
    log(f"USERPROFILE: {os.environ.get('USERPROFILE', '<unset>')}")
    log(f"APPDATA: {os.environ.get('APPDATA', '<unset>')}")
    log(f"USERNAME: {os.environ.get('USERNAME', '<unset>')}")
    return is_admin


def step_wx_key_cache():
    """Step 2: read wx_key cache like _read_wx_key_cache does."""
    appdata = os.environ.get('APPDATA', '')
    cache_path = os.path.join(appdata, 'com.example', 'wx_key', 'shared_preferences.json')
    log(f"Cache path: {cache_path}")
    log(f"Cache exists: {os.path.exists(cache_path)}")
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            prefs = json.load(f)
        key = prefs.get('flutter.wechat_db_key', '')
        log(f"Cache key length: {len(key)}")
        log(f"Cache key prefix: {key[:16]}...")
        is_hex = len(key) == 64 and all(c in '0123456789abcdef' for c in key)
        log(f"Cache key valid (64 lowercase hex): {is_hex}")
        return key if is_hex else None
    except Exception as e:
        log(f"  cache read threw: {e}")
        return None


def step_fast_find():
    """Step 3: _fast_find_data_dir equivalent."""
    import psutil
    for proc in psutil.process_iter(['name', 'pid']):
        name = proc.name()
        if name not in ('Weixin.exe', 'WeChatAppEx.exe'):
            continue
        try:
            for mm in proc.memory_maps(grouped=False):
                p = mm.path or ''
                idx = p.find('db_storage')
                if idx != -1:
                    db_storage_path = p[:idx + len('db_storage')] + '\\'
                    parts = db_storage_path.rstrip('\\').split('\\')
                    uid = '_'.join(parts[-2].split('_')[0:-1])
                    data_dir = '\\'.join(parts[:-1])
                    log(f"  Fast-find hit: PID={proc.pid} uid={uid} data_dir={data_dir}")
                    return uid, data_dir, uid
        except Exception as e:
            log(f"  proc scan threw for PID={proc.pid}: {e}")
            continue
    return None


def step_full_scan():
    """Step 4: full YARA scan via get_info_v4."""
    log("Running get_info_v4 (YARA scan, may take 10-30s)...")
    t0 = time.time()
    from memoir.decrypt import get_info_v4
    infos = get_info_v4()
    log(f"Scan took {time.time()-t0:.1f}s, found {len(infos)} session(s)")
    for i, si in enumerate(infos):
        log(f"  [{i}] uid={si.uid} key={'set' if si.key else 'None'} data_dir={si.data_dir}")
    return infos


def step_derive_keys(passphrase, data_dir):
    """Step 5: PBKDF2 per-DB key derivation."""
    import hashlib
    log(f"Deriving per-DB keys via PBKDF2-SHA512 x256000 (passphrase={passphrase[:16]}...)")
    t0 = time.time()
    db_files = []
    for root, dirs, files in os.walk(data_dir):
        for fn in files:
            if not fn.endswith('.db'):
                continue
            fp = os.path.join(root, fn)
            try:
                if os.path.getsize(fp) < 4096:
                    continue
            except OSError:
                continue
            db_files.append((root, fn))
    total = len(db_files)
    log(f"Found {total} .db files to derive keys for")
    key_map = {}
    for i, (root, fn) in enumerate(db_files):
        fp = os.path.join(root, fn)
        with open(fp, 'rb') as fh:
            salt = fh.read(16)
        dk = hashlib.pbkdf2_hmac('sha512', bytes.fromhex(passphrase), salt, 256000, dklen=32)
        rel_dir = os.path.relpath(root, data_dir)
        key_map[os.path.join(rel_dir, fn)] = dk.hex()
        if (i + 1) % 5 == 0 or i + 1 == total:
            log(f"  derived {i+1}/{total} ({(i+1)*100//total}%)")
    log(f"PBKDF2 total: {time.time()-t0:.1f}s")
    return key_map


def step_decrypt(uid, key, key_map, data_dir, label="cache"):
    """Step 6: decrypt_db_files to a fresh verify-output dir.
    Returns (output_dir, total, failed)."""
    from memoir.decrypt import decrypt_v4
    output_dir = os.path.join(SCRIPT_DIR, 'verify-output', uid)
    if os.path.exists(output_dir):
        log(f"Cleaning previous output: {output_dir}")
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)
    log(f"Decrypting to {output_dir} (key source: {label})...")
    t0 = time.time()
    total, failed = decrypt_v4.decrypt_db_files(
        key, src_dir=data_dir, dest_dir=output_dir,
        key_map=key_map or None, skip_existing=False)
    log(f"Decrypt [{label}]: total={total} failed={failed} took {time.time()-t0:.1f}s")
    return output_dir, total, failed


def step_yara_fallback(data_dir):
    """Run get_info_v4() to extract a YARA-verified key from WeChat memory.
    Returns (session_info, key, key_map) or (None, None, None) on failure."""
    log("--- YARA fallback: get_info_v4 ---")
    t0 = time.time()
    from memoir.decrypt import get_info_v4
    infos = get_info_v4()
    log(f"YARA scan took {time.time()-t0:.1f}s, found {len(infos)} session(s)")
    if not infos:
        log("YARA found no sessions")
        return None, None, None
    si = infos[0]
    log(f"YARA session: uid={si.uid} key={'set' if si.key else 'None'}")
    if not si.key:
        log("YARA session has no key")
        return None, None, None
    # If session has a key_map (per-DB keys), use it; else single key.
    key_map = getattr(si, 'key_map', None) or None
    log(f"YARA key prefix: {si.key[:16]}... key_map={'yes' if key_map else 'no'}")
    return si, si.key, key_map


def step_query_contacts(db_dir):
    """Step 7: open ArchiveConnection and list contacts."""
    from memoir import ArchiveConnection
    log(f"Opening ArchiveConnection at {db_dir}...")
    conn = ArchiveConnection(db_dir, 4)
    db = conn.get_interface()
    if db is None:
        log("ERROR: ArchiveConnection returned None")
        return None
    log("Loading contacts...")
    contacts = list(db.get_contacts())
    log(f"Contacts: {len(contacts)}")
    for c in contacts[:5]:
        nm = getattr(c, 'remark', None) or getattr(c, 'nickname', None) or getattr(c, 'uid', '?')
        log(f"  - {nm}")
    return db


def main():
    reset_log()
    log(f"Python: {sys.version}")
    log(f"CWD: {os.getcwd()}")
    log(f"SCRIPT_DIR: {SCRIPT_DIR}")
    log(f"sys.argv: {sys.argv}")
    log("")

    # 1. Admin
    if not step_admin():
        log("ERROR: Not admin. Run via verify.bat (UAC self-elevate).")
        return 1
    log("")

    # Make memoir importable
    sys.path.insert(0, SCRIPT_DIR)
    log(f"sys.path[0:3]: {sys.path[:3]}")
    log("")

    # 2. wx_key cache
    log("--- Step 2: wx_key cache ---")
    passphrase = step_wx_key_cache()
    log("")

    # 3. Fast-find or full scan
    log("--- Step 3: locate WeChat data dir ---")
    direct_key = None  # set only if full scan yields a usable key directly
    fast = step_fast_find() if passphrase else None
    if fast:
        uid, data_dir, _ = fast
        log(f"Fast path: uid={uid} data_dir={data_dir}")
    else:
        log("Fast path failed or no cache; falling back to full scan")
        infos = step_full_scan()
        if not infos:
            log("ERROR: no sessions found via full scan either")
            return 1
        si = infos[0]
        uid, data_dir = si.uid, si.data_dir
        if si.key:
            direct_key = si.key
            passphrase = None  # scan key supersedes passphrase path
            log(f"Using direct key from scan: {direct_key[:16]}...")
    log("")

    # 4. Derive keys if we have a passphrase; else fall back to direct key.
    key = None
    key_map = None
    if passphrase:
        log("--- Step 4: PBKDF2 key derivation ---")
        key_map = step_derive_keys(passphrase, data_dir)
        key = list(key_map.values())[0] if key_map else passphrase
        log("")
    elif direct_key:
        key = direct_key
        log(f"Skipping PBKDF2 (using scan-provided key)")
    else:
        log("ERROR: no key obtainable — neither cache passphrase nor scan key")
        return 1

    # 5. Decrypt (cache path)
    log("--- Step 5: decrypt_db_files ---")
    output_dir, total, failed = step_decrypt(uid, key, key_map, data_dir, label="cache")
    info_dir = os.path.join(output_dir, 'db_storage')
    log("")

    # 5b. YARA fallback if cache path failed completely
    if total > 0 and failed == total:
        log(f"!!! Cache-derived key decrypted 0/{total} DBs — passphrase is stale.")
        log(f"!!! Falling back to YARA scan to extract current key from WeChat memory.")
        log("")
        si_yara, key_yara, key_map_yara = step_yara_fallback(data_dir)
        if si_yara is None:
            log("YARA fallback failed too. Both paths dead — regex needs updating for this WeChat version.")
            return 1
        log("")
        log("--- Step 5c: retry decrypt with YARA key ---")
        uid = si_yara.uid
        output_dir, total, failed = step_decrypt(uid, key_yara, key_map_yara, si_yara.data_dir, label="yara")
        info_dir = os.path.join(output_dir, 'db_storage')
        log("")
        if total > 0 and failed == total:
            log("YARA key also failed to decrypt any DBs.")
            return 1

    # 6. Query contacts
    log("--- Step 6: ArchiveConnection + get_contacts ---")
    db = step_query_contacts(info_dir)
    if db is None:
        return 1
    log("")

    log("=== ALL STEPS OK ===")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL EXCEPTION: {e}")
        log(traceback.format_exc())
        sys.exit(2)
