"""ChatMemoir GUI 工具方法：重启、打开目录、光标应用。"""

import os
import tkinter as tk


class UtilityMixin:
    """Mixin providing utility actions for ChatMemoirApp."""

    def apply_cursor(self, widget=None):
        """把位图光标应用到 widget 及其所有子控件（含后续创建的 Toplevel）。

        WSLg 下字体字形光标隐形，位图可见；但控件类样式（Text→xterm 等）
        优先级高于 option_add('*cursor')，所以必须逐控件 configure 覆盖，
        否则鼠标扫过时光标形状切换，表现为指针跳变/闪烁。
        """
        spec = getattr(self, '_cursor_spec', None)
        if not spec:
            return
        w = widget or self.root
        try:
            w.configure(cursor=spec)
        except tk.TclError:
            pass
        for child in w.winfo_children():
            self.apply_cursor(child)

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
        """打开解密数据库目录"""
        if self.db_dir_actual and os.path.exists(self.db_dir_actual):
            try:
                os.startfile(self.db_dir_actual)
            except Exception:
                pass
