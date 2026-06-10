"""ChatMemoir GUI 线程安全日志与进度更新。"""

import os
from datetime import datetime


class LoggingMixin:
    """Mixin providing thread-safe log and progress methods for ChatMemoirApp."""

    def log(self, msg, loading=True):
        """线程安全日志 — 通过 root.after 调度 GUI 更新"""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        def _update():
            if loading:
                self._loading_log.configure(state="normal")
                self._loading_log.insert("end", line)
                self._loading_log.see("end")
                self._loading_log.configure(state="disabled")
        try:
            self.root.after(0, _update)
        except Exception:
            pass

    def set_loading_status(self, text):
        """线程安全 — 更新加载状态文字"""
        def _update():
            self._lbl_loading_status.configure(text=text)
        try:
            self.root.after(0, _update)
        except Exception:
            pass

    def set_status(self, msg):
        self._statusbar.configure(text=msg)

    def set_loading_progress(self, current, total, filename=""):
        """线程安全 — 更新解密加载进度"""
        if total <= 0:
            return
        pct = int(current / total * 100)
        short_name = os.path.basename(filename)[:30] if filename else ""
        def _update():
            self._loading_progress["value"] = pct
            self._lbl_loading_pct.configure(text=f"{current}/{total} ({pct}%)  {short_name}")
        try:
            self.root.after(0, _update)
        except Exception:
            pass

    def set_progress(self, pct):
        """设置导出进度（0-100）"""
        self._export_progress["value"] = pct
        if pct > 0:
            self._export_progress.pack(side="left", padx=(8, 4))
        if pct >= 100:
            self._export_progress.pack_forget()
