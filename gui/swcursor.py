"""软件光标：WSLg/msrdc 不渲染远程指针时的代码级兜底。

原理：窗口像素的 RDP 渲染是正常的（界面能看到），坏的只是"指针通道"。
因此隐藏 X 指针（cursor="none"），在指针旁画一个 override-redirect 箭头小窗。

两个环境事实决定的实现细节（实测 WSLg RAIL）：
1. RAIL 输入路由无视 X ShapeInput → 点击穿透改用"偏移放置"：窗口放在
   指针 +2,+2 处，指针点永远不在窗口矩形内，任何点击都落在真实控件上。
2. Tk 窗口不透明 → 用 X11 ShapeBounding 位掩码把窗口裁成箭头形状
   （RAIL 不支持裁剪则退化为浅灰方块+箭头，仍可用）。
仅 Linux/WSLg 启用；Windows 原生渲染正常，全部跳过。
"""

import tkinter as tk

ARROW_PTS = [(0, 0), (0, 16), (4, 12.5), (6.8, 18.5), (9.3, 17.3),
             (6.6, 11.4), (11.5, 11.4)]


def _rasterize(pts, w, h):
    """多边形栅格化为 XBM 位图字节（LSB-first per row）。"""
    def inside(x, y):
        n, j, c = len(pts), len(pts) - 1, False
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                c = not c
            j = i
        return c
    bits = bytearray(((w + 7) // 8) * h)
    row_bytes = (w + 7) // 8
    for y in range(h):
        for x in range(w):
            if inside(x + 0.5, y + 0.5):
                bits[y * row_bytes + x // 8] |= 1 << (x % 8)
    return bytes(bits)


class SoftwareCursor:
    def __init__(self, root, scale=1.0):
        self.root = root
        self.size = int(20 * scale)
        self._last = (-1, -1)

        root.option_add('*cursor', 'none')
        root.configure(cursor='none')

        size = self.size
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.cv = tk.Canvas(self.win, width=size, height=size,
                            highlightthickness=0, bd=0, bg='#F0F2F5')
        self.cv.pack(fill='both', expand=True)
        s = size / 20.0
        pts = [(x * s, y * s) for x, y in ARROW_PTS]
        self.cv.create_polygon(pts, fill='white', outline='black', width=1.5)
        self.win.withdraw()

        root.bind_all('<Motion>', self._on_motion, add='+')
        self._watchdog()

    def _on_motion(self, event):
        x, y = event.x_root, event.y_root
        if (x, y) == self._last:
            return
        self._last = (x, y)
        if not self.win.winfo_viewable():
            self.win.deiconify()
            self.win.after(60, self._clip_window)
        # +2,+2 偏移：指针点位于窗口矩形外 → 点击永远穿透到真实控件
        self.win.geometry(f'+{x + 2}+{y + 2}')

    def _clip_window(self):
        """X11 ShapeBounding：把窗口可见区域裁成箭头形状。"""
        if not self.win.winfo_viewable():
            return
        try:
            import ctypes
            from ctypes import c_char_p, c_int, c_uint, c_ulong, c_void_p
            x11 = ctypes.CDLL('libX11.so.6')
            xshape = ctypes.CDLL('libXext.so.6')
            x11.XOpenDisplay.restype = c_void_p
            x11.XOpenDisplay.argtypes = [c_char_p]
            x11.XDefaultRootWindow.restype = c_ulong
            x11.XDefaultRootWindow.argtypes = [c_void_p]
            x11.XFlush.argtypes = [c_void_p]
            x11.XCloseDisplay.argtypes = [c_void_p]
            x11.XCreatePixmapFromBitmapData.restype = c_ulong
            x11.XCreatePixmapFromBitmapData.argtypes = [
                c_void_p, c_ulong, c_char_p, c_uint, c_uint,
                c_ulong, c_ulong, c_uint]
            xshape.XShapeCombineMask.argtypes = [
                c_void_p, c_ulong, c_int, c_int, c_int, c_ulong, c_int]
            d = x11.XOpenDisplay(None)
            if not d:
                return
            data = _rasterize([(x * self.size / 20.0, y * self.size / 20.0)
                               for x, y in ARROW_PTS], self.size, self.size)
            pm = x11.XCreatePixmapFromBitmapData(
                d, self.win.winfo_id(), data, self.size, self.size, 1, 0, 1)
            if pm:
                xshape.XShapeCombineMask(d, self.win.winfo_id(), 0, 0, 0, pm, 0)
            x11.XFreePixmap.argtypes = [c_void_p, c_ulong]
            x11.XFreePixmap(d, pm)
            x11.XFlush(d)
            x11.XCloseDisplay(d)
        except Exception:
            pass

    def _watchdog(self):
        """指针离开应用所有窗口时隐藏软件光标（避免残留悬浮箭头）。"""
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
        if px >= 0 and py >= 0:
            inside = False
            for w in self.root.winfo_children() + [self.root]:
                try:
                    if not isinstance(w, (tk.Tk, tk.Toplevel)) or not w.winfo_ismapped():
                        continue
                    x1, y1 = w.winfo_rootx(), w.winfo_rooty()
                    if x1 <= px < x1 + w.winfo_width() and y1 <= py < y1 + w.winfo_height():
                        inside = True
                        break
                except Exception:
                    continue
            if not inside and self.win.winfo_viewable():
                self.win.withdraw()
        self.root.after(200, self._watchdog)
