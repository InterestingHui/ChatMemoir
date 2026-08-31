"""Unit tests for v4 decryption logic.

Tests cover pure crypto and I/O functions that don't require a live WeChat process.
Windows-specific modules (ctypes.windll, pymem, yara, winreg) are mocked at import time.
"""

import hashlib
import hmac
import os
import struct
import sys
import tempfile
import types
from unittest import mock

import pytest

# ── Mock Windows-only imports before importing any memoir modules ──

mock_kernel32 = mock.MagicMock()
mock_kernel32.OpenProcess = mock.MagicMock()
mock_kernel32.ReadProcessMemory = mock.MagicMock()
mock_kernel32.CloseHandle = mock.MagicMock()
mock_kernel32.VirtualQueryEx = mock.MagicMock()

# Mock ctypes.windll
mock_windll = mock.MagicMock()
mock_windll.kernel32 = mock_kernel32
mock_windll.shell32 = mock.MagicMock()

import ctypes as _ctypes
if not hasattr(_ctypes, 'windll'):
    _ctypes.windll = mock_windll

# Mock ctypes.WinDLL (doesn't exist on Linux)
if not hasattr(_ctypes, 'WinDLL'):
    _ctypes.WinDLL = lambda name, **kw: mock_kernel32 if name == 'kernel32' else mock.MagicMock()

# Ensure ctypes.wintypes is available
if 'ctypes.wintypes' not in sys.modules:
    _wt = types.ModuleType('ctypes.wintypes')
    _wt.DWORD = _ctypes.c_ulong
    _wt.BOOL = _ctypes.c_int
    _wt.HANDLE = _ctypes.c_void_p
    _wt.LPCVOID = _ctypes.c_void_p
    _wt.LPVOID = _ctypes.c_void_p
    sys.modules['ctypes.wintypes'] = _wt

# Mock all Windows-only modules
for _mod_name in ['pymem', 'yara', 'win32api', 'winreg', 'win32com',
                   'win32com.client', 'psutil', 'pythoncom',
                   'pymem.process']:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()

# Now we can import
from memoir.decrypt.session_v4 import (
    collect_db_salts,
    is_ok,
    is_ok_passphrase,
    _verify_key_stdlib,
    read_string,
    read_num,
    read_bytes,
    get_key_,
    verify_key,
    check_chunk,
    dump_session_info_v4,
)
from memoir.decrypt.decrypt_v4 import (
    decrypt_db_file_v4,
    decrypt_db_files,
    IV_SIZE,
    HMAC_SHA512_SIZE,
    KEY_SIZE,
    AES_BLOCK_SIZE,
    ROUND_COUNT,
    PAGE_SIZE,
    SALT_SIZE,
    SQLITE_HEADER,
)

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512


# ── Helpers ──────────────────────────────────────────────────

def _make_encrypted_page(key: bytes, salt: bytes, page_num: int = 0):
    """Create a single valid encrypted page for testing.

    Returns the full PAGE_SIZE bytes: salt + encrypted_data + IV + HMAC.
    """
    mac_salt = bytes(x ^ 0x3a for x in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', key, mac_salt, 2, dklen=KEY_SIZE)

    # Random plaintext (enough to fill the page minus salt and reserve)
    reserve = IV_SIZE + 64  # HMAC_SHA512_SIZE = 64
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE

    if page_num == 0:
        data_size = PAGE_SIZE - SALT_SIZE - reserve
    else:
        data_size = PAGE_SIZE - reserve

    plaintext = os.urandom(data_size)

    iv = os.urandom(IV_SIZE)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(plaintext)

    # HMAC covers (encrypted data || iv portion before reserve)
    if page_num == 0:
        payload = salt + encrypted
        hmac_data = payload[SALT_SIZE:len(payload)]
    else:
        payload = encrypted
        hmac_data = payload[:len(payload)]

    # Actually the HMAC covers from SALT_SIZE offset (or 0) up to end - reserve + IV_SIZE
    # Let's reconstruct properly
    if page_num == 0:
        start = SALT_SIZE
    else:
        start = 0

    # Build the full page
    # Layout: [salt (16)] [encrypted_data] [iv (16)] [hmac (64)] [padding]
    # Total after salt: encrypted + iv + hmac, padded to reserve
    page = bytearray(PAGE_SIZE)
    if page_num == 0:
        page[:SALT_SIZE] = salt

    enc_offset = SALT_SIZE if page_num == 0 else 0
    page[enc_offset:enc_offset + len(encrypted)] = encrypted

    # Place IV at end - reserve
    iv_offset = PAGE_SIZE - reserve
    page[iv_offset:iv_offset + IV_SIZE] = iv

    # Compute HMAC over page[start : end - reserve + IV_SIZE]
    end = PAGE_SIZE
    hmac_input = bytes(page[start:end - reserve + IV_SIZE])
    mac = hmac.new(mac_key, hmac_input, hashlib.sha512)
    mac.update(struct.pack('<I', page_num + 1))
    hash_mac = mac.digest()

    # Place HMAC after IV
    hmac_offset = iv_offset + IV_SIZE
    page[hmac_offset:hmac_offset + len(hash_mac)] = hash_mac

    return bytes(page)


# ── Tests: read_string / read_num / read_bytes ──

class TestReadHelpers:
    def test_read_string_valid(self):
        data = b'Hello World\x00garbage'
        assert read_string(data, 0, 11) == 'Hello World'

    def test_read_string_out_of_bounds(self):
        data = b'short'
        # Python slicing doesn't raise, just truncates
        assert read_string(data, 0, 100) == 'short'

    def test_read_string_invalid_utf8(self):
        data = b'\xff\xfe\xfd'
        assert read_string(data, 0, 3) == ''

    def test_read_num_1byte(self):
        data = struct.pack('<B', 42)
        assert read_num(data, 0, 1) == 42

    def test_read_num_2byte(self):
        data = struct.pack('<H', 1000)
        assert read_num(data, 0, 2) == 1000

    def test_read_num_4byte(self):
        data = struct.pack('<I', 100000)
        assert read_num(data, 0, 4) == 100000

    def test_read_num_8byte(self):
        data = struct.pack('<Q', 2**40)
        assert read_num(data, 0, 8) == 2**40

    def test_read_num_unsupported_size(self):
        with pytest.raises(ValueError):
            read_num(b'\x00\x00\x00', 0, 3)

    def test_read_bytes(self):
        data = b'\x01\x02\x03\x04\x05'
        assert read_bytes(data, 1, 3) == b'\x02\x03\x04'


# ── Tests: collect_db_salts ──

class TestCollectDbSalts:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert collect_db_salts(tmpdir) == {}

    def test_nonexistent_dir(self):
        assert collect_db_salts('/nonexistent/path') == {}

    def test_none_dir(self):
        assert collect_db_salts(None) == {}

    def test_finds_db_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            salt1 = os.urandom(16)
            salt2 = os.urandom(16)
            with open(os.path.join(tmpdir, 'test1.db'), 'wb') as f:
                f.write(salt1 + b'\x00' * 100)
            with open(os.path.join(tmpdir, 'test2.db'), 'wb') as f:
                f.write(salt2 + b'\x00' * 100)
            result = collect_db_salts(tmpdir)
            assert len(result) == 2
            assert salt1.hex() in result
            assert salt2.hex() in result

    def test_skips_empty_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'empty.db'), 'wb') as f:
                pass
            assert collect_db_salts(tmpdir) == {}

    def test_skips_non_db_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'data.txt'), 'wb') as f:
                f.write(os.urandom(100))
            assert collect_db_salts(tmpdir) == {}

    def test_nested_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, 'subdir')
            os.makedirs(sub)
            salt = os.urandom(16)
            with open(os.path.join(sub, 'nested.db'), 'wb') as f:
                f.write(salt + b'\x00' * 100)
            result = collect_db_salts(tmpdir)
            assert len(result) == 1
            assert salt.hex() in result


# ── Tests: _verify_key_stdlib ──

class TestVerifyKeyStdlib:
    def test_correct_key(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert _verify_key_stdlib(key, page) is True

    def test_wrong_key(self):
        key = os.urandom(KEY_SIZE)
        wrong_key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert _verify_key_stdlib(wrong_key, page) is False

    def test_corrupted_page(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = bytearray(_make_encrypted_page(key, salt, page_num=0))
        page[100] ^= 0xFF  # flip a bit
        assert _verify_key_stdlib(key, bytes(page)) is False


# ── Tests: is_ok ──

class TestIsOk:
    def test_correct_key(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert is_ok(key, page) is True

    def test_wrong_key(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert is_ok(os.urandom(KEY_SIZE), page) is False

    def test_shared_flag_set(self):
        from multiprocessing import Value
        flag = Value('b', True, lock=True)
        key = os.urandom(KEY_SIZE)
        page = _make_encrypted_page(key, os.urandom(SALT_SIZE), page_num=0)
        assert is_ok(key, page, shared_flag=flag) is False


# ── Tests: is_ok_passphrase ──

class TestIsOkPassphrase:
    def test_correct_passphrase(self):
        passphrase = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        derived_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT,
                             hmac_hash_module=SHA512)
        page = _make_encrypted_page(derived_key, salt, page_num=0)
        assert is_ok_passphrase(passphrase, page) is True

    def test_wrong_passphrase(self):
        passphrase = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        derived_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT,
                             hmac_hash_module=SHA512)
        page = _make_encrypted_page(derived_key, salt, page_num=0)
        assert is_ok_passphrase(os.urandom(KEY_SIZE), page) is False


# ── Tests: get_key_ ──

class TestGetKey:
    def test_finds_raw_key(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        candidates = [os.urandom(KEY_SIZE), key]
        result, is_passphrase = get_key_(candidates, page)
        assert result == key.hex()
        assert is_passphrase is False

    def test_no_match(self):
        salt = os.urandom(SALT_SIZE)
        key = os.urandom(KEY_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        candidates = [os.urandom(KEY_SIZE), os.urandom(KEY_SIZE)]
        result, is_passphrase = get_key_(candidates, page)
        assert result is None
        assert is_passphrase is False

    def test_empty_candidates(self):
        key = os.urandom(KEY_SIZE)
        page = _make_encrypted_page(key, os.urandom(SALT_SIZE), page_num=0)
        result, is_passphrase = get_key_([], page)
        assert result is None


# ── Tests: decrypt_db_file_v4 ──

class TestDecryptDbFileV4:
    def test_decrypt_valid_file(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        key_hex = key.hex()

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_path = os.path.join(tmpdir, 'test_dec.db')

            # Build a minimal encrypted DB with one page
            page = _make_encrypted_page(key, salt, page_num=0)
            with open(in_path, 'wb') as f:
                f.write(page)

            result = decrypt_db_file_v4(key_hex, in_path, out_path)
            assert result is True
            assert os.path.exists(out_path)

            with open(out_path, 'rb') as f:
                content = f.read()
            # Output starts with SQLite header
            assert content[:len(SQLITE_HEADER)] == SQLITE_HEADER
            # Output should be larger than just the header
            assert len(content) > len(SQLITE_HEADER) + 1

    def test_nonexistent_input(self):
        result = decrypt_db_file_v4('00' * 32, '/nonexistent/path.db', '/tmp/out.db')
        assert result is False

    def test_wrong_key_fails(self):
        key = os.urandom(KEY_SIZE)
        wrong_key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_path = os.path.join(tmpdir, 'test_dec.db')

            page = _make_encrypted_page(key, salt, page_num=0)
            with open(in_path, 'wb') as f:
                f.write(page)

            result = decrypt_db_file_v4(wrong_key.hex(), in_path, out_path)
            assert result is False
            # Failed output should be cleaned up
            assert not os.path.exists(out_path)


# ── Tests: decrypt_db_files ──

class TestDecryptDbFiles:
    def test_nonexistent_src_dir(self):
        total, failed = decrypt_db_files('00' * 32, '/nonexistent/src', '/tmp/dest')
        assert total == 0
        assert failed == 0

    def test_skip_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src')
            dest = os.path.join(tmpdir, 'dest')
            os.makedirs(src)

            # Create a small .db that's too small to decrypt (< PAGE_SIZE)
            with open(os.path.join(src, 'tiny.db'), 'wb') as f:
                f.write(b'\x00' * 100)

            total, failed = decrypt_db_files('00' * 32, src, dest)
            assert total == 0  # skipped because < PAGE_SIZE

    def test_progress_callback(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        key_hex = key.hex()

        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src')
            dest = os.path.join(tmpdir, 'dest')
            os.makedirs(src)

            page = _make_encrypted_page(key, salt, page_num=0)
            with open(os.path.join(src, 'test.db'), 'wb') as f:
                f.write(page)

            callbacks = []
            def cb(current, total, filename):
                callbacks.append((current, total, filename))

            total, failed = decrypt_db_files(key_hex, src, dest, progress_callback=cb)
            assert len(callbacks) >= 1
            assert callbacks[0][0] == 0  # initial call with current=0


# ── Tests: verify_key ──

class TestVerifyKey:
    def test_correct_key(self):
        from multiprocessing import Value
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        flag = Value('b', False, lock=True)
        result = verify_key(key, page, flag, None)
        assert result == key
        assert bool(flag.value)

    def test_wrong_length_key(self):
        from multiprocessing import Value
        salt = os.urandom(SALT_SIZE)
        key = os.urandom(KEY_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        flag = Value('b', False, lock=True)
        assert verify_key(b'\x00' * 16, page, flag, None) is False
        assert verify_key(b'\x00' * 31, page, flag, None) is False
        assert verify_key(b'\x00' * 33, page, flag, None) is False
        assert verify_key(b'', page, flag, None) is False

    def test_wrong_key(self):
        from multiprocessing import Value
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        flag = Value('b', False, lock=True)
        assert verify_key(os.urandom(KEY_SIZE), page, flag, None) is False
        assert not bool(flag.value)

    def test_flag_already_set_skips(self):
        from multiprocessing import Value
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        flag = Value('b', True, lock=True)
        assert verify_key(key, page, flag, None) is False


# ── Tests: check_chunk ──

class TestCheckChunk:
    def test_correct_chunk(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert check_chunk(key, page) == key

    def test_wrong_chunk(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert check_chunk(os.urandom(KEY_SIZE), page) is False

    def test_shared_flag_set_skips(self):
        from multiprocessing import Value
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        flag = Value('b', True, lock=True)
        assert check_chunk(key, page, shared_flag=flag) is False

    def test_no_shared_flag(self):
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        assert check_chunk(key, page) == key


# ── Tests: get_key_ passphrase mode ──

class TestGetKeyPassphrase:
    def test_finds_passphrase(self):
        passphrase = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        derived_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT,
                             hmac_hash_module=SHA512)
        page = _make_encrypted_page(derived_key, salt, page_num=0)
        candidates = [os.urandom(KEY_SIZE), passphrase]
        result, is_passphrase = get_key_(candidates, page)
        assert result == passphrase.hex()
        assert is_passphrase is True

    def test_raw_key_before_passphrase(self):
        """Raw key should match before passphrase (cheaper check first)."""
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        page = _make_encrypted_page(key, salt, page_num=0)
        # First candidate is valid as raw key — should stop there
        candidates = [key, os.urandom(KEY_SIZE)]
        result, is_passphrase = get_key_(candidates, page)
        assert result == key.hex()
        assert is_passphrase is False


# ── Tests: decrypt_db_file_v4 edge cases ──

class TestDecryptDbFileV4EdgeCases:
    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'empty.db')
            out_path = os.path.join(tmpdir, 'out.db')
            with open(in_path, 'wb') as f:
                pass
            result = decrypt_db_file_v4('00' * 32, in_path, out_path)
            assert result is False

    def test_file_smaller_than_page(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'small.db')
            out_path = os.path.join(tmpdir, 'out.db')
            with open(in_path, 'wb') as f:
                f.write(os.urandom(100))
            result = decrypt_db_file_v4(key.hex(), in_path, out_path)
            assert result is False

    def test_invalid_hex_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_path = os.path.join(tmpdir, 'out.db')
            with open(in_path, 'wb') as f:
                f.write(os.urandom(PAGE_SIZE))
            with pytest.raises((ValueError, Exception)):
                decrypt_db_file_v4('not-a-valid-hex-key', in_path, out_path)

    def test_requires_existing_output_dir(self):
        """decrypt_db_file_v4 does not create parent directories."""
        key = os.urandom(KEY_SIZE)
        salt = os.urandom(SALT_SIZE)
        key_hex = key.hex()

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_path = os.path.join(tmpdir, 'new_dir', 'test_dec.db')

            page = _make_encrypted_page(key, salt, page_num=0)
            with open(in_path, 'wb') as f:
                f.write(page)

            with pytest.raises(FileNotFoundError):
                decrypt_db_file_v4(key_hex, in_path, out_path)


# ── Tests: dump_session_info_v4 ──
#
# Patch targets are all in memoir.decrypt.session_v4 (where the function reads them):
#   - multiprocessing (module attribute) — avoids spawning a real worker subprocess
#   - open_process, get_wx_dir, regex_scan_keys, collect_db_salts, get_key,
#     CloseHandle, worker — all module-level names in session_v4
# data_dir uses literal backslashes because dump_session_info_v4 splits on '\\'.

_TEST_PID = 12345
_TEST_VERSION = '4.1.8.29'
# data_dir shape produced by get_wx_dir: "...\\xwechat_files\\<uid>\\db_storage\"
# Note: exactly ONE trailing backslash (matches real get_wx_dir YARA rule output).
# split('\\') on this yields [..., 'wxid_abc_def', 'db_storage', ''], so [-3] = 'wxid_abc_def'.
# Python raw strings cannot end with a single backslash, so concatenate explicitly.
_TEST_DB_STORAGE = r'C:\Users\x\xwechat_files\wxid_abc_def\db_storage' + '\\'
# After trim (drop last 2 segments) dump_session_info_v4 stores this as data_dir:
#   '\\'.join('...db_storage'.split('\\')[:-2]) -> '...xwechat_files\wxid_abc_def'
_TEST_TRIMMED_WX_DIR = r'C:\Users\x\xwechat_files\wxid_abc_def'
# uid is derived from segment -3 of the ORIGINAL data_dir, split on '_', dropping last part:
#   'wxid_abc_def' -> ['wxid', 'abc', 'def'] -> joined minus last -> 'wxid_abc'
_TEST_UID = 'wxid_abc'


class TestDumpSessionInfoV4:
    """Behavioral coverage of dump_session_info_v4 across all return paths."""

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=None)
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_open_process_returns_none_sets_404(
            self, mock_get_version, mock_open_process, mock_close_handle,
            mock_mp, mock_worker):
        """When open_process returns a falsy handle, the function short-circuits.

        Expected: key stays empty, errcode=404, version+pid still populated,
        and regex_scan_keys / get_wx_dir are NEVER called.
        """
        with mock.patch('memoir.decrypt.session_v4.regex_scan_keys') as mock_regex, \
             mock.patch('memoir.decrypt.session_v4.get_wx_dir') as mock_wxdir:
            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.pid == _TEST_PID
        assert result.version == _TEST_VERSION
        assert result.key == ''
        assert result.errcode == 404
        # Critical: did not proceed past the open_process guard
        mock_regex.assert_not_called()
        mock_wxdir.assert_not_called()
        # close_handle was NOT called on the None path (guard returns before CloseHandle)
        mock_close_handle.assert_not_called()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value='')
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_get_wx_dir_returns_empty_sets_404(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_close_handle, mock_mp, mock_worker):
        """When get_wx_dir returns '', CloseHandle is called and the function returns early.

        Expected: key='', errcode=404, regex_scan_keys not called.
        """
        with mock.patch('memoir.decrypt.session_v4.regex_scan_keys') as mock_regex:
            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.key == ''
        assert result.errcode == 404
        assert result.data_dir == ''
        mock_regex.assert_not_called()
        mock_close_handle.assert_called_once()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.regex_scan_keys')
    @mock.patch('memoir.decrypt.session_v4.collect_db_salts')
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value=_TEST_DB_STORAGE)
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_regex_scan_success_sets_key_map_and_uid(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_collect_salts, mock_regex, mock_close_handle,
            mock_mp, mock_worker):
        """When regex_scan_keys returns a salt->key map, key_map and key are populated.

        Expected: key_map built from collect_db_salts mapping, key set to any value,
        uid derived from data_dir backslash split, errcode=200, data_dir trimmed.
        """
        salt_hex = 'aa' * 16
        enc_key_hex = 'bb' * 32
        # Use forward-slash join for the mock value; dump_session_info_v4 passes
        # it to os.path.relpath which normalizes separators on the host OS.
        db_abs_path = _TEST_DB_STORAGE.rstrip('\\').replace('\\', '/') + '/contact/contact.db'
        mock_collect_salts.return_value = {salt_hex: db_abs_path}
        mock_regex.return_value = {salt_hex: enc_key_hex}

        result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.errcode == 200
        assert result.key == enc_key_hex
        assert len(result.key_map) == 1
        # rel_path key is computed via os.path.relpath(db_abs_path, trimmed_wx_dir)
        rel_keys = list(result.key_map.keys())
        assert any(k.endswith('contact.db') for k in rel_keys)
        assert result.key_map[rel_keys[0]] == enc_key_hex
        # uid derived from segment -3 of original data_dir ('wxid_abc_def') split on '_'
        assert result.uid == _TEST_UID
        # data_dir trimmed (last 2 segments dropped)
        assert result.data_dir == _TEST_TRIMMED_WX_DIR
        mock_close_handle.assert_called_once()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.get_key')
    @mock.patch('memoir.decrypt.session_v4.regex_scan_keys', return_value={})
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value=_TEST_DB_STORAGE)
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_yara_fallback_raw_key_success(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_regex, mock_get_key, mock_close_handle,
            mock_mp, mock_worker):
        """When regex_scan_keys returns {} and get_key finds a raw key, errcode=200.

        The YARA fallback needs to find at least one .db file under data_dir.
        Since data_dir is a Windows path that doesn't exist on Linux test hosts,
        we mock os.path.exists / os.path.getsize / open to simulate a real file.
        """
        raw_key_hex = 'cc' * 32
        mock_get_key.return_value = (raw_key_hex, False)  # is_passphrase=False

        with mock.patch('os.path.exists', return_value=True), \
             mock.patch('os.path.getsize', return_value=PAGE_SIZE), \
             mock.patch('builtins.open', mock.mock_open(read_data=b'\x00' * PAGE_SIZE)):
            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.errcode == 200
        assert result.key == raw_key_hex
        # Raw-key branch does not populate key_map
        assert result.key_map == {}
        mock_get_key.assert_called_once()
        mock_close_handle.assert_called_once()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.get_key')
    @mock.patch('memoir.decrypt.session_v4.collect_db_salts')
    @mock.patch('memoir.decrypt.session_v4.regex_scan_keys', return_value={})
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value=_TEST_DB_STORAGE)
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_yara_fallback_passphrase_derives_per_db_keys(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_regex, mock_collect_salts, mock_get_key, mock_close_handle,
            mock_mp, mock_worker):
        """When get_key returns (passphrase_hex, True), per-DB keys are derived via PBKDF2.

        Expected: errcode=200, key set to the passphrase hex, key_map populated
        with derived per-DB keys.
        """
        salt = bytes.fromhex('11' * 16)
        salt_hex = salt.hex()
        passphrase = bytes.fromhex('22' * 32)
        passphrase_hex = passphrase.hex()
        # collect_db_salts returns {salt_hex: db_path}; db_path is only used to
        # compute rel_path via os.path.relpath, so a forward-slash form works on Linux.
        db_abs_path = _TEST_DB_STORAGE.rstrip('\\').replace('\\', '/') + '/contact/contact.db'
        mock_collect_salts.return_value = {salt_hex: db_abs_path}
        mock_get_key.return_value = (passphrase_hex, True)

        # The YARA fallback needs to find a .db file; mock the file-discovery
        # calls since data_dir is a fake Windows path.
        with mock.patch('os.path.exists', return_value=True), \
             mock.patch('os.path.getsize', return_value=PAGE_SIZE), \
             mock.patch('builtins.open', mock.mock_open(read_data=b'\x00' * PAGE_SIZE)), \
             mock.patch('memoir.decrypt.session_v4.PBKDF2') as mock_pbkdf2:
            derived_key = bytes.fromhex('33' * 32)
            mock_pbkdf2.return_value = derived_key

            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.errcode == 200
        assert result.key == passphrase_hex
        assert len(result.key_map) == 1
        # Each value is the hex of the PBKDF2-derived key
        assert list(result.key_map.values())[0] == derived_key.hex()
        mock_close_handle.assert_called_once()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4.multiprocessing')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.get_key', return_value=(None, False))
    @mock.patch('memoir.decrypt.session_v4.regex_scan_keys', return_value={})
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value=_TEST_DB_STORAGE)
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_all_paths_fail_sets_404(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_regex, mock_get_key, mock_close_handle,
            mock_mp, mock_worker):
        """When regex_scan_keys returns {} and get_key returns (None, _), errcode=404.

        Note: get_key is only reached if a candidate DB file is found.
        We need os.path.exists / os.path.getsize / os.walk to find a file.
        Patching them to True ensures the YARA fallback path runs and get_key
        gets invoked.
        """
        with mock.patch('os.path.exists', return_value=True), \
             mock.patch('os.path.getsize', return_value=PAGE_SIZE), \
             mock.patch('os.walk', return_value=[(_TEST_DB_STORAGE, [], ['fake.db'])]), \
             mock.patch('builtins.open', mock.mock_open(read_data=b'\x00' * PAGE_SIZE)):
            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.errcode == 404
        assert result.key == ''
        mock_get_key.assert_called_once()
        mock_close_handle.assert_called_once()

    @mock.patch('memoir.decrypt.session_v4.worker')
    @mock.patch('memoir.decrypt.session_v4._CloseHandle')
    @mock.patch('memoir.decrypt.session_v4.get_wx_dir', return_value=_TEST_DB_STORAGE)
    @mock.patch('memoir.decrypt.session_v4.open_process', return_value=mock.MagicMock())
    @mock.patch('memoir.decrypt.session_v4.get_version', return_value=_TEST_VERSION)
    def test_nickname_queue_populated(
            self, mock_get_version, mock_open_process, mock_wxdir,
            mock_close_handle, mock_worker):
        """When the multiprocessing worker puts nickname info on the queue,
        nick_name/phone/account_name are read into the SessionInfo.

        We stub the real multiprocessing module with a fake that delivers a
        pre-populated queue synchronously, so worker() need not actually run.
        regex_scan_keys / collect_db_salts are patched via context managers to
        avoid decorator parameter-ordering pitfalls.
        """
        salt_hex = 'aa' * 16
        enc_key_hex = 'bb' * 32
        db_abs_path = _TEST_DB_STORAGE.rstrip('\\').replace('\\', '/') + '/contact/contact.db'

        nickname_payload = {
            'nick_name': 'TestUser',
            'phone': '13800000000',
            'account_name': 'test_user',
        }

        class _FakeQueue:
            def __init__(self):
                self._items = [nickname_payload]

            def empty(self):
                return not self._items

            def get(self):
                return self._items.pop(0)

        class _FakeProcess:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def join(self):
                pass

        fake_mp = mock.MagicMock()
        fake_mp.Queue = _FakeQueue
        fake_mp.Process = _FakeProcess

        with mock.patch('memoir.decrypt.session_v4.regex_scan_keys',
                        return_value={salt_hex: enc_key_hex}), \
             mock.patch('memoir.decrypt.session_v4.collect_db_salts',
                        return_value={salt_hex: db_abs_path}), \
             mock.patch('memoir.decrypt.session_v4.multiprocessing', fake_mp):
            result = dump_session_info_v4(_TEST_PID)

        assert result is not None
        assert result.errcode == 200
        assert result.nick_name == 'TestUser'
        assert result.phone == '13800000000'
        assert result.account_name == 'test_user'
        assert result.key == enc_key_hex
