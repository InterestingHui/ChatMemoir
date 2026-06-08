#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/1/10 2:36
@Author      : SiYuan
@Email       : 863909694@qq.com
@File        : memoir-session_info_v4.py
@Description : 部分思路参考：https://github.com/0xlane/wechat-dump-rs
"""

import ctypes
import multiprocessing
import os.path

import hmac
import os
import struct
import time
from ctypes import wintypes
from multiprocessing import freeze_support

import pymem
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512
import yara
import re
import logging

from memoir.decrypt.common import SessionInfo
from memoir.decrypt.common import get_version

# 定义必要的常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000

# Constants
IV_SIZE = 16
HMAC_SHA256_SIZE = 64
HMAC_SHA512_SIZE = 64
KEY_SIZE = 32
AES_BLOCK_SIZE = 16
ROUND_COUNT = 256000
PAGE_SIZE = 4096
SALT_SIZE = 16

logger = logging.getLogger(__name__)


# 定义 MEMORY_BASIC_INFORMATION 结构
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


# Windows API Constants
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

# Load Windows DLLs with proper type annotations
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


def open_process(pid):
    return OpenProcess(PROCESS_ALL_ACCESS, False, pid)


# 读取目标进程内存
def read_process_memory(process_handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    success = ReadProcessMemory(
        process_handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read)
    )
    if not success:
        return None
    return buffer.raw


# 获取所有内存区域
def get_memory_regions(process_handle):
    regions = []
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    while kernel32.VirtualQueryEx(
            process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
    ):
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE:
            regions.append((mbi.BaseAddress, mbi.RegionSize))
        address += mbi.RegionSize
    return regions


rules_v4 = r'''
rule GetDataDir {
    strings:
        $a = /[a-zA-Z]:\\(.{1,100}?\\){0,1}?xwechat_files\\[0-9a-zA-Z_-]{6,24}?\\db_storage\\/
    condition:
        $a
}

rule GetPhoneNumberOffset {
    strings:
        $a = /[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}/
    condition:
        $a
}
rule GetKeyAddrStub
{
    strings:
        $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
    condition:
        all of them
}
'''


def read_string(data: bytes, offset, size):
    try:
        return data[offset:offset + size].decode('utf-8')
    except (UnicodeDecodeError, IndexError):
        return ''


def read_num(data: bytes, offset, size):
    # 构建格式字符串，根据 size 来选择相应的格式
    if size == 1:
        fmt = '<B'  # 1 字节，unsigned char
    elif size == 2:
        fmt = '<H'  # 2 字节，unsigned short
    elif size == 4:
        fmt = '<I'  # 4 字节，unsigned int
    elif size == 8:
        fmt = '<Q'  # 8 字节，unsigned long long
    else:
        raise ValueError("Unsupported size")

    # 使用 struct.unpack 从指定 offset 开始读取 size 字节的数据并转换为数字
    result = struct.unpack_from(fmt, data, offset)[0]  # 通过 unpack_from 来读取指定偏移的数据
    return result


def read_bytes(data: bytes, offset, size):
    return data[offset:offset + size]


# def read_bytes_from_pid(pid, offset, size):
#     with open(f'/proc/{pid}/mem', 'rb') as mem_file:
#         mem_file.seek(offset)
#         return mem_file.read(size)


def read_bytes_from_pid(pid: int, addr: int, size: int):
    hprocess = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not hprocess:
        raise OSError(f"Failed to open process with PID {pid}")
    try:
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        success = ReadProcessMemory(hprocess, addr, buffer, size, ctypes.byref(bytes_read))
        if not success:
            return b''
        return bytes(buffer)
    finally:
        CloseHandle(hprocess)


def read_string_from_pid(pid: int, addr: int, size: int):
    bytes0 = read_bytes_from_pid(pid, addr, size)
    try:
        return bytes0.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        return ''


def is_ok(enc_key, buf, shared_flag=None):
    if shared_flag is not None and shared_flag.value:
        return False
    # 获取文件开头的 salt
    salt = buf[:SALT_SIZE]
    # salt 异或 0x3a 得到 mac_salt，用于计算 HMAC
    mac_salt = bytes(x ^ 0x3a for x in salt)
    # enc_key is the derived key from memory — use directly, only derive mac_key
    mac_key = PBKDF2(enc_key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)
    # 计算 hash 校验码的保留空间
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE
    # 校验 HMAC
    start = SALT_SIZE
    end = PAGE_SIZE
    mac = hmac.new(mac_key, buf[start:end - reserve + IV_SIZE], SHA512)
    mac.update(struct.pack('<I', 1))  # page number as 1
    hash_mac = mac.digest()
    # 校验 HMAC 是否一致
    hash_mac_start_offset = end - reserve + IV_SIZE
    hash_mac_end_offset = hash_mac_start_offset + len(hash_mac)
    if hash_mac == buf[hash_mac_start_offset:hash_mac_end_offset]:
        print(f"[v] found key at 0x{start:x}")
        if shared_flag is not None:
            with shared_flag.get_lock():
                shared_flag.value = True
        return True
    return False


def check_chunk(chunk, buf, shared_flag=None):
    if shared_flag is not None and shared_flag.value:
        return False
    if is_ok(chunk, buf, shared_flag):
        return chunk
    return False


def verify_key(key: bytes, buffer: bytes, flag, result):
    if len(key) != 32:
        return False
    if flag.value:  # 如果其他进程已找到结果，提前退出
        return False
    if is_ok(key, buffer):  # 替换为实际的目标检测条件
        print("Key found!", key)
        with flag.get_lock():  # 保证线程安全
            flag.value = True
            return key
    else:
        return False


def is_ok_passphrase(passphrase, buf):
    """WeChat 4.1.x: passphrase → PBKDF2(256000) → derived key → HMAC verify."""
    salt = buf[:SALT_SIZE]
    derived_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
    return is_ok(derived_key, buf)


def get_key_(keys, buf):
    # Sequential verification — avoids multiprocessing.Value serialization
    # crash on Windows/Python 3.14 (Synchronized objects not picklable via Pool.starmap).
    # Each PBKDF2 check is ~0.5s; YARA typically produces <20 candidates.
    logger.info(f"[get_key_] Verifying {len(keys)} YARA candidate keys sequentially")
    for i, key in enumerate(keys):
        # Try as raw derived key (WeChat 4.0.x)
        if is_ok(key, buf):
            logger.info(f"[get_key_] Key verified at candidate #{i+1} (raw derived key)")
            return bytes.hex(key), False
        # Try as passphrase (WeChat 4.1.x) — expensive PBKDF2 derivation
        if is_ok_passphrase(key, buf):
            logger.info(f"[get_key_] Key verified at candidate #{i+1} (passphrase, 4.1.x format)")
            return bytes.hex(key), True
    logger.warning("[get_key_] No YARA candidate key passed verification (tried raw and passphrase modes)")
    return None, False


def collect_db_salts(data_dir):
    """Read the first 16 bytes (salt) from each .db file under data_dir."""
    salt_to_path = {}
    if not data_dir or not os.path.isdir(data_dir):
        return salt_to_path
    for root, dirs, files in os.walk(data_dir):
        for fname in files:
            if fname.endswith('.db'):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'rb') as f:
                        salt = f.read(SALT_SIZE)
                    if salt and len(salt) == SALT_SIZE:
                        salt_to_path[salt.hex()] = fpath
                except (OSError, IOError):
                    continue
    logger.info(f"[collect_db_salts] Found {len(salt_to_path)} .db files with valid salts under {data_dir}")
    return salt_to_path


def _verify_key_stdlib(key: bytes, buf: bytes) -> bool:
    """Verify enc_key (already-derived) against a DB page using HMAC-SHA512.
    WCDB caches the derived key in memory — no 256000-iteration PBKDF2 needed.
    Only the 2-iteration mac_key derivation is applied (same as lane2077/wechat-decrypt)."""
    import hashlib
    salt = buf[:SALT_SIZE]
    mac_salt = bytes(x ^ 0x3a for x in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', key, mac_salt, 2, dklen=KEY_SIZE)
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE
    start = SALT_SIZE
    end = PAGE_SIZE
    mac = hmac.new(mac_key, buf[start:end - reserve + IV_SIZE], hashlib.sha512)
    mac.update(struct.pack('<I', 1))
    hash_mac = mac.digest()
    hash_mac_start_offset = end - reserve + IV_SIZE
    hash_mac_end_offset = hash_mac_start_offset + len(hash_mac)
    return hash_mac == buf[hash_mac_start_offset:hash_mac_end_offset]


def regex_scan_keys(pid, process_handle, data_dir):
    """
    Scan process memory for WCDB hex key cache patterns.
    Each database has an independent enc_key cached as x'<enc_key64><salt32>'.
    Returns dict: salt_hex -> enc_key_hex (ALL verified keys, with cross-validation).
    """
    import re as _re
    hex_re = _re.compile(b"x'([0-9a-fA-F]{64,192})'")

    # Step A: Collect salt-to-DB-file mapping from disk
    salt_to_path = collect_db_salts(data_dir)
    if not salt_to_path:
        logger.warning("[regex_scan_keys] No .db files found with valid salts, cannot verify keys")
        return {}

    # Pre-load page1 for each DB (needed for verification and cross-validation)
    salt_to_page1 = {}
    for salt_hex, db_path in salt_to_path.items():
        try:
            with open(db_path, 'rb') as f:
                page1 = f.read(PAGE_SIZE)
            if len(page1) >= PAGE_SIZE:
                salt_to_page1[salt_hex] = page1
        except Exception:
            continue

    # Step B: Scan process memory regions for hex patterns
    process_infos = get_memory_regions(process_handle)
    candidates = []

    logger.info(f"[regex_scan_keys] Scanning {len(process_infos)} memory regions for WCDB hex patterns")
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        if not memory:
            continue
        for match in hex_re.finditer(memory):
            hex_str = match.group(1).decode('ascii', errors='ignore')
            if len(hex_str) == 96:
                # Standard: x'<enc_key64><salt32>'
                enc_key_hex = hex_str[:64]
                salt_hex = hex_str[64:]
                if salt_hex in salt_to_path:
                    candidates.append((enc_key_hex, salt_hex, '96-key+salt'))
            elif len(hex_str) == 64:
                # Key only, no salt — try against all DBs
                enc_key_hex = hex_str
                for salt_hex in salt_to_page1:
                    candidates.append((enc_key_hex, salt_hex, '64-key-only'))
            elif len(hex_str) > 96 and len(hex_str) % 2 == 0:
                # Extended format: take first 64 as enc_key, last 32 as salt
                enc_key_hex = hex_str[:64]
                salt_hex = hex_str[-32:]
                if salt_hex in salt_to_path:
                    candidates.append((enc_key_hex, salt_hex, f'{len(hex_str)}-extended'))

    logger.info(f"[regex_scan_keys] Found {len(candidates)} candidate key+salt pairs")

    if not candidates:
        return {}

    # Step C: Verify candidates — build salt -> enc_key map
    key_map = {}  # salt_hex -> enc_key_hex
    checked = set()
    for enc_key_hex, salt_hex, mode in candidates:
        check = (enc_key_hex, salt_hex)
        if check in checked or salt_hex in key_map:
            continue
        checked.add(check)
        page1 = salt_to_page1.get(salt_hex)
        if not page1:
            continue
        try:
            enc_key = bytes.fromhex(enc_key_hex)
            if _verify_key_stdlib(enc_key, page1):
                key_map[salt_hex] = enc_key_hex
                logger.info(f"[regex_scan_keys] Verified key for salt={salt_hex[:16]}... ({mode})")
        except Exception:
            continue

    logger.info(f"[regex_scan_keys] Direct match: {len(key_map)}/{len(salt_to_path)} databases")

    # Step D: Cross-validation — try known enc_keys against unmatched databases
    missing_salts = set(salt_to_page1.keys()) - set(key_map.keys())
    if missing_salts and key_map:
        logger.info(f"[regex_scan_keys] Cross-validating {len(missing_salts)} unmatched databases")
        known_keys = list(set(key_map.values()))  # unique enc_keys
        for salt_hex in list(missing_salts):
            page1 = salt_to_page1[salt_hex]
            for enc_key_hex in known_keys:
                try:
                    enc_key = bytes.fromhex(enc_key_hex)
                    if _verify_key_stdlib(enc_key, page1):
                        key_map[salt_hex] = enc_key_hex
                        missing_salts.discard(salt_hex)
                        logger.info(f"[regex_scan_keys] Cross-validated key for salt={salt_hex[:16]}...")
                        break
                except Exception:
                    continue

    if missing_salts:
        logger.warning(f"[regex_scan_keys] {len(missing_salts)} databases still without keys")
    else:
        logger.info(f"[regex_scan_keys] All {len(key_map)} databases have keys")

    return key_map


def get_key_inner(pid, process_infos):
    """
    扫描可能为key的内存
    :param pid:
    :param process_infos:
    :return:
    """
    process_handle = open_process(pid)
    rules_v4_key = r'''
        rule GetKeyAddrStub
        {
            strings:
                $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
            condition:
                all of them
        }
        '''
    rules = yara.compile(source=rules_v4_key)
    pre_addresses = []
    keys = []
    key_set = set()
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        # 定义目标数据（如内存或文件内容）
        target_data = memory  # 二进制数据
        if not memory:
            continue
        # 加上这些判断条件时灵时不灵
        # if b'-----BEGIN PUBLIC KEY-----' not in target_data or b'USER_KEYINFO' not in target_data:
        #     continue
        # if b'db_storage' not in memory:
        #     continue
        # with open(f'key-{base_address}.bin', 'wb') as f:
        #     f.write(target_data)
        matches = rules.match(data=target_data)
        if matches:
            for match in matches:
                rule_name = match.rule
                if rule_name == 'GetKeyAddrStub':
                    for string in match.strings:
                        instance = string.instances[0]
                        offset, content = instance.offset, instance.matched_data
                        # Method 1: read 8-byte pointer from match → read 32 bytes at address (4.0.x)
                        addr = read_num(target_data, offset, 8)
                        if addr:
                            pre_addresses.append(addr)
                        # Method 2: read 32 bytes directly from match offset (4.1.x passphrase inline)
                        if offset + KEY_SIZE <= len(target_data):
                            inline_key = target_data[offset:offset + KEY_SIZE]
                            if inline_key not in key_set and len(inline_key) == KEY_SIZE:
                                keys.append(inline_key)
                                key_set.add(inline_key)
                        # Method 3: read 32 bytes from wide range around match (passphrase may be far from anchor)
                        for delta in range(-256, 257, 8):
                            pos = offset + delta
                            if 0 <= pos and pos + KEY_SIZE <= len(target_data):
                                near_key = target_data[pos:pos + KEY_SIZE]
                                if near_key not in key_set and len(near_key) == KEY_SIZE:
                                    # Quick filter: skip low-entropy (all zeros, all FFs, repeating)
                                    if near_key == b'\x00' * KEY_SIZE:
                                        continue
                                    if len(set(near_key)) <= 3:
                                        continue
                                    keys.append(near_key)
                                    key_set.add(near_key)
    logger.info(f"[get_key_inner] Found {len(pre_addresses)} pointer candidates and {len(keys)} inline candidates from YARA")
    for pre_address in pre_addresses:
        if any([base_address <= pre_address <= base_address + region_size - KEY_SIZE for base_address, region_size in
                process_infos]):
            key = read_bytes_from_pid(pid, pre_address, 32)
            if key not in key_set:
                keys.append(key)
                key_set.add(key)
    logger.info(f"[get_key_inner] Collected {len(keys)} unique candidate keys")
    return keys


def get_key(pid, process_handle, buf):
    """Scans process memory for WCDB encryption key or passphrase.
    Returns (key_hex, is_passphrase) or (None, False)."""
    process_infos = get_memory_regions(process_handle)

    def split_list(lst, n):
        k, m = divmod(len(lst), n)
        return (lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n))

    keys = []
    pool = multiprocessing.Pool(processes=multiprocessing.cpu_count() // 2)
    results = pool.starmap(get_key_inner, ((pid, process_info_) for process_info_ in
                                           split_list(process_infos, min(len(process_infos), 40))))
    pool.close()
    pool.join()
    for r in results:
        if r:
            keys += r
    return get_key_(keys, buf)


def get_wx_dir(process_handle):
    rules_v4_dir = r'''
    rule GetDataDir {
        strings:
            $a = /[a-zA-Z]:\\(.{1,100}?\\)*?xwechat_files\\[0-9a-zA-Z_-]{6,24}?\\db_storage\\/
        condition:
            $a
    }
    '''
    rules = yara.compile(source=rules_v4_dir)
    process_infos = get_memory_regions(process_handle)
    data_dir_cnt = {}
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        # 定义目标数据（如内存或文件内容）
        target_data = memory  # 二进制数据
        if not memory:
            continue
        if b'db_storage' not in memory:
            continue
        matches = rules.match(data=target_data)
        if matches:
            # 输出匹配结果
            for match in matches:
                rule_name = match.rule
                if rule_name == 'GetDataDir':
                    for string in match.strings:
                        content = string.instances[0].matched_data
                        data_dir_cnt[content] = data_dir_cnt.get(content, 0) + 1
    return max(data_dir_cnt, key=data_dir_cnt.get).decode('utf-8') if data_dir_cnt else ''


def get_nickname(pid):
    process_handle = open_process(pid)
    if not process_handle:
        print(f"无法打开进程 {pid}")
        return {}
    try:
        process_infos = get_memory_regions(process_handle)
        # 加载规则
        r'''$a = /(.{16}[\x00-\x20]\x00{7}(\x0f|\x1f)\x00{7}){2}.{16}[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}.{25}\x00{7}(\x3f|\x2f|\x1f|\x0f)\x00{7}/s'''
        rules_v4_phone = r'''
        rule GetPhoneNumberOffset {
            strings:
                $a = /[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}/
            condition:
                $a
        }
        '''
        nick_name = ''
        phone = ''
        account_name = ''
        rules = yara.compile(source=rules_v4_phone)
        for base_address, region_size in process_infos:
            memory = read_process_memory(process_handle, base_address, region_size)
            # 定义目标数据（如内存或文件内容）
            target_data = memory  # 二进制数据
            if not memory:
                continue
            # if not (b'db_storage' in target_data or b'USER_KEYINFO' in target_data):
            #     continue
            # if not (b'-----BEGIN PUBLIC KEY-----' in target_data):
            #     continue
            matches = rules.match(data=target_data)
            if matches:
                # 输出匹配结果
                for match in matches:
                    rule_name = match.rule
                    if rule_name == 'GetPhoneNumberOffset':
                        for string in match.strings:
                            instance = string.instances[0]
                            offset, content = instance.offset, instance.matched_data
                            phone_addr = offset + 0x10
                            phone = read_string(target_data, phone_addr, 11)

                            # 提取前 8 个字节
                            data_slice = target_data[offset:offset + 8]
                            # 使用 struct.unpack() 将字节转换为 u64，'<Q' 表示小端字节序的 8 字节无符号整数
                            nick_name_length = struct.unpack('<Q', data_slice)[0]
                            # print('nick_name_length', nick_name_length)
                            nick_name = read_string(target_data, phone_addr - 0x20, nick_name_length)
                            a = target_data[phone_addr - 0x60:phone_addr + 0x50]
                            account_name_length = read_num(target_data, phone_addr - 0x30, 8)
                            # print('account_name_length', account_name_length)
                            account_name = read_string(target_data, phone_addr - 0x40, account_name_length)
                            # with open('a.bin', 'wb') as f:
                            #     f.write(target_data)
                            if not account_name:
                                addr = read_num(target_data, phone_addr - 0x40, 8)
                                # print(hex(addr))
                                account_name = read_string_from_pid(pid, addr, account_name_length)
        return {
            'nick_name': nick_name,
            'phone': phone,
            'account_name': account_name
        }
    finally:
        CloseHandle(process_handle)


def worker(pid, queue):
    nickname_dic = get_nickname(pid)
    queue.put(nickname_dic)


def dump_session_info_v4(pid) -> SessionInfo | None:
    session_info = SessionInfo()
    session_info.pid = pid
    session_info.version = get_version(pid)
    logger.info(f"[dump_session_info_v4] Starting extraction for WeChat {session_info.version}, PID={pid}")

    process_handle = open_process(pid)
    if not process_handle:
        logger.error(f"[dump_session_info_v4] Cannot open process {pid}")
        print(f"Cannot open WeChat process (PID {pid}). Please run as administrator.")
        return session_info

    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=worker, args=(pid, queue))
    process.start()

    session_info.data_dir = get_wx_dir(process_handle)
    if not session_info.data_dir:
        logger.error("[dump_session_info_v4] Could not find WeChat data directory")
        CloseHandle(process_handle)
        process.join()
        return session_info

    # Try regex-based WCDB hex scan first (more robust across versions).
    # NOTE: data_dir already ends with db_storage\ from get_wx_dir, so pass it directly.
    db_storage_dir = session_info.data_dir  # save before data_dir gets trimmed
    salt_key_map = regex_scan_keys(pid, process_handle, session_info.data_dir)  # salt_hex -> enc_key_hex

    if salt_key_map:
        # Build per-file key map: relative_path -> enc_key_hex
        # Use the TRIMMED data_dir (parent of db_storage) as base, since that's what decrypt uses.
        trimmed_wx_dir = '\\'.join(db_storage_dir.rstrip('\\').split('\\')[:-1])
        salt_to_path = collect_db_salts(db_storage_dir)
        for salt_hex, enc_key_hex in salt_key_map.items():
            if salt_hex in salt_to_path:
                db_path = salt_to_path[salt_hex]
                rel_path = os.path.relpath(db_path, trimmed_wx_dir)
                session_info.key_map[rel_path] = enc_key_hex
        # Set legacy key field to any found key
        session_info.key = next(iter(salt_key_map.values()))
        logger.info(f"[dump_session_info_v4] Found keys for {len(session_info.key_map)} databases via regex scan")
    else:
        # Fall back to YARA-based extraction
        logger.info("[dump_session_info_v4] Regex scan found no keys, falling back to YARA")
        # Find a valid DB file for YARA verification
        db_file_path = ''
        for candidate in ['favorite/favorite_fts.db', 'head_image/head_image.db', 'session/session.db', 'contact/contact.db', 'message/message_0.db']:
            candidate_path = os.path.join(session_info.data_dir, candidate)
            if os.path.exists(candidate_path) and os.path.getsize(candidate_path) >= PAGE_SIZE:
                db_file_path = candidate_path
                break
        if not db_file_path:
            for root, dirs, files in os.walk(session_info.data_dir):
                for fname in files:
                    if fname.endswith('.db'):
                        fpath = os.path.join(root, fname)
                        if os.path.getsize(fpath) >= PAGE_SIZE:
                            db_file_path = fpath
                            break
                if db_file_path:
                    break
        if db_file_path:
            logger.info(f"[dump_session_info_v4] Using {db_file_path} for YARA verification")
            with open(db_file_path, 'rb') as f:
                buf = f.read()
            key_hex, is_passphrase = get_key(pid, process_handle, buf)
            if key_hex:
                session_info.key = key_hex
                if is_passphrase:
                    logger.info("[dump_session_info_v4] Passphrase found, deriving per-DB keys")
                    passphrase = bytes.fromhex(key_hex)
                    db_storage = session_info.data_dir
                    trimmed_wx_dir = '\\'.join(db_storage.rstrip('\\').split('\\')[:-1])
                    salt_to_path = collect_db_salts(db_storage)
                    for salt_hex, db_path in salt_to_path.items():
                        salt = bytes.fromhex(salt_hex)
                        derived_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
                        rel_path = os.path.relpath(db_path, trimmed_wx_dir)
                        session_info.key_map[rel_path] = derived_key.hex()
                    logger.info(f"[dump_session_info_v4] Derived keys for {len(session_info.key_map)} databases")
                else:
                    logger.info("[dump_session_info_v4] Raw key found via YARA fallback")
        else:
            logger.error("[dump_session_info_v4] No .db file found for YARA verification")

    CloseHandle(process_handle)
    session_info.uid = '_'.join(session_info.data_dir.split('\\')[-3].split('_')[0:-1])
    session_info.data_dir = '\\'.join(session_info.data_dir.split('\\')[:-2])
    process.join()
    if not queue.empty():
        nickname_info = queue.get()
        session_info.nick_name = nickname_info.get('nick_name', '')
        session_info.phone = nickname_info.get('phone', '')
        session_info.account_name = nickname_info.get('account_name', '')
    if not session_info.key:
        session_info.errcode = 404
        logger.error(f"[dump_session_info_v4] Key extraction FAILED for WeChat {session_info.version}")
        print(f"Key extraction failed. WeChat version: {session_info.version}")
        print("Please ensure WeChat is running and logged in.")
        print(f"Data directory: {session_info.data_dir}")
    else:
        session_info.errcode = 200
        logger.info(f"[dump_session_info_v4] Key extraction succeeded")
    return session_info


if __name__ == '__main__':
    freeze_support()
    st = time.time()
    pm = pymem.Pymem("Weixin.exe")
    pid = pm.process_id
    w = dump_session_info_v4(pid)
    print(w)
    et = time.time()
    print(et - st)
