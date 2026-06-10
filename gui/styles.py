"""ChatMemoir GUI 样式配置。"""

from tkinter import ttk

from gui.constants import BG, BORDER, CARD_BG, PRIMARY, PRIMARY_HOVER, TEXT_PRIMARY, TEXT_SECONDARY


def configure_styles():
    """Configure ttk.Style with ChatMemoir theme."""
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

    return style
