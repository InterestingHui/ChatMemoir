---
phase: quick
plan: 260629-urj
type: execute
wave: 1
depends_on: []
files_modified:
  - tests/test_gui.py
autonomous: true
requirements: []
tags: [gui, test, regression, progressbar]
must_haves:
  truths:
    - "_on_start triggers _loading_progress.start(10) exactly once (enters marquee mode)"
    - "_auto_decrypt v4 branch invokes decrypt_v4.decrypt_db_files with progress_callback=self.set_loading_progress"
    - "First set_loading_progress callback triggers _loading_progress.stop() (exits marquee) and sets [value]=0"
    - "Subsequent callbacks advance [value] to 50 then 100 in order"
    - "Ordered call sequence on _loading_progress is: start(10) -> stop() -> [value]=0 -> [value]=50 -> [value]=100"
  artifacts:
    - path: "tests/test_gui.py"
      provides: "TestAutoDecryptProgressFlow end-to-end regression test"
      contains: "class TestAutoDecryptProgressFlow"
  key_links:
    - from: "gui/decryption.py:_on_start"
      to: "_loading_progress.start(10)"
      via: "direct call"
      pattern: "_loading_progress\\.start\\(10\\)"
    - from: "gui/decryption.py:_auto_decrypt"
      to: "decrypt_v4.decrypt_db_files(progress_callback=self.set_loading_progress)"
      via: "kwarg threading"
      pattern: "progress_callback=self\\.set_loading_progress"
    - from: "gui/logging.py:set_loading_progress"
      to: "_loading_progress.stop() + ['value']=pct"
      via: "root.after(0, _update) — mocked to run synchronously"
      pattern: "_loading_progress\\.stop\\(\\)"
---

<objective>
Add end-to-end integration test `TestAutoDecryptProgressFlow` covering the full
`_on_start` -> `_auto_decrypt` -> `_on_decrypt_done` flow on the v4 branch, asserting
the complete ordered call sequence on the mocked `_loading_progress` widget.

Purpose: Lock down the marquee-to-determinate transition regression fixed in
quick task 260628-u53 (`_on_start` calls `start(10)` to enter marquee; the first
`set_loading_progress` callback must call `stop()` before writing `[value]`).
Without this test, a future refactor could silently re-introduce the bug where
`[value]` writes are dropped because the bar is still in marquee mode.

Output: New `TestAutoDecryptProgressFlow` class appended to `tests/test_gui.py`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@gui/decryption.py
@gui/logging.py
@tests/test_gui.py

<interfaces>
<!-- Contracts the executor needs. Extracted from source. -->

From gui/decryption.py — `_on_start` (line 14):
```python
def _on_start(self):
    self._show_screen("loading")
    self._loading_progress.start(10)        # enters marquee mode
    self.set_loading_status("正在扫描微信进程...")
    # ... log cleanup ...
    self.run_task(self._auto_decrypt,
                  on_done=self._on_decrypt_done,
                  on_error=self._on_decrypt_error)
```

From gui/decryption.py — `_auto_decrypt` v4 branch (lines 148-160):
```python
if self._db_version == 4:
    from memoir.decrypt.decrypt_dat import get_decode_code_v4
    me = Me()
    me.data_dir = session_info.data_dir
    me.uid = uid
    me.name = session_info.nick_name
    me.xor_key = get_decode_code_v4(session_info.data_dir)
    output_dir = os.path.join(self._script_dir, uid)
    total, failed = decrypt_v4.decrypt_db_files(
        key, src_dir=session_info.data_dir, dest_dir=output_dir,
        key_map=getattr(session_info, 'key_map', None) or None,
        skip_existing=True,
        progress_callback=self.set_loading_progress)
```

From gui/decryption.py — final phase (lines 207-221):
```python
self.set_loading_status("正在加载联系人...")
self.set_loading_progress(1, 1, "")     # Note: this also fires stop()+[value]=100
self.log("正在连接数据库...")
conn = ArchiveConnection(db_dir, self._db_version)
self.database = conn.get_interface()
# ...
self.contacts = list(self.database.get_contacts())
return db_dir
```

From gui/logging.py — `set_loading_progress` (line 37):
```python
def set_loading_progress(self, current, total, filename=""):
    if total <= 0:
        return
    pct = int(current / total * 100)
    short_name = os.path.basename(filename)[:30] if filename else ""
    def _update():
        try:
            self._loading_progress.stop()       # exits marquee
        except Exception:
            pass
        self._loading_progress["value"] = pct
        self._lbl_loading_pct.configure(text=f"{current}/{total} ({pct}%)  {short_name}")
    try:
        self.root.after(0, _update)             # must be mocked to run synchronously
    except Exception:
        pass
```

From memoir/decrypt/common.py — `SessionInfo` (line 25):
```python
class SessionInfo:
    def __init__(self):
        self.nick_name = ''
        self.data_dir = ''
        self.key = ''
        self.key_map = {}
        self.uid = ''
```

From memoir/decrypt/decrypt_v4.py — `decrypt_db_files` (line 123):
```python
def decrypt_db_files(key, src_dir, dest_dir, key_map=None,
                     skip_existing=True, progress_callback=None):
    # Calls progress_callback(0, total, "") at start
    # Calls progress_callback(completed, total, filename) per file
    # Returns (total, failed)
```

Existing test infrastructure in tests/test_gui.py (lines 11-17):
```python
import sys
from unittest import mock
sys.modules['tkinter'] = mock.MagicMock()
sys.modules['tkinter.ttk'] = mock.MagicMock()
from gui.logging import LoggingMixin
```

The existing `_FakeHost` pattern (line 103):
```python
class _FakeHost(LoggingMixin):
    def __init__(self):
        self.root = mock.MagicMock()
        self.root.after.side_effect = lambda ms, fn: fn()   # synchronous dispatch
        self._loading_progress = mock.MagicMock()
        self._lbl_loading_pct = mock.MagicMock()
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add TestAutoDecryptProgressFlow end-to-end regression test</name>
  <files>tests/test_gui.py</files>
  <behavior>
    - Test 1 (happy_path_v4_marquee_to_determinate_sequence): After patching all
      `_auto_decrypt` external dependencies, calling `_on_start()` on a fake host
      whose `run_task` invokes `_auto_decrypt` synchronously must produce this
      exact ordered sequence on `_loading_progress`:
      1. `start(10)` called exactly once
      2. `stop()` called at least once (first `set_loading_progress` triggers it)
      3. `__setitem__('value', ...)` called with values whose ordered sequence
         includes `[0, 50, 100]` as the decrypt-progress portion (final
         `set_loading_progress(1, 1, "")` after ArchiveConnection also writes 100,
         so the assertion is `values[0:3] == [0, 50, 100]` — i.e., the first three
         `[value]=` writes are the three decrypt callbacks).
    - Test 2 (decrypt_db_files_receives_progress_callback): The mock
      `decrypt_v4.decrypt_db_files` is called with `progress_callback` kwarg bound
      to `self.set_loading_progress` (verified via call kwargs).
    - Test 3 (marquee_start_happens_before_first_value_write): In the recorded
      method-call order on `_loading_progress`, `start` must appear before any
      `__setitem__('value', ...)` write.
  </behavior>
  <action>
    Append a new `TestAutoDecryptProgressFlow` class to `tests/test_gui.py`.
    Do NOT modify any `gui/` files — this is a pure test addition.

    **Imports to add at top of new class block** (avoid module-level imports
    beyond what already exists; use local imports inside the test for the
    decryption mixin to keep test setup isolated):
    ```python
    from gui.decryption import DecryptionMixin
    from memoir.decrypt.common import SessionInfo
    ```

    **Fake host fixture class** (define immediately above the test class,
    following the existing `_FakeHost` pattern in this file at line 103).
    The host combines `DecryptionMixin` + `LoggingMixin` and must set up:
    - `self.root = mock.MagicMock()` with `self.root.after.side_effect = lambda ms, fn: fn()`
      so `_update` closures execute synchronously
    - `self._loading_progress = mock.MagicMock()` — the widget under test
    - `self._lbl_loading_pct = mock.MagicMock()`
    - `self._loading_status = mock.MagicMock()` (for `set_loading_status`)
    - `self._loading_log = mock.MagicMock()` (for log clearing in `_on_start`)
    - `self._btn_retry = mock.MagicMock()`; `self._btn_cancel = mock.MagicMock()`
    - `self._script_dir = tempfile.mkdtemp(prefix="cm_test_")` — a real temp dir
      so `os.path.join(self._script_dir, uid)` and subsequent `os.makedirs` succeed
    - `self._config = {}`
    - `self._db_version = 4` (set by `_auto_decrypt`, but pre-set is harmless)
    - `self.contacts = []`; `self.database = None`; `self.db_dir_actual = None`
    - `self._show_screen = mock.MagicMock()`
    - `self.run_task = mock.MagicMock(side_effect=lambda fn, **kw: fn())` —
      CRITICAL: makes `_on_start` invoke `_auto_decrypt` synchronously so all
      progressbar calls happen in the test's call frame
    - `self.log = mock.MagicMock()` (overrides LoggingMixin.log to avoid
      `root.after` nesting complications — we only care about progressbar ops)
    - `self.set_loading_status = mock.MagicMock()` (overrides LoggingMixin method
      to avoid `root.after` scheduling noise)
    - `self._read_wx_key_cache = mock.MagicMock(return_value=None)` — ensures
      `_auto_decrypt` takes the full-scan branch (no wx_key cache), so
      `get_info_v4()` is the entry point we patch
    - `self._get_wx_key_passphrase = mock.MagicMock(return_value=None)`
    - `self._ask_passphrase = mock.MagicMock(return_value=None)`
    - `self._populate_contacts = mock.MagicMock()`
    - `self._compute_stats = mock.MagicMock()`
    - `self._update_adv_menu = mock.MagicMock()`
    - `self._save_config = mock.MagicMock()` — not strictly needed since
      `_save_config` is imported from `gui.constants` and called directly;
      patch it via `mock.patch('gui.decryption._save_config')` in the test instead.

    **Fake session info** built via `SessionInfo()`:
    ```python
    si = SessionInfo()
    si.uid = "wxid_testuser123"
    si.data_dir = tempfile.mkdtemp(prefix="cm_src_")  # must exist for os.walk
    si.nick_name = "TestUser"
    si.key = "00" * 32   # 64-hex string so `if not key` is False; per-DB key path is skipped
    ```

    **Patches** (use `unittest.mock.patch` as context managers, all targeting
    the symbol as looked up inside `gui.decryption` — i.e.,
    `mock.patch('gui.decryption.X')` for everything that is imported inside
    `_auto_decrypt`'s body via `from memoir.decrypt import X`):

    The imports inside `_auto_decrypt` execute at call time:
    - `from memoir.decrypt import get_info_v4, get_info_v3` — line 56
    - `from memoir.decrypt import decrypt_v4, decrypt_v3` — line 57
    - `from memoir import Me, ArchiveConnection` — line 58
    - `import ctypes` — line 62
    - `from memoir.decrypt.decrypt_dat import get_decode_code_v4` — line 149

    Because these are local imports, `mock.patch('gui.decryption.get_info_v4')`
    will NOT work — the symbol is bound inside the function frame from the
    `memoir.decrypt` module. Patch at the SOURCE module instead:
    - `mock.patch('memoir.decrypt.get_info_v4', return_value=[si])`
    - `mock.patch.object(decrypt_v4, 'decrypt_db_files', side_effect=...)` —
      patch the attribute on the `decrypt_v4` module object since the local
      import `from memoir.decrypt import decrypt_v4` binds the module reference
      and `decrypt_v4.decrypt_db_files` is looked up at call time. Use:
      `mock.patch('memoir.decrypt.decrypt_v4.decrypt_db_files', ...)`
    - `mock.patch('memoir.decrypt.decrypt_dat.get_decode_code_v4', return_value=b'\x00')`
    - `mock.patch('ctypes.windll')` — `ctypes.windll.shell32.IsUserAnAdmin()` must
      return truthy. Patch the whole `ctypes.windll` with a MagicMock whose
      `shell32.IsUserAnAdmin.return_value = 1`. Patch path:
      `mock.patch('ctypes.windll')`.
    - `mock.patch('gui.decryption.ArchiveConnection')` — NOTE: `ArchiveConnection`
      is imported via `from memoir import Me, ArchiveConnection` at line 58,
      which is a local import inside `_auto_decrypt`. So this patch also will
      NOT intercept. Instead, patch at source: `mock.patch('memoir.ArchiveConnection')`.
      Configure the mock to return an object whose `get_interface()` returns a
      MagicMock with `get_contacts.return_value = []`.

    **`decrypt_db_files` side_effect** — must invoke the callback with the
    prescribed sequence and return `(10, 0)`:
    ```python
    def _fake_decrypt_db_files(key, src_dir, dest_dir, key_map=None,
                               skip_existing=True, progress_callback=None):
        # Reproduce the production callback contract:
        # progress_callback(current, total, filename)
        progress_callback(0, 10, "")
        progress_callback(5, 10, "contact.db")
        progress_callback(10, 10, "message_0.db")
        return (10, 0)   # (total, failed)
    ```
    Wire via:
    ```python
    mock.patch('memoir.decrypt.decrypt_v4.decrypt_db_files',
               side_effect=_fake_decrypt_db_files)
    ```

    **Additional setup for v3 fallback avoidance**: `_auto_decrypt` only tries
    v3 if `session_info_list` is empty AND `wx_passphrase` is falsy. Our
    `get_info_v4` mock returns `[si]`, so the v3 branch is skipped naturally.
    Pre-set `host._read_wx_key_cache.return_value = None` to skip the wx_key
    fast-path.

    **Avoiding real filesystem writes for `info.json` / `contact.db`**:
    `_auto_decrypt` writes `info.json` to `info_dir = os.path.join(output_dir, "db_storage")`
    and (for v4) attempts to open `contact.db` at
    `os.path.join(info_dir, "contact", "contact.db")`. The guard
    `if os.path.exists(contact_db)` protects the open call — since we never
    create that file, the branch is skipped. `os.makedirs(info_dir, exist_ok=True)`
    DOES run and needs a writable path; `self._script_dir = tempfile.mkdtemp(...)`
    covers this. Strip out at the end of the test via `shutil.rmtree`.

    **Test body for happy_path_v4_marquee_to_determinate_sequence**:
    ```python
    host = _AutoDecryptFakeHost()
    si = _build_fake_session(host._script_dir)

    with mock.patch('ctypes.windll') as m_windll, \
         mock.patch('memoir.decrypt.get_info_v4', return_value=[si]), \
         mock.patch('memoir.decrypt.decrypt_v4.decrypt_db_files',
                    side_effect=_fake_decrypt_db_files), \
         mock.patch('memoir.decrypt.decrypt_dat.get_decode_code_v4',
                    return_value=b'\x00'), \
         mock.patch('memoir.ArchiveConnection') as m_arc, \
         mock.patch('gui.decryption._save_config'):
        m_windll.shell32.IsUserAnAdmin.return_value = 1
        m_arc.return_value.get_interface.return_value.get_contacts.return_value = []

        host._on_start()   # triggers _auto_decrypt synchronously via run_task

        # Assert marquee entry
        host._loading_progress.start.assert_called_once_with(10)

        # Assert stop() invoked at least once (first set_loading_progress)
        assert host._loading_progress.stop.called, (
            "First progress_callback must trigger _loading_progress.stop() to "
            "exit marquee mode; otherwise [value] writes are silently dropped."
        )

        # Extract ordered [value]= writes
        value_writes = [
            call.args[1] for call in host._loading_progress.__setitem__.call_args_list
            if call.args and call.args[0] == "value"
        ]
        # First three value writes come from the decrypt callback sequence
        assert value_writes[:3] == [0, 50, 100], (
            f"Expected first three [value] writes to be [0, 50, 100] from the "
            f"decrypt callback sequence (0/10, 5/10, 10/10), got {value_writes}"
        )

        # Assert ordering: start appears before any value write
        all_calls = host._loading_progress.method_calls
        # method_calls records child calls like start(), stop(), etc.
        start_idx = next(i for i, c in enumerate(all_calls) if c[0] == 'start')
        # __setitem__ is not in method_calls; use mock_calls which includes dunders
        all_mock_calls = host._loading_progress.mock_calls
        value_indices = [i for i, c in enumerate(all_mock_calls)
                         if c[0] == '__setitem__' and c.args[0] == 'value']
        assert value_indices, "No [value]= writes recorded"
        first_value_idx = value_indices[0]
        # Find start in mock_calls
        start_mock_idx = next(i for i, c in enumerate(all_mock_calls) if c[0] == 'start')
        assert start_mock_idx < first_value_idx, (
            f"_loading_progress.start() (idx={start_mock_idx}) must occur before "
            f"the first [value]= write (idx={first_value_idx}) — otherwise the bar "
            f"is never in marquee mode and the regression test is meaningless."
        )
    ```

    **Test body for decrypt_db_files_receives_progress_callback**:
    ```python
    # Same setup as test 1, then:
    with mock.patch(...) as ...:
        host._on_start()
        # Find the decrypt_db_files call
        from memoir.decrypt import decrypt_v4 as dv4_real
        # The patched mock is what got called — re-import inside the with block
        # is unnecessary; instead assert on the patch target via the context mgr.
    ```
    Simpler approach: hoist the patch context managers into a helper or use
    `pytest.fixture` to share setup. For minimal churn, just repeat the
    `with` block and assert:
    ```python
        # The mock that replaced decrypt_db_files
        # (capture via `as m_decrypt` in the with statement)
        m_decrypt.assert_called_once()
        kwargs = m_decrypt.call_args.kwargs
        assert 'progress_callback' in kwargs, (
            "decrypt_v4.decrypt_db_files must be invoked with progress_callback kwarg"
        )
        assert kwargs['progress_callback'] == host.set_loading_progress, (
            "progress_callback must be bound to self.set_loading_progress so "
            "GUI updates flow through the thread-safe logging path"
        )
    ```

    **Test body for marquee_start_happens_before_first_value_write**:
    Covered by the ordering assertion in test 1; if test 1 passes, this is
    implicitly green. Either skip this test or keep it as a focused
    single-assertion regression marker that produces a clearer failure message
    when only the ordering invariant breaks. Prefer KEEPING it as a separate
    test for diagnostic granularity.

    **Cleanup**: Use a `try/finally` or `tempfile.TemporaryDirectory()` for
    `host._script_dir` and `si.data_dir` to avoid leaking temp dirs across
    tests. pytest fixtures (`tmp_path`) are preferred but the existing test
    file uses `tempfile` directly — match the existing style for consistency.

    **Avoiding import side effects**: The top-of-file `sys.modules['tkinter'] = mock.MagicMock()`
    (line 12-13 of test_gui.py) is already in place, so `from gui.decryption import DecryptionMixin`
    will not pull in real tkinter. Confirm by running the test — if import fails,
    the mock-tkinter setup needs to extend to `tkinter.font` or similar; add
    `sys.modules['tkinter.font'] = mock.MagicMock()` defensively at the top of
    the new test class block if needed.

    **WSL caveat**: This project is Windows-only (`ctypes.windll`), but the
    `ctypes.windll` patch makes the test run anywhere. The test MUST pass under
    `python -m pytest tests/test_gui.py -v` in WSL — that is the verification
    gate.

    **Defensive note on `_save_config`**: `_save_config` is imported at the top
    of `gui/decryption.py` via `from gui.constants import ... _save_config`.
    Patch path is therefore `gui.decryption._save_config` (it is bound into the
    `gui.decryption` namespace at import time). Verify by grepping
    `grep -n "_save_config" gui/decryption.py` — it appears at lines 6 (import)
    and 197, 216 (calls). Patch at `gui.decryption._save_config` works.
  </action>
  <verify>
    <automated>cd /home/ChatMemoir && python -m pytest tests/test_gui.py::TestAutoDecryptProgressFlow -v</automated>
  </verify>
  <done>
    - `TestAutoDecryptProgressFlow` class exists in tests/test_gui.py with 3 tests
    - All 3 tests pass under `python -m pytest tests/test_gui.py -v` in WSL
    - The ordered `[value]` write sequence `[0, 50, 100]` is asserted (locks
      down the marquee->determinate regression)
    - `start(10)` called exactly once is asserted
    - `stop()` called at least once is asserted
    - `decrypt_db_files` invoked with `progress_callback=host.set_loading_progress`
      is asserted
    - No `gui/` source files are modified
    - Existing `TestSetLoadingProgress` tests still pass (no regression)
  </done>
</task>

</tasks>

<verification>
- `python -m pytest tests/test_gui.py -v` — all tests green, including the
  new `TestAutoDecryptProgressFlow` class and the pre-existing
  `TestSetLoadingProgress` regression suite.
- `grep -c "class TestAutoDecryptProgressFlow" tests/test_gui.py` returns 1.
- `git diff --stat` shows only `tests/test_gui.py` modified (no `gui/` touches).
</verification>

<success_criteria>
- New end-to-end test locks down the progressbar marquee->determinate transition
  across the full `_on_start` -> `_auto_decrypt` (v4 branch) flow.
- Test runs in WSL without requiring a real WeChat process, real Windows APIs,
  or real tkinter.
- Ordered call sequence `[start(10), stop(), value=0, value=50, value=100]`
  is the load-bearing assertion — any future regression that drops `stop()`
  or reorders the calls will fail this test loudly.
</success_criteria>

<output>
Create `.planning/quick/260629-urj-gui-testautodecryptprogressflow-mock-aut/260629-urj-SUMMARY.md` when done
</output>
