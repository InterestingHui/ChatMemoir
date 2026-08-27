"""GUI 回退加载的账号选择验证（WSL 真实数据，headless）。

复现用户路径：GUI「开始解析」→ Linux 上实时解密失败 → 回退加载 decrypted/。
修复前：无脑返回 last_db_dir（旧账号）。
修复后：优先返回当前登录账号（/mnt/c 热点 db mtime 最新者）。

运行: python3 tests/test_gui_live_account.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.decryption import DecryptionMixin


class _Stub(DecryptionMixin):
    """DecryptionMixin 只用到 _config / log / 进度回调，全部 stub 掉。"""

    def __init__(self, last_db_dir):
        self._config = {'last_db_dir': last_db_dir}
        self.logs = []
        self._db_version = 4

    def log(self, msg):
        self.logs.append(str(msg))
        print(f"  [gui] {msg}")


def test_detect_live_uid():
    stub = _Stub('')
    uid = stub._detect_live_wechat_uid()
    print(f"detect_live_wechat_uid -> {uid!r}")
    assert uid in (None, 'wxid_ka89oj7i1mz622', 'wxid_ttlo1sb5pyh811'), uid
    return uid


def test_fallback_prefers_live_account(live_uid):
    # last_db_dir 故意指向旧账号 — 修复后应返回当前登录账号
    old = '/home/ChatMemoir/decrypted/wxid_ka89oj7i1mz622/db_storage'
    stub = _Stub(old)
    got = stub._try_load_existing_db_dir()
    print(f"fallback dir -> {got}")
    if live_uid:
        assert got and live_uid in got, f"期望当前登录账号 {live_uid}，实际 {got}"
    else:
        assert got, "至少要返回一个可用目录"
    print("PASS")


def test_missing_live_data_raises():
    # live uid 有解密数据时不抛；此处验证 raise 分支存在即可（构造不匹配 uid）
    stub = _Stub('')
    stub._detect_live_wechat_uid = lambda: 'wxid_nonexistent'
    try:
        stub._try_load_existing_db_dir()
    except RuntimeError as e:
        assert 'wxid_nonexistent' in str(e)
        print("PASS (raise 分支)")
        return
    raise AssertionError("当前账号无解密数据时应 raise 而非静默加载别的账号")


if __name__ == '__main__':
    print("== detect live uid ==")
    live = test_detect_live_uid()
    print("== fallback prefers live account ==")
    test_fallback_prefers_live_account(live)
    print("== missing live data raises ==")
    test_missing_live_data_raises()
    print("\nALL PASS")
