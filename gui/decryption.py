"""ChatMemoir GUI 解密核心：密钥提取、数据库解密、账号加载。"""

import os
import time

from gui.constants import BG, DANGER, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, _resource_path, _save_config


class DecryptionMixin:
    """Mixin providing decryption workflow for ChatMemoirApp."""

    # ── 开始解析（一键解密）────────────────────────────────

    def _on_start(self):
        """开始一键解密"""
        self._show_screen("loading")
        self._loading_progress.start(10)
        self.set_loading_status("正在扫描微信进程...")
        self._loading_log.configure(state="normal")
        self._loading_log.delete("1.0", "end")
        self._loading_log.configure(state="disabled")
        self._btn_retry.pack_forget()
        self._btn_cancel.pack(side="right")
        self.run_task(self._auto_decrypt, on_done=self._on_decrypt_done, on_error=self._on_decrypt_error)

    def _fast_find_data_dir(self):
        """快速找到微信数据目录（不扫描密钥，避免卡死）。
        Returns (uid, data_dir, nick_name) or None.
        data_dir 格式与 dump_session_info_v4 一致：父目录（不含 db_storage）。"""
        import psutil
        for proc in psutil.process_iter(['name', 'pid']):
            name = proc.name()
            if name not in ('Weixin.exe', 'WeChatAppEx.exe'):
                continue
            try:
                for mm in proc.memory_maps(grouped=False):
                    p = mm.path or ''
                    idx = p.find('db_storage')
                    if idx != -1:
                        db_storage_path = p[:idx + len('db_storage')] + '\\'
                        # 与 dump_session_info_v4 一致：data_dir = 去掉最后两层
                        # db_storage_path = ...\wxid_xxxx\db_storage\
                        # data_dir = ...\wxid_xxxx（与原始代码一致）
                        parts = db_storage_path.rstrip('\\').split('\\')
                        uid = '_'.join(parts[-2].split('_')[0:-1])
                        data_dir = '\\'.join(parts[:-1])  # 父目录，不含 db_storage
                        nick_name = uid
                        self.log(f"  快速定位到微信数据目录 (PID={proc.pid}): {data_dir}")
                        return uid, data_dir, nick_name
            except Exception:
                continue
        return None

    def _auto_decrypt(self):
        """自动检测微信版本、提取密钥、解密数据库、加载联系人"""
        from memoir.decrypt import get_info_v4, get_info_v3
        from memoir.decrypt import decrypt_v4, decrypt_v3
        from memoir import Me, ArchiveConnection
        import json as _json

        # 1. 检查管理员权限
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            self.log("请以管理员身份运行本程序")
            self.log("右键 ChatMemoir.exe → 以管理员身份运行")
            raise PermissionError("需要管理员权限才能读取微信进程内存")

        # 2. 检查 wx_key 缓存，有缓存则走快速路径（跳过耗时的 YARA/偏移扫描）
        wx_passphrase = self._read_wx_key_cache()
        if wx_passphrase:
            self.set_loading_status("正在定位微信数据目录...")
            self.log("检测到 wx_key 密钥缓存，使用快速解密流程...")
            fast_info = self._fast_find_data_dir()
            if fast_info:
                uid, data_dir, nick_name = fast_info
                import sys as _sys
                from memoir.decrypt.common import SessionInfo
                si = SessionInfo()
                si.uid = uid
                si.data_dir = data_dir
                si.nick_name = nick_name
                si.key = None  # 触发 wx_key fallback
                session_info_list = [si]
                self._db_version = 4
            else:
                session_info_list = []
        else:
            # 无缓存 — 走完整扫描流程（YARA + 偏移量 + multiprocessing）
            self.set_loading_status("正在扫描微信进程...")
            self.log("正在扫描微信 v4 进程 (Weixin.exe / WeChatAppEx.exe)...")
            session_info_list = get_info_v4()
            self._db_version = 4

        if not session_info_list and not wx_passphrase:
            self.set_loading_status("尝试 v3 微信进程...")
            self.log("v4 未找到，尝试 v3 (WeChat.exe)...")
            vl_path = _resource_path(os.path.join("memoir", "decrypt", "version_list.json"))
            with open(vl_path, "r", encoding="utf-8") as f:
                version_list = _json.loads(f.read())
            session_info_list = get_info_v3(version_list)
            self._db_version = 3

        if not session_info_list:
            self.log("未找到已登录的微信进程")
            self.log("请确认：1) 微信已打开  2) 已扫码登录  3) 以管理员身份运行本程序")
            raise RuntimeError("未找到已登录的微信进程，请先打开微信并扫码登录")

        # 3. 解密每个账号的数据库
        seen_uids = set()
        db_dir = None
        for session_info in session_info_list:
            uid = session_info.uid
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)

            self.log(f"发现微信账号: {session_info.nick_name or uid} ({uid})")
            key = session_info.key
            if not key:
                # Try wx_key automatic extraction
                passphrase = self._get_wx_key_passphrase(uid)
                if not passphrase:
                    self.log(f"  {uid}: 未能获取密钥，跳过")
                    continue
                # Derive per-DB keys from passphrase
                import hashlib as _hl
                key_map = {}
                for root, dirs, files in os.walk(session_info.data_dir):
                    for fn in files:
                        if fn.endswith('.db'):
                            fp = os.path.join(root, fn)
                            if os.path.getsize(fp) < 4096:
                                continue
                            with open(fp, 'rb') as fh:
                                salt = fh.read(16)
                            dk = _hl.pbkdf2_hmac('sha512', bytes.fromhex(passphrase), salt, 256000, dklen=32)
                            # key path relative to data_dir, matching decrypt_db_files lookup
                            rel_dir = os.path.relpath(root, session_info.data_dir)
                            key_map[os.path.join(rel_dir, fn)] = dk.hex()
                session_info.key_map = key_map
                session_info.key = list(key_map.values())[0] if key_map else passphrase
                key = session_info.key
                self.log(f"  已从 passphrase 派生 {len(key_map)} 个数据库密钥")

            self.set_loading_status(f"正在解密 {uid} 的数据库...")
            self.set_loading_progress(0, 1, "")
            self.log("正在解密数据库...")
            if self._db_version == 4:
                from memoir.decrypt.decrypt_dat import get_decode_code_v4
                me = Me()
                me.data_dir = session_info.data_dir
                me.uid = uid
                me.name = session_info.nick_name
                me.xor_key = get_decode_code_v4(session_info.data_dir)
                output_dir = os.path.join(self._script_dir, uid)
                total, failed = decrypt_v4.decrypt_db_files(
                    key, src_dir=session_info.data_dir, dest_dir=output_dir,
                    key_map=getattr(session_info, 'key_map', None) or None,
                    skip_existing=True,
                    progress_callback=self.set_loading_progress)
                if failed:
                    self.log(f"  警告: {failed}/{total} 个数据库解密失败")
                info_dir = os.path.join(output_dir, "db_storage")
            else:
                me = Me()
                me.data_dir = session_info.data_dir
                me.uid = uid
                me.name = session_info.nick_name
                output_dir = os.path.join(self._script_dir, uid)
                decrypt_v3.decrypt_db_files(key, src_dir=session_info.data_dir,
                                            dest_dir=output_dir, skip_existing=True)
                info_dir = os.path.join(output_dir, "Msg")

            # 从 contact.db 读取昵称（v4）
            if self._db_version == 4:
                import sqlite3
                contact_db = os.path.join(info_dir, "contact", "contact.db")
                if os.path.exists(contact_db):
                    try:
                        conn = sqlite3.connect(contact_db)
                        cur = conn.cursor()
                        cur.execute("SELECT nick_name FROM contact WHERE username = ?", [uid])
                        row = cur.fetchone()
                        conn.close()
                        if row and row[0]:
                            me.name = row[0]
                    except Exception:
                        pass

            import json as _json2
            os.makedirs(info_dir, exist_ok=True)
            with open(os.path.join(info_dir, "info.json"), "w", encoding="utf-8") as f:
                _json2.dump(me.to_json(), f, ensure_ascii=False, indent=4)

            db_dir = os.path.abspath(info_dir)
            self._config['last_db_dir'] = db_dir
            _save_config(self._config)
            self.log(f"解密完成: {db_dir}")

        if not db_dir:
            self.log("所有账号均未成功解密，可能原因：")
            self.log("  - 微信未登录（请扫码登录后再试）")
            self.log("  - wx_key 未提取到密钥（请手动运行 tools/wx_key/wx_key.exe）")
            raise RuntimeError("未能解密任何数据库，请确认微信已登录且 wx_key 提取成功")

        # 4. 加载联系人
        self.set_loading_status("正在加载联系人...")
        self.set_loading_progress(1, 1, "")
        self.log("正在连接数据库...")
        conn = ArchiveConnection(db_dir, self._db_version)
        self.database = conn.get_interface()
        if self.database is None:
            raise RuntimeError(f"数据库初始化失败: {db_dir}")
        self.db_dir_actual = db_dir
        self._config['last_db_dir'] = db_dir
        _save_config(self._config)

        self.log("正在加载联系人...")
        self.contacts = list(self.database.get_contacts())
        self.log(f"加载完成: {len(self.contacts)} 个联系人")
        return db_dir

    def _read_wx_key_cache(self):
        """读取 wx_key 缓存的 passphrase（仅检查缓存，不启动 wx_key）。"""
        import json as _json
        wx_key_prefs = os.path.join(os.environ.get('APPDATA', ''),
                                     'com.example', 'wx_key', 'shared_preferences.json')
        if os.path.exists(wx_key_prefs):
            try:
                with open(wx_key_prefs, 'r', encoding='utf-8') as f:
                    prefs = _json.load(f)
                cached_key = prefs.get('flutter.wechat_db_key', '')
                if len(cached_key) == 64 and all(c in '0123456789abcdef' for c in cached_key):
                    return cached_key
            except Exception:
                pass
        return None

    def _get_wx_key_passphrase(self, uid):
        """自动从 wx_key 工具获取 passphrase。
        先检查缓存文件，没有则启动 wx_key.exe 等待其提取。"""
        import json as _json

        wx_key_prefs = os.path.join(os.environ.get('APPDATA', ''),
                                     'com.example', 'wx_key', 'shared_preferences.json')

        # 1. Try cached key first
        if os.path.exists(wx_key_prefs):
            try:
                with open(wx_key_prefs, 'r', encoding='utf-8') as f:
                    prefs = _json.load(f)
                cached_key = prefs.get('flutter.wechat_db_key', '')
                if len(cached_key) == 64 and all(c in '0123456789abcdef' for c in cached_key):
                    self.log(f"  从 wx_key 缓存读取到密钥")
                    return cached_key
            except Exception:
                pass

        # 2. Launch wx_key.exe and wait for it
        wx_key_exe = os.path.join(os.path.dirname(__file__), "..", "tools", "wx_key", "wx_key.exe")
        if not os.path.exists(wx_key_exe):
            self.log(f"  wx_key.exe 未找到: {wx_key_exe}")
            # Fall back to manual input
            return self._ask_passphrase(uid)

        self.log(f"  启动 wx_key 自动提取密钥...")
        try:
            os.startfile(wx_key_exe)
        except Exception:
            self.log(f"  无法启动 wx_key.exe")
            return self._ask_passphrase(uid)

        # 3. Wait for wx_key to save the key (max 60 seconds)
        self.log(f"  等待 wx_key 完成提取（最多60秒）...")
        for _ in range(120):
            time.sleep(0.5)
            if os.path.exists(wx_key_prefs):
                try:
                    with open(wx_key_prefs, 'r', encoding='utf-8') as f:
                        prefs = _json.load(f)
                    key = prefs.get('flutter.wechat_db_key', '')
                    if len(key) == 64 and all(c in '0123456789abcdef' for c in key):
                        self.log(f"  wx_key 提取成功")
                        return key
                except Exception:
                    pass
            try:
                self.root.update()
            except Exception:
                pass

        self.log(f"  wx_key 超时，切换到手动输入")
        return self._ask_passphrase(uid)

    def _ask_passphrase(self, uid):
        """在主线程弹出输入框，让用户粘贴 wx_key 提取的密钥"""
        import threading as _th
        import tkinter as tk
        from tkinter import messagebox

        result = [None]
        event = _th.Event()

        def _show_dialog():
            dialog = tk.Toplevel(self.root)
            dialog.title("需要微信密钥")
            dialog.geometry("520x240")
            dialog.configure(bg=BG)
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.resizable(False, False)

            # Content
            tk.Label(dialog, text=f"微信 {uid} 的密钥未能自动提取",
                     font=("Microsoft YaHei", 11), bg=BG, fg=TEXT_PRIMARY).pack(pady=(15, 5))
            tk.Label(dialog, text="请运行 wx_key.exe 工具获取密钥，粘贴到下方：",
                     font=("Microsoft YaHei", 9), bg=BG, fg=TEXT_SECONDARY).pack()

            # Button to open wx_key
            btn_frame = tk.Frame(dialog, bg=BG)
            btn_frame.pack(pady=(5, 10))
            wx_key_path = os.path.join(os.path.dirname(__file__), "..", "tools", "wx_key", "wx_key.exe")
            if os.path.exists(wx_key_path):
                tk.Button(btn_frame, text="一键打开 wx_key 提取密钥",
                         font=("Microsoft YaHei", 9), bg=PRIMARY, fg="white",
                         relief="flat", padx=15, pady=5,
                         command=lambda: os.startfile(wx_key_path)).pack(side=tk.LEFT, padx=5)

            # Passphrase entry
            entry_frame = tk.Frame(dialog, bg=BG)
            entry_frame.pack(pady=5)
            tk.Label(entry_frame, text="密钥:", font=("Microsoft YaHei", 10),
                     bg=BG, fg=TEXT_PRIMARY).pack(side=tk.LEFT, padx=(0, 8))
            entry_var = tk.StringVar()
            entry = tk.Entry(entry_frame, textvariable=entry_var, width=50,
                            font=("Consolas", 11))
            entry.pack(side=tk.LEFT)

            def _submit():
                val = entry_var.get().strip()
                if len(val) == 64 and all(c in '0123456789abcdefABCDEF' for c in val):
                    result[0] = val.lower()
                    dialog.destroy()
                else:
                    messagebox.showwarning("格式错误", "请输入64位十六进制密钥", parent=dialog)

            def _skip():
                dialog.destroy()

            btn_frame2 = tk.Frame(dialog, bg=BG)
            btn_frame2.pack(pady=(10, 0))
            tk.Button(btn_frame2, text="确定", font=("Microsoft YaHei", 10),
                     bg=PRIMARY, fg="white", relief="flat", padx=25, pady=5,
                     command=_submit).pack(side=tk.LEFT, padx=8)
            tk.Button(btn_frame2, text="跳过", font=("Microsoft YaHei", 10),
                     bg="#E0E0E0", fg=TEXT_PRIMARY, relief="flat", padx=25, pady=5,
                     command=_skip).pack(side=tk.LEFT, padx=8)

            dialog.protocol("WM_DELETE_WINDOW", _skip)

        self.root.after(0, _show_dialog)
        # Busy-wait processing GUI events until user responds (max 5 min)
        start = time.time()
        while result[0] is None and (time.time() - start) < 300:
            try:
                self.root.update()
            except Exception:
                pass
            time.sleep(0.05)
        return result[0]

    def _on_decrypt_done(self, db_dir):
        """解密成功后切换到主屏"""
        import json as _json
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        # 更新账号信息
        info_path = os.path.join(db_dir, "info.json")
        if os.path.exists(info_path):
            try:
                with open(info_path, 'r', encoding='utf-8') as f:
                    info = _json.load(f)
                self._lbl_account.configure(text=f"账号: {info.get('nickname', info.get('uid', ''))}")
            except Exception:
                pass

        # 填充联系人列表
        self._populate_contacts()
        self._compute_stats()
        self._show_screen("main")
        self._update_adv_menu()

    def _on_decrypt_error(self, e):
        """解密失败后显示错误"""
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        self.set_loading_status(f"解析失败: {e}")
        self._btn_retry.pack(side="left", pady=(12, 0))
