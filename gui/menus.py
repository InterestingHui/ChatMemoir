"""ChatMemoir GUI 菜单栏。"""

import tkinter as tk


class MenuMixin:
    """Mixin providing menu builder for ChatMemoirApp."""

    def _build_menu(self):
        menubar = tk.Menu(self.root, font=("Microsoft YaHei UI", 9))
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, font=("Microsoft YaHei UI", 9))
        file_menu.add_command(label="重新开始", command=self._on_restart)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        adv_menu = tk.Menu(menubar, tearoff=0, font=("Microsoft YaHei UI", 9))
        adv_menu.add_command(label="转写当前联系人的语音消息",
                            command=self._on_transcribe, state="disabled")
        adv_menu.add_separator()
        adv_menu.add_command(label="打开解密数据库目录", command=self._on_open_db_dir, state="disabled")
        menubar.add_cascade(label="高级", menu=adv_menu)
        self._menu_adv = adv_menu

    def _update_adv_menu(self):
        """更新高级菜单项的启用状态"""
        state = "normal" if self.database else "disabled"
        self._menu_adv.entryconfigure(0, state=state)
        self._menu_adv.entryconfigure(2, state=state)
