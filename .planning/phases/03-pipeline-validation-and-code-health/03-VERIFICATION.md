---
phase: 03-pipeline-validation-and-code-health
verified: 2026-04-24T19:00:00Z
status: human_needed
score: 10/10 must-haves verified (8 automated, 2 require human UAT)
overrides_applied: 0
human_verification:
  - test: "Run full three-step pipeline on Windows with WeChat 4.1.8.29 running"
    expected: "All steps complete without unhandled exceptions; contacts listed; HTML export generated"
    why_human: "Requires running WeChat on Windows with administrator privileges; cannot execute in Linux verification environment"
  - test: "Verify no 'file is not a database' errors when opening decrypted DBs"
    expected: "Decrypted databases open and read successfully in contact query step"
    why_human: "Requires actual decrypted databases from a running WeChat instance"
  - test: "Check handle count in Task Manager after repeated 1-decrypt.py runs"
    expected: "Handle count does not grow across 2-3 consecutive runs"
    why_human: "Requires Windows Task Manager and ability to run decryption repeatedly"
---

# Phase 03: Pipeline Validation and Code Health -- Verification Report

**Phase Goal:** Validate and fix the full decrypt-query-export pipeline -- restore regex key extraction from Phase 1 (lost during Phase 2 merge), fix code bugs (multiprocessing, handle leaks, empty close(), uninitialized favorite_db), and provide a human UAT checklist for the user to validate on Windows with WeChat 4.1.8.29.
**Verified:** 2026-04-24T19:00:00Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | regex_scan_keys function exists and is called before YARA in dump_wechat_info_v4 | VERIFIED | `def regex_scan_keys` at wx_info_v4.py:330 and wxinfo.py:363; called at wx_info_v4.py:594 and wxinfo.py:631 before YARA fallback at lines 598/634 |
| 2 | check_chunk and get_key_ use multiprocessing.Value for cross-process flag sharing | VERIFIED | `multiprocessing.Value('b', False)` at wx_info_v4.py:278 and wxinfo.py:311; `shared_flag` passed via `pool.starmap(check_chunk, ...)` |
| 3 | get_nickname closes its process handle in all return paths | VERIFIED | try/finally with `CloseHandle(process_handle)` at wx_info_v4.py:560-561 and wxinfo.py:598-599 |
| 4 | dump_wechat_info_v4 closes process_handle even on early return when wx_dir is empty | VERIFIED | `ctypes.windll.kernel32.CloseHandle(process_handle)` before early return at wx_info_v4.py:588 and wxinfo.py:625 |
| 5 | if True or bypass is removed from get_key_inner in both files | VERIFIED | `grep "if True or"` returns no matches in either file |
| 6 | get_favorite_items returns empty list instead of raising AttributeError when favorite_db is not initialized | VERIFIED | `hasattr` + `None` guard at manager_v4.py:455 and manager_v3.py:665; returns `[]` on guard |
| 7 | DataBaseV4.close() closes all 9 database connections | VERIFIED | 9 explicit `.close()` calls at manager_v4.py:108-116; no `pass` in method body |
| 8 | All 9 database attributes in DataBaseV4 have corresponding close() calls | VERIFIED | contact_db, head_image_db, session_db, message_db, biz_message_db, media_db, hardlink_db, emotion_db, audio2text_db all closed |
| 9 | Decrypted databases are opened and read successfully by the contact query step | VERIFIED (code) | Code structure correct: regex key extraction + proper decryption + DataBaseV4 contact_db reads. No "file is not a database" errors in code path. Human UAT required for runtime validation. |
| 10 | The full three-step pipeline runs on WeChat 4.1.8.29 data without unhandled exceptions | VERIFIED (code) | All code paths verified structurally; HUMAN-UAT.md checklist created for runtime validation. |

**Score:** 10/10 truths verified (8 fully automated, 2 code-level verified but requiring human UAT for runtime confirmation)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `wxManager/decrypt/wx_info_v4.py` | Regex key extraction + bug fixes for v4 path | VERIFIED | Contains regex_scan_keys, collect_db_salts, _verify_key_stdlib, multiprocessing.Value, try/finally CloseHandle, no if-True-or bypass |
| `wxManager/decrypt/wxinfo.py` | Regex key extraction + bug fixes for standalone path | VERIFIED | Same functions present; same fixes applied |
| `wxManager/manager_v4.py` | Fixed close() method and favorite_db guard | VERIFIED | close() has 9 calls; get_favorite_items has None guard |
| `wxManager/manager_v3.py` | Fixed favorite_db guard | VERIFIED | get_favorite_items has None guard |
| `.planning/phases/03-pipeline-validation-and-code-health/HUMAN-UAT.md` | Manual validation checklist | VERIFIED | 26 PASS/FAIL checkboxes, all 3 pipeline steps covered, post-validation resource leak checks included |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| dump_wechat_info_v4 | regex_scan_keys | regex-first control flow | WIRED | Called at wx_info_v4.py:594 before YARA fallback at :598-623 |
| get_key_ | multiprocessing.Value | shared_flag via Pool.starmap | WIRED | Value created at wx_info_v4.py:278, passed through starmap at :280 |
| get_nickname | CloseHandle | try/finally cleanup | WIRED | try/finally at wx_info_v4.py:501-561 and wxinfo.py:534-599 |
| DataBaseV4.close | self.contact_db.close() etc. | direct method call | WIRED | 9 close calls at manager_v4.py:108-116 |
| get_favorite_items | favorite_db | None guard before access | WIRED | Guard at manager_v4.py:455 and manager_v3.py:665 |
| 1-decrypt.py | Phase 2 nickname query | unchanged | WIRED | `SELECT nick_name FROM contact` at 1-decrypt.py:76 preserved |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| wx_info_v4.py dump_wechat_info_v4 | wechat_info.key | regex_scan_keys -> get_key (YARA fallback) | FLOWING | regex_scan_keys scans process memory for WCDB hex patterns, verifies via PBKDF2+HMAC against DB file salts |
| wx_info_v4.py dump_wechat_info_v4 | wechat_info.nick_name | get_nickname via multiprocessing worker | FLOWING | YARA scans process memory for phone number offset pattern, extracts nickname from memory region |
| manager_v4.py close() | N/A (resource cleanup) | self.contact_db etc. | FLOWING | Calls .close() on all 9 DB attributes |
| manager_v4.py get_favorite_items | return value | self.favorite_db | GUARDED | Returns [] when favorite_db is None; no data flow needed |

### Behavioral Spot-Checks

Step 7b: SKIPPED -- all behavioral verification requires running WeChat on Windows with administrator privileges. The code is Windows-only (uses `ctypes.windll`, `win32api`, `pymem`) and cannot be executed in the Linux verification environment. The HUMAN-UAT.md checklist serves this purpose instead.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PIPE-01 | 03-01, 03-02 | Decrypted databases opened and read by contact query step | VERIFIED (code) | Regex key extraction restored; DataBaseV4 properly initializes all DB connections |
| PIPE-02 | 03-01, 03-02 | Contact data flows to export step, generates output file | VERIFIED (code) | Manager layer connects contact/message DBs to exporter; close() fixed ensures clean connections |
| PIPE-03 | 03-01, 03-02 | Full three-step pipeline runs end-to-end without errors | VERIFIED (code) | All code paths structurally verified; HUMAN-UAT.md provides runtime validation checklist |
| CODE-01 | 03-01 | Fix multiprocessing finish_flag for cross-process sharing | VERIFIED | `global finish_flag` removed; `multiprocessing.Value('b', False)` in both files; `shared_flag` passed through starmap |
| CODE-02 | 03-01 | Fix process handle leaks | VERIFIED | get_nickname: try/finally CloseHandle in both files; dump early returns: CloseHandle before return |
| CODE-03 | 03-01, 03-02 | Minimal changes, no refactoring | VERIFIED | Only targeted fixes applied: regex restoration, Value swap, try/finally addition, close() body, None guards |

No orphaned requirements found. All 6 requirement IDs from REQUIREMENTS.md Phase 3 traceability are covered by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| wxManager/decrypt/wxinfo.py | 572-573 | Active debug file write: `with open('a.bin','wb') as f: f.write(target_data)` | Warning | Writes multi-MB memory dump to CWD during get_nickname; commented out in wx_info_v4.py but left active in wxinfo.py |
| wxManager/decrypt/wxinfo.py | 526 | `max(wx_dir_cnt, ...)` without empty dict guard | Warning | ValueError crash if no YARA match found; guard exists in wx_info_v4.py:493 but not in wxinfo.py:526 |
| wxManager/decrypt/wx_info_v4.py | 205 | Unreachable `raise Exception` after `return b''` in read_bytes_from_pid | Info | Dead code; no functional impact but confusing |
| wxManager/decrypt/wxinfo.py | 231 | Unreachable `raise Exception` after `return b''` in read_bytes_from_pid | Info | Same as above |
| wxManager/decrypt/wx_info_v4.py | 209 | Bare `except: pass` in read_bytes_from_pid can swallow handle close errors | Info | Pre-existing; handle leaked if CloseHandle at :208 raises and is caught by :209 |
| wxManager/decrypt/wxinfo.py | 235 | Bare `except: pass` in read_bytes_from_pid can swallow handle close errors | Info | Same as above |

### Human Verification Required

### 1. Full Pipeline End-to-End Test

**Test:** Follow the HUMAN-UAT.md checklist: run `python 1-decrypt.py`, then `python 2-contact.py`, then `python 3-exporter.py` on Windows with WeChat 4.1.8.29 running.
**Expected:** All three steps complete without unhandled exceptions. Step 1 finds a key. Step 2 lists contacts. Step 3 generates HTML output.
**Why human:** Requires running WeChat process on Windows with administrator privileges; cannot be tested in Linux verification environment.

### 2. Handle Leak Verification

**Test:** Run `1-decrypt.py` 2-3 times consecutively. Check Task Manager handle count.
**Expected:** Handle count does not grow with each run.
**Why human:** Requires Windows Task Manager observation across multiple process invocations.

### 3. No "file is not a database" Errors

**Test:** After running Step 1 (decrypt), run Step 2 (contact query) with the output directory.
**Expected:** No "file is not a database" errors in console output.
**Why human:** Requires actual decrypted database files from a live WeChat instance.

### Code Review Findings (from 03-REVIEW.md)

The code review identified 3 critical, 12 warning, and 5 info issues. Of the critical issues:

- **CR-01/CR-02** (read_bytes_from_pid handle leak + dead code): Pre-existing bugs not introduced by Phase 3. Not in scope for this phase. Would be addressed by a v2 CODE-04/CODE-05/CODE-06 cleanup phase.
- **CR-03** (get_wx_dir crash on empty dict in wxinfo.py): Not in scope for Phase 3 plan but is a real bug that affects wxinfo.py users. The guard exists in wx_info_v4.py but was not propagated to wxinfo.py. This is noted as a Warning in anti-patterns above.

### Gaps Summary

No structural gaps found. All planned fixes are implemented and wired:

1. Regex key extraction fully restored in both decrypt files (3 functions: regex_scan_keys, collect_db_salts, _verify_key_stdlib)
2. Multiprocessing finish_flag replaced with shared `multiprocessing.Value` in both files
3. Process handle leaks fixed via try/finally and explicit CloseHandle before early returns
4. DataBaseV4.close() properly closes all 9 database connections
5. get_favorite_items guards against uninitialized favorite_db in both V3 and V4 managers
6. HUMAN-UAT.md created with 26 checkboxes covering all 3 pipeline steps plus resource leak checks

Two pre-existing issues in wxinfo.py that were NOT part of the Phase 3 plan scope but are worth noting:
- Active `a.bin` debug write in get_nickname (line 572-573)
- Missing empty-dict guard in get_wx_dir (line 526) -- will crash with ValueError on edge case

These are deferred to future code health work (v2 requirements CODE-04 through CODE-06).

The phase status is **human_needed** because the core deliverable -- validating the full pipeline on WeChat 4.1.8.29 -- requires actual Windows execution with a running WeChat instance. The HUMAN-UAT.md checklist is the mechanism for this validation.

---

_Verified: 2026-04-24T19:00:00Z_
_Verifier: Claude (gsd-verifier)_
