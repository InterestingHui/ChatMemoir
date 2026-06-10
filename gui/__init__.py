"""ChatMemoir GUI package."""

from gui.app import ChatMemoirApp


def main():
    import tkinter as tk
    import multiprocessing
    multiprocessing.freeze_support()
    root = tk.Tk()
    _ = ChatMemoirApp(root)
    root.mainloop()
