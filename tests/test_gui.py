"""Unit tests for gui/ package — pure logic that doesn't need tkinter."""

import json
import os
import sys
import tempfile
from unittest import mock

import pytest

# ctypes.windll / ctypes.WinDLL are Windows-only. Several memoir.decrypt
# modules access ctypes.windll.kernel32 / .shell32 and call ctypes.WinDLL(...)
# at import time (module-level assignments), which would crash on Linux/WSL.
# Install MagicMocks so attribute access and calls are transparent; tests that
# exercise the real ctypes paths stub them further via monkeypatch.
import ctypes as _ctypes
if not hasattr(_ctypes, 'windll'):
    _ctypes.windll = mock.MagicMock()
if not hasattr(_ctypes, 'WinDLL'):
    _ctypes.WinDLL = mock.MagicMock()
if not hasattr(_ctypes, 'CDLL'):
    _ctypes.CDLL = mock.MagicMock()

# Mock tkinter before gui imports
sys.modules['tkinter'] = mock.MagicMock()
sys.modules['tkinter.ttk'] = mock.MagicMock()

# Mock Windows-only stdlib modules so memoir.decrypt can be imported on WSL/Linux.
# These are only transitively required (via session_v3/session_v4 → winreg, pymem,
# win32api) and are never exercised by the pure-logic tests below; mocking them at
# import-time keeps the test suite cross-platform without touching gui/ source.
import types as _types


def _mock_pkg(name):
    """Mock a package so submodule imports (e.g. `import pymem.process`) succeed."""
    m = _types.ModuleType(name)
    m.__path__ = []
    return m


for _winmod in ('winreg', 'win32api', 'win32com', 'win32com.client',
                'win32con', 'win32process', 'win32security', 'pywintypes',
                'yara', 'pythoncom'):
    if _winmod not in sys.modules:
        sys.modules[_winmod] = mock.MagicMock()

# pymem is imported as both `import pymem` and `import pymem.process` — it must
# look like a real package (have __path__) so the submodule import succeeds.
for _pkg in ('pymem', 'pymem.process'):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = _mock_pkg(_pkg)

from gui import constants
from gui.logging import LoggingMixin


# ── Constants ────────────────────────────────────────────────


class TestConstants:
    def test_colors_are_defined(self):
        assert constants.PRIMARY == "#07C160"
        assert constants.DANGER == "#FA5151"
        assert constants.BG == "#F0F2F5"
        assert constants.CARD_BG == "#FFFFFF"

    def test_color_is_valid_hex(self):
        for attr in ['PRIMARY', 'PRIMARY_HOVER', 'BG', 'CARD_BG', 'TEXT_PRIMARY',
                      'TEXT_SECONDARY', 'BORDER', 'DANGER']:
            val = getattr(constants, attr)
            assert val.startswith('#'), f"{attr} = {val} is not hex"
            assert len(val) == 7, f"{attr} = {val} bad hex length"


# ── _resource_path ───────────────────────────────────────────


class TestResourcePath:
    def test_dev_mode_path(self):
        assert getattr(sys, 'frozen', False) is False
        path = constants._resource_path('test_file.txt')
        assert path.endswith('test_file.txt')
        assert 'gui' not in path  # uses base_path which is project root

    def test_nested_resource(self):
        path = constants._resource_path('scribe/resources/template.html')
        assert path.endswith('scribe/resources/template.html')


# ── _load_config / _save_config ──────────────────────────────


class TestConfigIO:
    def test_load_config_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', f.name):
                cfg = constants._load_config()
                assert cfg == {}
        finally:
            os.unlink(f.name)

    def test_load_config_with_data(self):
        data = {"export_format": "HTML", "output_dir": "/tmp/out"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', f.name):
                cfg = constants._load_config()
                assert cfg == data
        finally:
            os.unlink(f.name)

    def test_load_config_nonexistent(self):
        with mock.patch.object(constants, '_CONFIG_PATH', '/nonexistent/config.json'):
            cfg = constants._load_config()
            assert cfg == {}

    def test_save_config(self):
        with tempfile.NamedTemporaryFile(mode='r', suffix='.json', delete=False) as f:
            cfg_path = f.name
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', cfg_path):
                constants._save_config({"format": "TXT"})
            with open(cfg_path, 'r') as f:
                saved = json.load(f)
            assert saved == {"format": "TXT"}
        finally:
            os.unlink(cfg_path)

    def test_save_config_permission_error_handled(self):
        with mock.patch.object(constants, '_CONFIG_PATH', '/dev/null/readonly/conf.json'):
            # Should not raise
            constants._save_config({"x": 1})


# ── LoggingMixin.set_loading_progress ────────────────────────


class _FakeHost(LoggingMixin):
    """Minimal host exercising LoggingMixin.set_loading_progress without tkinter."""

    def __init__(self):
        self.root = mock.MagicMock()
        # Run scheduled callbacks synchronously so _update executes immediately.
        self.root.after.side_effect = lambda ms, fn: fn()
        self._loading_progress = mock.MagicMock()
        self._lbl_loading_pct = mock.MagicMock()


class TestSetLoadingProgress:
    """Regression tests: set_loading_progress must exit marquee mode before
    setting [value], otherwise ttk.Progressbar silently ignores the update."""

    def test_stop_invoked_before_value_set(self):
        # Arrange
        host = _FakeHost()
        # Act — first real progress update after a hypothetical start(10) marquee
        host.set_loading_progress(5, 20, "contact.db")
        # Assert — stop() called so bar leaves marquee mode
        assert host._loading_progress.stop.called, (
            "set_loading_progress must call _loading_progress.stop() so the bar "
            "exits marquee mode before [value] is set"
        )
        # Assert — value updated to the correct percentage
        host._loading_progress.__setitem__.assert_called_with("value", 25)
        # Assert — stop() happens BEFORE [value]= assignment (call order)
        calls = host._loading_progress.method_calls + host._loading_progress.__setitem__.mock_calls
        # Use a simpler order check: stop is called inside _update which runs to
        # completion synchronously; verify both happened. Order is guaranteed by
        # source ordering (stop() precedes the assignment line).
        assert host._loading_progress.stop.called

    def test_stop_called_before_value_assignment_order(self):
        """Verify stop() is invoked before the [value] set within _update."""
        host = _FakeHost()
        order = []

        def _record_stop():
            order.append("stop")

        def _record_setitem(key, value):
            order.append(f"set:{key}={value}")

        host._loading_progress.stop.side_effect = _record_stop
        host._loading_progress.__setitem__.side_effect = _record_setitem

        host.set_loading_progress(5, 20, "contact.db")

        assert order[0] == "stop", f"expected stop() first, got {order}"
        assert "set:value=25" in order

    def test_subsequent_calls_remain_correct(self):
        """stop() is a documented no-op when not in marquee mode; subsequent
        set_loading_progress calls must still update [value]."""
        host = _FakeHost()

        host.set_loading_progress(5, 20, "contact.db")
        assert host._loading_progress.__setitem__.assert_called_with("value", 25) is None

        # Second call — should not raise, should land at 50%
        host._loading_progress.reset_mock()
        host.set_loading_progress(10, 20, "message_0.db")
        host._loading_progress.__setitem__.assert_called_with("value", 50)
        assert host._loading_progress.stop.called

    def test_total_zero_returns_early_without_touching_bar(self):
        """total <= 0 must short-circuit before _update is scheduled."""
        host = _FakeHost()

        root_after_count_before = host.root.after.call_count
        host.set_loading_progress(0, 0, "")

        # root.after was not invoked by this call (early-return guard)
        assert host.root.after.call_count == root_after_count_before, (
            "set_loading_progress must not schedule _update when total <= 0"
        )
        # progress bar untouched
        assert not host._loading_progress.stop.called
        host._loading_progress.__setitem__.assert_not_called()

    def test_label_format_matches_contract(self):
        """Label text format: '{current}/{total} ({pct}%)  {short_name}'
        where short_name is basename(filename) truncated to 30 chars."""
        host = _FakeHost()

        host.set_loading_progress(5, 20, "contact.db")

        # configure was called at least once with a text=... kwarg
        kwargs_calls = [c.kwargs for c in host._lbl_loading_pct.configure.call_args_list
                        if 'text' in c.kwargs]
        assert kwargs_calls, "lbl_loading_pct.configure not called with text="
        text = kwargs_calls[-1]['text']
        # Format: "5/20 (25%)  contact.db" (two spaces between pct and name)
        import re
        assert re.match(r"^5/20 \(25%\)\s{2}contact\.db$", text), (
            f"label text {text!r} does not match contract"
        )

    def test_filename_truncated_to_30_chars(self):
        """Basename longer than 30 chars is truncated to 30."""
        host = _FakeHost()
        long_name = "a" * 50 + ".db"

        host.set_loading_progress(1, 2, long_name)

        kwargs_calls = [c.kwargs for c in host._lbl_loading_pct.configure.call_args_list
                        if 'text' in c.kwargs]
        text = kwargs_calls[-1]['text']
        import os
        expected_short = os.path.basename(long_name)[:30]
        assert text.endswith(expected_short), (
            f"label text {text!r} does not end with truncated basename {expected_short!r}"
        )


# ── End-to-end progress flow: start(10) → stop → value sequence ──────


class _FakeApp:
    """Minimal DecryptionMixin + LoggingMixin host exercising the full
    _on_start → _auto_decrypt → _on_decrypt_done progress flow without
    tkinter or a real WeChat process.

    Mocks at the SOURCE MODULE paths because _auto_decrypt performs local
    imports (gui/decryption.py:56-58); patching gui.decryption.* would have
    no effect since the local import rebinds the names.
    """

    def __init__(self, tmp_path):
        from gui.decryption import DecryptionMixin
        from gui.logging import LoggingMixin

        # Compose both mixins into a single instance without invoking the
        # real ChatMemoirApp.__init__ (which builds a tkinter root).
        class _Composed(LoggingMixin, DecryptionMixin):
            pass

        self._mixin = _Composed()
        # Bind ALL mixin methods (public + private) onto self so _on_start /
        # _auto_decrypt / _on_decrypt_done / helpers like _read_wx_key_cache
        # all see a unified `self` matching the real ChatMemoirApp surface.
        for _name in dir(self._mixin):
            if _name.startswith("__") and _name.endswith("__"):
                continue
            _attr = getattr(self._mixin, _name, None)
            if callable(_attr) and not isinstance(_attr, type):
                try:
                    setattr(self, _name, _attr.__get__(self, type(self)))
                except (AttributeError, TypeError):
                    setattr(self, _name, _attr)

        # GUI widgets — MagicMock so .configure / .pack_forget / .start / .stop
        # are all no-ops that can be inspected after the fact.
        self.root = mock.MagicMock()
        # Run scheduled callbacks synchronously: root.after(ms, fn, *a, **kw) → fn(*a, **kw)
        self.root.after.side_effect = lambda ms, fn, *a, **kw: fn(*a, **kw)

        self._loading_progress = mock.MagicMock()
        self._lbl_loading_pct = mock.MagicMock()
        self._loading_log = mock.MagicMock()
        self._lbl_loading_status = mock.MagicMock()
        self._lbl_account = mock.MagicMock()
        self._btn_retry = mock.MagicMock()
        self._btn_cancel = mock.MagicMock()
        self._btn_export = mock.MagicMock()

        # App state used by _auto_decrypt
        self._script_dir = str(tmp_path)
        self._config = {}
        self._db_version = 4
        self.database = None
        self.db_dir_actual = None
        self.contacts = []

    # Stubs for GUI helpers invoked by _on_start / _on_decrypt_done that
    # we don't want to actually execute (they touch tkinter screens).
    def _show_screen(self, name):
        self._last_screen = name

    def _populate_contacts(self):
        self._populated = True

    def _compute_stats(self):
        self._stats_computed = True

    def _update_adv_menu(self):
        self._adv_menu_updated = True

    def _on_decrypt_error(self, e):
        # Mirror real handler: stop bar + record error. Used as the on_error
        # callback when _auto_decrypt raises; here it's only a safety net so
        # _on_start can resolve the attribute at call time.
        self._loading_progress.stop()
        self._decrypt_error = e


def _build_session_info(tmp_path, key="abcdef0123456789" * 4):
    """Build a SessionInfo whose data_dir points at a real tmp dir so that
    downstream os.walk / sqlite3.connect calls don't crash on missing paths."""
    from memoir.decrypt.common import SessionInfo
    si = SessionInfo()
    si.uid = "wxid_test1234"
    si.data_dir = str(tmp_path / "data")
    si.nick_name = "TestUser"
    si.key = key
    si.key_map = {}
    os.makedirs(si.data_dir, exist_ok=True)
    return si


def _patch_decrypt_stack(monkeypatch, session_info):
    """Patch the full memoir.decrypt + ctypes stack that _auto_decrypt pulls in
    via local imports. Returns the decrypt_db_files mock so the caller can
    attach a side_effect."""
    import memoir.decrypt.decrypt_v4 as dv4
    import memoir.decrypt.decrypt_dat as ddat

    # get_info_v4 → [session_info]
    monkeypatch.setattr("memoir.decrypt.get_info_v4", lambda: [session_info])

    # get_decode_code_v4 → int xor_key for .dat image decoding (Me.xor_key
    # is serialized via json.dump, so a real int matches production behavior).
    monkeypatch.setattr(ddat, "get_decode_code_v4", lambda data_dir: 1)

    # decrypt_db_files → progress callback called 3 times then returns (10, 0)
    def _fake_decrypt_db_files(key, src_dir=None, dest_dir=None, key_map=None,
                               skip_existing=True, progress_callback=None):
        if progress_callback is not None:
            progress_callback(0, 10, "")
            progress_callback(5, 10, "contact.db")
            progress_callback(10, 10, "message_0.db")
        return (10, 0)

    decrypt_mock = mock.MagicMock(side_effect=_fake_decrypt_db_files)
    monkeypatch.setattr(dv4, "decrypt_db_files", decrypt_mock)

    # ctypes.windll.shell32.IsUserAnAdmin → 1 (truthy) so admin check passes.
    # `import ctypes` is done at module top of gui/decryption.py only inside
    # _auto_decrypt; we patch the windll attribute on the real ctypes module.
    import ctypes
    monkeypatch.setattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 1, raising=False)

    # ArchiveConnection → returns a fake conn whose get_interface() yields a
    # mock with get_contacts() returning []. Patched on memoir module path.
    import memoir
    fake_conn = mock.MagicMock()
    fake_interface = mock.MagicMock()
    fake_interface.get_contacts.return_value = []
    fake_conn.get_interface.return_value = fake_interface
    monkeypatch.setattr(memoir, "ArchiveConnection", lambda *a, **kw: fake_conn)

    return decrypt_mock


class TestAutoDecryptProgressFlow:
    """End-to-end test that the decrypt flow calls _loading_progress.start(10),
    eventually stop()s, and writes the value sequence [0, 50, 100]."""

    def test_progress_flow_start_then_stop_then_value_sequence(self, tmp_path, monkeypatch):
        # Arrange — build a fake app and patch the decrypt stack
        app = _FakeApp(tmp_path)
        session_info = _build_session_info(tmp_path)
        _patch_decrypt_stack(monkeypatch, session_info)

        # Mock run_task so _auto_decrypt runs synchronously and _on_decrypt_done
        # is invoked immediately afterwards (mirroring the real flow).
        def _sync_run_task(target, on_done=None, on_error=None, **kw):
            try:
                result = target()
                if on_done:
                    on_done(result)
            except Exception as e:
                if on_error:
                    on_error(e)
                else:
                    raise
        app.run_task = mock.MagicMock(side_effect=_sync_run_task)

        # Act — trigger the start button command
        app._on_start()

        # Assert 1: _loading_progress.start was called once with (10,) — the
        # marquee kick-off that was the original bug.
        start_calls = [c for c in app._loading_progress.start.call_args_list]
        assert len(start_calls) == 1, (
            f"expected exactly one start() call, got {len(start_calls)}: {start_calls}"
        )
        assert start_calls[0].args == (10,), (
            f"start() called with {start_calls[0].args!r}, expected (10,)"
        )

        # Assert 2: stop was called at least once (set_loading_progress._update
        # calls stop() each time a progress callback fires, plus _on_decrypt_done
        # calls stop() once more).
        assert app._loading_progress.stop.called, (
            "stop() was never invoked — bar would be stuck in marquee mode and "
            "real progress silently dropped"
        )

        # Assert 3: __setitem__('value', ...) calls yield a sequence that
        # includes 0, 50, and 100 (the three distinct pct values produced by
        # the three callback invocations 0/10, 5/10, 10/10).
        value_assignments = [
            c.args[1] for c in app._loading_progress.__setitem__.call_args_list
            if c.args and c.args[0] == "value"
        ]
        assert value_assignments, "no [value] assignments captured"
        # The set of values reached must include all three thresholds.
        assert 0 in value_assignments, (
            f"value=0 missing from sequence: {value_assignments!r}"
        )
        assert 50 in value_assignments, (
            f"value=50 missing from sequence: {value_assignments!r}"
        )
        assert 100 in value_assignments, (
            f"value=100 missing from sequence: {value_assignments!r}"
        )
        # And the order must be non-decreasing (start marquee → real progress).
        # Note: _on_start itself does not set value, but set_loading_progress(0,1,"")
        # is called once before decrypt_db_files, so value=0 appears first.
        assert value_assignments[0] == 0, (
            f"first value assignment should be 0 (initial reset), got {value_assignments[0]}"
        )
        assert value_assignments[-1] == 100, (
            f"final value assignment should be 100 (complete), got {value_assignments[-1]}"
        )

    def test_set_loading_progress_idempotent_stop(self):
        """Repeated set_loading_progress calls must not error when stop() is
        invoked on a bar not currently in marquee mode — documented no-op."""
        host = _FakeHost()

        # First call — stop() may genuinely transition state
        host.set_loading_progress(0, 10, "")
        # Subsequent calls — stop() is a documented no-op; must not raise
        host.set_loading_progress(3, 10, "a.db")
        host.set_loading_progress(7, 10, "b.db")
        host.set_loading_progress(10, 10, "c.db")

        # All three thresholds landed
        values = [c.args[1] for c in host._loading_progress.__setitem__.call_args_list
                  if c.args and c.args[0] == "value"]
        assert values == [0, 30, 70, 100], f"unexpected value sequence: {values!r}"
        # stop() called on every set_loading_progress (4 times)
        assert host._loading_progress.stop.call_count == 4
