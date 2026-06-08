#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/1/10 2:36
@Author      : SiYuan
@Email       : 863909694@qq.com
@File        : memoir-session_legacy.py
@Description :
"""

import ctypes
import multiprocessing
import os.path

import hmac
import os
import struct
import sys
import time
import traceback
from ctypes import wintypes
from multiprocessing import freeze_support
from typing import Set, Tuple

import pymem
import win32api
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512
import psutil
import yara
import re
import logging

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


class SessionInfo:
    def __init__(self):
        self.pid = 0
        self.version = '0.0.0.0'
        self.account_name = ''
        self.nick_name = ''
        self.phone = ''
        self.data_dir = ''
        self.key = ''
        self.uid = ''

    def __str__(self):
        return f'''
pid:          {self.pid}
version:      {self.version}
account_name: {self.account_name}
nickname:     {self.nick_name}
phone:        {self.phone}
uid:         {self.uid}
data_dir:       {self.data_dir}
key:          {self.key}
'''


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

# Load Windows DLLs
kernel32 = ctypes.windll.kernel32


# 打开目标进程
def open_process(pid):
    return ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)


# 读取目标进程内存
def read_process_memory(process_handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    success = ctypes.windll.kernel32.ReadProcessMemory(
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
    while ctypes.windll.kernel32.VirtualQueryEx(
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
    except Exception:
        # print(data[offset:offset + size])
        # print(traceback.format_exc())
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


# 导入 Windows API 函数
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


def read_bytes_from_pid(pid: int, addr: int, size: int):
    # 打开进程
    hprocess = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not hprocess:
        raise Exception(f"Failed to open process with PID {pid}")
    buffer = b''
    try:
        # 创建缓冲区
        buffer = ctypes.create_string_buffer(size)

        # 读取内存
        bytes_read = ctypes.c_size_t(0)
        success = ReadProcessMemory(hprocess, addr, buffer, size, ctypes.byref(bytes_read))
        if not success:
            CloseHandle(hprocess)
            return b''
            raise Exception(f"Failed to read memory at address {hex(addr)}")

        # 关闭句柄
        CloseHandle(hprocess)
    except Exception:
        pass
    # 返回读取的字节数组
    return bytes(buffer)


def read_string_from_pid(pid: int, addr: int, size: int):
    bytes0 = read_bytes_from_pid(pid, addr, size)
    try:
        return bytes0.decode('utf-8')
    except Exception:
        return ''


def is_ok(passphrase, buf, shared_flag=None):
    if shared_flag is not None and shared_flag.value:
        return False
    # 获取文件开头的 salt
    salt = buf[:SALT_SIZE]
    # salt 异或 0x3a 得到 mac_salt，用于计算 HMAC
    mac_salt = bytes(x ^ 0x3a for x in salt)
    # 使用 PBKDF2 生成新的密钥
    new_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
    # 使用新的密钥和 mac_salt 计算 mac_key
    mac_key = PBKDF2(new_key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)
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


def get_version(pid):
    p = psutil.Process(pid)
    version_info = win32api.GetFileVersionInfo(p.exe(), '\\')
    version = f"{win32api.HIWORD(version_info['FileVersionMS'])}.{win32api.LOWORD(version_info['FileVersionMS'])}.{win32api.HIWORD(version_info['FileVersionLS'])}.{win32api.LOWORD(version_info['FileVersionLS'])}"
    return version


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


def get_key_(keys, buf):
    shared_flag = multiprocessing.Value('b', False)
    pool = multiprocessing.Pool(processes=multiprocessing.cpu_count() // 2)
    results = pool.starmap(check_chunk, ((key, buf, shared_flag) for key in keys))
    pool.close()
    pool.join()

    for r in results:
        if r:
            print("Key found!", r)
            return bytes.hex(r)
    return None


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
    """Verify key using stdlib hashlib + hmac (avoids pycryptodome dependency in regex path)."""
    import hashlib
    salt = buf[:SALT_SIZE]
    mac_salt = bytes(x ^ 0x3a for x in salt)
    new_key = hashlib.pbkdf2_hmac('sha512', key, salt, ROUND_COUNT, dklen=KEY_SIZE)
    mac_key = hashlib.pbkdf2_hmac('sha512', new_key, mac_salt, 2, dklen=KEY_SIZE)
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
    Scan process memory for WCDB hex key cache patterns (x'<key><salt>').
    Returns verified key as hex string, or None if not found.
    """
    import re as _re
    hex_re = _re.compile(b"x'([0-9a-fA-F]{64,192})'")

    # Step A: Collect salt-to-DB-file mapping from disk
    salt_to_path = collect_db_salts(data_dir)
    if not salt_to_path:
        logger.warning("[regex_scan_keys] No .db files found with valid salts, cannot verify keys")
        return None

    # Step B: Scan process memory regions for hex patterns
    process_infos = get_memory_regions(process_handle)
    candidates = {}  # salt_hex -> key_hex

    logger.info(f"[regex_scan_keys] Scanning {len(process_infos)} memory regions for WCDB hex patterns")
    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        if not memory:
            continue
        for match in hex_re.finditer(memory):
            hex_str = match.group(1).decode('ascii', errors='ignore')
            if len(hex_str) >= 96:  # 64 hex key (32 bytes) + 32 hex salt (16 bytes) minimum
                key_hex = hex_str[:64]
                salt_hex = hex_str[64:96]
                if salt_hex in salt_to_path and salt_hex not in candidates:
                    candidates[salt_hex] = key_hex

    logger.info(f"[regex_scan_keys] Found {len(candidates)} candidate key+salt matches")

    if not candidates:
        return None

    # Step C: Verify each candidate against its matching DB file
    for salt_hex, key_hex in candidates.items():
        db_path = salt_to_path[salt_hex]
        try:
            with open(db_path, 'rb') as f:
                buf = f.read(PAGE_SIZE)
            if len(buf) < PAGE_SIZE:
                logger.warning(f"[regex_scan_keys] DB file too small: {db_path}")
                continue
            key_bytes = bytes.fromhex(key_hex)
            if _verify_key_stdlib(key_bytes, buf):
                logger.info(f"[regex_scan_keys] Key verified successfully via regex scan (matched {db_path})")
                return key_hex
            else:
                logger.info(f"[regex_scan_keys] Candidate key did not verify against {db_path}")
        except Exception as e:
            logger.warning(f"[regex_scan_keys] Error verifying against {db_path}: {e}")

    logger.warning("[regex_scan_keys] All candidates failed verification")
    return None


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
                        addr = read_num(target_data, offset, 8)
                        pre_addresses.append(addr)
    logger.info(f"[get_key_inner] Found {len(pre_addresses)} candidate addresses from YARA")
    keys = []
    key_set = set()
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
    key = get_key_(keys, buf)
    return key


def get_wx_dir(process_handle):
    rules_v4_dir = r'''
    rule GetDataDir {
        strings:
            $a = /[a-zA-Z]:\\(.{1,100}?\\){0,1}?xwechat_files\\[0-9a-zA-Z_-]{6,24}?\\db_storage\\/
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
    return max(data_dir_cnt, key=data_dir_cnt.get).decode('utf-8')


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
                            # print(
                            #     f"匹配字符串: {identifier} 内容:  偏移: {offset} 在地址: {hex(base_address + offset + 0x10)}")
                            # print(string)
                            with open('a.bin','wb') as f:
                                f.write(target_data)
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


def dump_session_info_v4_(pid) -> SessionInfo | None:
    session_info = SessionInfo()
    session_info.pid = pid
    session_info.version = get_version(pid)
    logger.info(f"[dump_session_info_v4_] Starting extraction for WeChat {session_info.version}, PID={pid}")

    process_handle = open_process(pid)
    if not process_handle:
        logger.error(f"[dump_session_info_v4_] Cannot open process {pid}")
        return None

    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=worker, args=(pid, queue))
    process.start()

    session_info.data_dir = get_wx_dir(process_handle)
    if not session_info.data_dir:
        logger.error("[dump_session_info_v4_] Could not find WeChat data directory")
        ctypes.windll.kernel32.CloseHandle(process_handle)
        process.join()
        return None

    # Try regex-based WCDB hex scan first (more robust across versions).
    # NOTE: data_dir already ends with db_storage\ from get_wx_dir, so pass it directly.
    session_info.key = regex_scan_keys(pid, process_handle, session_info.data_dir)
    if session_info.key:
        logger.info("[dump_session_info_v4_] Key found via regex scan")
    else:
        # Fall back to YARA-based extraction
        logger.info("[dump_session_info_v4_] Regex scan found no key, falling back to YARA")
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
            logger.info(f"[dump_session_info_v4_] Using {db_file_path} for YARA verification")
            with open(db_file_path, 'rb') as f:
                buf = f.read()
            session_info.key = get_key(pid, process_handle, buf)
            if session_info.key:
                logger.info("[dump_session_info_v4_] Key found via YARA fallback")
        else:
            logger.error("[dump_session_info_v4_] No .db file found for YARA verification")

    ctypes.windll.kernel32.CloseHandle(process_handle)
    session_info.uid = '_'.join(session_info.data_dir.split('\\')[-3].split('_')[0:-1])
    session_info.data_dir = '\\'.join(session_info.data_dir.split('\\')[:-2])
    process.join()  # 等待子进程完成
    if not queue.empty():
        nickname_info = queue.get()
        session_info.nick_name = nickname_info.get('nick_name', '')
        session_info.phone = nickname_info.get('phone', '')
        session_info.account_name = nickname_info.get('account_name', '')
    if not session_info.key:
        logger.error(f"[dump_session_info_v4_] Key extraction FAILED for WeChat {session_info.version}")
        print(f"Key extraction failed. WeChat version: {session_info.version}")
        print("Please ensure WeChat is running and logged in.")
        print(f"Data directory: {session_info.data_dir}")
    else:
        logger.info(f"[dump_session_info_v4_] Key extraction succeeded")
    return session_info


if __name__ == '__main__':
    freeze_support()
    st = time.time()
    pm = pymem.Pymem("Weixin.exe")
    pid = pm.process_id
    w = dump_session_info_v4_(pid)
    print(w)
    et = time.time()
    print(et - st)
