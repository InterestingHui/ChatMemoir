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
