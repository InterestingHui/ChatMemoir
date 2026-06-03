#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir 聊天记录导出工具
一键解密微信数据库，浏览联系人，导出聊天记录
"""

import json
import os
import sqlite3
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk, scrolledtext

# 源码运行时将项目根目录加入 sys.path
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置文件路径（frozen 模式使用 %APPDATA% 可写目录）
if getattr(sys, 'frozen', False):
    _CONFIG_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ChatMemoir')
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, '.gui_config.json')
else:
    _CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.gui_config.json')


def _resource_path(relative_path):
    """获取资源绝对路径，兼容开发模式和 Nuitka onefile 模式"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


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


# ── 配色 ──────────────────────────────────────────────────

PRIMARY = "#07C160"
PRIMARY_HOVER = "#06AD56"
BG = "#F0F2F5"
CARD_BG = "#FFFFFF"
TEXT_PRIMARY = "#191919"
TEXT_SECONDARY = "#8E8E93"
BORDER = "#E5E5EA"
DANGER = "#FA5151"


class ChatMemoirApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatMemoir 留痕")
        self.root.geometry("960x700")
        self.root.minsize(800, 560)
        self.root.configure(bg=BG)

        self._config = _load_config()

        if getattr(sys, 'frozen', False):
            self._script_dir = os.path.dirname(sys.executable)
        else:
            self._script_dir = os.path.dirname(os.path.abspath(__file__))

        # 状态变量
        self._state = "startup"  # startup | decrypting | ready | exporting
        self._screens = {}
        self.database = None
        self.db_dir_actual = None
        self.contacts = []
        self.selected_contact = None
        self.contact_msg_counts = {}
        self.contact_voice_counts = {}
        self.voice_transcribed_counts = {}
        self._all_contact_items = []
        self.running = False
        self._db_version = None  # auto-detected

        self._configure_styles()
        self._build_menu()
        self._build_screens()
        self._show_screen("welcome")

    # ── 样式 ──────────────────────────────────────────────

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT_PRIMARY, font=("Microsoft YaHei UI", 9))

        # 卡片
        style.configure("Card.TFrame", background=CARD_BG, relief="solid", borderwidth=1)
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT_PRIMARY)
        style.configure("CardTitle.TLabel", background=CARD_BG, foreground=TEXT_PRIMARY,
                        font=("Microsoft YaHei UI", 12, "bold"))

        # 按钮
        style.configure("TButton", padding=(16, 6), font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", background=PRIMARY, foreground="white",
                        borderwidth=0, focusthickness=0, font=("Microsoft YaHei UI", 10))
        style.map("Accent.TButton",
                  background=[("active", PRIMARY_HOVER), ("disabled", "#C8C8CC")],
                  foreground=[("disabled", "#FFFFFF")])
        style.configure("Start.TButton", font=("Microsoft YaHei UI", 16, "bold"),
                        padding=(48, 18))

        # 输入
        style.configure("TEntry", fieldbackground=CARD_BG, borderwidth=1, relief="solid", padding=6)
        style.configure("Search.TEntry", fieldbackground=CARD_BG, borderwidth=1, relief="solid",
                        padding=8, font=("Microsoft YaHei UI", 10))
        style.configure("TCombobox", fieldbackground=CARD_BG, padding=6)

        # 进度条
        style.configure("TProgressbar", troughcolor=BORDER, background=PRIMARY, thickness=8)

        # PanedWindow
        style.configure("TPanedwindow", background=BORDER)

        # LabelFrame
        style.configure("TLabelframe", background=CARD_BG, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=CARD_BG, foreground=TEXT_PRIMARY,
                        font=("Microsoft YaHei UI", 11, "bold"))

        # Treeview
        style.configure("Treeview", background=CARD_BG, fieldbackground=CARD_BG,
                        borderwidth=0, rowheight=40, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", background=BG, font=("Microsoft YaHei UI", 9, "bold"),
                        borderwidth=0, padding=(8, 4))
        style.map("Treeview",
                  background=[("selected", PRIMARY)],
                  foreground=[("selected", "white")])

        # 自定义 Contact 计数标签样式
        style.configure("Count.TLabel", foreground=TEXT_SECONDARY, font=("Microsoft YaHei UI", 10))

    # ── 菜单 ──────────────────────────────────────────────

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

    # ── 屏幕管理 ──────────────────────────────────────────

    def _build_screens(self):
        self._screens["welcome"] = self._build_welcome_screen()
        self._screens["loading"] = self._build_loading_screen()
        self._screens["main"] = self._build_main_screen()
        for s in self._screens.values():
            s.place(relwidth=1, relheight=1)

    def _show_screen(self, name):
        for sname, sframe in self._screens.items():
            sframe.place_forget()
        self._screens[name].lift()
        self._screens[name].place(relwidth=1, relheight=1)

    # ── 欢迎屏 ────────────────────────────────────────────

    def _build_welcome_screen(self):
        frame = ttk.Frame(self.root)
        frame.configure(style="TFrame")

        center = ttk.Frame(frame, style="TFrame")
        center.place(relx=0.5, rely=0.42, anchor="center")

        ttk.Label(center, text="留痕",
                  font=("Microsoft YaHei UI", 36, "bold"),
                  foreground=PRIMARY, background=BG).pack()

        ttk.Label(center, text="微信聊天记录解密与导出工具",
                  font=("Microsoft YaHei UI", 12),
                  foreground=TEXT_SECONDARY, background=BG).pack(pady=(4, 32))

        ttk.Label(center, text="打开微信并登录后，点击下方按钮即可一键解析",
                  font=("Microsoft YaHei UI", 9),
                  foreground=TEXT_SECONDARY, background=BG).pack(pady=(0, 16))

        self._btn_start = ttk.Button(center, text="开始解析",
                                     style="Accent.TButton",
                                     command=self._on_start)
        self._btn_start.configure(style="Start.TButton")
        self._btn_start.pack()

        self._lbl_welcome_error = ttk.Label(center, text="", foreground=DANGER, background=BG,
                                            font=("Microsoft YaHei UI", 9))
        self._lbl_welcome_error.pack(pady=(12, 0))

        # 底部提示
        ttk.Label(frame, text="请确保微信已登录 · 需要管理员权限",
                  font=("Microsoft YaHei UI", 8),
                  foreground=TEXT_SECONDARY, background=BG).place(relx=0.5, rely=0.92, anchor="center")

        return frame

    # ── 加载屏 ────────────────────────────────────────────

    def _build_loading_screen(self):
        frame = ttk.Frame(self.root)

        center = ttk.Frame(frame, style="TFrame")
        center.place(relx=0.5, rely=0.35, anchor="center", relwidth=0.65)

        self._lbl_loading_status = ttk.Label(center, text="正在初始化...",
                                             font=("Microsoft YaHei UI", 14),
                                             foreground=TEXT_PRIMARY, background=BG)
        self._lbl_loading_status.pack(pady=(0, 12))

        self._loading_progress = ttk.Progressbar(center, mode="determinate", length=500)
        self._loading_progress.pack(fill="x", pady=(0, 16))
        self._loading_progress["value"] = 0
        self._lbl_loading_pct = ttk.Label(center, text="", font=("Consolas", 11),
                                           foreground=TEXT_SECONDARY, background=BG)
        self._lbl_loading_pct.pack(pady=(0, 8))

        # 日志区域
        log_frame = ttk.Frame(center, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True)
        self._loading_log = scrolledtext.ScrolledText(
            log_frame, height=10, font=("Consolas", 9),
            state="disabled", wrap="word", bg=CARD_BG, relief="flat",
            fg=TEXT_PRIMARY, borderwidth=0
        )
        self._loading_log.pack(fill="both", expand=True, padx=2, pady=2)

        btn_row = ttk.Frame(center, style="TFrame")
        btn_row.pack(fill="x", pady=(12, 0))
        self._btn_retry = ttk.Button(btn_row, text="重试", command=self._on_start, style="Accent.TButton")
        self._btn_cancel = ttk.Button(btn_row, text="取消", command=self._on_restart)

        return frame

    # ── 主屏 ──────────────────────────────────────────────

    def _build_main_screen(self):
        frame = ttk.Frame(self.root)

        # 顶部栏
        topbar = ttk.Frame(frame, style="Card.TFrame")
        topbar.pack(fill="x", padx=0, pady=0)

        top_inner = ttk.Frame(topbar, style="Card.TFrame")
        top_inner.pack(fill="x", padx=16, pady=10)

        self._lbl_account = ttk.Label(top_inner, text="", style="CardTitle.TLabel")
        self._lbl_account.pack(side="left")

        self._lbl_contact_count = ttk.Label(top_inner, text="", style="Count.TLabel")
        self._lbl_contact_count.pack(side="left", padx=(12, 0))

        btn_restart = ttk.Button(top_inner, text="重新开始", command=self._on_restart)
        btn_restart.pack(side="right")

        # 主内容区：PanedWindow 分割
        pw = ttk.PanedWindow(frame, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=0, pady=0)

        # 左侧面板：联系人列表
        left = ttk.Frame(pw, style="TFrame")
        left.configure(width=320)
        pw.add(left, weight=1)

        left_inner = ttk.Frame(left, style="TFrame")
        left_inner.pack(fill="both", expand=True, padx=12, pady=12)

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._filter_contacts())
        search_frame = ttk.Frame(left_inner, style="Card.TFrame")
        search_frame.pack(fill="x")
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var, style="Search.TEntry")
        search_entry.pack(fill="x", padx=2, pady=2)
        search_entry.insert(0, "")
        # 绑定 Esc 清空搜索
        search_entry.bind("<Escape>", lambda e: self._search_var.set(""))

        self._contact_tree = ttk.Treeview(left_inner, columns=("name", "count"),
                                          show="headings", selectmode="browse")
        self._contact_tree.heading("name", text="联系人")
        self._contact_tree.heading("count", text="消息数", anchor="e")
        self._contact_tree.column("name", width=200, minwidth=120)
        self._contact_tree.column("count", width=56, anchor="e", minwidth=50)
        self._contact_tree.pack(fill="both", expand=True, pady=(8, 0))
        self._contact_tree.bind("<<TreeviewSelect>>", self._on_contact_select)
        # 绑定 Enter 键
        self._contact_tree.bind("<Return>", self._on_contact_select)

        tree_scroll = ttk.Scrollbar(left_inner, orient="vertical", command=self._contact_tree.yview)
        self._contact_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self._contact_tree.pack(fill="both", expand=True, pady=(8, 0))

        # 右侧面板：详情 + 导出
        right = ttk.Frame(pw, style="TFrame")
        right.configure(width=600)
        pw.add(right, weight=2)

        right_inner = ttk.Frame(right, style="TFrame")
        right_inner.pack(fill="both", expand=True, padx=12, pady=12)

        # 联系人详情卡片
        self._detail_card = ttk.LabelFrame(right_inner, text="联系人详情", padding=12)
        self._detail_card.pack(fill="x", pady=(0, 12))

        self._detail_placeholder = ttk.Label(self._detail_card, text="请从左侧选择联系人",
                                             foreground=TEXT_SECONDARY, font=("Microsoft YaHei UI", 11))
        self._detail_placeholder.pack(pady=20)

        # 详情内容区（选中后显示）
        self._detail_content = ttk.Frame(self._detail_card, style="Card.TFrame")
        self._detail_labels = {}
        info_row = ttk.Frame(self._detail_content, style="Card.TFrame")
        info_row.pack(fill="x")
        left_info = ttk.Frame(info_row, style="Card.TFrame")
        left_info.pack(side="left", fill="x", expand=True)
        for field in ["昵称", "uid", "备注", "类型"]:
            row = ttk.Frame(left_info, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{field}:", width=6, anchor="e", style="Card.TLabel").pack(side="left")
            lbl = ttk.Label(row, text="-", anchor="w", style="Card.TLabel")
            lbl.pack(side="left", padx=(4, 0))
            self._detail_labels[field] = lbl
        right_info = ttk.Frame(info_row, style="Card.TFrame")
        right_info.pack(side="right")
        for field in ["消息数", "语音数", "已转写"]:
            row = ttk.Frame(right_info, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{field}:", width=6, anchor="e", style="Card.TLabel").pack(side="left")
            lbl = ttk.Label(row, text="-", anchor="w", style="Card.TLabel")
            lbl.pack(side="left", padx=(4, 0))
            self._detail_labels[field] = lbl

        # 导出卡片
        export_card = ttk.LabelFrame(right_inner, text="导出聊天记录", padding=12)
        export_card.pack(fill="x", pady=(0, 12))

        # 格式选择
        fmt_row = ttk.Frame(export_card, style="Card.TFrame")
        fmt_row.pack(fill="x", pady=2)
        ttk.Label(fmt_row, text="导出格式:", width=10, anchor="e", style="Card.TLabel").pack(side="left")
        self._export_fmt = ttk.Combobox(fmt_row, values=["HTML", "TXT", "Markdown", "DOCX", "XLSX", "AI-TXT"],
                                        state="readonly", width=14)
        self._export_fmt.pack(side="left", padx=(4, 0))
        self._export_fmt.set(self._config.get("export_format", "HTML"))

        # 时间范围
        time_row = ttk.Frame(export_card, style="Card.TFrame")
        time_row.pack(fill="x", pady=2)
        ttk.Label(time_row, text="时间范围:", width=10, anchor="e", style="Card.TLabel").pack(side="left")
        self._time_start = ttk.Entry(time_row, width=16)
        self._time_start.pack(side="left", padx=(4, 0))
        self._time_start.insert(0, self._config.get("time_start", ""))
        ttk.Label(time_row, text="  ~  ", style="Card.TLabel").pack(side="left")
        self._time_end = ttk.Entry(time_row, width=16)
        self._time_end.pack(side="left")
        self._time_end.insert(0, self._config.get("time_end", ""))
        ttk.Label(time_row, text="  留空 = 全部", foreground=TEXT_SECONDARY, style="Card.TLabel").pack(side="left")

        # 输出目录
        out_row = ttk.Frame(export_card, style="Card.TFrame")
        out_row.pack(fill="x", pady=2)
        ttk.Label(out_row, text="输出目录:", width=10, anchor="e", style="Card.TLabel").pack(side="left")
        self._output_dir = tk.StringVar(
            value=self._config.get("output_dir", os.path.join(self._script_dir, "data")))
        out_entry = ttk.Entry(out_row, textvariable=self._output_dir)
        out_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(out_row, text="浏览", command=self._on_browse_output).pack(side="left", padx=(4, 0))

        # 导出按钮 + 进度
        btn_row = ttk.Frame(export_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        self._btn_export = ttk.Button(btn_row, text="导出聊天记录",
                                      command=self._on_export, style="Accent.TButton")
        self._btn_export.pack(side="left")

        self._export_progress = ttk.Progressbar(btn_row, mode="determinate", length=200)
        self._export_status = ttk.Label(btn_row, text="", foreground=TEXT_SECONDARY, style="Card.TLabel")

        # 状态栏
        self._statusbar = ttk.Label(frame, text="就绪", foreground=TEXT_SECONDARY,
                                    font=("Microsoft YaHei UI", 8), background=BG, anchor="w")
        self._statusbar.pack(fill="x", side="bottom", padx=12, pady=(0, 4))

        return frame

    # ── 日志 ──────────────────────────────────────────────

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

    # ── 进度 ──────────────────────────────────────────────

    def set_loading_progress(self, current, total, filename=""):
        """线程安全 — 更新解密加载进度"""
        if total <= 0: return
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

    # ── 线程管理 ──────────────────────────────────────────

    def set_running(self, flag):
        self.running = flag
        state = "disabled" if flag else "normal"
        self._btn_export.configure(state=state)

    def run_task(self, target, on_done=None, on_error=None):
        """后台任务 + UI 回调"""
        def wrapper():
            try:
                self.root.after(0, lambda: self.set_running(True))
                result = target()
                if on_done:
                    self.root.after(0, lambda: on_done(result))
            except Exception as e:
                if on_error:
                    self.root.after(0, lambda: on_error(e))
                else:
                    self.root.after(0, lambda: self._show_error(e))
            finally:
                self.root.after(0, lambda: self.set_running(False))
        threading.Thread(target=wrapper, daemon=True).start()

    def _show_error(self, e, context=""):
        import traceback
        msg = f"{context}: {e}" if context else str(e)
        self.log(msg)
        self.log(traceback.format_exc())

    # ── 开始解析（一键解密）────────────────────────────────

    def _on_start(self):
        """开始一键解密"""
        self._show_screen("loading")
        self._loading_progress.start(10)
        self.set_loading_status("正在扫描微信进程...")
        self._loading_log.configure(state="normal")
        self._loading_log.delete("1.0", "end")
        self._loading_log.configure(state="disabled")
        self._btn_retry.pack_forget()
        self._btn_cancel.pack(side="right")
        self.run_task(self._auto_decrypt, on_done=self._on_decrypt_done, on_error=self._on_decrypt_error)

    def _auto_decrypt(self):
        """自动检测微信版本、提取密钥、解密数据库、加载联系人"""
        from memoir.decrypt import get_info_v4, get_info_v3
        from memoir.decrypt import decrypt_v4, decrypt_v3
        from memoir import Me, ArchiveConnection

        # 1. 检查管理员权限
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            self.log("请以管理员身份运行本程序")
            self.log("右键 ChatMemoir.exe → 以管理员身份运行")
            raise PermissionError("需要管理员权限才能读取微信进程内存")

        # 2. 扫描微信进程
        self.set_loading_status("正在扫描微信进程...")
        self.log("正在扫描微信 v4 进程 (Weixin.exe / WeChatAppEx.exe)...")
        session_info_list = get_info_v4()
        self._db_version = 4

        if not session_info_list:
            self.set_loading_status("尝试 v3 微信进程...")
            self.log("v4 未找到，尝试 v3 (WeChat.exe)...")
            import json as _json
            vl_path = _resource_path(os.path.join("memoir", "decrypt", "version_list.json"))
            with open(vl_path, "r", encoding="utf-8") as f:
                version_list = _json.loads(f.read())
            session_info_list = get_info_v3(version_list)
            self._db_version = 3

        if not session_info_list:
            self.log("未找到已登录的微信进程")
            self.log("请确认：1) 微信已打开  2) 已扫码登录  3) 以管理员身份运行本程序")
            raise RuntimeError("未找到已登录的微信进程，请先打开微信并扫码登录")

        # 3. 解密每个账号的数据库
        seen_uids = set()
        db_dir = None
        for session_info in session_info_list:
            uid = session_info.uid
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)

            self.log(f"发现微信账号: {session_info.nick_name or uid} ({uid})")
            key = session_info.key
            if not key:
                # Try wx_key automatic extraction
                passphrase = self._get_wx_key_passphrase(uid)
                if not passphrase:
                    self.log(f"  {uid}: 未能获取密钥，跳过")
                    continue
                # Derive per-DB keys from passphrase
                import hashlib as _hl
                key_map = {}
                trimmed = '\\'.join(session_info.data_dir.rstrip('\\').split('\\')[:-1])
                for root, dirs, files in os.walk(session_info.data_dir):
                    for fn in files:
                        if fn.endswith('.db'):
                            fp = os.path.join(root, fn)
                            if os.path.getsize(fp) < 4096: continue
                            with open(fp, 'rb') as fh: salt = fh.read(16)
                            dk = _hl.pbkdf2_hmac('sha512', bytes.fromhex(passphrase), salt, 256000, dklen=32)
                            key_map[os.path.relpath(fp, trimmed)] = dk.hex()
                session_info.key_map = key_map
                session_info.key = list(key_map.values())[0] if key_map else passphrase
                key = session_info.key
                self.log(f"  已从 passphrase 派生 {len(key_map)} 个数据库密钥")

            self.set_loading_status(f"正在解密 {uid} 的数据库...")
            self.set_loading_progress(0, 1, "")
            self.log("正在解密数据库...")
            if self._db_version == 4:
                from memoir.decrypt.decrypt_dat import get_decode_code_v4
                me = Me()
                me.data_dir = session_info.data_dir
                me.uid = uid
                me.name = session_info.nick_name
                me.xor_key = get_decode_code_v4(session_info.data_dir)
                output_dir = os.path.join(self._script_dir, uid)
                total, failed = decrypt_v4.decrypt_db_files(
                    key, src_dir=session_info.data_dir, dest_dir=output_dir,
                    key_map=getattr(session_info, 'key_map', None) or None,
                    skip_existing=True,
                    progress_callback=self.set_loading_progress)
                if failed:
                    self.log(f"  警告: {failed}/{total} 个数据库解密失败")
                info_dir = os.path.join(output_dir, "db_storage")
            else:
                me = Me()
                me.data_dir = session_info.data_dir
                me.uid = uid
                me.name = session_info.nick_name
                output_dir = os.path.join(self._script_dir, uid)
                decrypt_v3.decrypt_db_files(key, src_dir=session_info.data_dir,
                                            dest_dir=output_dir, skip_existing=True)
                info_dir = os.path.join(output_dir, "Msg")

            # 从 contact.db 读取昵称（v4）
            if self._db_version == 4:
                contact_db = os.path.join(info_dir, "contact", "contact.db")
                if os.path.exists(contact_db):
                    try:
                        conn = sqlite3.connect(contact_db)
                        cur = conn.cursor()
                        cur.execute("SELECT nick_name FROM contact WHERE username = ?", [uid])
                        row = cur.fetchone()
                        conn.close()
                        if row and row[0]:
                            me.name = row[0]
                    except Exception:
                        pass

            os.makedirs(info_dir, exist_ok=True)
            with open(os.path.join(info_dir, "info.json"), "w", encoding="utf-8") as f:
                json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

            db_dir = os.path.abspath(info_dir)
            self._config['last_db_dir'] = db_dir
            _save_config(self._config)
            self.log(f"解密完成: {db_dir}")

        if not db_dir:
            self.log("所有账号均未成功解密，可能原因：")
            self.log("  - 微信未登录（请扫码登录后再试）")
            self.log("  - wx_key 未提取到密钥（请手动运行 tools/wx_key/wx_key.exe）")
            raise RuntimeError("未能解密任何数据库，请确认微信已登录且 wx_key 提取成功")

        # 4. 加载联系人
        self.set_loading_status("正在加载联系人...")
        self.set_loading_progress(1, 1, "")
        self.log("正在连接数据库...")
        conn = ArchiveConnection(db_dir, self._db_version)
        self.database = conn.get_interface()
        if self.database is None:
            raise RuntimeError(f"数据库初始化失败: {db_dir}")
        self.db_dir_actual = db_dir
        self._config['last_db_dir'] = db_dir
        _save_config(self._config)

        self.log("正在加载联系人...")
        self.contacts = list(self.database.get_contacts())
        self.log(f"加载完成: {len(self.contacts)} 个联系人")
        return db_dir

    def _get_wx_key_passphrase(self, uid):
        """自动从 wx_key 工具获取 passphrase。
        先检查缓存文件，没有则启动 wx_key.exe 等待其提取。"""
        import json as _json

        wx_key_prefs = os.path.join(os.environ.get('APPDATA', ''),
                                     'com.example', 'wx_key', 'shared_preferences.json')

        # 1. Try cached key first
        if os.path.exists(wx_key_prefs):
            try:
                with open(wx_key_prefs, 'r', encoding='utf-8') as f:
                    prefs = _json.load(f)
                cached_key = prefs.get('flutter.wechat_db_key', '')
                if len(cached_key) == 64 and all(c in '0123456789abcdef' for c in cached_key):
                    self.log(f"  从 wx_key 缓存读取到密钥")
                    return cached_key
            except Exception:
                pass

        # 2. Launch wx_key.exe and wait for it
        wx_key_exe = os.path.join(os.path.dirname(__file__), "tools", "wx_key", "wx_key.exe")
        if not os.path.exists(wx_key_exe):
            self.log(f"  wx_key.exe 未找到: {wx_key_exe}")
            # Fall back to manual input
            return self._ask_passphrase(uid)

        self.log(f"  启动 wx_key 自动提取密钥...")
        try:
            os.startfile(wx_key_exe)
        except Exception:
            self.log(f"  无法启动 wx_key.exe")
            return self._ask_passphrase(uid)

        # 3. Wait for wx_key to save the key (max 60 seconds)
        self.log(f"  等待 wx_key 完成提取（最多60秒）...")
        for _ in range(120):
            time.sleep(0.5)
            if os.path.exists(wx_key_prefs):
                try:
                    with open(wx_key_prefs, 'r', encoding='utf-8') as f:
                        prefs = _json.load(f)
                    key = prefs.get('flutter.wechat_db_key', '')
                    if len(key) == 64 and all(c in '0123456789abcdef' for c in key):
                        self.log(f"  wx_key 提取成功")
                        return key
                except Exception:
                    pass
            try:
                self.root.update()
            except Exception:
                pass

        self.log(f"  wx_key 超时，切换到手动输入")
        return self._ask_passphrase(uid)

    def _ask_passphrase(self, uid):
        """在主线程弹出输入框，让用户粘贴 wx_key 提取的密钥"""
        import threading as _th
        result = [None]
        event = _th.Event()

        def _show_dialog():
            dialog = tk.Toplevel(self.root)
            dialog.title("需要微信密钥")
            dialog.geometry("520x240")
            dialog.configure(bg=BG)
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.resizable(False, False)

            # Content
            tk.Label(dialog, text=f"微信 {uid} 的密钥未能自动提取",
                     font=("Microsoft YaHei", 11), bg=BG, fg=TEXT_PRIMARY).pack(pady=(15, 5))
            tk.Label(dialog, text="请运行 wx_key.exe 工具获取密钥，粘贴到下方：",
                     font=("Microsoft YaHei", 9), bg=BG, fg=TEXT_SECONDARY).pack()

            # Button to open wx_key
            btn_frame = tk.Frame(dialog, bg=BG)
            btn_frame.pack(pady=(5, 10))
            wx_key_path = os.path.join(os.path.dirname(__file__), "tools", "wx_key", "wx_key.exe")
            if os.path.exists(wx_key_path):
                tk.Button(btn_frame, text="一键打开 wx_key 提取密钥",
                         font=("Microsoft YaHei", 9), bg=PRIMARY, fg="white",
                         relief="flat", padx=15, pady=5,
                         command=lambda: os.startfile(wx_key_path)).pack(side=tk.LEFT, padx=5)

            # Passphrase entry
            entry_frame = tk.Frame(dialog, bg=BG)
            entry_frame.pack(pady=5)
            tk.Label(entry_frame, text="密钥:", font=("Microsoft YaHei", 10),
                     bg=BG, fg=TEXT_PRIMARY).pack(side=tk.LEFT, padx=(0, 8))
            entry_var = tk.StringVar()
            entry = tk.Entry(entry_frame, textvariable=entry_var, width=50,
                            font=("Consolas", 11))
            entry.pack(side=tk.LEFT)

            def _submit():
                val = entry_var.get().strip()
                if len(val) == 64 and all(c in '0123456789abcdefABCDEF' for c in val):
                    result[0] = val.lower()
                    dialog.destroy()
                else:
                    messagebox.showwarning("格式错误", "请输入64位十六进制密钥", parent=dialog)

            def _skip():
                dialog.destroy()

            btn_frame2 = tk.Frame(dialog, bg=BG)
            btn_frame2.pack(pady=(10, 0))
            tk.Button(btn_frame2, text="确定", font=("Microsoft YaHei", 10),
                     bg=PRIMARY, fg="white", relief="flat", padx=25, pady=5,
                     command=_submit).pack(side=tk.LEFT, padx=8)
            tk.Button(btn_frame2, text="跳过", font=("Microsoft YaHei", 10),
                     bg="#E0E0E0", fg=TEXT_PRIMARY, relief="flat", padx=25, pady=5,
                     command=_skip).pack(side=tk.LEFT, padx=8)

            dialog.protocol("WM_DELETE_WINDOW", _skip)

        self.root.after(0, _show_dialog)
        # Busy-wait processing GUI events until user responds (max 5 min)
        start = time.time()
        while result[0] is None and (time.time() - start) < 300:
            try:
                self.root.update()
            except Exception:
                pass
            time.sleep(0.05)
        return result[0]

    def _on_decrypt_done(self, db_dir):
        """解密成功后切换到主屏"""
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        # 更新账号信息
        info_path = os.path.join(db_dir, "info.json")
        if os.path.exists(info_path):
            try:
                with open(info_path, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                self._lbl_account.configure(text=f"账号: {info.get('nickname', info.get('uid', ''))}")
            except Exception:
                pass

        # 填充联系人列表
        self._populate_contacts()
        self._compute_stats()
        self._show_screen("main")
        self._update_adv_menu()

    def _on_decrypt_error(self, e):
        """解密失败后显示错误"""
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        self.set_loading_status(f"解析失败: {e}")
        self._btn_retry.pack(side="left", pady=(12, 0))

    # ── 联系人列表 ────────────────────────────────────────

    def _populate_contacts(self):
        self._contact_tree.delete(*self._contact_tree.get_children())
        self._all_contact_items = []
        for c in self.contacts:
            name = c.remark or c.nickname or c.uid
            msg_count = self.contact_msg_counts.get(c.uid, 0)
            count_str = f"{msg_count}条" if msg_count > 0 else ""
            item_id = self._contact_tree.insert("", "end", values=(name, count_str))
            self._all_contact_items.append((item_id, c.uid, name))
        self._lbl_contact_count.configure(text=f"共 {len(self.contacts)} 个联系人")
        self.set_status(f"已加载 {len(self.contacts)} 个联系人")

    def _filter_contacts(self):
        keyword = self._search_var.get().strip().lower()
        self._contact_tree.delete(*self._contact_tree.get_children())
        for item_id, uid, name in self._all_contact_items:
            if not keyword or keyword in name.lower() or keyword in uid.lower():
                msg_count = self.contact_msg_counts.get(uid, 0)
                count_str = f"{msg_count}条" if msg_count > 0 else ""
                new_id = self._contact_tree.insert("", "end", values=(name, count_str))
                # Update the item reference
                for i, (_, u, n) in enumerate(self._all_contact_items):
                    if u == uid:
                        self._all_contact_items[i] = (new_id, uid, name)
                        break

    # ── 联系人详情 ────────────────────────────────────────

    def _on_contact_select(self, event):
        sel = self._contact_tree.selection()
        if not sel:
            return
        # 找到对应的 uid
        uid = None
        for item_id, u, name in self._all_contact_items:
            if item_id == sel[0]:
                uid = u
                break
        if not uid:
            return
        self.selected_contact = self.database.get_contact_by_username(uid)
        c = self.selected_contact
        if c is None:
            return

        # 显示详情内容，隐藏占位提示
        self._detail_placeholder.pack_forget()
        self._detail_content.pack(fill="x")

        self._detail_labels["昵称"].configure(text=c.nickname or "-")
        self._detail_labels["uid"].configure(text=c.uid)
        self._detail_labels["备注"].configure(text=c.remark or "(无)")
        type_str = "群聊" if c.is_chatroom else "好友"
        self._detail_labels["类型"].configure(text=type_str)
        self._detail_labels["消息数"].configure(text=str(self.contact_msg_counts.get(c.uid, 0)))
        voice = self.contact_voice_counts.get(c.uid, 0)
        voiced = self.voice_transcribed_counts.get(c.uid, 0)
        self._detail_labels["语音数"].configure(text=str(voice))
        self._detail_labels["已转写"].configure(text=f"{voiced}/{voice}")

        self.set_status(f"已选择: {c.remark or c.nickname or c.uid}")

    # ── 消息/语音统计 ──────────────────────────────────────

    def _compute_stats(self):
        import hashlib
        import glob

        self.contact_msg_counts.clear()
        self.contact_voice_counts.clear()
        self.voice_transcribed_counts.clear()

        try:
            msg_dir = os.path.join(self.db_dir_actual, "message")
            if not os.path.isdir(msg_dir):
                return

            tbl_to_uid = {}
            for contact in self.contacts:
                tbl_to_uid[f"Msg_{hashlib.md5(contact.uid.encode()).hexdigest()}"] = contact.uid

            a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
            transcribed = set()
            if os.path.exists(a2t_path):
                conn = sqlite3.connect(a2t_path)
                transcribed = set(r[0] for r in conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
                conn.close()

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
                    pass

            self.root.after(0, self._populate_contacts)
        except Exception as e:
            pass

    # ── 导出 ──────────────────────────────────────────────

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

    # ── 语音转写（高级菜单）────────────────────────────────

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
        import hashlib
        import glob
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

    # ── 辅助操作 ──────────────────────────────────────────

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

    def _update_adv_menu(self):
        """更新高级菜单项的启用状态"""
        state = "normal" if self.database else "disabled"
        self._menu_adv.entryconfigure(0, state=state)
        self._menu_adv.entryconfigure(2, state=state)


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    root = tk.Tk()
    _ = ChatMemoirApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
