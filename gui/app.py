"""ChatMemoirApp — main GUI application class composed from mixins."""

import os
import sys

from gui.constants import BG, _load_config
from gui.styles import configure_styles
from gui.screens import ScreenMixin
from gui.menus import MenuMixin
from gui.logging import LoggingMixin
from gui.threads import ThreadMixin
from gui.decryption import DecryptionMixin
from gui.contacts import ContactMixin
from gui.export import ExportMixin
from gui.transcribe import TranscribeMixin
from gui.scheduler import SchedulerMixin
from gui.utils import UtilityMixin


def _hidpi_scale(root):
    """Estimate UI scale for HiDPI displays.

    Windows: real system DPI via API. WSLg/RDP: every physical-size source is
    fake (xdpyinfo mm is back-computed from 96 DPI, weston/xrandr report 0mm),
    so fall back to a resolution heuristic. A `ui_scale` value in
    .gui_config.json overrides this (calibration knob for odd setups).
    """
    if os.name == 'nt':
        try:
            import ctypes
            return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
        except Exception:
            return 1.0
    w = root.winfo_screenwidth()
    if w >= 3000:
        return 2.0
    if w >= 2200:
        return 1.5
    return 1.0


class ChatMemoirApp(
    ScreenMixin,
    MenuMixin,
    LoggingMixin,
    ThreadMixin,
    DecryptionMixin,
    ContactMixin,
    ExportMixin,
    TranscribeMixin,
    SchedulerMixin,
    UtilityMixin,
):
    def __init__(self, root):
        self.root = root
        self.root.title("ChatMemoir 留痕")
        self._config = _load_config()
        # HiDPI: 按物理 PPI 缩放（WSLg 谎报 96 DPI，高密度屏不缩放会太小）
        self._ui_scale = self._config.get("ui_scale") or _hidpi_scale(self.root)
        try:
            self.root.tk.call('tk', 'scaling', (96.0 / 72.0) * self._ui_scale)
        except Exception:
            pass
        self.root.geometry(f"{int(960 * self._ui_scale)}x{int(700 * self._ui_scale)}")
        self.root.minsize(int(800 * self._ui_scale), int(560 * self._ui_scale))
        self.root.configure(bg=BG)

        if getattr(sys, 'frozen', False):
            self._script_dir = os.path.dirname(sys.executable)
        else:
            self._script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

        configure_styles()
        self._build_menu()
        self._build_screens()
        # ponytail: WSLg 不渲染 Tk 的字体字形光标（默认光标=隐形），位图光标可见。
        # 必须"逐控件"设置：option_add 的 *cursor 会被控件类样式（如 Text 的
        # xterm，类模式比 *cursor 更specific）压过，鼠标扫过那些区域时光标在
        # 位图/隐形间切换，表现为指针"跳变"。统一形状后既可见又稳定。
        # Windows 原生渲染光标，跳过（UNC 反斜杠也会破坏 Tcl cursor 语法）。
        self._cursor_spec = None
        if os.name != 'nt':
            _xbm = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arrow.xbm')
            if os.path.exists(_xbm):
                try:
                    self._cursor_spec = f"@{_xbm} {_xbm} #00E5FF black"
                    self.root.option_add('*cursor', self._cursor_spec)
                    for _pat in ('*Text.cursor', '*Entry.cursor', '*TCombobox.cursor',
                                 '*TButton.cursor', '*Treeview.cursor'):
                        self.root.option_add(_pat, self._cursor_spec)
                    self.apply_cursor()
                except Exception:
                    pass
        self._show_screen("welcome")
        # ponytail: WSLg/XWayland 后台拉起的窗口不开在最前 — 闪一下 topmost
        # 把窗口顶到前台并抢焦点，否则用户找不到窗口（表现为"看不到/没置顶"）。
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(200, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass
        self._start_scheduler()
