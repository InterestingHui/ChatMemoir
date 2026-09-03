"""V2 图片动态 AES 密钥解密管线自检。

微信 4.1 的 V2 dat 用每账号动态 AES-128-ECB 密钥加密头部、xor_key 异或
尾部。构造合成 dat 验证 decode_dat 全链路（含动态密钥传入）。
"""
import os
import struct
import tempfile

from Crypto.Cipher import AES

from memoir.decrypt.decrypt_dat import decode_dat, get_aes_key

V2_HEAD = b'\x07\x08V2\x08\x07'


def _make_v2_dat(path, aes_key, xor_key, payload):
    """payload: 明文图片字节（以 jpg/png magic 开头，≥48 字节）。

    头部固定 0xf=15 字节；加密区长度按解码器算法 = enc_len//16*16+16；
    末字节为 PKCS7 风格 pad（解码器按最后一字节截断）。文件尾补 1MB 零，
    对应解码器只异或最后 0x100000 字节的约定。
    """
    enc_len = 32
    first_block = payload[:47] + b'\x01'  # 48 字节，末位 pad=1
    cipher = AES.new(aes_key, AES.MODE_ECB)
    encrypted = cipher.encrypt(first_block)
    tail = bytes(b ^ xor_key for b in payload[48:48 + 64])
    with open(path, 'wb') as f:
        f.write(V2_HEAD + struct.pack('<H', enc_len) + b'\x00' * 7)
        f.write(encrypted)
        f.write(tail + b'\x00' * 0x100000)


def test_dynamic_aes_key_overrides_v2_map():
    key = 'aabbccddeeff00112233445566778899'
    assert get_aes_key(V2_HEAD, key) == bytes.fromhex(key)
    # 无动态密钥退回内置映射（老数据兼容）
    assert get_aes_key(V2_HEAD) != bytes.fromhex(key)
    assert get_aes_key(V2_HEAD, None) == get_aes_key(V2_HEAD)


def test_decode_dat_with_dynamic_key_roundtrip():
    aes_key = os.urandom(16)
    xor_key = 0xD2
    payload = b'\xff\xd8\xff\xe0' + b'J' * 92
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'x.dat')
        _make_v2_dat(src, aes_key, xor_key, payload)
        out = decode_dat(xor_key, src, d, dst_name='rt', aes_key=aes_key.hex())
        assert out and os.path.exists(out)
        with open(out, 'rb') as f:
            assert f.read(4) == b'\xff\xd8\xff\xe0'


def test_decode_without_dynamic_key_yields_garbage_not_crash():
    """密钥缺失时旧路径不崩溃（产出 .bin/乱码，由 GUI 提示兜底）。"""
    aes_key = os.urandom(16)
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'y.dat')
        _make_v2_dat(src, aes_key, 0xD2, b'\xff\xd8\xff\xe0' + b'K' * 92)
        out = decode_dat(0xD2, src, d, dst_name='nokey')
        assert out  # 不抛异常
