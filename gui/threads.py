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
                # Capture traceback here in the worker thread — by the time
                # on_error runs on the main thread via root.after(), the
                # exception context is gone and format_exc() returns "NoneType: None".
                import traceback as _tb
                tb_str = _tb.format_exc()
                # ponytail: write to a sidecar log so we can see the real cause
                # even if e._gui_traceback doesn't survive the lambda closure.
                try:
                    import os as _os, time as _t
                    with open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'gui_worker_error.log'), 'a', encoding='utf-8') as _f:
                        _f.write(f"[{_t.strftime('%H:%M:%S')}] captured e={e!r} type={type(e).__name__}\n{tb_str}\n----\n")
                except Exception:
                    pass
                e._gui_traceback = tb_str
                if on_error:
                    # ponytail: default-arg capture — Python 3's `except ... as e`
                    # clears e (sets to None) at end of the except block, so a
                    # plain `lambda: on_error(e)` would deliver None to the
                    # callback by the time root.after() fires it on the main
                    # thread. `e=e` snapshots the reference now.
                    self.root.after(0, lambda e=e: on_error(e))
                else:
                    self.root.after(0, lambda e=e: self._show_error(e))
            finally:
                self.root.after(0, lambda: self.set_running(False))
        threading.Thread(target=wrapper, daemon=True).start()

    def _show_error(self, e, context=""):
        import traceback
        msg = f"{context}: {e}" if context else str(e)
        self.log(msg)
        self.log(traceback.format_exc())
