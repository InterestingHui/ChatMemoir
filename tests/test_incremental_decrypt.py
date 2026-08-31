"""增量解密自检：合成 WCDB v4 密文库，验证页级 HMAC-diff 同步。

无 pytest 依赖，python3 tests/test_incremental_decrypt.py 直接跑（WSL/Linux 均可，
不需要微信/Windows）。构造方式与生产格式逐字节一致：
  页 0: [salt 16][AES-CBC 密文 4000][IV 16][HMAC-SHA512 64]
  页 N: [AES-CBC 密文 4016][IV 16][HMAC 64]
  HMAC = HMAC-SHA512(mac_key, 密文区+IV || le32(页号从 1 起))
  全零页不加密、原样拷贝。
"""

import hashlib
import hmac
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Crypto.Cipher import AES

from memoir.decrypt.decrypt_v4 import (
    decrypt_db_file_v4,
    PAGE_SIZE,
    SALT_SIZE,
    SQLITE_HEADER,
)

IV_SIZE, HMAC_SIZE, KEY_SIZE, AES_BLOCK = 16, 64, 32, 16
RESERVE = ((IV_SIZE + HMAC_SIZE + AES_BLOCK - 1) // AES_BLOCK) * AES_BLOCK  # 80


def _enc_page(key, mac_key, page_no, salt=b''):
    """构造第 page_no 页（0 基）。返回 (src 密文页, 期望解密输出页)。"""
    enc_off = SALT_SIZE if page_no == 0 else 0
    data_size = PAGE_SIZE - enc_off - RESERVE
    plaintext = os.urandom(data_size)
    iv = os.urandom(IV_SIZE)
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext)
    page = bytearray(PAGE_SIZE)
    if page_no == 0:
        page[:SALT_SIZE] = salt
    page[enc_off:enc_off + len(ciphertext)] = ciphertext
    page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_SIZE] = iv
    mac = hmac.new(mac_key, bytes(page[enc_off:PAGE_SIZE - RESERVE + IV_SIZE]),
                   hashlib.sha512)
    mac.update(struct.pack('<I', page_no + 1))
    page[PAGE_SIZE - RESERVE + IV_SIZE:] = mac.digest()
    src_page = bytes(page)
    # 输出页布局：页 0 的 salt 换成 SQLite 头，尾巴 80B 原样保留
    head = SQLITE_HEADER + b'\x00' if page_no == 0 else b''
    out = head + plaintext + src_page[-RESERVE:]
    return src_page, out


def build_src(path, key, salt, n_pages, zero_page=2):
    """写一个 n_pages 页的合成密文库；返回 (期望解密输出页列表, mac_key)。"""
    mac_salt = bytes(x ^ 0x3a for x in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', key, mac_salt, 2, dklen=KEY_SIZE)
    pages, expected = [], []
    for i in range(n_pages):
        if i == zero_page:
            p = b'\x00' * PAGE_SIZE  # 零页：不加密、原样拷贝
            pages.append(p)
            expected.append(p)
        else:
            p, out = _enc_page(key, mac_key, i, salt)
            pages.append(p)
            expected.append(out)
    with open(path, 'wb') as f:
        f.write(b''.join(pages))
    return expected, mac_key


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _scenario(tmp, name, n_pages=6):
    """建库 + 初次全量解密，返回增量场景的公共素材。"""
    key, salt = os.urandom(KEY_SIZE), os.urandom(SALT_SIZE)
    src = os.path.join(tmp, f'{name}.src.db')
    dst = os.path.join(tmp, f'{name}.dec.db')
    build_src(src, key, salt, n_pages)
    assert decrypt_db_file_v4(key.hex(), src, dst) is True
    return key, salt, src, dst


def check_1_full_decrypt(tmp):
    """全量解密语义：SQLite 头、尺寸、逐页明文、尾巴不变式。"""
    key, salt = os.urandom(KEY_SIZE), os.urandom(SALT_SIZE)
    src, out = os.path.join(tmp, 'c1.db'), os.path.join(tmp, 'c1.out.db')
    n = 6
    expected, _ = build_src(src, key, salt, n)
    assert decrypt_db_file_v4(key.hex(), src, out) is True
    data = _read(out)
    assert data[:16] == SQLITE_HEADER + b'\x00', '页 0 应以 SQLite 头开头'
    assert len(data) == n * PAGE_SIZE, f'尺寸应为 {n} 页'
    raw = _read(src)
    for i, exp in enumerate(expected):
        got = data[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
        assert got == exp, f'第 {i} 页明文不符'
        # 尾巴不变式：输出页尾巴 == 源密文页尾巴（增量同步依赖它判变）
        assert got[-RESERVE:] == raw[i * PAGE_SIZE:(i + 1) * PAGE_SIZE][-RESERVE:]


def check_2_incremental_matches_full(tmp):
    """增量 == 全量：原地改写 2 个旧页 + 追加 3 个新页。"""
    key, salt, src, dst = _scenario(tmp, 'c2')
    mac_salt = bytes(x ^ 0x3a for x in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', key, mac_salt, 2, dklen=KEY_SIZE)
    raw = bytearray(_read(src))
    for idx in (1, 3):  # 原地重写（同偏移新密文/IV/HMAC）
        p, _ = _enc_page(key, mac_key, idx, salt)
        raw[idx * PAGE_SIZE:(idx + 1) * PAGE_SIZE] = p
    for idx in (6, 7, 8):  # 追加新页
        p, _ = _enc_page(key, mac_key, idx, salt)
        raw += p
    with open(src, 'wb') as f:
        f.write(bytes(raw))
    assert decrypt_db_file_v4(key.hex(), src, dst) is True  # 已有 dst → 增量路径
    ref = os.path.join(tmp, 'c2.ref.db')  # 全量对照组
    assert decrypt_db_file_v4(key.hex(), src, ref) is True
    assert _read(dst) == _read(ref), '增量输出必须与全量重解逐字节一致'


def check_3_noop_sync_writes_nothing(tmp):
    """无变化同步零写入：内容与 mtime_ns 均不变。"""
    key, _, src, dst = _scenario(tmp, 'c3')
    before = hashlib.sha256(_read(dst)).hexdigest()
    mtime = os.stat(dst).st_mtime_ns
    assert decrypt_db_file_v4(key.hex(), src, dst) is True  # 无变化 → 全部跳过
    assert os.stat(dst).st_mtime_ns == mtime, '无变化同步不得触碰 mtime'
    assert hashlib.sha256(_read(dst)).hexdigest() == before, '无变化同步不得改内容'


def check_4_key_error_preserves_dst(tmp):
    """HMAC 校验失败 → 返回 False 且 dst 保留原快照（不删除）。"""
    key, salt, src, dst = _scenario(tmp, 'c4')
    before = _read(dst)
    raw = bytearray(_read(src))
    raw[4 * PAGE_SIZE + PAGE_SIZE - RESERVE + IV_SIZE + 30] ^= 0xFF  # 破坏第 4 页 HMAC
    with open(src, 'wb') as f:
        f.write(bytes(raw))
    assert decrypt_db_file_v4(key.hex(), src, dst) is False
    assert os.path.exists(dst), '密钥错误时 dst 必须保留'
    assert _read(dst) == before, 'dst 内容必须与同步前一致'


def check_5_shrunk_src_full_rewrite(tmp):
    """src 缩水 → 前置条件不满足 → 全量重写，结果 == 全量对照组。"""
    key, salt = os.urandom(KEY_SIZE), os.urandom(SALT_SIZE)
    src, dst = os.path.join(tmp, 'c5.db'), os.path.join(tmp, 'c5.dec.db')
    build_src(src, key, salt, 6)
    assert decrypt_db_file_v4(key.hex(), src, dst) is True
    small = os.path.join(tmp, 'c5.small.db')
    build_src(small, key, salt, 4)  # 同 key/salt 的更小库
    assert decrypt_db_file_v4(key.hex(), small, dst) is True  # 已有更大的 dst → 全量
    ref = os.path.join(tmp, 'c5.ref.db')
    assert decrypt_db_file_v4(key.hex(), small, ref) is True
    out = _read(dst)
    assert out == _read(ref)
    assert len(out) == 4 * PAGE_SIZE


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        for fn in (check_1_full_decrypt, check_2_incremental_matches_full,
                   check_3_noop_sync_writes_nothing, check_4_key_error_preserves_dst,
                   check_5_shrunk_src_full_rewrite):
            fn(tmp)
            print(f'PASS {fn.__name__}')
    print('ALL PASS')
