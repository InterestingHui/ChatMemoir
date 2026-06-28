"""Unit tests for gui/ package — pure logic that doesn't need tkinter."""

import json
import os
import sys
import tempfile
from unittest import mock

import pytest

# Mock tkinter before gui imports
sys.modules['tkinter'] = mock.MagicMock()
sys.modules['tkinter.ttk'] = mock.MagicMock()

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
