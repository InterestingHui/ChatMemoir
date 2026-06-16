"""Unit tests for memoir.decrypt.decrypt_v3 — v3 SQLite decryption logic.

Tests cover pure crypto functions: decrypt_db_file_v3, decrypt_db_files.
Windows-specific ProcessPoolExecutor is mocked to test sequentially.
"""

import hashlib
import hmac
import os
import stat
import sys
import tempfile
import types
from unittest import mock

import pytest

# Mock Windows-only modules
if 'ctypes.windll' not in sys.modules:
    import ctypes as _ctypes
    _mw = types.ModuleType('ctypes.windll')
    _mw.kernel32 = _ctypes.WinDLL('kernel32') if hasattr(_ctypes, 'WinDLL') else mock.MagicMock()
    _mw.shell32 = mock.MagicMock()
    sys.modules['ctypes.windll'] = _mw

from Crypto.Cipher import AES

from memoir.decrypt.decrypt_v3 import (
    decrypt_db_file_v3,
    decrypt_db_files,
    KEY_SIZE,
    DEFAULT_PAGESIZE,
    DEFAULT_ITER,
    SQLITE_FILE_HEADER,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_encrypted_db_v3(key: bytes, salt: bytes = None, num_pages: int = 1):
    """Create a minimal encrypted SQLite database v3-style.

    Page layout: [salt(16)] [data] [IV(16)] [HMAC(20)] [padding(12)]
    Subsequent pages: [data] [IV(16)] [HMAC(20)] [padding(12)]
    """
    if salt is None:
        salt = os.urandom(16)

    byteKey = hashlib.pbkdf2_hmac("sha1", key, salt, DEFAULT_ITER, KEY_SIZE)
    mac_salt = bytes([salt[i] ^ 58 for i in range(16)])
    mac_key = hashlib.pbkdf2_hmac("sha1", byteKey, mac_salt, 2, KEY_SIZE)

    PAGE = DEFAULT_PAGESIZE
    full = bytearray()

    for page_num in range(num_pages):
        page = bytearray(PAGE)
        if page_num == 0:
            page[:16] = salt

        # Random plaintext
        data_offset = 16 if page_num == 0 else 0
        data_size = PAGE - 48 - data_offset
        plaintext = os.urandom(data_size)

        iv = os.urandom(16)
        cipher = AES.new(byteKey, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(plaintext)

        page[data_offset:data_offset + len(encrypted)] = encrypted
        page[PAGE - 48:PAGE - 32] = iv

        # HMAC over data portion before IV
        hmac_input = bytes(page[:PAGE - 48 + 16])
        hash_mac = hmac.new(mac_key, hmac_input, hashlib.sha1)
        if page_num == 0:
            hash_mac.update(b'\x01\x00\x00\x00')
        else:
            hash_mac.update(struct.pack('<I', page_num + 1))  # noqa: F821
        page[PAGE - 32:PAGE - 12] = hash_mac.digest()

        full.extend(page)

    return bytes(full)


import struct as _struct


def _make_encrypted_db_v3_correct_hmac(key: bytes, salt: bytes = None, num_pages: int = 1):
    """Create encrypted v3 DB with correct HMAC that matches decrypt_db_file_v3 logic."""
    if salt is None:
        salt = os.urandom(16)

    byteKey = hashlib.pbkdf2_hmac("sha1", key, salt, DEFAULT_ITER, KEY_SIZE)
    mac_salt = bytes([salt[i] ^ 58 for i in range(16)])
    mac_key = hashlib.pbkdf2_hmac("sha1", byteKey, mac_salt, 2, KEY_SIZE)

    PAGE = DEFAULT_PAGESIZE
    full = bytearray()

    for page_num in range(num_pages):
        page = bytearray(PAGE)
        if page_num == 0:
            page[:16] = salt

        data_offset = 16 if page_num == 0 else 0
        data_size = PAGE - 48 - data_offset
        plaintext = os.urandom(data_size)

        iv = os.urandom(16)
        cipher = AES.new(byteKey, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(plaintext)

        page[data_offset:data_offset + len(encrypted)] = encrypted
        # IV at page_size - 48
        page[PAGE - 48:PAGE - 32] = iv

        # HMAC covers first bytes up to IV (page_size - 48)
        # and excludes the last 32 bytes (IV + HMAC) — but includes IV
        # decrypt_db_file_v3 uses: first[:-32] where first = page[16:page_size]
        # first is the page data excluding the 16-byte salt
        # So for page 0: hash over page[16:PAGE-32]
        if page_num == 0:
            hmac_data = bytes(page[16:PAGE - 32])
        else:
            hmac_data = bytes(page[:PAGE - 32])

        hash_mac = hmac.new(mac_key, hmac_data, hashlib.sha1)
        hash_mac.update(b'\x01\x00\x00\x00')

        page[PAGE - 32:PAGE - 12] = hash_mac.digest()

        full.extend(page)

    return bytes(full)


# ── Tests: decrypt_db_file_v3 ────────────────────────────────


class TestDecryptDbFileV3:
    def test_decrypt_valid_file(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_dir = os.path.join(tmpdir, 'out')
            os.makedirs(out_dir)
            out_path = os.path.join(out_dir, 'test.db')

            db = _make_encrypted_db_v3_correct_hmac(key, num_pages=1)
            with open(in_path, 'wb') as f:
                f.write(db)

            success, result = decrypt_db_file_v3(key.hex(), in_path, out_path)
            assert success is True
            assert os.path.exists(out_path)

            with open(out_path, 'rb') as f:
                content = f.read()
            assert content[:len(SQLITE_FILE_HEADER)] == SQLITE_FILE_HEADER.encode()

    def test_nonexistent_input(self):
        result, msg = decrypt_db_file_v3('00' * 32, '/nonexistent/path.db', '/tmp/out.db')
        assert result is False
        assert 'not found' in msg

    def test_nonexistent_output_dir(self):
        result, msg = decrypt_db_file_v3('00' * 32, __file__, '/nonexistent/out.db')
        assert result is False

    def test_invalid_key_length(self):
        result, msg = decrypt_db_file_v3('too_short', __file__, '/tmp/out.db')
        assert result is False
        assert 'Len Error' in msg

    def test_wrong_key_fails(self):
        key = os.urandom(KEY_SIZE)
        wrong_key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_dir = os.path.join(tmpdir, 'out')
            os.makedirs(out_dir)
            out_path = os.path.join(out_dir, 'test.db')

            db = _make_encrypted_db_v3_correct_hmac(key, num_pages=1)
            with open(in_path, 'wb') as f:
                f.write(db)

            success, msg = decrypt_db_file_v3(wrong_key.hex(), in_path, out_path)
            assert success is False
            assert 'Key Error' in msg

    def test_multi_page_file(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, 'test.db')
            out_dir = os.path.join(tmpdir, 'out')
            os.makedirs(out_dir)
            out_path = os.path.join(out_dir, 'test.db')

            db = _make_encrypted_db_v3_correct_hmac(key, num_pages=3)
            with open(in_path, 'wb') as f:
                f.write(db)

            success, result = decrypt_db_file_v3(key.hex(), in_path, out_path)
            assert success is True
            assert os.path.exists(out_path)


# ── Tests: decrypt_db_files ──────────────────────────────────


class TestDecryptDbFiles:
    def test_nonexistent_src_dir(self):
        """Should not raise, just log and return None."""
        result = decrypt_db_files('00' * 32, '/nonexistent/src', '/tmp/dest')
        assert result is None

    def test_creates_dest_dir(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src')
            dest = os.path.join(tmpdir, 'dest')
            os.makedirs(src)

            db = _make_encrypted_db_v3_correct_hmac(key, num_pages=1)
            with open(os.path.join(src, 'msg.db'), 'wb') as f:
                f.write(db)

            decrypt_db_files(key.hex(), src, dest, skip_existing=False)
            assert os.path.isdir(dest)

    def test_skip_non_db_files(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src')
            dest = os.path.join(tmpdir, 'dest')
            os.makedirs(src)

            with open(os.path.join(src, 'data.txt'), 'wb') as f:
                f.write(os.urandom(100))

            decrypt_db_files(key.hex(), src, dest, skip_existing=False)
            # No .db files, should not create anything
            assert not os.path.exists(os.path.join(dest, 'data.txt'))

    def test_skip_existing_up_to_date(self):
        key = os.urandom(KEY_SIZE)
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src')
            dest = os.path.join(tmpdir, 'dest')
            os.makedirs(src)
            os.makedirs(dest)

            db = _make_encrypted_db_v3_correct_hmac(key, num_pages=1)
            src_file = os.path.join(src, 'test.db')
            with open(src_file, 'wb') as f:
                f.write(db)

            # Create dest file with newer mtime
            dest_file = os.path.join(dest, 'test.db')
            with open(dest_file, 'wb') as f:
                f.write(b'existing')
            # Touch dest to be newer
            os.utime(dest_file, (os.path.getmtime(src_file) + 100,
                                 os.path.getmtime(src_file) + 100))

            # Mock ProcessPoolExecutor to avoid multiprocessing in test
            with mock.patch('memoir.decrypt.decrypt_v3.ProcessPoolExecutor') as mock_pool:
                decrypt_db_files(key.hex(), src, dest, skip_existing=True)
                # Should skip — executor should not be called
                mock_pool.assert_not_called()
