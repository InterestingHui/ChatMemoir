"""ChatMemoir GUI 语音转写（Whisper）。"""

import glob
import hashlib
import os
import sqlite3
from tkinter import messagebox


class TranscribeMixin:
    """Mixin providing voice transcription for ChatMemoirApp."""

    def _on_transcribe(self):
        if not self.selected_contact:
            messagebox.showwarning("提示", "请先选择联系人")
            return
        if self.running:
            return

        try:
            import numpy as np
            import pysilk
            import whisper
        except ImportError:
            messagebox.showinfo("提示",
                                "语音转文字功能需要安装额外依赖:\n"
                                "pip install openai-whisper pysilk-mod numpy\n"
                                "打包版本不支持此功能。")
            return

        self.run_task(self._do_transcribe, on_done=lambda _: self.set_status("语音转写完成"))

    def _do_transcribe(self):
        import numpy as np
        import pysilk
        import whisper

        uid = self.selected_contact.uid
        voice_count = self.contact_voice_counts.get(uid, 0)
        if voice_count == 0:
            self.set_status("该联系人没有语音消息")
            return

        self.set_status("加载 Whisper 模型...")
        model = whisper.load_model("small")
        self.set_status("模型加载完成，开始转写...")

        tbl = f"Msg_{hashlib.md5(uid.encode()).hexdigest()}"
        msg_dir = os.path.join(self.db_dir_actual, "message")
        voice_ids = []
        for f in sorted(glob.glob(os.path.join(msg_dir, "message_?.db"))):
            c = sqlite3.connect(f)
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if tbl in tables:
                for r in c.execute(f"SELECT server_id FROM [{tbl}] WHERE local_type=34").fetchall():
                    voice_ids.append(r[0])
            c.close()

        media_db = os.path.join(self.db_dir_actual, "message", "media_0.db")
        media_conn = sqlite3.connect(media_db)
        todo = []
        for vid in voice_ids:
            row = media_conn.execute(
                "SELECT svr_id, voice_data FROM VoiceInfo WHERE svr_id=?", [vid]).fetchone()
            if row and row[1]:
                todo.append(row)
        media_conn.close()

        a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
        a2t_conn = sqlite3.connect(a2t_path)
        a2t_conn.execute("""CREATE TABLE IF NOT EXISTS Audio2Text (
            ID INTEGER PRIMARY KEY, msgSvrId INTEGER UNIQUE, Text TEXT NOT NULL)""")
        a2t_conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_id ON Audio2Text (msgSvrId)")
        a2t_conn.commit()
        existing = set(r[0] for r in a2t_conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
        todo = [(sid, d) for sid, d in todo if sid not in existing]

        if not todo:
            a2t_conn.close()
            self.set_status("所有语音已转写")
            return

        success = 0
        for i, (svr_id, silk_data) in enumerate(todo):
            try:
                pcm_buf = pysilk.decode(silk_data, to_wav=False, sample_rate=16000)
                samples = np.frombuffer(pcm_buf, dtype=np.int16).astype(np.float32) / 32768.0
                result = model.transcribe(samples, language="zh", fp16=False)
                text = result["text"].strip()
                if text:
                    a2t_conn.execute("INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)",
                                     [svr_id, text])
                    a2t_conn.commit()
                    success += 1
                if (i + 1) % 5 == 0:
                    self.set_status(f"转写中: {i+1}/{len(todo)}")
            except Exception:
                pass

        a2t_conn.close()
        self.set_status(f"转写完成: {success}/{len(todo)} 条")
