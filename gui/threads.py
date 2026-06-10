"""ChatMemoir GUI 线程管理。"""

import threading


class ThreadMixin:
    """Mixin providing background task runner for ChatMemoirApp."""

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
