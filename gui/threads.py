"""ChatMemoir GUI 线程管理。"""

import queue
import threading


class ThreadMixin:
    """Mixin providing background task runner for ChatMemoirApp."""

    def _start_ui_poller(self):
        """主线程轮询队列，把工作线程投递的 UI 回调调度回 Tk 主循环。

        ponytail: Python 3.12 / Tk 8.6 下从非主线程调用 root.after() 会抛
        ``RuntimeError: main thread is not in main loop``（Tcl 解释器线程亲和）。
        因此 worker 线程不能直接 after()，改投递到 queue，由主线程每 50ms
        排空执行。这是全部跨线程 UI 更新的唯一通道。
        """
        self._ui_queue = queue.Queue()

        def _drain():
            while True:
                try:
                    fn = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:
                    pass
            self.root.after(50, _drain)

        self.root.after(50, _drain)

    def _ui_call(self, fn):
        """线程安全地把 fn 调度到主线程执行（替代 root.after(0, fn)）。"""
        try:
            self._ui_queue.put_nowait(fn)
        except Exception:
            pass

    def set_running(self, flag):
        self.running = flag
        state = "disabled" if flag else "normal"
        self._btn_export.configure(state=state)
        btn_transcribe = getattr(self, '_btn_transcribe', None)
        if btn_transcribe is not None:
            btn_transcribe.configure(state=state)

    def run_task(self, target, on_done=None, on_error=None):
        """后台任务 + UI 回调"""
        def wrapper():
            try:
                self._ui_call(lambda: self.set_running(True))
                result = target()
                if on_done:
                    self._ui_call(lambda: on_done(result))
            except Exception as e:
                # Capture traceback here in the worker thread — by the time
                # on_error runs on the main thread via _ui_call, the
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
                    # callback by the time _ui_call fires it on the main
                    # thread. `e=e` snapshots the reference now.
                    self._ui_call(lambda e=e: on_error(e))
                else:
                    self._ui_call(lambda e=e: self._show_error(e))
            finally:
                self._ui_call(lambda: self.set_running(False))
        threading.Thread(target=wrapper, daemon=True).start()

    def _show_error(self, e, context=""):
        import traceback
        msg = f"{context}: {e}" if context else str(e)
        self.log(msg)
        self.log(traceback.format_exc())
