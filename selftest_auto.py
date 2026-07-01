#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Self-test driver: instantiates the real ChatMemoirApp and triggers
_on_start() programmatically so the actual Tk GUI runs end-to-end with the
real progress bar. Hooks set_loading_progress / log / set_loading_status to
mirror every callback into selftest.log so we can verify bar==reality.

Ponytail: reuses ChatMemoirApp as-is, no test rig or mock objects. The only
override is wrapping the three logging/progress methods to tee to a file.
"""
import os
import sys
import time
import tkinter as tk

_PROJ = os.path.dirname(os.path.abspath(__file__))
_LOG = os.path.join(_PROJ, "selftest.log")


def main():
    with open(_LOG, "w", encoding="utf-8") as f:
        f.write(f"selftest started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    sys.path.insert(0, _PROJ)
    from gui.app import ChatMemoirApp

    root = tk.Tk()
    app = ChatMemoirApp(root)

    def _tee(tag, *args):
        line = f"[{time.strftime('%H:%M:%S')}] {tag} " + " ".join(str(a) for a in args) + "\n"
        try:
            with open(_LOG, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    _orig_slp = app.set_loading_progress
    _orig_sls = app.set_loading_status
    _orig_log = app.log

    def _slp(current, total, filename=""):
        pct = int(current / total * 100) if total else 0
        _tee("PROGRESS", f"{current}/{total} ({pct}%) file={os.path.basename(filename)[:40]}")
        return _orig_slp(current, total, filename)

    def _sls(text):
        _tee("STATUS", text)
        return _orig_sls(text)

    def _log(msg, loading=True):
        _tee("GUILog", msg)
        return _orig_log(msg, loading=loading)

    app.set_loading_progress = _slp
    app.set_loading_status = _sls
    app.log = _log

    def _auto_start():
        _tee("SELFTEST", "auto-invoking app._on_start()")
        try:
            app._on_start()
        except Exception as e:
            _tee("SELFTEST", f"_on_start raised: {e!r}")

    def _auto_exit():
        _tee("SELFTEST", "10min timer elapsed, exiting")
        try:
            root.destroy()
        except Exception:
            pass

    root.after(1500, _auto_start)
    root.after(600000, _auto_exit)

    _tee("SELFTEST", "entering mainloop, _on_start scheduled in 1.5s")
    root.mainloop()
    _tee("SELFTEST", "mainloop exited")


if __name__ == "__main__":
    main()
