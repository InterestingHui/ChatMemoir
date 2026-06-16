"""Unit tests for scribe export format utilities and simple formatters.

Tests cover format-specific logic that doesn't require a live ArchiveInterface.
"""

import os
import sys
import tempfile
import types
from unittest import mock

import pytest

# Mock Windows-only modules
for _mod_name in ['pymem', 'yara', 'win32api', 'winreg', 'win32com',
                   'win32com.client', 'psutil', 'pythoncom', 'pysilk']:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()

if 'ctypes.windll' not in sys.modules:
    import ctypes as _ctypes
    _mw = types.ModuleType('ctypes.windll')
    _mw.kernel32 = mock.MagicMock()
    sys.modules['ctypes.windll'] = _mw

from memoir import MessageType


# ── MessageType coverage ─────────────────────────────────────


class TestMessageTypeExports:
    def test_all_exportable_types(self):
        """Verify all message types have consistent integer values."""
        types_to_check = [
            MessageType.Text,
            MessageType.Image,
            MessageType.Video,
            MessageType.Audio,
            MessageType.File,
            MessageType.Emoji,
            MessageType.LinkMessage,
            MessageType.Quote,
            MessageType.System,
            MessageType.Voip,
            MessageType.Position,
            MessageType.RedEnvelope,
            MessageType.Transfer,
            MessageType.BusinessCard,
            MessageType.FavNote,
            MessageType.Pat,
            MessageType.MergedMessages,
            MessageType.FavoritesVideo,
            MessageType.Applet,
            MessageType.Music,
        ]
        for t in types_to_check:
            assert isinstance(t, int)
            name = MessageType.name(t)
            assert isinstance(name, str)
            assert name != '未知类型'


# ── Config constants ─────────────────────────────────────────


class TestConfig:
    def test_file_type_constants(self):
        from scribe.config import FileType
        # FileType should define known export format constants
        assert hasattr(FileType, 'HTML') or hasattr(FileType, 'TXT')


# ── Integration: Export utility functions ───────────────────

class TestExportUtils:
    def test_safe_makedirs_integration(self):
        from scribe.exporter_base import safe_makedirs
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'deep', 'nested', 'path')
            safe_makedirs(path)
            assert os.path.isdir(path)
            # Second call should not error
            safe_makedirs(path)

    def test_makedirs_integration(self):
        from scribe.exporter_base import makedirs
        with tempfile.TemporaryDirectory() as tmpdir:
            makedirs(tmpdir)
            for sub in ('image', 'emoji', 'video', 'voice', 'file', 'avatar', 'music', 'icon'):
                assert os.path.isdir(os.path.join(tmpdir, sub))
