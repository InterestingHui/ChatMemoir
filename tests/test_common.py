"""Unit tests for memoir.decrypt.common — SessionInfo and helpers."""

import sys
import types
from unittest import mock

import pytest

# Mock all Windows-only modules before any memoir imports
mock_kernel32 = mock.MagicMock()
mock_kernel32.OpenProcess = mock.MagicMock()
mock_kernel32.CloseHandle = mock.MagicMock()

import ctypes as _ctypes
if not hasattr(_ctypes, 'windll'):
    mock_windll = mock.MagicMock()
    mock_windll.kernel32 = mock_kernel32
    _ctypes.windll = mock_windll

if not hasattr(_ctypes, 'WinDLL'):
    _ctypes.WinDLL = lambda name, **kw: mock_kernel32

if 'ctypes.wintypes' not in sys.modules:
    _wt = types.ModuleType('ctypes.wintypes')
    _wt.DWORD = _ctypes.c_ulong
    _wt.BOOL = _ctypes.c_int
    _wt.HANDLE = _ctypes.c_void_p
    _wt.LPCVOID = _ctypes.c_void_p
    _wt.LPVOID = _ctypes.c_void_p
    sys.modules['ctypes.wintypes'] = _wt

for _mod_name in ['psutil', 'win32api', 'winreg', 'pymem', 'yara',
                   'win32com', 'win32com.client', 'pythoncom',
                   'pymem.process']:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()

from memoir.decrypt.common import SessionInfo


class TestSessionInfo:
    def test_default_values(self):
        info = SessionInfo()
        assert info.pid == 0
        assert info.version == '0.0.0.0'
        assert info.account_name == ''
        assert info.nick_name == ''
        assert info.phone == ''
        assert info.data_dir == ''
        assert info.key == ''
        assert info.key_map == {}
        assert info.uid == ''
        assert info.errcode == 404
        assert info.errmsg == '错误！请登录微信。'

    def test_set_and_get(self):
        info = SessionInfo()
        info.pid = 1234
        info.version = '4.1.8.29'
        info.nick_name = 'TestUser'
        info.key = 'ab' * 16
        info.key_map = {'contact/contact.db': 'cd' * 16}

        assert info.pid == 1234
        assert info.version == '4.1.8.29'
        assert info.nick_name == 'TestUser'
        assert len(info.key_map) == 1

    def test_str_contains_fields(self):
        info = SessionInfo()
        info.pid = 42
        info.version = '4.0.0.0'
        s = str(info)
        assert '42' in s
        assert '4.0.0.0' in s

    def test_to_json(self):
        info = SessionInfo()
        info.version = '4.1.8.29'
        info.nick_name = 'TestUser'
        info.data_dir = r'C:\Users\test\xwechat_files\abc\db_storage'
        info.uid = 'wxid_123'

        j = info.to_json()
        assert j['version'] == '4.1.8.29'
        assert j['nickname'] == 'TestUser'
        assert j['data_dir'] == r'C:\Users\test\xwechat_files\abc\db_storage'
        assert j['uid'] == 'wxid_123'

    def test_key_map_independent(self):
        """Verify key_map is not shared across instances."""
        info1 = SessionInfo()
        info2 = SessionInfo()
        info1.key_map['test.db'] = 'abc'
        assert 'test.db' not in info2.key_map

    def test_errcode_values(self):
        info = SessionInfo()
        assert info.errcode == 404

        info.errcode = 200
        assert info.errcode == 200

        info.errcode = 405
        assert info.errcode == 405
