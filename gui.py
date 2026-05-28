#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir 全流程 GUI
解密 → 查看联系人 → 语音转文字 → 导出聊天记录
"""

import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk, scrolledtext

# 获取脚本所在目录，确保 import 正确
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置文件路径（frozen 模式使用 %APPDATA% 可写目录）
if getattr(sys, 'frozen', False):
    _CONFIG_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ChatMemoir')
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, '.gui_config.json')
else:
    _CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.gui_config.json')


def _load_config():
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    try:
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class ChatMemoirApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatMemoir 聊天记录导出工具")
        self.root.geometry("750x820")
        self.root.resizable(True, True)

        # 读取记忆配置
        self._config = _load_config()

        # 脚本所在目录（filedialog 会改变 CWD，所有相对路径都基于此解析）
        if getattr(sys, 'frozen', False):
            self._script_dir = os.path.dirname(sys.executable)
        else:
            self._script_dir = os.path.dirname(os.path.abspath(__file__))

        # 状态变量
        self.db_dir = tk.StringVar(value=self._config.get('last_db_dir', ''))
        self.db_version = tk.IntVar(value=4)
        self.output_dir = tk.StringVar(value=os.path.join(self._script_dir, "data"))
        self.search_text = tk.StringVar()
        self.whisper_model = tk.StringVar(value="base")
        self.contacts = []
        self.database = None
        self.selected_contact = None
        self.contact_msg_counts = {}
        self.contact_voice_counts = {}
        self.voice_transcribed_counts = {}
        self.running = False
        self._all_contact_items = []

        self._build_ui()

    # ────────────────── UI 构建 ──────────────────

    def _build_ui(self):
        # 顶部标题
        ttk.Label(self.root, text="ChatMemoir 聊天记录导出工具",
                  font=("Microsoft YaHei", 14, "bold")).pack(pady=(8, 4))

        # 可滚动容器
        canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.main_frame = ttk.Frame(canvas)
        self.main_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        self._build_log()
        self._build_progress()

    def _build_step1(self):
        frame = ttk.LabelFrame(self.main_frame, text=" 步骤1：解密数据库 ", padding=8)
        frame.pack(fill="x", padx=8, pady=4)

        # 数据库路径（已解密目录）
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="数据库路径:").pack(side="left")
        ttk.Entry(row1, textvariable=self.db_dir, width=50).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="浏览", command=self._on_browse_db).pack(side="left")

        # 微信版本
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="微信版本:").pack(side="left")
        ttk.Radiobutton(row2, text="v4 (Weixin.exe)", variable=self.db_version, value=4).pack(side="left", padx=8)
        ttk.Radiobutton(row2, text="v3 (WeChat.exe)", variable=self.db_version, value=3).pack(side="left")

        # 解密按钮 + 加载按钮
        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=4)
        ttk.Button(row3, text="解密数据库", command=self._on_decrypt).pack(side="left", padx=4)
        ttk.Button(row3, text="直接加载已解密数据", command=self._on_load).pack(side="left", padx=4)
        self.decrypt_status = ttk.Label(row3, text="未加载", foreground="gray")
        self.decrypt_status.pack(side="left", padx=8)

    def _build_step2(self):
        frame = ttk.LabelFrame(self.main_frame, text=" 步骤2：选择联系人 ", padding=8)
        frame.pack(fill="x", padx=8, pady=4)

        content = ttk.Frame(frame)
        content.pack(fill="x")

        # 左侧：联系人列表
        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="搜索:").pack(anchor="w")
        search_entry = ttk.Entry(left, textvariable=self.search_text)
        search_entry.pack(fill="x")
        search_entry.bind("<KeyRelease>", lambda e: self._filter_contacts())

        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True, pady=2)
        self.contact_listbox = tk.Listbox(list_frame, height=8, font=("Microsoft YaHei", 10))
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.contact_listbox.yview)
        self.contact_listbox.configure(yscrollcommand=list_scroll.set)
        self.contact_listbox.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.contact_listbox.bind("<<ListboxSelect>>", self._on_contact_select)

        # 右侧：联系人详情
        right = ttk.LabelFrame(content, text="联系人详情", padding=8)
        right.pack(side="right", fill="both", padx=(8, 0), expand=False)
        self.detail_labels = {}
        for field in ["昵称", "uid", "备注", "消息数", "语音数", "已转写", "类型"]:
            row = ttk.Frame(right)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{field}:", width=8, anchor="e").pack(side="left")
            lbl = ttk.Label(row, text="-", width=20, anchor="w")
            lbl.pack(side="left", padx=4)
            self.detail_labels[field] = lbl

    def _build_step3(self):
        frame = ttk.LabelFrame(self.main_frame, text=" 步骤3：语音转文字 ", padding=8)
        frame.pack(fill="x", padx=8, pady=4)

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        self.voice_info_label = ttk.Label(row1, text="请先选择联系人")
        self.voice_info_label.pack(side="left")

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Whisper模型:").pack(side="left")
        for m in ["tiny", "base", "small", "medium"]:
            ttk.Radiobutton(row2, text=m, variable=self.whisper_model, value=m).pack(side="left", padx=4)

        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=4)
        self.btn_transcribe = ttk.Button(row3, text="开始转写", command=self._on_transcribe)
        self.btn_transcribe.pack(side="left", padx=4)

    def _build_step4(self):
        frame = ttk.LabelFrame(self.main_frame, text=" 步骤4：导出聊天记录 ", padding=8)
        frame.pack(fill="x", padx=8, pady=4)

        # 格式选择
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="导出格式:").pack(side="left")
        self.format_vars = {}
        formats = [("TXT", "TXT"), ("HTML", "HTML"), ("Markdown", "MD"),
                   ("DOCX", "DOCX"), ("XLSX", "XLSX"), ("AI_TXT", "AI-TXT")]
        for label, key in formats:
            var = tk.BooleanVar(value=(key == "TXT"))
            self.format_vars[key] = var
            ttk.Checkbutton(row1, text=label, variable=var).pack(side="left", padx=4)

        # 时间范围
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="时间范围:").pack(side="left")
        self.time_start = ttk.Entry(row2, width=18)
        self.time_start.pack(side="left", padx=4)
        ttk.Label(row2, text="~").pack(side="left")
        self.time_end = ttk.Entry(row2, width=18)
        self.time_end.pack(side="left", padx=4)
        ttk.Label(row2, text="(留空=全部)", foreground="gray").pack(side="left")

        # 输出目录
        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="输出目录:").pack(side="left")
        ttk.Entry(row3, textvariable=self.output_dir, width=50).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row3, text="浏览", command=self._on_browse_output).pack(side="left")

        # 导出按钮
        row4 = ttk.Frame(frame)
        row4.pack(fill="x", pady=4)
        self.btn_export = ttk.Button(row4, text="开始导出", command=self._on_export)
        self.btn_export.pack(side="left", padx=4)

    def _build_log(self):
        frame = ttk.LabelFrame(self.main_frame, text=" 日志 ", padding=4)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.log_text = scrolledtext.ScrolledText(frame, height=10, font=("Consolas", 9),
                                                   state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _build_progress(self):
        frame = ttk.Frame(self.main_frame)
        frame.pack(fill="x", padx=8, pady=(0, 8))
        self.progress_bar = ttk.Progressbar(frame, mode="determinate", length=700)
        self.progress_bar.pack(fill="x")
        self.progress_label = ttk.Label(frame, text="就绪")
        self.progress_label.pack()

    # ────────────────── 工具方法 ──────────────────

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_progress(self, pct):
        self.progress_bar["value"] = pct
        self.progress_label.configure(text=f"{pct:.0f}%")

    def set_running(self, flag):
        self.running = flag
        state = "disabled" if flag else "normal"
        for btn in [self.btn_transcribe, self.btn_export]:
            btn.configure(state=state)

    def run_in_thread(self, func, *args):
        t = threading.Thread(target=func, args=args, daemon=True)
        t.start()

    def _check_db_valid(self, db_dir):
        """检查数据库目录是否有效"""
        if not db_dir or not os.path.isdir(db_dir):
            return False, "目录不存在"
        info_json = os.path.join(db_dir, "info.json")
        if not os.path.exists(info_json):
            return False, "未找到 info.json，请确认是解密后的数据库目录"
        return True, "OK"

    # ────────────────── Step 1: 解密 / 加载 ──────────────────

    def _on_browse_db(self):
        # 如果直接选择已解密的 db_storage 目录
        d = filedialog.askdirectory(title="选择数据库目录（解密后的 db_storage 或 uid 目录）")
        if d:
            self.db_dir.set(d)

    def _on_decrypt(self):
        """执行解密"""
        try:
            from memoir.decrypt import get_info_v4, get_info_v3
        except ImportError:
            messagebox.showerror("错误", "无法导入解密模块，请确认在 Windows 上运行")
            return

        version = self.db_version.get()
        self.run_in_thread(self._do_decrypt, version)

    def _do_decrypt(self, version):
        self.set_running(True)
        self.set_progress(0)
        try:
            from memoir.decrypt import get_info_v4, get_info_v3
            from memoir.decrypt import decrypt_v4, decrypt_v3
            from memoir import Me
            from memoir.decrypt.decrypt_dat import get_decode_code_v4

            self.log(f"开始扫描微信进程 (v{version})...")
            if version == 4:
                session_info_list = get_info_v4()
            else:
                import json as _json
                vl_path = os.path.join(os.path.dirname(__file__), "memoir", "decrypt", "version_list.json")
                with open(vl_path, "r", encoding="utf-8") as f:
                    version_list = _json.loads(f.read())
                session_info_list = get_info_v3(version_list)

            if not session_info_list:
                self.log("未找到运行中的微信进程，请先打开微信并登录")
                return

            for i, session_info in enumerate(session_info_list):
                self.log(f"发现微信账号: {session_info.nick_name} ({session_info.uid})")
                me = Me()
                me.data_dir = session_info.data_dir
                me.uid = session_info.uid
                me.name = session_info.nick_name
                key = session_info.key
                if not key:
                    self.log("未找到密钥，请重启微信后再试")
                    continue
                self.set_progress(20)
                self.log("正在解密数据库...")
                if version == 4:
                    me.xor_key = get_decode_code_v4(session_info.data_dir)
                    output_dir = os.path.join(self._script_dir, session_info.uid)
                    # 增量解密：只解密有变化的数据库，跳过未变化的文件
                    total, failed = decrypt_v4.decrypt_db_files(key, src_dir=session_info.data_dir, dest_dir=output_dir,
                                                key_map=session_info.key_map if session_info.key_map else None,
                                                skip_existing=True)
                    if failed:
                        self.log(f"警告: {failed} 个数据库解密失败，可能导致加载错误")
                    info_dir = os.path.join(output_dir, "db_storage")
                else:
                    output_dir = os.path.join(self._script_dir, session_info.uid)
                    # 增量解密：只解密有变化的数据库，跳过未变化的文件
                    decrypt_v3.decrypt_db_files(key, src_dir=session_info.data_dir, dest_dir=output_dir,
                                                skip_existing=True)
                    info_dir = os.path.join(output_dir, "Msg")
                self.set_progress(80)
                info_data = me.to_json()
                with open(os.path.join(info_dir, "info.json"), "w", encoding="utf-8") as f:
                    json.dump(info_data, f, ensure_ascii=False, indent=4)
                self.db_dir.set(os.path.abspath(info_dir))
                # 记忆路径
                self._config['last_db_dir'] = self.db_dir.get()
                _save_config(self._config)
                self.log(f"解密完成: {info_dir}")
            self.set_progress(100)
            self.decrypt_status.configure(text="已解密", foreground="green")
            self._on_load()
        except Exception as e:
            self.log(f"解密失败: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.set_running(False)

    def _on_load(self):
        """直接加载已解密的数据库"""
        db_dir = self.db_dir.get().strip()
        if not db_dir:
            messagebox.showwarning("提示", "请先选择或输入数据库路径")
            return
        ok, msg = self._check_db_valid(db_dir)
        if not ok:
            # 尝试加 db_storage 子目录
            alt = os.path.join(db_dir, "db_storage")
            if os.path.exists(os.path.join(alt, "info.json")):
                db_dir = alt
                self.db_dir.set(db_dir)
            else:
                messagebox.showerror("错误", f"数据库路径无效: {msg}")
                return

        self.run_in_thread(self._do_load, db_dir)

    def _do_load(self, db_dir):
        self.set_running(True)
        self.set_progress(0)
        try:
            from memoir import ArchiveConnection
            self.log("正在连接数据库...")
            version = self.db_version.get()
            conn = ArchiveConnection(db_dir, version)
            self.database = conn.get_interface()
            self.db_dir_actual = db_dir
            self.set_progress(30)
            self.log("正在加载联系人...")
            self.contacts = self.database.get_contacts()
            # 记忆路径
            self._config['last_db_dir'] = self.db_dir.get()
            _save_config(self._config)
            self.set_progress(60)
            self.log(f"加载完成: {len(self.contacts)} 个联系人")
            # 立即显示联系人列表，并解除按钮锁定，用户可以马上操作
            self.root.after(0, self._populate_contacts)
            self.set_running(False)
            self.decrypt_status.configure(text=f"已加载 ({len(self.contacts)} 人)", foreground="green")
            # 后台统计消息数和语音数，不阻塞 UI
            self._compute_stats()
            self.set_progress(100)
            self.root.after(0, self._populate_contacts)
        except Exception as e:
            self.log(f"加载失败: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.set_running(False)

    def _compute_stats(self):
        """统计每个联系人的消息数和语音数（每个数据库文件只打开一次）"""
        import hashlib
        self.contact_msg_counts.clear()
        self.contact_voice_counts.clear()
        self.voice_transcribed_counts.clear()
        try:
            import glob
            msg_dir = os.path.join(self.db_dir_actual, "message")
            if not os.path.isdir(msg_dir):
                return
            # 预计算 uid -> 表名 映射
            tbl_to_uid = {}
            for contact in self.contacts:
                tbl_to_uid[f"Msg_{hashlib.md5(contact.uid.encode()).hexdigest()}"] = contact.uid
            # 获取已转写 ID 集合
            a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
            transcribed = set()
            if os.path.exists(a2t_path):
                conn = sqlite3.connect(a2t_path)
                transcribed = set(r[0] for r in conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
                conn.close()
            # 每个数据库文件只打开一次，遍历所有表
            db_files = sorted(glob.glob(os.path.join(msg_dir, "message_?.db")))
            for db_file in db_files:
                try:
                    conn = sqlite3.connect(db_file)
                    tables = [r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    for tbl in tables:
                        uid = tbl_to_uid.get(tbl)
                        if not uid:
                            continue
                        row = conn.execute(f"SELECT count(*) FROM [{tbl}]").fetchone()
                        total = row[0] if row else 0
                        vrows = conn.execute(f"SELECT server_id FROM [{tbl}] WHERE local_type=34").fetchall()
                        voice = len(vrows)
                        voiced = sum(1 for r in vrows if r[0] in transcribed)
                        self.contact_msg_counts[uid] = self.contact_msg_counts.get(uid, 0) + total
                        self.contact_voice_counts[uid] = self.contact_voice_counts.get(uid, 0) + voice
                        self.voice_transcribed_counts[uid] = self.voice_transcribed_counts.get(uid, 0) + voiced
                    conn.close()
                except Exception as e:
                    self.log(f"跳过损坏的数据库: {os.path.basename(db_file)} ({e})")
            self.log(f"统计完成: {len(self.contact_msg_counts)} 个联系人有消息记录")
        except Exception as e:
            self.log(f"统计消息数时出错: {e}")

    def _populate_contacts(self):
        self.contact_listbox.delete(0, "end")
        self._all_contact_items = []
        for c in self.contacts:
            name = c.remark or c.nickname or c.uid
            msg_count = self.contact_msg_counts.get(c.uid, 0)
            if msg_count > 0:
                display = f"{name} ({msg_count}条)"
            else:
                display = name
            self._all_contact_items.append((display, c.uid, name))
            self.contact_listbox.insert("end", display)

    def _filter_contacts(self):
        keyword = self.search_text.get().strip().lower()
        self.contact_listbox.delete(0, "end")
        for display, uid, name in self._all_contact_items:
            if not keyword or keyword in display.lower() or keyword in uid.lower():
                self.contact_listbox.insert("end", display)

    # ────────────────── Step 2: 选择联系人 ──────────────────

    def _on_contact_select(self, event):
        sel = self.contact_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        # 找到对应的联系人（考虑搜索过滤后的索引）
        display_text = self.contact_listbox.get(idx)
        # 从显示文本中提取 uid
        uid = None
        for d, w, n in self._all_contact_items:
            if d == display_text:
                uid = w
                break
        if not uid:
            return
        self.selected_contact = self.database.get_contact_by_username(uid)
        c = self.selected_contact
        self.detail_labels["昵称"].configure(text=c.nickname or "-")
        self.detail_labels["uid"].configure(text=c.uid)
        self.detail_labels["备注"].configure(text=c.remark or "(无)")
        self.detail_labels["消息数"].configure(text=str(self.contact_msg_counts.get(c.uid, 0)))
        voice = self.contact_voice_counts.get(c.uid, 0)
        voiced = self.voice_transcribed_counts.get(c.uid, 0)
        self.detail_labels["语音数"].configure(text=str(voice))
        self.detail_labels["已转写"].configure(text=f"{voiced}/{voice}")
        type_str = "群聊" if c.is_chatroom else "好友"
        self.detail_labels["类型"].configure(text=type_str)
        self.voice_info_label.configure(
            text=f"选中联系人语音: {voice} 条, 已转写: {voiced} 条")

    # ────────────────── Step 3: 语音转文字 ──────────────────

    def _on_transcribe(self):
        if not self.selected_contact:
            messagebox.showwarning("提示", "请先选择联系人")
            return
        if self.running:
            return
        self.run_in_thread(self._do_transcribe)

    def _do_transcribe(self):
        self.set_running(True)
        self.set_progress(0)
        try:
            import numpy as np
            import pysilk
            import whisper

            uid = self.selected_contact.uid
            voice_count = self.contact_voice_counts.get(uid, 0)
            if voice_count == 0:
                self.log("该联系人没有语音消息")
                return

            self.log(f"加载 Whisper 模型 ({self.whisper_model.get()})...")
            model = whisper.load_model(self.whisper_model.get())
            self.log("模型加载完成")

            # 收集语音 server_id
            import hashlib
            import glob
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

            # 读取音频数据
            media_db = os.path.join(self.db_dir_actual, "message", "media_0.db")
            media_conn = sqlite3.connect(media_db)
            todo = []
            for vid in voice_ids:
                row = media_conn.execute(
                    "SELECT svr_id, voice_data FROM VoiceInfo WHERE svr_id=?", [vid]).fetchone()
                if row and row[1]:
                    todo.append(row)
            media_conn.close()

            # 过滤已转写的
            a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
            a2t_conn = sqlite3.connect(a2t_path)
            a2t_conn.execute("""CREATE TABLE IF NOT EXISTS Audio2Text (
                ID INTEGER PRIMARY KEY, msgSvrId INTEGER UNIQUE, Text TEXT NOT NULL)""")
            a2t_conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_id ON Audio2Text (msgSvrId)")
            a2t_conn.commit()
            existing = set(r[0] for r in a2t_conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
            todo = [(sid, d) for sid, d in todo if sid not in existing]
            self.log(f"待转写: {len(todo)} 条")

            if not todo:
                self.log("所有语音已转写")
                a2t_conn.close()
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
                    pct = (i + 1) / len(todo) * 100
                    self.set_progress(pct)
                    if (i + 1) % 5 == 0 or i == 0 or i == len(todo) - 1:
                        self.log(f"转写进度: {i+1}/{len(todo)} ({pct:.0f}%)")
                except Exception as e:
                    self.log(f"[{i+1}/{len(todo)}] 转写出错: {e}")

            a2t_conn.close()
            self.log(f"转写完成: {success}/{len(todo)} 条成功")
            # 刷新统计
            self.voice_transcribed_counts[uid] = self.contact_voice_counts.get(uid, 0)
            self.root.after(0, lambda: self._on_contact_select(None))
        except ImportError as e:
            self.log(f"缺少依赖: {e}")
            self.log("请安装: pip install openai-whisper pysilk-mod numpy")
        except Exception as e:
            self.log(f"转写失败: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.set_running(False)

    # ────────────────── Step 4: 导出 ──────────────────

    def _on_browse_output(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.output_dir.set(d)

    def _on_export(self):
        if not self.selected_contact:
            messagebox.showwarning("提示", "请先选择联系人")
            return
        if not self.database:
            messagebox.showwarning("提示", "请先加载数据库")
            return
        if self.running:
            return

        # 收集选中的格式
        from scribe.config import FileType
        from scribe import (TxtExporter, HtmlExporter, DocxExporter,
                              MarkdownExporter, ExcelExporter, AiTxtExporter)
        format_map = {
            "TXT": (FileType.TXT, TxtExporter),
            "HTML": (FileType.HTML, HtmlExporter),
            "MD": (FileType.MARKDOWN, MarkdownExporter),
            "DOCX": (FileType.DOCX, DocxExporter),
            "XLSX": (FileType.XLSX, ExcelExporter),
            "AI_TXT": (FileType.AI_TXT, AiTxtExporter),
        }
        selected = []
        for key, var in self.format_vars.items():
            if var.get() and key in format_map:
                selected.append((key, format_map[key]))
        if not selected:
            messagebox.showwarning("提示", "请至少选择一种导出格式")
            return

        # 时间范围
        time_range = None
        ts = self.time_start.get().strip()
        te = self.time_end.get().strip()
        if ts or te:
            time_range = [ts or "2000-01-01 00:00:00", te or "2099-12-31 23:59:59"]

        self.run_in_thread(self._do_export, selected, time_range)

    def _do_export(self, selected_formats, time_range):
        self.set_running(True)
        self.set_progress(0)
        try:
            contact = self.selected_contact
            output_dir = self.output_dir.get()
            if not os.path.isabs(output_dir):
                output_dir = os.path.join(self._script_dir, output_dir)
            total = len(selected_formats)

            for idx, (key, (file_type, scribe_cls)) in enumerate(selected_formats):
                self.log(f"导出 {key} 格式...")
                try:
                    scribe = scribe_cls(
                        self.database,
                        contact,
                        output_dir=output_dir,
                        type_=file_type,
                        message_types=None,
                        time_range=time_range,
                    )
                    scribe.start()
                    self.log(f"{key} 导出完成")
                except Exception as e:
                    import traceback as _tb
                    self.log(f"{key} 导出失败: {e}")
                    self.log(_tb.format_exc())
                pct = (idx + 1) / total * 100
                self.set_progress(pct)

            self.log(f"全部导出完成，输出目录: {output_dir}")
            # 打开输出目录
            try:
                out_path = os.path.join(output_dir, "聊天记录")
                if os.path.exists(out_path):
                    os.startfile(out_path)
            except Exception:
                pass
        except Exception as e:
            self.log(f"导出失败: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.set_running(False)


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = ChatMemoirApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
