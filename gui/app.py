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
        # ponytail: WSLg/XWayland cannot render Tk's cursor-font glyphs, leaving
        # the pointer invisible. A bitmap (@xbm) cursor is raw pixel data and
        # composites fine. Applies to all widgets via the option database.
        # ponytail: WSLg/XWayland cannot render Tk's cursor-font glyphs, leaving
        # the pointer invisible. A bitmap (@xbm) cursor is raw pixel data and
        # composites fine. Windows renders cursors natively — skip there (UNC
        # backslashes also break the Tcl cursor spec).
        if os.name != 'nt':
            _xbm = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arrow.xbm')
            if os.path.exists(_xbm):
                try:
                    # source mask fg bg — cyan arrow, visible on light & dark
                    _cur = f"@{_xbm} {_xbm} #00E5FF black"
                    self.root.option_add('*cursor', _cur)
                    self.root.config(cursor=_cur)
                except Exception:
                    pass

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
        self._start_scheduler()
