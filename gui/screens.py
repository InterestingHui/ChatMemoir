"""ChatMemoir GUI 屏幕：欢迎屏、加载屏、主屏。"""

import os
import tkinter as tk
from tkinter import ttk, scrolledtext

from gui.constants import BG, CARD_BG, DANGER, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY


class ScreenMixin:
    """Mixin providing screen builder methods for ChatMemoirApp."""

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
