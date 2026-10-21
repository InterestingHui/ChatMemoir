"""ChatMemoir GUI 工具方法：重启、打开目录。"""

import os


class UtilityMixin:
    """Mixin providing utility actions for ChatMemoirApp."""

    def _on_restart(self):
        """回到欢迎屏"""
        self._state = "startup"
        self.database = None
        self.contacts = []
        self.selected_contact = None
        self._all_contact_items = []
        self._db_version = None
        self.contact_msg_counts.clear()
        self.contact_voice_counts.clear()
        self.voice_transcribed_counts.clear()
        self._show_screen("welcome")
        self._update_adv_menu()

    def _on_open_db_dir(self):
        """打开解密数据库目录（本地镜像优先，旧 UNC 产物兜底）"""
        import sys as _sys
        target = None
        if self.db_dir_actual and os.path.exists(self.db_dir_actual):
            target = self.db_dir_actual
        elif _sys.platform == 'win32':
            # db_dir_actual 失效时（如镜像被移动），按账号 uid 找本地镜像
            mirror_root = self._local_mirror_root()
            if mirror_root and os.path.isdir(mirror_root):
                uids = [d for d in os.listdir(mirror_root) if os.path.isdir(os.path.join(mirror_root, d))]
                if len(uids) == 1:
                    target = os.path.join(mirror_root, uids[0], 'db_storage')
        if target:
            try:
                os.startfile(target)
            except Exception:
                pass

    # ── 输出目录解析 ────────────────────────────────────────

    def _scoped_output_dir(self):
        """导出/报告的基准输出目录：解析用户配置 → 按当前账号分区。

        ponytail: 此前所有导出共用一个 data/聊天记录/，换账号后上一账号的
        113 个导出永远躺在同一目录里 —— 看起来就是"显示了别的微信的聊天记录"。
        现在落地到 <输出目录>/<账号uid>/ 下。config 里的 Windows UNC 路径
        （打包 exe 侧写入的 \\\\wsl.localhost\\<distro>\\…）在 Linux 上会被当
        相对路径拼出字面量垃圾目录，这里一并归一化回 / 路径。
        """
        out = self._output_dir.get() if hasattr(self, "_output_dir") else None
        if not out:
            out = os.path.join(self._script_dir, "data")
        if os.name != 'nt' and out.startswith('\\\\wsl.localhost\\'):
            parts = [p for p in out.split('\\') if p]  # ['wsl.localhost', distro, ...]
            out = '/' + '/'.join(parts[2:]) if len(parts) > 2 else out
        if not os.path.isabs(out):
            out = os.path.join(self._script_dir, out)
        from memoir import Me
        uid = getattr(Me(), 'uid', '')
        if uid and uid != 'wxid_00112233':  # 默认占位 uid 不分区
            out = os.path.join(out, uid)
        return out


if __name__ == "__main__":
    # 自检：UNC 归一化 + 账号分区（假 app / 假 Me 单例）。
    # 须以 `python3 -m gui.utils` 从项目根运行 — 直接跑 gui/utils.py 会因
    # gui/ 进 sys.path 让 gui.logging 遮蔽 stdlib logging，memoir 导入即炸。
    from memoir import Me

    class FakeApp(UtilityMixin):
        _script_dir = '/proj'
        _output_dir = None

    app = FakeApp()
    class _Var:
        def __init__(self, v): self.v = v
        def get(self): return self.v

    Me().uid = 'wxid_00112233'  # 占位 → 不分区
    app._output_dir = _Var('')
    assert app._scoped_output_dir() == '/proj/data'
    app._output_dir = _Var('out')
    assert app._scoped_output_dir() == '/proj/out'
    Me().uid = 'wxid_abc'
    assert app._scoped_output_dir() == '/proj/out/wxid_abc'
    app._output_dir = _Var('\\\\wsl.localhost\\Ubuntu\\home\\proj\\data')
    assert app._scoped_output_dir() == '/home/proj/data/wxid_abc', app._scoped_output_dir()
    Me().uid = 'wxid_00112233'
    print("utils output-dir self-check OK")
