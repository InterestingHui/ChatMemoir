"""ChatMemoir GUI 线程安全日志与进度更新。"""

import os
from datetime import datetime


class LoggingMixin:
    """Mixin providing thread-safe log and progress methods for ChatMemoirApp."""

    def log(self, msg, loading=True):
        """线程安全日志 — 通过 _ui_call 调度 GUI 更新"""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        def _update():
            if loading:
                self._loading_log.configure(state="normal")
                self._loading_log.insert("end", line)
                self._loading_log.see("end")
                self._loading_log.configure(state="disabled")
        self._ui_call(_update)

    def set_loading_status(self, text):
        """线程安全 — 更新加载状态文字"""
        def _update():
            self._lbl_loading_status.configure(text=text)
        self._ui_call(_update)

    def set_status(self, msg):
        """线程安全 — 更新状态栏（转写/导出等 worker 线程也会调用）"""
        def _update():
            self._statusbar.configure(text=msg)
        self._ui_call(_update)

    def set_loading_progress(self, current, total, filename=""):
        """线程安全 — 更新解密加载进度"""
        if total <= 0:
            return
        pct = int(current / total * 100)
        short_name = os.path.basename(filename)[:30] if filename else ""
        def _update():
            # stop() is required: ttk.Progressbar in marquee mode (started via
            # start([intervalMs]) in _on_start) ignores [value] writes until
            # stop() is called. Without this, real progress is silently dropped.
            try:
                self._loading_progress.stop()
            except Exception:
                pass
            # ponytail: flip back to determinate so [value] reflects real X/Y.
            # _on_start sets mode=indeterminate for the scan phase (true marquee
            # for unknown-duration work). The first real progress callback lands
            # here and switches to determinate so subsequent pct values render
            # as a filling bar instead of a bouncing block.
            self._loading_progress.configure(mode="determinate")
            self._loading_progress["value"] = pct
            self._lbl_loading_pct.configure(text=f"{current}/{total} ({pct}%)  {short_name}")
        self._ui_call(_update)

    def set_progress(self, pct):
        """设置导出进度（0-100）"""
        # marquee 模式下 [value] 写入被忽略（同 set_loading_progress 的坑），
        # 先 stop() 再切回 determinate，跑马灯→真实百分比的交接才生效。
        try:
            self._export_progress.stop()
        except Exception:
            pass
        self._export_progress.configure(mode="determinate")
        self._export_progress["value"] = pct
        if pct > 0:
            self._export_progress.pack(side="left", padx=(8, 4))
        if pct >= 100:
            self._export_progress.pack_forget()

    def start_export_progress(self):
        """导出开始时显示跑马灯进度条。

        ponytail: 读消息/解析阶段耗时未知且无回调（get_messages 是单次阻塞
        调用），跑马灯足以回答"在不在干活"；首个真实百分比回调到达后
        set_progress 会接管成 determinate。要真进度条就给 get_messages 加
        分批回调，等有人抱怨再加。
        """
        self._export_progress.configure(mode="indeterminate")
        self._export_progress.pack(side="left", padx=(8, 4))
        self._export_progress.start(50)
