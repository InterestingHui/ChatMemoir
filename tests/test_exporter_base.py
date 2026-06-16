"""Unit tests for scribe exporter utilities and ExporterBase.

Tests cover: safe_makedirs, makedirs, escape_js_and_html, ExporterBaseBase
lifecycle, ExporterBase constructor defaults, message filtering helpers.
"""

import os
import sys
import tempfile
import types
from unittest import mock

import pytest

# Mock Windows-only modules before scribe imports
for _mod_name in ['pymem', 'yara', 'win32api', 'winreg', 'win32com',
                   'win32com.client', 'psutil', 'pythoncom', 'pysilk']:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()

if 'ctypes.windll' not in sys.modules:
    import ctypes as _ctypes
    _mw = types.ModuleType('ctypes.windll')
    _mw.kernel32 = mock.MagicMock()
    sys.modules['ctypes.windll'] = _mw


from scribe.exporter_base import (
    safe_makedirs,
    makedirs,
    escape_js_and_html,
    ExporterBaseBase,
    ExporterBase,
)


# ── safe_makedirs ────────────────────────────────────────────


class TestSafeMakedirs:
    def test_creates_new_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'new_dir')
            safe_makedirs(path)
            assert os.path.isdir(path)

    def test_no_error_on_existing_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            safe_makedirs(tmpdir)  # already exists, should not raise

    def test_nested_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'a', 'b', 'c')
            safe_makedirs(path)
            assert os.path.isdir(path)


# ── makedirs ─────────────────────────────────────────────────


class TestMakedirs:
    def test_creates_all_subdirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            makedirs(tmpdir)
            for sub in ('image', 'emoji', 'video', 'voice', 'file', 'avatar', 'music', 'icon'):
                assert os.path.isdir(os.path.join(tmpdir, sub))


# ── escape_js_and_html ───────────────────────────────────────


class TestEscapeJsAndHtml:
    def test_empty_input(self):
        assert escape_js_and_html('') == ''
        assert escape_js_and_html(None) == ''

    def test_html_escape(self):
        result = escape_js_and_html('<script>alert("xss")</script>')
        assert '<script>' not in result
        assert '&lt;script&gt;' in result

    def test_newline_escape_to_br(self):
        """Literal \\r\\n and \\n text is replaced with <br>."""
        result = escape_js_and_html(r'line1\r\nline2\nline3')
        assert '<br>' in result

    def test_quote_escaping(self):
        result = escape_js_and_html("he said \"hello\"")
        assert r'\"' in result

    def test_tab_escape_to_emsp(self):
        """Literal \\t text is replaced with &emsp;."""
        result = escape_js_and_html(r'col1\tcol2')
        assert '&emsp;' in result

    def test_plain_text_passes_through(self):
        result = escape_js_and_html('Hello World 123')
        assert 'Hello World 123' in result


# ── ExporterBaseBase ─────────────────────────────────────────


class TestExporterBaseBase:
    def test_lifecycle(self):
        eb = ExporterBaseBase()
        assert eb._is_running is True
        assert eb._is_paused is False

    def test_pause_resume(self):
        eb = ExporterBaseBase()
        eb.pause()
        assert eb._is_paused is True
        eb.resume()
        assert eb._is_paused is False

    def test_stop(self):
        eb = ExporterBaseBase()
        eb.stop()
        assert eb._is_running is False
        assert eb._is_paused is False  # resume called in stop

    def test_id_increments(self):
        id1 = ExporterBaseBase().id
        id2 = ExporterBaseBase().id
        assert id2 > id1
