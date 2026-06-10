"""ChatMemoir GUI 导出聊天记录。"""

import os
from tkinter import filedialog, messagebox

from gui.constants import _save_config


class ExportMixin:
    """Mixin providing export workflow for ChatMemoirApp."""

    def _on_browse_output(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self._output_dir.set(d)

    def _on_export(self):
        if not self.selected_contact:
            messagebox.showwarning("提示", "请先选择联系人")
            return
        if not self.database:
            messagebox.showwarning("提示", "数据库未加载")
            return
        if self.running:
            return

        fmt = self._export_fmt.get()
        time_start = self._time_start.get().strip()
        time_end = self._time_end.get().strip()
        time_range = None
        if time_start or time_end:
            time_range = [time_start or "2000-01-01 00:00:00",
                          time_end or "2099-12-31 23:59:59"]

        # 记忆设置
        self._config["export_format"] = fmt
        self._config["time_start"] = time_start
        self._config["time_end"] = time_end
        self._config["output_dir"] = self._output_dir.get()
        _save_config(self._config)

        self.run_task(
            lambda: self._do_export(fmt, time_range),
            on_done=lambda _: self._on_export_done(),
            on_error=lambda e: self._on_export_error(e),
        )

    def _do_export(self, fmt, time_range):
        from scribe.config import FileType
        from scribe import (TxtExporter, HtmlExporter, DocxExporter,
                            MarkdownExporter, ExcelExporter, AiTxtExporter)

        fmt_map = {
            "TXT": (FileType.TXT, TxtExporter),
            "HTML": (FileType.HTML, HtmlExporter),
            "Markdown": (FileType.MARKDOWN, MarkdownExporter),
            "DOCX": (FileType.DOCX, DocxExporter),
            "XLSX": (FileType.XLSX, ExcelExporter),
            "AI-TXT": (FileType.AI_TXT, AiTxtExporter),
        }

        file_type, scribe_cls = fmt_map[fmt]
        contact = self.selected_contact
        output_dir = self._output_dir.get()
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(self._script_dir, output_dir)

        scribe = scribe_cls(
            self.database,
            contact,
            output_dir=output_dir,
            type_=file_type,
            message_types=None,
            time_range=time_range,
            progress_callback=lambda pct: self.root.after(0, lambda: self.set_progress(int(pct * 100))),
        )
        scribe.start()
        return output_dir

    def _on_export_done(self):
        self.set_status("导出完成")
        self.set_progress(100)
        messagebox.showinfo("导出完成", "聊天记录导出成功！")

    def _on_export_error(self, e):
        self.set_status(f"导出失败: {e}")
        self.set_progress(0)
