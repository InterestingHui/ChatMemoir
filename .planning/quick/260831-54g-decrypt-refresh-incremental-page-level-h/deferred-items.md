# Deferred items — 260831-54g

## Pre-existing test failures (out of scope, not touched)

`python3 -m pytest tests/test_decrypt_v4.py` → 7 failed, 47 passed.
All 7 failures are `TestDumpSessionInfoV4::*` — `mock.patch` targets
`memoir.decrypt.session_v4.CloseHandle` / `open_process` / `get_wx_dir`
attributes that no longer exist in `session_v4.py` (stale test vs. a since-
refactored module). Nothing in `TestDecryptDbFileV4*` / `TestDecryptDbFiles`
(the classes covering the code changed by this task) fails.

Discovered while running the regression gate after Task 1; verified the
failure signature is an `AttributeError` in mock setup, independent of
`decrypt_db_file_v4`. Fix = re-pointing those patches at the current
session_v4 API — separate task, not auto-fixed per scope boundary.

---

## Resolved 2026-08-31 (follow-up session commits)

- 7 TestDumpSessionInfoV4 failures → fixed in 2e37c26 (CloseHandle → lazy
  _CloseHandle patch targets).
- Torn-read residual (see SUMMARY "Orchestrator verification") → guarded in
  cee3a26 (mtime/size stat around each decrypt + single retry, check_6).
- Related stale-test debt found while re-running the gate: 8 test_gui.py
  failures + 1 test_gui_live_account.py setup error, all pre-existing at
  baseline 2faa079 → fixed in 3b00c1b (fakes gained _ui_call; progress
  contracts updated to determinate-at-0 + late sys.platform=win32 patch;
  live-account test made pytest-compatible). .gitignore test* anchored to
  root in 9041051. Full suite now 161 passed, 0 failed.
