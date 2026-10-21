---
quick_id: 260629-urj
title: TestAutoDecryptProgressFlow — end-to-end GUI decrypt progress flow
subsystem: gui/tests
tags: [gui, tests, regression, progress-bar, marquee, mocks]
duration: ~25m
completed: 2026-06-29
commit: 3f1625e
---

# 260629-urj: TestAutoDecryptProgressFlow end-to-end progress test

## One-liner

Added `TestAutoDecryptProgressFlow` with two tests covering the full
`_on_start → _auto_decrypt → _on_decrypt_done` flow on a fake host,
asserting the loading progress bar sees `start(10)`, at least one `stop()`,
and reaches value thresholds 0/50/100 — plus an idempotent-stop regression.
Added Windows-only module mocks at import time so `memoir.decrypt` is
importable on WSL/Linux without touching `gui/` source.

## What was built

### Tests added (`tests/test_gui.py`)

- `TestAutoDecryptProgressFlow::test_progress_flow_start_then_stop_then_value_sequence`
  - Builds `_FakeApp` (a composed `LoggingMixin + DecryptionMixin` host with
    all mixin methods bound onto itself and GUI widgets stubbed as MagicMock).
  - Patches the decrypt stack at SOURCE module paths (since `_auto_decrypt`
    does local imports at `gui/decryption.py:56-58`):
    * `memoir.decrypt.get_info_v4` → `[session_info]`
    * `memoir.decrypt.decrypt_dat.get_decode_code_v4` → `1` (int, JSON-safe)
    * `memoir.decrypt.decrypt_v4.decrypt_db_files` → side_effect invokes
      `progress_callback(0,10,"")`, `(5,10,"contact.db")`, `(10,10,"message_0.db")`
      then returns `(10, 0)`
    * `memoir.ArchiveConnection` → fake conn with `get_interface().get_contacts() == []`
    * `ctypes.windll.shell32.IsUserAnAdmin` → `1`
  - Mocks `app.run_task` to run `_auto_decrypt` synchronously and invoke
    `on_done` immediately afterwards.
  - Mocks `app.root.after` with `side_effect=lambda ms, fn, *a, **kw: fn(*a, **kw)`
    so the `_update` closure inside `set_loading_progress` executes synchronously.
  - Asserts:
    * `_loading_progress.start` called exactly once with `(10,)` (marquee kick-off)
    * `_loading_progress.stop.called` is true (otherwise marquee swallows value writes)
    * `__setitem__('value', ...)` sequence contains `0`, `50`, `100` in order;
      first is `0`, last is `100`

- `TestAutoDecryptProgressFlow::test_set_loading_progress_idempotent_stop`
  - Reuses `_FakeHost` to fire `set_loading_progress` four times across a
    0→30→70→100 sequence and asserts `stop()` is called on every invocation
    (documented no-op when bar isn't in marquee mode).

### Test infrastructure additions (`tests/test_gui.py` header)

- Mock Windows-only modules at import time so `memoir.decrypt` chains
  (`session_v3`, `session_v4`, `common`) import cleanly on WSL/Linux:
  `winreg`, `win32api`, `win32com(.client)`, `win32con`, `win32process`,
  `win32security`, `pywintypes`, `yara`, `pythoncom` (MagicMock), and
  `pymem` + `pymem.process` (package-shaped `types.ModuleType` mocks so
  `import pymem.process` succeeds).
- Stub `ctypes.windll`, `ctypes.WinDLL`, `ctypes.CDLL` when absent (Linux)
  because the decrypt modules touch `ctypes.windll.kernel32.ReadProcessMemory`
  and call `ctypes.WinDLL('kernel32', ...)` at module top-level.

These bootstrap changes are confined to the test file and do NOT modify
`gui/` or `memoir/` source.

## Files

| File | Change |
|------|--------|
| `tests/test_gui.py` | +271 lines: 2 new tests, `_FakeApp`, `_FakeHost`, `_build_session_info`, `_patch_decrypt_stack`, Windows-module import mocks, ctypes shims |

## Commits

- `3f1625e` — test(260629-urj): add TestAutoDecryptProgressFlow end-to-end progress test

## How to run

```bash
python3 -m pytest tests/test_gui.py -v
python3 -m pytest tests/ -v   # full regression — 154 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Windows-only module imports crash on WSL**
- **Found during:** Initial test run — `ModuleNotFoundError: No module named 'winreg'`, then `pythoncom`, then `pymem.process`, then `ctypes.windll`/`ctypes.WinDLL`.
- **Issue:** `memoir/decrypt/__init__.py` transitively imports `session_v3`/`session_v4` which require Windows-only stdlib (`winreg`, `ctypes.windll`, `ctypes.WinDLL`) and third-party packages (`pymem`, `pythoncom`, `yara`). On WSL these don't exist, so `from memoir.decrypt.common import SessionInfo` (needed by the test fixture) fails before the test body runs.
- **Fix:** Added import-time mocks in the test file header (`sys.modules[...] = mock.MagicMock()` for leaf modules, `types.ModuleType` with `__path__` for `pymem`/`pymem.process` packages, and `ctypes.windll`/`WinDLL`/`CDLL` shims on the real `ctypes` module). No production source touched.
- **Files modified:** `tests/test_gui.py` (header only).
- **Commit:** `3f1625e`.

**2. [Rule 1 - Bug] `_FakeApp` initially missed private mixin methods**
- **Found during:** Test iteration — `_auto_decrypt` calls `self._read_wx_key_cache()`, `self._fast_find_data_dir()`, etc.; original binding only listed public methods (`_on_start`, `_auto_decrypt`, `_on_decrypt_done`, `set_loading_progress`, `set_loading_status`, `log`).
- **Fix:** Switched `_FakeApp.__init__` to bind ALL callable attributes from the composed mixin (`dir(self._mixin)`) onto `self`, so every helper resolves to a bound method.
- **Files modified:** `tests/test_gui.py` (`_FakeApp.__init__`).
- **Commit:** `3f1625e`.

**3. [Rule 1 - Bug] Mocked `get_decode_code_v4` returned bytes (not JSON-serializable)**
- **Found during:** Test iteration — `Me.xor_key` is serialized via `json.dump(me.to_json(), ...)` at `gui/decryption.py:193`; bytes raised `TypeError: Object of type bytes is not JSON serializable`.
- **Fix:** Changed mock return from `b"\x01"` to `1` (int), matching production `Me.xor_key` default and real `get_decode_code_v4` int contract.
- **Files modified:** `tests/test_gui.py` (`_patch_decrypt_stack`).
- **Commit:** `3f1625e`.

## Verification

- `python3 -m pytest tests/test_gui.py -v` → **17 passed** (15 pre-existing + 2 new)
- `python3 -m pytest tests/ -v` → **154 passed** (full regression, no breakage)
- Test file is the only changed file in the commit; no `gui/` source modified (per plan constraint)

## Notes for future work

- The Windows-module mock bootstrap in `tests/test_gui.py` is reusable: any
  future test that imports `memoir.decrypt` on a non-Windows host will benefit
  automatically (the mocks live at module top-level, before any project import).
- The `_FakeApp` pattern (composed mixin + all-methods bound) can be extracted
  into a `tests/conftest.py` fixture if additional GUI tests need the same
  harness. For now it lives in `test_gui.py` to keep the change self-contained.

## Self-Check: PASSED

- File exists: `tests/test_gui.py` — FOUND
- Commit exists: `3f1625e` — FOUND (`git log --oneline | grep 3f1625e`)
- Tests pass: 17/17 in `tests/test_gui.py`, 154/154 in `tests/`
