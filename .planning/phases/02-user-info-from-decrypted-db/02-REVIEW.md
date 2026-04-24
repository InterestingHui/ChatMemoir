---
phase: 02-user-info-from-decrypted-db
reviewed: 2026-04-24T12:00:00Z
depth: standard
files_reviewed: 1
files_reviewed_list:
  - 1-decrypt.py
findings:
  critical: 0
  warning: 3
  info: 1
  total: 4
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-04-24T12:00:00Z
**Depth:** standard
**Files Reviewed:** 1
**Status:** issues_found

## Summary

Reviewed `1-decrypt.py`, the entry point script for decrypting WeChat databases. The file is a new addition (98 lines) containing two functions: `dump_v3()` for WeChat 3.x and `dump_v4()` for WeChat 4.0. The v4 path includes a new feature that reads the user's nickname from the decrypted `contact.db` instead of relying on memory scanning.

Found 3 warnings and 1 info item. No critical issues. The most significant finding is a SQLite connection leak in the new nickname-reading code (the connection is not closed if an exception occurs during query execution).

## Warnings

### WR-01: SQLite connection leak on exception in nickname query

**File:** `1-decrypt.py:72-85`
**Issue:** The `conn.close()` call on line 78 is placed inside the `try` block *after* the query execution (lines 76-77). If `cursor.execute()` or `cursor.fetchone()` raises an exception, control jumps to the `except` block (line 84) and `conn.close()` is never reached. This leaks an open SQLite connection and file handle. The `except` block catches the exception and prints a message but does not close the connection.

Additionally, there is no guarantee `conn.close()` runs even in the happy path if the `if row and row[0]` branch on line 79 somehow causes an issue before line 78 completes (though this is unlikely in practice, the structural problem remains: close is not in a `finally`).

**Fix:**
```python
db_path = os.path.join(output_dir, 'db_storage', 'contact', 'contact.db')
if os.path.exists(db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT nick_name FROM contact WHERE username = ?', [me.wxid])
        row = cursor.fetchone()
        if row and row[0]:
            me.name = row[0]
            print(f'[*] \u4ece\u6570\u636e\u5e93\u8bfb\u53d6\u6635\u79f0: {me.name}')
        else:
            print(f'[!] \u672a\u5728 contact \u8868\u4e2d\u627e\u5230 wxid={me.wxid} \u7684\u6635\u79f0')
    except Exception as e:
        print(f'[!] \u67e5\u8be2\u6635\u79f0\u5931\u8d25: {e}')
    finally:
        if conn:
            conn.close()
else:
    print(f'[!] \u672a\u627e\u5230\u89e3\u5bc6\u540e\u7684 contact.db: {db_path}')
```

### WR-02: Incorrect success message path in dump_v4

**File:** `1-decrypt.py:92`
**Issue:** The success print statement says the output is at `{output_dir}/Msg`, but the actual v4 output directory is `{output_dir}/db_storage`. The `info.json` is written to `db_storage` on line 90, and the decrypted databases are also under `db_storage`. This misleading message will confuse users about where to find their data.

**Fix:**
```python
# Line 92: Change "Msg" to "db_storage"
print(f'\u6570\u636e\u5e93\u89e3\u6790\u6210\u529f\uff0c\u5728{os.path.join(output_dir, "db_storage")}\u8def\u5f84\u4e0b')
```

### WR-03: dump_v3 writes info.json without verifying Msg directory exists

**File:** `1-decrypt.py:46`
**Issue:** After calling `decrypt_v3.decrypt_db_files()` on line 44, the code writes `info.json` to `os.path.join(output_dir, 'Msg', 'info.json')` on line 46. However, if the decryption process fails to create the `Msg` subdirectory (e.g., if no `Msg` folder exists in the source, or if decryption silently skips files), the `open()` call will raise a `FileNotFoundError`. There is no error handling around this write. Compare with `dump_v4` where the `info.json` write (line 90) at least follows the decryption output convention, though it also lacks a directory existence check.

**Fix:**
```python
# Ensure directory exists before writing info.json
msg_dir = os.path.join(output_dir, 'Msg')
os.makedirs(msg_dir, exist_ok=True)
with open(os.path.join(msg_dir, 'info.json'), 'w', encoding='utf-8') as f:
    json.dump(info_data, f, ensure_ascii=False, indent=4)
```

## Info

### IN-01: Hardcoded relative path for version_list.json in dump_v3

**File:** `1-decrypt.py:27`
**Issue:** `version_list_path = '../wxManager/decrypt/version_list.json'` uses a relative path with `../`. This path only works if the current working directory is the project root and the script is run from a specific location. If the script is invoked from a different directory (e.g., `python /path/to/1-decrypt.py`), the file will not be found. The `dump_v4` function does not have this problem since `get_info_v4()` takes no version list argument. Consider using `os.path.dirname(__file__)` to construct an absolute path relative to the script's location.

**Fix:**
```python
version_list_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wxManager', 'decrypt', 'version_list.json')
```

---

_Reviewed: 2026-04-24T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
