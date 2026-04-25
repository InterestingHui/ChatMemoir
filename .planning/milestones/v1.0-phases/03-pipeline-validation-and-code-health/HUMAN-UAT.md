# HUMAN-UAT: Full Pipeline Validation Checklist

**Target Environment:** Windows 10/11 with WeChat 4.1.8.29 running and logged in
**Purpose:** Validate the complete decrypt-query-export pipeline end-to-end

---

## Prerequisites

- [ ] WeChat 4.1.8.29 (or compatible 4.x) is running and logged in
- [ ] Python 3.10+ installed and accessible from terminal
- [ ] All dependencies installed: `pip install -r requirements.txt`
- [ ] Terminal is running as **Administrator** (required for process memory reading)
- [ ] Working directory is the project root (where `1-decrypt.py` lives)

---

## Step 1: Decrypt Databases

**Command:**
```
python 1-decrypt.py
```

### Expected Output

- [ ] PASS - Console shows key scanning activity (regex hex scan of WeChat process memory)
- [ ] PASS - Console prints key information: `wx_info` object with wxid, wx_dir, key fields
- [ ] PASS - Console shows `[*] 从数据库读取昵称: <nickname>` (Phase 2 feature reading nickname from decrypted contact.db)
- [ ] PASS - Console prints `数据库解析成功` message indicating successful decryption
- [ ] PASS - No `error! 未找到key` message appears (key was found successfully)
- [ ] PASS - File `{wxid}/db_storage/info.json` is created with non-empty `key`, `wxid`, and `name` fields

### If Key Not Found

- [ ] FAIL - Console shows `error! 未找到key，请重启微信后再试`
  - **Recovery:** Ensure WeChat is running and logged in, terminal has admin privileges, then re-run

### Diagnostic Notes

If key scanning fails, check:
1. Is WeChat.exe or Weixin.exe visible in Task Manager?
2. Is the terminal running as Administrator?
3. Does `wxManager/decrypt/version_list.json` contain the WeChat version?

---

## Step 2: Contact Query

**Before running:** Edit `2-contact.py` and set `db_dir` to the output path from Step 1 (e.g., `'./wxid_xxxx/db_storage'`). Also set `db_version = 4`.

**Command:**
```
python 2-contact.py
```

### Expected Output

- [ ] PASS - A list of contacts is printed, each showing wxid, nickname, and remark
- [ ] PASS - No `file is not a database` errors appear
- [ ] PASS - No `AttributeError: 'DataBaseV4' object has no attribute 'favorite_db'` error (this was the bug fixed in this phase)
- [ ] PASS - Chatroom contacts show member count > 0 (e.g., `群成员个数：N`)
- [ ] PASS - Final line shows total contact count and elapsed time: `联系人个数：N 耗时：X.XXs`

---

## Step 3: Export Chat Records

**Before running:** Edit `3-exporter.py`:
1. Set `db_dir` to the same path used in Step 2
2. Set `db_version = 4`
3. Set `wxid` to a real contact wxid from Step 2 output
4. Set `output_dir` to a writable output directory (e.g., `'./data/'`)

**Command:**
```
python 3-exporter.py
```

### Expected Output

- [ ] PASS - At least one HTML export file is generated in `output_dir`
- [ ] PASS - No unhandled exceptions during export (script completes normally)
- [ ] PASS - Export HTML file contains readable message text (open in browser to verify)
- [ ] PASS - Export shows timestamps and contact names correctly
- [ ] PASS - Console prints elapsed time: `耗时：X.XXs`

---

## Post-Validation: Resource Leak Checks

These checks verify that the `close()` fix properly releases database connections.

- [ ] PASS - After running Step 2, close the Python process. Open Task Manager and check handle count is not abnormally high (tens of thousands of handles would indicate a leak)
- [ ] PASS - Re-run `1-decrypt.py` 2-3 times consecutively. Handle count in Task Manager should NOT grow with each run
- [ ] PASS - `info.json` in `{wxid}/db_storage/` has non-empty `key` (hex string) and `name` (nickname) fields

---

## Summary

| Step | Status | Notes |
|------|--------|-------|
| Prerequisites | - [ ] PASS / - [ ] FAIL | |
| Step 1: Decrypt | - [ ] PASS / - [ ] FAIL | |
| Step 2: Contacts | - [ ] PASS / - [ ] FAIL | |
| Step 3: Export | - [ ] PASS / - [ ] FAIL | |
| Resource Leak Check | - [ ] PASS / - [ ] FAIL | |

**Overall Result:** - [ ] ALL PASS / - [ ] FAILURES FOUND

**Date Validated:** _____________
**WeChat Version:** _____________
**Windows Version:** _____________
