#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ChatMemoir GUI 语音转写（Whisper）——一键转写当前选中联系人。

复用 voice2text_batch 的统一转写/台账逻辑：
  - 增量：只转 Audio2Text.db 里没有的语音（已有微信转写的自动跳过）
  - 台账：每条追加到 data/voice_ledger.jsonl（状态 OK/EMPTY/FAILED + 秒级分段）
  - 失败不静默：FAILED 条目计入状态栏汇总，数据缺失/损坏显式标注
"""

import os
import sys

import tkinter.messagebox as messagebox

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from voice2text_batch import (  # noqa: E402
    transcribe_one, append_ledger, STATUS_OK, STATUS_EMPTY, STATUS_FAILED,
)


class TranscribeMixin:
    """Mixin providing voice transcription for ChatMemoirApp."""

    def _on_transcribe(self):
        if not self.selected_contact:
            messagebox.showwarning("提示", "请先在左侧选择联系人")
            return
        if self.running:
            return

        uid = self.selected_contact.uid
        voice_count = self.contact_voice_counts.get(uid, 0)
        if voice_count == 0:
            messagebox.showinfo("提示", "该联系人没有语音消息")
            return

        try:
            import numpy  # noqa: F401
            import pysilk  # noqa: F401
            import whisper  # noqa: F401
        except ImportError:
            messagebox.showinfo(
                "提示",
                "语音转文字功能需要安装额外依赖（WSL 内执行）:\n"
                "pip install openai-whisper pysilk numpy\n"
                "安装后重启 GUI 即可使用。")
            return

        name = self.selected_contact.remark or self.selected_contact.nickname or uid
        self.run_task(
            lambda: self._do_transcribe(uid),
            on_done=lambda summary: self._after_transcribe(summary, name),
        )

    def _count_untranscribed(self, uid, time_range=None):
        """快速统计联系人（可选时间范围）内未转写的语音条数——只查库不加载模型。"""
        import glob
        import hashlib
        import sqlite3
        import time as _time
        if not getattr(self, 'db_dir_actual', None):
            return 0
        msg_dir = os.path.join(self.db_dir_actual, "message")
        a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
        existing = set()
        if os.path.exists(a2t_path):
            conn = sqlite3.connect(a2t_path)
            existing = set(r[0] for r in conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
            conn.close()
        tbl = f"Msg_{hashlib.md5(uid.encode()).hexdigest()}"
        t0 = t1 = None
        try:
            if time_range and time_range[0]:
                t0 = _time.mktime(_time.strptime(time_range[0], "%Y-%m-%d %H:%M:%S"))
            if time_range and len(time_range) > 1 and time_range[1]:
                t1 = _time.mktime(_time.strptime(time_range[1], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
        cond = "WHERE local_type=34"
        params = []
        if t0 is not None:
            cond += " AND create_time>=?"
            params.append(int(t0))
        if t1 is not None:
            cond += " AND create_time<=?"
            params.append(int(t1))
        pending = 0
        for f in sorted(glob.glob(os.path.join(msg_dir, "message_*.db"))):
            try:
                conn = sqlite3.connect(f)
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if tbl in tables:
                    vids = [r[0] for r in conn.execute(
                        f"SELECT server_id FROM [{tbl}] {cond}", params).fetchall()]
                    pending += sum(1 for v in vids if v not in existing)
                conn.close()
            except sqlite3.Error:
                continue
        return pending

    def _do_transcribe(self, uid):
        return self._do_transcribe_range(uid, None)

    def _do_transcribe_range(self, uid, time_range=None):
        """转写联系人语音；time_range=['YYYY-MM-DD HH:MM:SS', ...] 时只转范围内的语音。"""
        import whisper

        self.set_status("加载 Whisper 模型（首次约 10 秒）...")
        model = whisper.load_model("small")

        db_dir = self.db_dir_actual
        msg_dir = os.path.join(db_dir, "message")
        media_conn = __import__("sqlite3").connect(os.path.join(msg_dir, "media_0.db"))
        a2t_conn = __import__("sqlite3").connect(os.path.join(db_dir, "Audio2Text.db"))
        a2t_conn.execute("""CREATE TABLE IF NOT EXISTS Audio2Text (
            ID INTEGER PRIMARY KEY, msgSvrId INTEGER UNIQUE, Text TEXT NOT NULL)""")
        a2t_conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_id ON Audio2Text (msgSvrId)")
        a2t_conn.commit()

        existing = set(r[0] for r in a2t_conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())

        # 目标联系人的语音 server_id（跨 message_*.db 分库；可选时间范围过滤）
        import glob
        import hashlib
        import sqlite3
        import time as _time
        tbl = f"Msg_{hashlib.md5(uid.encode()).hexdigest()}"
        t0 = t1 = None
        if time_range and time_range[0]:
            t0 = _time.mktime(_time.strptime(time_range[0], "%Y-%m-%d %H:%M:%S"))
        if time_range and len(time_range) > 1 and time_range[1]:
            t1 = _time.mktime(_time.strptime(time_range[1], "%Y-%m-%d %H:%M:%S"))
        cond = "WHERE local_type=34"
        params = []
        if t0 is not None:
            cond += " AND create_time>=?"
            params.append(int(t0))
        if t1 is not None:
            cond += " AND create_time<=?"
            params.append(int(t1))
        voice_ids = []
        for f in sorted(glob.glob(os.path.join(msg_dir, "message_*.db"))):
            conn = sqlite3.connect(f)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if tbl in tables:
                voice_ids.extend(r[0] for r in conn.execute(
                    f"SELECT server_id FROM [{tbl}] {cond}", params).fetchall())
            conn.close()

        todo = [s for s in voice_ids if s not in existing]
        if not todo:
            media_conn.close()
            a2t_conn.close()
            return {"ok": 0, "empty": 0, "failed": 0, "total": 0,
                    "msg": "所有语音都已有文字，无需转写"}

        ledger = os.path.join(BASE, "data", "voice_ledger.jsonl")
        ok_n = empty_n = fail_n = 0
        import time
        for i, sid in enumerate(todo, 1):
            status, text, segments, duration, err = transcribe_one(model, media_conn, sid)
            if ledger:
                append_ledger(ledger, {
                    "msgSvrId": sid, "uid": uid, "create_time": "",
                    "duration_sec": round(duration, 2), "transcribe_sec": 0,
                    "model": "small", "status": status, "text": text,
                    "segments": segments, "error": err,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
            if status == STATUS_OK:
                a2t_conn.execute(
                    "INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)", [sid, text])
                a2t_conn.commit()
                ok_n += 1
            elif status == STATUS_EMPTY:
                # 空语音写空文本占位，避免每次重跑重复解码
                a2t_conn.execute(
                    "INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)", [sid, ""])
                a2t_conn.commit()
                empty_n += 1
            else:
                fail_n += 1  # FAILED 不写缓存，修复后重跑可重试

            if i % 5 == 0 or i == len(todo):
                self.set_status(f"转写中: {i}/{len(todo)}  成功={ok_n} 空={empty_n} 失败={fail_n}")

        media_conn.close()
        a2t_conn.close()
        return {"ok": ok_n, "empty": empty_n, "failed": fail_n, "total": len(todo),
                "msg": f"转写完成: 成功 {ok_n} / 共 {len(todo)}（空语音 {empty_n}、失败 {fail_n}）"}

    def _after_transcribe(self, summary, name):
        self.set_status(f"{name} · {summary['msg']}")
        # 刷新联系人详情里的「已转写 x/y」统计
        try:
            self._compute_stats()
            if hasattr(self, "selected_contact") and self.selected_contact:
                self._on_contact_select_refresh()
        except Exception:
            pass
        if summary["failed"]:
            messagebox.showwarning(
                "一键转写", summary["msg"] +
                "\n\n失败条目未写入缓存（台账 data/voice_ledger.jsonl 有原因），重跑可重试。")
            return
        if summary["total"] == 0:
            messagebox.showinfo("一键转写", summary["msg"])
            return
        if messagebox.askyesno(
                "一键转写", summary["msg"] + "\n\n现在立即导出该联系人的聊天记录吗？"):
            self._export_after_transcribe()

    def _on_contact_select_refresh(self):
        """重新选中当前联系人以刷新详情面板（不动搜索框）。"""
        try:
            sel = self._contact_tree.selection()
            if sel:
                # 详情面板直接用已存字段重刷
                c = self.selected_contact
                self._detail_labels["已转写"].configure(
                    text=f"{self.voice_transcribed_counts.get(c.uid, 0)}"
                         f"/{self.contact_voice_counts.get(c.uid, 0)}")
        except Exception:
            pass


    # ── 全库转写 ─────────────────────────────────────────

    def _on_transcribe_all(self):
        """把库里所有联系人的语音全部转写（增量），完成后可联动批量导出。"""
        if self.running:
            return
        if not self.db_dir_actual:
            messagebox.showwarning("提示", "请先解密数据库")
            return
        try:
            import numpy  # noqa: F401
            import pysilk  # noqa: F401
            import whisper  # noqa: F401
        except ImportError:
            messagebox.showinfo(
                "提示",
                "语音转文字功能需要安装额外依赖（WSL 内执行）:\n"
                "pip install openai-whisper pysilk numpy\n"
                "安装后重启 GUI 即可使用。")
            return

        total_voices = sum(self.contact_voice_counts.values())
        if total_voices == 0:
            messagebox.showinfo("全库转写", "库里没有语音消息")
            return
        if not messagebox.askyesno(
                "全库转写",
                f"将对全部联系人的语音执行转写（增量，已有文字的自动跳过）。\n"
                f"语音总量约 {total_voices} 条，CPU 转写约 0.6-0.9 条/秒，"
                f"耗时长，可随时关闭 GUI（已完成部分已入库，重开续跑）。\n\n继续？"):
            return
        self.run_task(
            self._do_transcribe_all,
            on_done=lambda s: self._after_transcribe_all(s),
        )

    def _do_transcribe_all(self):
        import glob
        import hashlib
        import sqlite3
        import time
        import whisper

        self.set_status("全库转写: 加载 Whisper 模型...")
        model = whisper.load_model("small")

        db_dir = self.db_dir_actual
        msg_dir = os.path.join(db_dir, "message")
        sqlite3_mod = __import__("sqlite3")
        media_conn = sqlite3_mod.connect(os.path.join(msg_dir, "media_0.db"))
        a2t_conn = sqlite3_mod.connect(os.path.join(db_dir, "Audio2Text.db"))
        a2t_conn.execute("""CREATE TABLE IF NOT EXISTS Audio2Text (
            ID INTEGER PRIMARY KEY, msgSvrId INTEGER UNIQUE, Text TEXT NOT NULL)""")
        a2t_conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_id ON Audio2Text (msgSvrId)")
        a2t_conn.commit()
        existing = set(r[0] for r in a2t_conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())

        # uid 解析表（md5 -> uid），沿用 contacts.py 的思路
        tbl_to_uid = {}
        for contact in self.contacts:
            tbl_to_uid[f"Msg_{hashlib.md5(contact.uid.encode()).hexdigest()}"] = contact

        ledger = os.path.join(BASE, "data", "voice_ledger.jsonl")
        ok_n = empty_n = fail_n = 0
        scanned = 0
        done_flag = {"stop": False}

        for f in sorted(glob.glob(os.path.join(msg_dir, "message_*.db"))):
            if done_flag["stop"]:
                break
            try:
                conn = sqlite3_mod.connect(f)
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for tbl in tables:
                    if not tbl.startswith("Msg_"):
                        continue
                    contact = tbl_to_uid.get(tbl)
                    uid = contact.uid if contact else tbl[4:]
                    try:
                        vids = [r[0] for r in conn.execute(
                            f"SELECT server_id FROM [{tbl}] WHERE local_type=34").fetchall()]
                    except sqlite3_mod.Error:
                        continue
                    for sid in vids:
                        if sid in existing:
                            continue
                        scanned += 1
                        status, text, segments, duration, err = transcribe_one(
                            model, media_conn, sid)
                        if ledger:
                            append_ledger(ledger, {
                                "msgSvrId": sid, "uid": uid, "create_time": "",
                                "duration_sec": round(duration, 2), "transcribe_sec": 0,
                                "model": "small", "status": status, "text": text,
                                "segments": segments, "error": err,
                                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            })
                        if status == STATUS_OK:
                            a2t_conn.execute(
                                "INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)",
                                [sid, text])
                            a2t_conn.commit()
                            ok_n += 1
                        elif status == STATUS_EMPTY:
                            a2t_conn.execute(
                                "INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)",
                                [sid, ""])
                            a2t_conn.commit()
                            empty_n += 1
                        else:
                            fail_n += 1
                        if scanned % 10 == 0:
                            self.set_status(
                                f"全库转写: 已转 {scanned}  成功={ok_n} 空={empty_n} 失败={fail_n}")
                conn.close()
            except sqlite3_mod.Error:
                continue

        media_conn.close()
        a2t_conn.close()
        return {"ok": ok_n, "empty": empty_n, "failed": fail_n, "total": scanned,
                "msg": f"全库转写完成: 新转写 {scanned} 条（成功 {ok_n}、空 {empty_n}、失败 {fail_n}）"}

    def _after_transcribe_all(self, summary):
        self.set_status(summary["msg"])
        try:
            self._compute_stats()
        except Exception:
            pass
        parts = [summary["msg"]]
        if summary["failed"]:
            parts.append(f"失败 {summary['failed']} 条未入缓存（台账有原因），重跑可重试。")
        if summary["total"] == 0:
            parts.append("所有语音都已有文字。")
        parts.append("\n\n是否立即批量导出全部联系人的 HTML（语音将带文字）？")
        if messagebox.askyesno("全库转写", "\n".join(parts)):
            self._batch_export_after_transcribe()

    def _export_after_transcribe(self):
        """转写完成后联动导出当前联系人（复用导出 mixin）。"""
        if self.running or not self.selected_contact:
            return
        self._on_export()

    def _batch_export_after_transcribe(self):
        """转写完成后联动批量导出（复用导出 mixin，跳过二次确认）。"""
        if self.running or not self.database:
            return
        self.set_status(f"批量导出中 (0/{len(self.contacts)})...")
        self._ui_call(self.start_export_progress)
        self.run_task(
            self._do_batch_export,
            on_done=lambda d: self._on_export_done(d),
            on_error=lambda e: self._on_export_error(e),
        )
