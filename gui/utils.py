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
        """打开解密数据库目录"""
        if self.db_dir_actual and os.path.exists(self.db_dir_actual):
            try:
                os.startfile(self.db_dir_actual)
            except Exception:
                pass
