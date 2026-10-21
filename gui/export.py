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
        msg_limit = self._parse_msg_limit(getattr(self, '_msg_limit', None))

        # 记忆设置
        self._config["export_format"] = fmt
        self._config["time_start"] = time_start
        self._config["time_end"] = time_end
        self._config["msg_limit"] = getattr(self._msg_limit, 'get', lambda: "最近 50 条")()
        self._config["output_dir"] = self._output_dir.get()
        _save_config(self._config)

        # AI 整理 HTML：检查时间范围内未转写语音，询问是否先转写
        if fmt == "AI 整理 HTML":
            pending = self._count_untranscribed(self.selected_contact.uid, time_range)
            if pending > 0:
                minutes = max(1, round(pending / 45))
                if not messagebox.askyesno(
                        "AI 整理导出",
                        f"该时间范围有 {pending} 条语音还没有转成文字。\n"
                        f"先转写（约 {minutes} 分钟）后导出，语音内容才会进入整理稿。\n\n"
                        f"立即转写并导出？\n（选“否”则直接导出，未转写语音显示占位）"):
                    self._transcribe_first = False
                else:
                    self._transcribe_first = True
            else:
                self._transcribe_first = False

        name = (self.selected_contact.remark or self.selected_contact.nickname
                or self.selected_contact.uid)
        limit_note = f"，最近 {msg_limit} 条" if msg_limit else "，全部"
        self.set_status(f"正在导出 {name} ({fmt})...")
        self.log(f"开始导出: {name} [{fmt}]{limit_note} → {self._scoped_output_dir()}")
        self._ui_call(self.start_export_progress)
        self.run_task(
            lambda: self._do_export(fmt, time_range, msg_limit),
            on_done=lambda d: self._on_export_done(d),
            on_error=lambda e: self._on_export_error(e),
        )

    @staticmethod
    def _parse_msg_limit(combobox):
        """把下拉框选项解析成条数：'最近 50 条' -> 50，'全部'/其他 -> None。"""
        if combobox is None:
            return None
        text = combobox.get()
        for part in text.replace('＋', '+').split():
            if part.isdigit():
                return int(part)
        return None

    def _on_batch_export(self):
        """Batch-export every contact as HTML. Mirrors run_export.py."""
        if not self.database:
            messagebox.showwarning("提示", "数据库未加载")
            return
        if self.running:
            return
        if not messagebox.askyesno(
            "确认批量导出",
            f"将为 {len(self.contacts)} 个联系人导出 HTML。\n这可能需要几分钟。继续？",
        ):
            return
        self.set_status(f"批量导出中 (0/{len(self.contacts)})...")
        self._ui_call(self.start_export_progress)
        self.run_task(
            self._do_batch_export,
            on_done=lambda d: self._on_export_done(d),
            on_error=lambda e: self._on_export_error(e),
        )

    def _do_batch_export(self):
        # ponytail: reuse project's HtmlExporter + batch_export flow. Output
        # under the user's selected output_dir (default ./data/).
        from scribe.config import FileType
        from scribe import HtmlExporter
        from memoir import MessageType

        # 按当前账号分区（utils._scoped_output_dir），避免换账号后导出混目录
        output_dir = self._scoped_output_dir()
        os.makedirs(output_dir, exist_ok=True)
        time_range = ['2020-01-01 00:00:00', '2099-12-31 23:59:59']
        total = len(self.contacts)
        for i, contact in enumerate(self.contacts):
            self._ui_call(lambda i=i, t=total, n=(contact.remark or contact.nickname or contact.uid):
                            self.set_status(f"批量导出 {i+1}/{t}: {n}"))
            try:
                scribe = HtmlExporter(
                    self.database,
                    contact,
                    output_dir=output_dir,
                    type_=FileType.HTML,
                    message_types=None,  # 全类型：None=全部（含语音/视频/文件），语音带缓存文字
                    time_range=time_range,
                    progress_callback=lambda pct: self._ui_call(lambda p=pct: self.set_progress(int(p * 100))),
                )
                scribe.start()
            except Exception as e:
                # Log and continue — one bad contact shouldn't abort the batch.
                self.log(f"  跳过 {contact.uid}: {e}")
        return output_dir

    def _do_export(self, fmt, time_range, msg_limit=None):
        from scribe.config import FileType
        from scribe import (TxtExporter, HtmlExporter, DocxExporter, AiHtmlExporter,
                            MarkdownExporter, ExcelExporter, AiTxtExporter)

        fmt_map = {
            "TXT": (FileType.TXT, TxtExporter),
            "HTML": (FileType.HTML, HtmlExporter),
            "Markdown": (FileType.MARKDOWN, MarkdownExporter),
            "DOCX": (FileType.DOCX, DocxExporter),
            "XLSX": (FileType.XLSX, ExcelExporter),
            "AI-TXT": (FileType.AI_TXT, AiTxtExporter),
            "AI 整理 HTML": (FileType.AI_HTML, AiHtmlExporter),
        }

        file_type, scribe_cls = fmt_map[fmt]
        contact = self.selected_contact
        # 按当前账号分区（utils._scoped_output_dir），避免换账号后导出混目录
        output_dir = self._scoped_output_dir()

        # AI 整理 HTML：先转写该时间范围内未转写的语音（用户已在 _on_export 确认）
        if fmt == "AI 整理 HTML" and getattr(self, '_transcribe_first', False):
            try:
                self._do_transcribe_range(contact.uid, time_range)
            except Exception as e:
                self.log(f"  语音转写失败（导出继续，未转写语音将显示占位）: {e}")

        if fmt in ('HTML', 'XLSX'):
            from memoir.model.contact import Me
            if not Me().image_aes_key:
                self.log("  提示: 未配置图片密钥，V2 加密图片无法解密 — "
                         "微信里点开几张图片 → 运行 tools/wx_key/wx_key.exe → 点「图片密钥」，再重新解密/导出")

        scribe = scribe_cls(
            self.database,
            contact,
            output_dir=output_dir,
            type_=file_type,
            message_types=None,
            time_range=time_range,
            progress_callback=lambda pct: self._ui_call(lambda: self.set_progress(int(pct * 100))),
            msg_limit=msg_limit,  # None=全部；否则只导出最近 N 条
        )
        if hasattr(self, '_config'):
            scribe.gui_config = self._config
        if fmt == "AI 整理 HTML":
            scribe.status_callback = lambda m: self._ui_call(lambda: self.set_status(m))
        scribe.start()
        return output_dir

    def _on_export_done(self, output_dir=None):
        self.set_status("导出完成")
        self.set_progress(100)
        self.log(f"导出完成: {output_dir or '输出目录'}")
        messagebox.showinfo("导出完成", "聊天记录导出成功！")

    def _on_export_error(self, e):
        self.set_status(f"导出失败: {e}")
        self.log(f"导出失败: {e}")
        self.set_progress(0)
