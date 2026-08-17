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
        self.root.geometry("960x700")
        self.root.minsize(800, 560)
        self.root.configure(bg=BG)
        # ponytail: no custom cursor. The earlier @arrow.xbm bitmap cursor was
        # added for "invisible cursor" in WSLg, but WSLg renders custom X
        # cursors over RDP with mismatched hotspots/update cadence — the pointer
        # visibly jumps while moving. The real invisibility cause was the
        # unfocused/unraised window (fixed by the topmost flash below); with the
        # window focused the default cursor renders natively and smoothly.

        self._config = _load_config()

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
