"""ChatMemoir GUI 解密核心：密钥提取、数据库解密、账号加载。"""

import os
import time

from gui.constants import BG, DANGER, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, _resource_path, _save_config


class DecryptionMixin:
    """Mixin providing decryption workflow for ChatMemoirApp."""

    # ── 开始解析（一键解密）────────────────────────────────

    def _on_start(self):
        """开始一键解密"""
        # ponytail: 防重入 — 启动自动触发（app.py root.after）与用户手点
        # 「开始解析」可能在加载屏上叠加；重复跑一遍解密纯属浪费，第二击
        # 直接吞掉。
        if getattr(self, '_state', '') == 'decrypting':
            return
        self._state = "decrypting"
        self._show_screen("loading")
        # ponytail: no marquee during scan phase. Earlier revision called
        # start(10) to bounce the block as an "alive" signal, but user
        # feedback was that a bouncing bar reads as "progress not matching
        # reality". Keep the bar in determinate mode at 0% — status text +
        # log widget already convey liveness, the bar only moves when there
        # is real X/Y to show (first set_loading_progress call from PBKDF2).
        self._loading_progress.configure(mode="determinate")
        self._loading_progress["value"] = 0
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

    # ── 本地镜像（Windows pythonw @ UNC 项目场景）────────────
    #
    # ponytail: 为什么需要镜像 — GUI 由计划任务用 Windows pythonw 从
    # \\wsl.localhost UNC 路径启动（9p 慢速通道）：
    #   1) 解密产物写 UNC 极慢；旧方案在加载前还要把 3GB copytree 到
    #      %TEMP%（每次启动重来一遍，又几分钟）；
    #   2) UNC 上 SQLite 文件锁不稳（'database is locked'）。
    # 两者都靠"解密直写本地盘"根治：镜像放 %LOCALAPPDATA%\ChatMemoir\<uid>
    # （非 %TEMP%，不会被磁盘清理误删，跨启动复用），SQLite 直连本地路径。
    # 加载后迁移期 <script_dir>/<uid> 的旧 UNC 产物仍在，手动回退可用。

    @staticmethod
    def _local_mirror_root():
        """本地镜像根目录（Windows）。非 Windows 返回 None。"""
        import sys as _sys
        if _sys.platform != 'win32':
            return None
        base = os.environ.get('LOCALAPPDATA') or os.path.join(
            os.environ.get('USERPROFILE', ''), 'AppData', 'Local')
        if not base or not os.path.isdir(base):
            return None
        return os.path.join(base, 'ChatMemoir')

    def _mirror_dir_for(self, uid):
        """当前账号的本地镜像 db_storage 目录（不存在则 None）。"""
        root = self._local_mirror_root()
        if not root or not uid:
            return None
        d = os.path.join(root, uid, 'db_storage')
        return d if os.path.isdir(d) else None

    def _verify_passphrase_on(self, passphrase, db_path):
        """单库 PBKDF2+HMAC 验证 passphrase（对齐 _try_passphrase_decrypt_refresh
        第 3 步的算法）。返回 True/False/None（文件缺失等无法验证）。"""
        import hashlib as _hl
        import hmac as _hmac
        import struct as _struct
        KEY_SIZE, SALT_SIZE, PAGE_SIZE = 32, 16, 4096
        IV_SIZE, HMAC_SIZE, AES_BLOCK = 16, 64, 16
        if not os.path.exists(db_path):
            return None
        try:
            with open(db_path, 'rb') as fh:
                buf = fh.read(PAGE_SIZE)
        except OSError:
            return None
        if len(buf) < PAGE_SIZE:
            return None
        salt = buf[:SALT_SIZE]
        pp_bytes = bytes.fromhex(passphrase)
        dk = _hl.pbkdf2_hmac('sha512', pp_bytes, salt, 256000, dklen=KEY_SIZE)
        mac_salt = bytes(x ^ 0x3a for x in salt)
        mac_key = _hl.pbkdf2_hmac('sha512', dk, mac_salt, 2, dklen=KEY_SIZE)
        reserve = ((IV_SIZE + HMAC_SIZE + AES_BLOCK - 1) // AES_BLOCK) * AES_BLOCK
        mac = _hmac.new(mac_key, buf[SALT_SIZE:PAGE_SIZE - reserve + IV_SIZE], _hl.sha512)
        mac.update(_struct.pack('<I', 1))
        off = PAGE_SIZE - reserve + IV_SIZE
        return mac.digest() == buf[off:off + HMAC_SIZE]

    def _try_fast_load_fresh_snapshot(self):
        """新鲜度门（Windows 路径）：镜像足够新（落后实时数据 <10 分钟）时
        直接返回镜像目录，跳过解密。返回 (db_dir or None, live_uid or None)。

        快进条件（全部满足）：
          1) 微信在登录（_fast_find_data_dir 找得到数据目录）→ 拿到实时
             热库 mtime 作为"数据现在时刻"；
          2) 镜像 db_storage/<info.json 的 mtime ≥ 数据时刻 - 10min；
          3) 镜像里有完整的 contact.db。
        不满足 → 返回 None，调用方走正常解密（解密完会刷新镜像 info.json），
        下一轮（10 分钟内再点）就能秒进。"""
        live = self._fast_find_data_dir()
        if not live:
            return None, None
        uid, _data_dir, _nick = live
        self.log(f"  微信在线: {uid}")
        # 实时热库最新 mtime = "微信数据现在写到哪了"
        now_marker = 0.0
        try:
            db_storage_src = os.path.join(_data_dir, 'db_storage')
            for rel in ('session\\session.db', 'message\\message_0.db',
                        'contact\\contact.db', 'message\\message_fts.db'):
                try:
                    m = os.path.getmtime(os.path.join(db_storage_src, *rel.split('\\')))
                except OSError:
                    continue
                if m > now_marker:
                    now_marker = m
        except OSError:
            return None, uid
        if now_marker <= 0:
            return None, uid
        mirror = self._mirror_dir_for(uid)
        if not mirror:
            return None, uid
        info_json = os.path.join(mirror, 'info.json')
        if (os.path.exists(os.path.join(mirror, 'contact', 'contact.db'))
                and os.path.exists(info_json)
                and os.path.getmtime(info_json) >= now_marker - 10 * 60):
            self.log(f"  本地镜像已是最新（10 分钟内），直接加载: {mirror}")
            return mirror, uid
        return None, uid

    def _auto_decrypt(self):
        """自动检测微信版本、提取密钥、解密数据库、加载联系人"""
        import sys as _sys
        from memoir import Me, ArchiveConnection
        import json as _json

        # ponytail: 实时内存解密仅 Windows 可用。此前在 WSL 上也先试再捕
        # AttributeError("module 'ctypes' has no attribute 'windll'")，把预期
        # 的平台差异当异常打进日志吓人 — 非 Windows 直接走三级回退，一行干净日志。
        if _sys.platform == 'win32':
            return self._auto_decrypt_live()
        # ── 新鲜度门（WSL 侧，与 Windows 侧 _try_fast_load_fresh_snapshot 对称）──
        self._db_version = 4
        live_uid_gate, gate_mtime = self._detect_live_wechat_uid()
        if live_uid_gate:
            fresh = self._fresh_snapshot_dir(live_uid_gate, gate_mtime)
            if fresh:
                self.set_loading_status("已是最新数据，正在加载联系人...")
                self.set_loading_progress(1, 1, "")
                self.log(f"快照已是最新，直接加载: {fresh}")
                conn = ArchiveConnection(fresh, 4)
                self.database = conn.get_interface()
                if self.database is None:
                    raise RuntimeError(f"数据库初始化失败: {fresh}")
                self.db_dir_actual = fresh
                self._config['last_db_dir'] = fresh
                _save_config(self._config)
                self.contacts = list(self.database.get_contacts())
                self.log(f"加载完成: {len(self.contacts)} 个联系人")
                return fresh
        self.log("WSL 环境：跳过内存扫描，使用已存密钥增量刷新当前账号数据...")
        # 三级回退：① 历史 passphrase 本地直解（快，密钥未轮换时）→
        # ② Windows 管理员任务内存扫 key 重解（慢但万能）→ ③ 本地旧快照。
        db_dir = (self._try_passphrase_decrypt_refresh()
                  or self._try_native_decrypt_refresh()
                  or self._try_load_existing_db_dir())
        if not db_dir:
            raise RuntimeError(
                "解密失败且未找到已解密数据库。\n"
                "请在 Windows 上运行本程序完成解密。"
            )
        # ponytail: 身份断言 — 三级回退全靠 _detect_live_wechat_uid 的
        # 最新-mtime 启发式选账号，切换账号瞬间旧账号登出 flush 会让检测
        # 翻错方向，整条链路就静默加载旧账号数据。加载提交前再验一次：
        # 目录账号 ≠ 当前登录账号 → 明确报错让用户稍后重试，绝不静默串号。
        live_uid2, _ = self._detect_live_wechat_uid()
        if live_uid2 and f'/{live_uid2}/' not in db_dir.replace('\\', '/'):
            self.log(f"  账号不匹配: 当前登录 {live_uid2}，待加载目录 {db_dir}")
            raise RuntimeError(
                f"当前登录的微信账号是 {live_uid2}，但解析流程选中了其他账号的数据"
                f"（{db_dir}）。账号刚切换时检测有几秒窗口，请稍等片刻后重试。"
            )
        self._db_version = 4
        self.set_loading_status("正在加载联系人...")
        self.set_loading_progress(1, 1, "")
        self.log(f"加载已解密数据库: {db_dir}")
        conn = ArchiveConnection(db_dir, self._db_version)
        self.database = conn.get_interface()
        if self.database is None:
            raise RuntimeError(f"数据库初始化失败: {db_dir}")
        self.db_dir_actual = db_dir
        self._config['last_db_dir'] = db_dir
        _save_config(self._config)
        self.contacts = list(self.database.get_contacts())
        self.log(f"加载完成: {len(self.contacts)} 个联系人")
        return db_dir

    def _auto_decrypt_live(self):
        """实时解密: 快速路径 = 新鲜度门 → wx_key 缓存 → 本地镜像增量解密。

        ponytail: 提速重构 — 旧流程每次启动都：walk 整个微信账号目录（含
        attach/ 海量附件，几十秒）→ 逐库 PBKDF2（~0.5s×30）→ 解密产物写
        UNC（9p 慢）→ 加载前再把 3GB copytree 到 %TEMP%（每次重来）＝
        用户点「开始解析」后要等 5-8 分钟。新流程：
          1) 新鲜度门：镜像落后实时数据 <10min → 直接加载（秒进）；
          2) 只扫 db_storage/（不碰 attach/）；
          3) per-db key salt 缓存（keycache.json，salt 命中免 PBKDF2）；
          4) 解密直写 %LOCALAPPDATA%/ChatMemoir/<uid>/db_storage 本地镜像，
             SQLite 直连本地路径 — UNC 写和 %TEMP% 全量拷贝都消失。
        旧 YARA/多级回退逻辑保留在 _auto_decrypt_live_full()（异常时兜底）。"""
        from memoir import Me, ArchiveConnection
        import json as _json

        # 1. 检查管理员权限（读微信进程内存定位数据目录需要）
        import ctypes as _ct
        if not _ct.windll.shell32.IsUserAnAdmin():
            self.log("请以管理员身份运行本程序")
            self.log("右键 ChatMemoir.exe → 以管理员身份运行")
            raise PermissionError("需要管理员权限才能读取微信进程内存")

        # 2. 新鲜度门：镜像够新直接秒进
        self._db_version = 4
        fast_dir, live_uid_fast = self._try_fast_load_fresh_snapshot()
        if fast_dir:
            self.set_loading_status("已是最新数据，正在加载联系人...")
            self.set_loading_progress(1, 1, "")
            self.log(f"加载本地镜像: {fast_dir}")
            conn = ArchiveConnection(fast_dir, 4)
            self.database = conn.get_interface()
            if self.database is None:
                raise RuntimeError(f"数据库初始化失败: {fast_dir}")
            self.db_dir_actual = fast_dir
            self._config['last_db_dir'] = fast_dir
            _save_config(self._config)
            self.contacts = list(self.database.get_contacts())
            self.log(f"加载完成: {len(self.contacts)} 个联系人")
            return fast_dir

        # 3. wx_key 缓存密钥（无缓存走完整兜底流程）
        wx_passphrase = self._read_wx_key_cache()
        if not wx_passphrase:
            self.log("未找到 wx_key 缓存密钥，转完整扫描流程...")
            return self._auto_decrypt_live_full()

        # 4. 快速定位微信数据目录
        self.set_loading_status("正在定位微信数据目录...")
        self.log("检测到 wx_key 密钥缓存，使用快速解密流程...")
        fast_info = self._fast_find_data_dir()
        if not fast_info:
            self.log("未找到已登录的微信进程")
            self.log("请确认：1) 微信已打开  2) 已扫码登录  3) 以管理员身份运行本程序")
            raise RuntimeError("未找到已登录的微信进程，请先打开微信并扫码登录")
        uid, data_dir, nick_name = fast_info
        self.log(f"微信账号: {nick_name or uid} ({uid})")

        # 账号一致性：镜像账号 ≠ 当前登录账号 → 走兜底（含旧镜像迁移判断）
        mirror_root = self._local_mirror_root()
        mirror_uid_dir = os.path.join(mirror_root, uid) if mirror_root else None
        if mirror_uid_dir:
            mirror_info = os.path.join(mirror_uid_dir, 'db_storage', 'info.json')
            if os.path.exists(mirror_info):
                try:
                    import json as _json_mi
                    with open(mirror_info, 'r', encoding='utf-8') as f:
                        mi = _json_mi.load(f)
                    if mi.get('username') and mi['username'] != uid:
                        self.log(f"  镜像属于账号 {mi['username']}，与当前 {uid} 不符，走完整流程")
                        return self._auto_decrypt_live_full()
                except Exception:
                    pass

        # 5. 收集 db_storage 下的 .db（不碰 attach/）
        import hashlib as _hl
        db_storage_src = os.path.join(data_dir, 'db_storage')
        db_candidates = []
        for root, dirs, files in os.walk(db_storage_src):
            for fn in files:
                if not fn.endswith('.db'):
                    continue
                fp = os.path.join(root, fn)
                try:
                    if os.path.getsize(fp) < 4096:
                        continue
                except OSError:
                    continue
                db_candidates.append((root, fn))
        total = len(db_candidates)

        # 6. per-db key 缓存（salt 命中免 PBKDF2）
        keycache_path = (os.path.join(mirror_root, uid, 'keycache.json')
                         if mirror_root else None)
        keycache = {}
        if keycache_path and os.path.exists(keycache_path):
            try:
                import json as _json_kc
                with open(keycache_path, 'r', encoding='utf-8') as f:
                    _kc = _json_kc.load(f)
                keycache = _kc if isinstance(_kc, dict) else {}
            except Exception:
                keycache = {}
        pp_bytes = bytes.fromhex(wx_passphrase)
        key_map = {}
        misses = []
        for root, fn in db_candidates:
            rel = os.path.join(os.path.relpath(root, db_storage_src), fn)
            with open(os.path.join(root, fn), 'rb') as fh:
                s = fh.read(16)
            cached = keycache.get(rel) or {}
            if cached.get('salt') == s.hex() and cached.get('key'):
                key_map[rel] = cached['key']
            else:
                misses.append((rel, s, fn))
        if misses:
            self.set_loading_status(f"正在派生数据库密钥（{len(misses)}/{total} 个新文件，每个约0.5s）...")
            self.set_loading_progress(0, len(misses), "")
            for i, (rel, s, fn) in enumerate(misses):
                key_map[rel] = _hl.pbkdf2_hmac('sha512', pp_bytes, s, 256000, dklen=32).hex()
                keycache[rel] = {'salt': s.hex(), 'key': key_map[rel]}
                self.set_loading_progress(i + 1, len(misses), fn)
        else:
            self.log(f"  {total} 个库的 key 全部缓存命中，免 PBKDF2")
        if keycache_path:
            try:
                import json as _json_kcw
                os.makedirs(os.path.dirname(keycache_path), exist_ok=True)
                with open(keycache_path, 'w', encoding='utf-8') as f:
                    _json_kcw.dump(keycache, f, ensure_ascii=False)
            except OSError:
                pass

        # 7. 解密直写本地镜像（增量；本地盘写 + 免 UNC + 免 %TEMP% 拷贝）
        mirror_dir = (os.path.join(mirror_root, uid, 'db_storage')
                      if mirror_root else os.path.join(self._script_dir, uid, 'db_storage'))
        self.set_loading_status(f"正在解密 {uid} 的当前数据...")
        self.set_loading_progress(0, 1, "")
        from memoir.decrypt import decrypt_v4
        total_done, failed = decrypt_v4.decrypt_db_files(
            wx_passphrase, src_dir=db_storage_src, dest_dir=mirror_dir,
            key_map=key_map, skip_existing=True,
            progress_callback=self.set_loading_progress)
        if failed:
            self.log(f"  警告: {failed}/{total_done} 个数据库解密失败")
        if not os.path.exists(os.path.join(mirror_dir, 'contact', 'contact.db')):
            if total_done > 0 and failed == total_done and keycache_path and os.path.exists(keycache_path):
                self.log("  密钥可能已轮换，清除缓存密钥（下次重新派生）")
                try:
                    os.remove(keycache_path)
                except OSError:
                    pass
            self.log("  快速流程未能产出 contact.db，转完整扫描流程")
            return self._auto_decrypt_live_full()

        # 8. 刷新镜像 info.json（mtime = 新鲜度门依据；保留 xor_key 等导出依赖）
        info = {}
        for p in (os.path.join(mirror_dir, 'info.json'),
                  os.path.join(self._script_dir, uid, 'db_storage', 'info.json'),
                  os.path.join(self._script_dir, uid, 'info.json')):
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        info = _json.load(f)
                    break
                except Exception:
                    continue
        info.setdefault('username', uid)
        info['nickname'] = info.get('nickname') or nick_name or uid
        info['wx_dir'] = data_dir
        info['data_dir'] = data_dir
        if not info.get('xor_key'):
            try:
                from memoir.decrypt.decrypt_dat import get_decode_code_v4
                info['xor_key'] = get_decode_code_v4(data_dir)
            except Exception:
                info['xor_key'] = 0
        image_aes_key = self._read_wx_key_image_key()
        if image_aes_key:
            info['image_aes_key'] = image_aes_key
        os.makedirs(mirror_dir, exist_ok=True)
        with open(os.path.join(mirror_dir, 'info.json'), 'w', encoding='utf-8') as f:
            _json.dump(info, f, ensure_ascii=False, indent=4)

        db_dir = mirror_dir
        self._config['last_db_dir'] = path_str = db_dir
        _save_config(self._config)
        self.log(f"解密完成: {db_dir}")

        # 9. 加载联系人（本地路径直连）
        self.set_loading_status("正在加载联系人...")
        self.set_loading_progress(1, 1, "")
        self.log("正在连接数据库...")
        conn = ArchiveConnection(db_dir, 4)
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

    def _auto_decrypt_live_full(self):

        # 2. 无快速路径可走 — 完整扫描流程（YARA + 偏移量 + multiprocessing）
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
                # ponytail: two-pass PBKDF2 derivation. First pass collects .db
                # candidates so we can show real X/Y progress; previously this was
                # a single os.walk loop with no progress_callback, leaving the bar
                # in start(10) cycling mode for the full 30-60s PBKDF2 duration.
                import hashlib as _hl
                db_candidates = []
                for root, dirs, files in os.walk(session_info.data_dir):
                    for fn in files:
                        if not fn.endswith('.db'):
                            continue
                        fp = os.path.join(root, fn)
                        if os.path.getsize(fp) < 4096:
                            continue
                        db_candidates.append((root, fn))
                total = len(db_candidates)
                self.set_loading_status(f"正在派生数据库密钥（{total} 个，每个约0.5s）...")
                # Trigger stop() on the marquee bar before the first iteration;
                # total=0 still calls stop() so the bar doesn't cycle on empty dirs.
                self.set_loading_progress(0, max(total, 1), "")
                key_map = {}
                for i, (root, fn) in enumerate(db_candidates):
                    fp = os.path.join(root, fn)
                    with open(fp, 'rb') as fh:
                        salt = fh.read(16)
                    dk = _hl.pbkdf2_hmac('sha512', bytes.fromhex(passphrase), salt, 256000, dklen=32)
                    rel_dir = os.path.relpath(root, session_info.data_dir)
                    key_map[os.path.join(rel_dir, fn)] = dk.hex()
                    self.set_loading_progress(i + 1, total, fn)
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
                # ponytail: 解密产物落本地镜像（%LOCALAPPDATA%）而非 UNC 项目
                # 目录 — 免 9p 慢写 + 免加载前的 %TEMP% 全量拷贝。无镜像根
                # （异常环境）才退回 <script_dir>/<uid> 旧布局。
                _mirror_root_full = self._local_mirror_root()
                output_dir = (os.path.join(_mirror_root_full, uid) if _mirror_root_full
                              else os.path.join(self._script_dir, uid))
                total, failed = decrypt_v4.decrypt_db_files(
                    key, src_dir=session_info.data_dir, dest_dir=output_dir,
                    key_map=getattr(session_info, 'key_map', None) or None,
                    skip_existing=True,
                    progress_callback=self.set_loading_progress)
                if failed:
                    self.log(f"  警告: {failed}/{total} 个数据库解密失败")
                # ponytail: YARA fallback when every cache-derived key failed.
                # The wx_key cache passphrase can go stale (WeChat rotates keys
                # on re-login / version upgrade); the GUI used to abort here.
                # Scan WeChat memory for a fresh passphrase via get_info_v4(),
                # re-derive per-DB keys via PBKDF2, and retry decrypt_db_files.
                # Mirrors verify_pipeline.py's step_yara_fallback.
                if total > 0 and failed == total:
                    # ponytail: stale cache passphrase (WeChat rotates keys on
                    # re-login). Before hitting the expensive YARA scan (which
                    # can take hours with 500k+ candidates), try refreshing
                    # wx_key to get the new passphrase.
                    self.set_loading_status("缓存密钥过期，正在刷新 wx_key...")
                    self.log("  cache 密钥全部失败，重新运行 wx_key 获取新密钥...")
                    # Force wx_key re-run by clearing the stale cache check
                    fresh_passphrase = self._get_wx_key_passphrase(uid, force_refresh=True)
                    if fresh_passphrase:
                        import hashlib as _hl2
                        db_candidates2 = []
                        for root, dirs, files in os.walk(session_info.data_dir):
                            for fn in files:
                                if not fn.endswith('.db'):
                                    continue
                                fp = os.path.join(root, fn)
                                if os.path.getsize(fp) < 4096:
                                    continue
                                db_candidates2.append((root, fn))
                        total2 = len(db_candidates2)
                        self.set_loading_status(f"正在用新密钥重新派生（{total2} 个）...")
                        self.set_loading_progress(0, max(total2, 1), "")
                        key_map2 = {}
                        for i, (root, fn) in enumerate(db_candidates2):
                            fp = os.path.join(root, fn)
                            with open(fp, 'rb') as fh:
                                salt = fh.read(16)
                            dk = _hl2.pbkdf2_hmac('sha512', bytes.fromhex(fresh_passphrase), salt, 256000, dklen=32)
                            rel_dir = os.path.relpath(root, session_info.data_dir)
                            key_map2[os.path.join(rel_dir, fn)] = dk.hex()
                            self.set_loading_progress(i + 1, total2, fn)
                        key = key_map2.get(list(key_map2.keys())[0], fresh_passphrase) if key_map2 else fresh_passphrase
                        session_info.key_map = key_map2
                        session_info.key = list(key_map2.values())[0] if key_map2 else fresh_passphrase
                        self.log(f"  wx_key 刷新成功，重新解密...")
                        total, failed = decrypt_v4.decrypt_db_files(
                            fresh_passphrase, src_dir=session_info.data_dir, dest_dir=output_dir,
                            key_map=key_map2, skip_existing=False,
                            progress_callback=self.set_loading_progress)
                        self.log(f"  wx_key 重试结果: {total - failed}/{total} 成功")
                    if total > 0 and failed == total:
                        self.set_loading_status("正在通过 YARA 扫描提取新密钥...")
                        self.log("  wx_key 刷新也失败，启动 YARA 内存扫描（可能需要较长时间）...")
                        import hashlib as _hl_yara
                        from memoir.decrypt import get_info_v4
                        yara_infos = []
                        try:
                            yara_infos = get_info_v4() or []
                        except Exception as e:
                            self.log(f"  YARA 扫描异常: {e!r}")
                        yara_session = None
                        for info in yara_infos:
                            if info.key and info.uid == uid:
                                yara_session = info
                                break
                        if yara_session is None and yara_infos:
                            # exact-uid miss → take first session with a key
                            for info in yara_infos:
                                if info.key:
                                    yara_session = info
                                    break
                        if yara_session is None or not yara_session.key:
                            raise RuntimeError(
                                f"全部 {total} 个数据库解密失败，且 YARA 内存扫描未能提取新密钥"
                                f"（找到 {len(yara_infos)} 个 session，均无可用 key）。"
                                f"WeChat 4.1.8.29 兼容性问题，YARA regex 可能需要更新，"
                                f"或微信未登录。"
                            )
                        fresh_passphrase = yara_session.key
                        self.log(f"  YARA 找到新密钥，前缀: {fresh_passphrase[:16]}...")
                        # Re-collect db candidates (cheap ~1s walk) and re-derive keys.
                        yara_candidates = []
                        for root, dirs, files in os.walk(session_info.data_dir):
                            for fn in files:
                                if not fn.endswith('.db'):
                                    continue
                                fp = os.path.join(root, fn)
                                try:
                                    if os.path.getsize(fp) < 4096:
                                        continue
                                except OSError:
                                    continue
                                yara_candidates.append((root, fn))
                        yara_total = len(yara_candidates)
                        self.set_loading_status(f"正在用 YARA 密钥派生 {yara_total} 个数据库密钥...")
                        self.set_loading_progress(0, max(yara_total, 1), "")
                        yara_key_map = {}
                        for i, (root, fn) in enumerate(yara_candidates):
                            fp = os.path.join(root, fn)
                            with open(fp, 'rb') as fh:
                                salt = fh.read(16)
                            dk = _hl_yara.pbkdf2_hmac('sha512', bytes.fromhex(fresh_passphrase), salt, 256000, dklen=32)
                            rel_dir = os.path.relpath(root, session_info.data_dir)
                            yara_key_map[os.path.join(rel_dir, fn)] = dk.hex()
                            self.set_loading_progress(i + 1, yara_total, fn)
                        self.log(f"  从 YARA 密钥重新派生 {len(yara_key_map)} 个密钥，重试解密...")
                        # Force re-decrypt: skip_existing=False overwrites the 0-byte
                        # stubs the cache-path attempt left behind.
                        total, failed = decrypt_v4.decrypt_db_files(
                            fresh_passphrase, src_dir=session_info.data_dir, dest_dir=output_dir,
                            key_map=yara_key_map, skip_existing=False,
                            progress_callback=self.set_loading_progress)
                        self.log(f"  YARA 重试结果: {total - failed}/{total} 成功")
                        if total > 0 and failed == total:
                            raise RuntimeError(
                                f"YARA 提取的密钥也无法解密任何数据库（{failed}/{total} 失败）。"
                                f"WeChat 4.1.8.29 兼容性问题：YARA regex 命中内存但密钥仍不匹配，"
                                f"需要更新 regex 模式或 key 解析逻辑。"
                            )
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
            me.image_aes_key = self._read_wx_key_image_key() or ''
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
        # ponytail: SQLite file locking via \\wsl.localhost\ UNC paths is flaky
        # on Windows ('database is locked' on audio2text_db.create() even with
        # no other process holding the file). If db_dir is on a UNC path,
        # shallow-copy to %TEMP% and use the local path for the ArchiveConnection.
        # Affects users running the project from a WSL UNC root.
        connect_dir = db_dir
        if db_dir.startswith('\\\\') or db_dir.lower().startswith('//'):
            # ponytail: 改用持久镜像而非 mkdtemp — 旧方案每次启动把 3GB
            # copytree 到 %TEMP%（几分钟），且 %TEMP% 会被磁盘清理误删。
            # %LOCALAPPDATA%\ChatMemoir\<uid> 跨启动复用：首次拷一次，
            # 之后用 mtime 增量同步（只拷比镜像新的文件），秒级完成。
            import shutil as _sh
            mirror_root = self._local_mirror_root()
            if mirror_root:
                uid_name = None
                for seg in db_dir.replace('/', '\\').split('\\'):
                    if seg.startswith('wxid_') or seg.startswith('gh_'):
                        uid_name = '_'.join(seg.split('_')[:-1]) if seg.count('_') > 1 else seg
                        break
                if not uid_name:
                    uid_name = os.path.basename(os.path.dirname(db_dir.rstrip('\\/')))
                mirror_dir = os.path.join(mirror_root, uid_name, 'db_storage')
                os.makedirs(mirror_dir, exist_ok=True)
                copied = skipped = 0
                for root, dirs, files in os.walk(db_dir):
                    rel = os.path.relpath(root, db_dir)
                    dst_root = os.path.join(mirror_dir, rel) if rel != '.' else mirror_dir
                    os.makedirs(dst_root, exist_ok=True)
                    for fn in files:
                        src_fp = os.path.join(root, fn)
                        dst_fp = os.path.join(dst_root, fn)
                        try:
                            if (os.path.exists(dst_fp)
                                    and os.path.getmtime(dst_fp) >= os.path.getmtime(src_fp)):
                                skipped += 1
                                continue
                            _sh.copy2(src_fp, dst_fp)
                            copied += 1
                        except OSError:
                            continue
                self.log(f"  UNC 路径 SQLite 锁不稳，已镜像到本地: {mirror_dir}（新增 {copied} 个文件，复用 {skipped} 个）")
                connect_dir = mirror_dir
            else:
                import tempfile as _tf
                local_root = _tf.mkdtemp(prefix='chatmemoir_gui_')
                local_dir = _sh.copytree(db_dir, os.path.join(local_root, 'db_storage'))
                self.log(f"  UNC 路径 SQLite 锁不稳，已复制到本地: {local_dir}")
                connect_dir = local_dir
        self.log("正在连接数据库...")
        conn = ArchiveConnection(connect_dir, self._db_version)
        self.database = conn.get_interface()
        if self.database is None:
            raise RuntimeError(f"数据库初始化失败: {connect_dir}")
        self.db_dir_actual = db_dir  # keep the original (UNC) path for display
        self._config['last_db_dir'] = db_dir
        _save_config(self._config)

        self.log("正在加载联系人...")
        self.contacts = list(self.database.get_contacts())
        self.log(f"加载完成: {len(self.contacts)} 个联系人")
        return db_dir

    def _detect_live_wechat_uid(self):
        """Detect the currently-logged-in WeChat account from Windows-side
        xwechat_files db mtimes (WSL /mnt/c path only). Returns the bare uid
        (dir-suffix stripped) or None when detection is unavailable.

        ponytail: relative-newest heuristic — stat a few hot db files per
        wxid_* account dir and pick the most recently written. A full os.walk
        over /mnt/c (9p) is far too slow. If two accounts are logged in at
        the same time, the newest write wins; upgrade path would be parsing
        session.db content for the active session.

        Returns (uid, newest_hot_mtime) or (None, 0.0)."""
        import glob as _glob
        import time as _time
        # Hot files WeChat touches constantly while logged in (relative to
        # the wxid_* account root).
        _HOT = ('db_storage/session/session.db',
                'db_storage/message/message_fts.db',
                'db_storage/message/message_0.db',
                'db_storage/contact/contact.db')
        bases = _glob.glob('/mnt/c/Users/*/xwechat_files')
        bases += _glob.glob('/mnt/c/Users/*/Documents/xwechat_files')
        best_uid, best_mtime = None, 0.0
        for base in bases:
            for acct in _glob.glob(os.path.join(base, 'wxid_*')):
                name = os.path.basename(acct)
                if not name.startswith('wxid_'):
                    continue
                newest = 0.0
                for rel in _HOT:
                    try:
                        m = os.path.getmtime(os.path.join(acct, rel))
                    except OSError:
                        continue
                    if m > newest:
                        newest = m
                if newest > best_mtime:
                    best_mtime = newest
                    # wxid_xxx_452d -> wxid_xxx (same normalization as
                    # _fast_find_data_dir on the Windows path)
                    best_uid = '_'.join(name.split('_')[:-1])
        if best_uid is None or _time.time() - best_mtime > 86400:
            return None, 0.0
        return best_uid, best_mtime

    def _fresh_snapshot_dir(self, live_uid, live_mtime):
        """新鲜度门：快照落后实时数据 <10 分钟时直接返回其 db_storage 目录。

        ponytail: 10min 窗口是体验粒度标定旋钮 — 要更实时就调小；每次点击都
        触发解密难以接受就调大（解密已增量页级化，稳态秒级）。快照位置查两处：
        1-decrypt 的 <proj>/<uid>/ 和本地 passphrase 直解的 decrypted/<uid>/
        （两个刷新路径各自的输出约定）。
        """
        proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for base in (os.path.join(proj, live_uid), os.path.join(proj, 'decrypted', live_uid)):
            db_storage = os.path.join(base, 'db_storage')
            info_json = os.path.join(base, 'info.json')
            if not os.path.exists(os.path.join(db_storage, 'contact', 'contact.db')):
                continue
            if not os.path.exists(info_json):
                continue
            if os.path.getmtime(info_json) >= live_mtime - 10 * 60:
                return db_storage
        return None

    def _try_passphrase_decrypt_refresh(self):
        """WSL 本地直解：历史 passphrase 对当前 /mnt/c 加密库仍有效时，
        直接在 Linux 侧增量解密当前登录账号的数据（纯 pycryptodome，不需要
        Windows 内存扫描）。passphrase 失效（重登/换号轮换）则返回 None，
        调用方继续走管理员任务路径。

        实测：6 月 passphrase 至今有效（密钥不轮换是常态），29 个库 2.9G，
        PBKDF2 ~15s + AES 增量解密分钟级 — 比 YARA 内存扫描（小时级）快两个量级。
        """
        import glob as _glob
        import hashlib as _hl
        import json as _json
        from memoir.decrypt import decrypt_v4

        live_uid, live_mtime = self._detect_live_wechat_uid()
        if not live_uid:
            return None
        fresh = self._fresh_snapshot_dir(live_uid, live_mtime)
        if fresh:
            self.log(f"  快照已是最新，直接加载: {fresh}")
            return fresh

        # 1. 定位 /mnt/c 上的账号目录（wxid_xxx_YYYY 后缀形式）
        acct_dir = None
        for base in _glob.glob('/mnt/c/Users/*/xwechat_files') + _glob.glob('/mnt/c/Users/*/Documents/xwechat_files'):
            for d in _glob.glob(os.path.join(base, f'{live_uid}_*')):
                if '_'.join(os.path.basename(d).split('_')[:-1]) == live_uid:
                    acct_dir = d
                    break
            if acct_dir:
                break
        if not acct_dir:
            self.log(f"  未找到账号 {live_uid} 的数据目录，跳过本地直解")
            return None

        # 2. 从历史 info.json 找 passphrase（新 layout 优先，旧 decrypted/ 兜底）
        proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        passphrase = None
        # 图片 dat 解密的异或密钥只存在 Windows 侧解密写的 info.json 里
        # （passphrase 命中即 break 的循环可能到不了那个文件），先单独扫一遍。
        xor_key = None
        for info_path in (os.path.join(proj, live_uid, 'db_storage', 'info.json'),
                          os.path.join(proj, live_uid, 'info.json')):
            try:
                _ik = _json.load(open(info_path, 'r', encoding='utf-8')).get('xor_key')
                if _ik:
                    xor_key = _ik
                    break
            except Exception:
                continue
        for info_path in (os.path.join(proj, live_uid, 'info.json'),
                          os.path.join(proj, live_uid, 'db_storage', 'info.json'),
                          os.path.join(proj, 'decrypted', live_uid, 'info.json')):
            if not os.path.exists(info_path):
                continue
            try:
                info = _json.load(open(info_path, 'r', encoding='utf-8'))
                pp = info.get('passphrase', '')
                if info.get('username') == live_uid and len(pp) == 64:
                    passphrase = pp
                    self.log(f"  使用历史 passphrase ({os.path.basename(os.path.dirname(info_path))}/)")
                    break
            except Exception:
                continue
        if not passphrase:
            self.log("  无历史 passphrase，跳过本地直解")
            return None

        # 3. 快速验证 passphrase 对当前加密库仍有效（1 次 PBKDF2，~0.5s）
        verify_src = os.path.join(acct_dir, 'db_storage', 'session', 'session.db')
        if not os.path.exists(verify_src):
            for root, _dirs, files in os.walk(os.path.join(acct_dir, 'db_storage')):
                if any(f.endswith('.db') for f in files):
                    verify_src = os.path.join(root, next(f for f in files if f.endswith('.db')))
                    break
        KEY_SIZE, SALT_SIZE, PAGE_SIZE = 32, 16, 4096
        IV_SIZE, HMAC_SIZE, AES_BLOCK = 16, 64, 16
        import hmac as _hmac
        import struct as _struct
        buf = open(verify_src, 'rb').read(PAGE_SIZE)
        salt = buf[:SALT_SIZE]
        pp_bytes = bytes.fromhex(passphrase)
        dk = _hl.pbkdf2_hmac('sha512', pp_bytes, salt, 256000, dklen=KEY_SIZE)
        mac_salt = bytes(x ^ 0x3a for x in salt)
        mac_key = _hl.pbkdf2_hmac('sha512', dk, mac_salt, 2, dklen=KEY_SIZE)
        reserve = ((IV_SIZE + HMAC_SIZE + AES_BLOCK - 1) // AES_BLOCK) * AES_BLOCK
        mac = _hmac.new(mac_key, buf[SALT_SIZE:PAGE_SIZE - reserve + IV_SIZE], _hl.sha512)
        mac.update(_struct.pack('<I', 1))
        off = PAGE_SIZE - reserve + IV_SIZE
        if mac.digest() != buf[off:off + HMAC_SIZE]:
            self.log("  历史 passphrase 已失效（密钥轮换），转管理员任务路径")
            return None
        self.log("  历史 passphrase 对当前数据验证通过，本地增量解密...")

        # 4. 派生每个库的 key（salt = 文件前 16 字节），带进度。
        # ponytail: 只 walk db_storage/ — .db 全在这里；walk 整个账号目录会
        # 连带 attach/ 的海量附件元数据，9p 下列举一次要几分钟。
        db_storage_src = os.path.join(acct_dir, 'db_storage')
        db_candidates = []
        for root, _dirs, files in os.walk(db_storage_src):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    if not fn.endswith('.db') or os.path.getsize(fp) < PAGE_SIZE:
                        continue
                except OSError:
                    continue
                db_candidates.append((root, fn))
        total = len(db_candidates)
        # 每文件 key 缓存：salt 命中即免 PBKDF2（~0.5s/个，29 个库共 ~15s）。
        # 第 3 步已先验证 passphrase 对当前数据有效 → 缓存 key 必然同源，salt
        # 匹配即可复用。明文 key 与 info.json 的明文 passphrase 同目录同威胁
        # 模型（本机单用户），不再额外加密。
        keycache_path = os.path.join(proj, 'decrypted', live_uid, 'keycache.json')
        try:
            _kc = _json.load(open(keycache_path, 'r', encoding='utf-8'))
            keycache = _kc if isinstance(_kc, dict) else {}
        except Exception:
            keycache = {}
        key_map = {}
        misses = []  # (rel_path, salt, fn) 缓存未命中、需要 PBKDF2 的
        for root, fn in db_candidates:
            rel = os.path.join(os.path.relpath(root, db_storage_src), fn)
            with open(os.path.join(root, fn), 'rb') as fh:
                s = fh.read(SALT_SIZE)
            cached = keycache.get(rel) or {}
            if cached.get('salt') == s.hex() and cached.get('key'):
                key_map[rel] = cached['key']
            else:
                misses.append((rel, s, fn))
        if misses:
            self.set_loading_status(f"正在派生数据库密钥（{len(misses)}/{total} 个新文件，每个约0.5s）...")
            self.set_loading_progress(0, len(misses), "")
            for i, (rel, s, fn) in enumerate(misses):
                key_map[rel] = _hl.pbkdf2_hmac('sha512', pp_bytes, s, 256000, dklen=KEY_SIZE).hex()
                keycache[rel] = {'salt': s.hex(), 'key': key_map[rel]}
                self.set_loading_progress(i + 1, len(misses), fn)
        else:
            self.log(f"  {total} 个库的 key 全部缓存命中，免 PBKDF2")
        # 合并写回（旧条目保留；已删文件的陈旧条目无害，不清理）
        os.makedirs(os.path.dirname(keycache_path), exist_ok=True)
        with open(keycache_path, 'w', encoding='utf-8') as f:
            _json.dump(keycache, f, ensure_ascii=False)

        # 5. 增量解密到 decrypted/<uid>/db_storage/（沿用既有快照位置，
        # skip_existing 复用未变文件；src/db 基准一致 → key_map 相对路径吻合）
        dest_dir = os.path.join(proj, 'decrypted', live_uid, 'db_storage')
        self.set_loading_status(f"正在解密 {live_uid} 的当前数据...")
        self.set_loading_progress(0, 1, "")
        total_done, failed = decrypt_v4.decrypt_db_files(
            passphrase, src_dir=db_storage_src, dest_dir=dest_dir,
            key_map=key_map, skip_existing=True,
            progress_callback=self.set_loading_progress)
        if failed:
            self.log(f"  警告: {failed}/{total_done} 个数据库解密失败")
        db_storage = dest_dir
        if not os.path.exists(os.path.join(db_storage, 'contact', 'contact.db')):
            self.log("  本地直解未产出 contact.db，转管理员任务路径")
            return None

        # 6. 刷新 info.json（更新 mtime 供新鲜度门短路；wx_dir 指向当前账号目录）
        info = {}
        parent_info = os.path.join(proj, 'decrypted', live_uid, 'info.json')
        if os.path.exists(parent_info):
            try:
                info = _json.load(open(parent_info, 'r', encoding='utf-8'))
            except Exception:
                info = {}
        info.setdefault('username', live_uid)
        info['wx_dir'] = acct_dir.replace('/mnt/c/', 'C:\\').replace('/', '\\')
        info['passphrase'] = passphrase
        if xor_key is not None:
            info['xor_key'] = xor_key  # 图片 dat 解密需要；缺失会让导出图片全丢
        image_aes_key = self._read_wx_key_image_key()
        if image_aes_key:
            info['image_aes_key'] = image_aes_key
        os.makedirs(db_storage, exist_ok=True)
        for p in (parent_info, os.path.join(db_storage, 'info.json')):
            with open(p, 'w', encoding='utf-8') as f:
                _json.dump(info, f, ensure_ascii=False, indent=4)
        self.log(f"  本地直解完成: {db_storage}")
        return db_storage

    def _try_native_decrypt_refresh(self):
        """WSL/Linux 下触发 Windows 侧管理员任务重新解密当前登录账号。

        通过 .wxdecrypt-native-trigger sentinel + ChatMemoirAdmin 计划任务
        （免 UAC）运行 run_native_decrypt.py → 1-decrypt.py（内存扫 key +
        增量解密到 <proj>/<uid>/db_storage/）。轮询 wxdecrypt.log 的
        "exit code:" 完成标记，把新增日志行实时转发到 GUI 日志区。
        成功返回新解密目录，失败/超时返回 None（调用方回退旧快照）。
        """
        import subprocess
        import time as _time
        schtasks = '/mnt/c/Windows/System32/schtasks.exe'
        if not os.path.exists(schtasks):
            self.log("  未找到 schtasks.exe（非 WSL 环境？），跳过刷新")
            return None
        live_uid, live_mtime = self._detect_live_wechat_uid()
        if not live_uid:
            self.log("  未检测到正在登录的微信账号（24h 内无数据写入），跳过刷新")
            return None
        fresh = self._fresh_snapshot_dir(live_uid, live_mtime)
        if fresh:
            self.log(f"  快照已是最新，直接加载: {fresh}")
            return fresh

        proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(proj, 'wxdecrypt.log')
        fresh_dir = os.path.join(proj, live_uid, 'db_storage')
        fresh_info = os.path.join(fresh_dir, 'info.json')

        offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        # 记录触发时刻 — 完成后要求 info.json 比它新，防止把 6 月的旧产物当新结果
        triggered_at = _time.time()

        sentinel = os.path.join(proj, '.wxdecrypt-native-trigger')
        with open(sentinel, 'w') as f:
            f.write(str(int(triggered_at)))
        try:
            r = subprocess.run([schtasks, '/Run', '/TN', 'ChatMemoirAdmin'],
                               capture_output=True, timeout=30)
        except Exception as e:
            self.log(f"  schtasks 启动异常: {e!r}")
            return None
        if r.returncode != 0:
            # 计划任务已在跑（上一次触发的解密还没结束）→ 改为等它跑完
            self.log("  计划任务启动返回非 0，检查是否有解密正在进行...")
            if not (os.path.exists(log_path)
                    and _time.time() - os.path.getmtime(log_path) < 90):
                self.log(f"  无进行中的解密（rc={r.returncode}），无法刷新")
                return None
            self.log("  已有解密在跑，等待其完成...")

        self.set_loading_status(f"正在重新解密当前账号 {live_uid}（Windows 管理员任务）...")
        self.log("  已触发 Windows 侧原生解密，增量模式，可能需要几分钟...")

        # ponytail: 20 分钟上限。历史全量跑 ~12 分钟（含失败的 YARA 扫描）；
        # 增量重跑主要耗时在内存扫 key + PBKDF2，超时则回退旧快照不硬等。
        deadline = _time.time() + 1200
        pos = offset
        while _time.time() < deadline:
            _time.sleep(3)
            if not os.path.exists(log_path):
                continue
            size = os.path.getsize(log_path)
            if size <= pos:
                continue
            with open(log_path, 'rb') as f:
                f.seek(pos)
                chunk = f.read(size - pos)
            pos = size
            for raw_line in chunk.split(b'\n'):
                line = raw_line.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                self.log(f"  {line}")
                if line.startswith('exit code:'):
                    rc = line.split(':', 1)[1].strip()
                    if rc != '0':
                        self.log(f"  Windows 侧解密失败 (exit {rc})，回退本地旧快照")
                        return None
                    fresh = fresh_dir
                    info_json = fresh_info
                    if (os.path.exists(os.path.join(fresh, 'contact', 'contact.db'))
                            and os.path.exists(info_json)
                            and os.path.getmtime(info_json) > triggered_at):
                        self.log(f"  当前账号解密完成: {fresh}")
                        return fresh
                    self.log("  解密退出码 0，但未见当前账号的新产物，回退旧快照")
                    return None
        self.log("  等待 Windows 侧解密超时（20 分钟），回退本地旧快照")
        return None

    def _try_load_existing_db_dir(self):
        """Find an already-decrypted db_storage directory (non-Windows path)."""
        import os as _os
        candidates = []
        # 1. config last_db_dir
        last = self._config.get('last_db_dir', '')
        if last and _os.path.isdir(last):
            candidates.append(last)
        # 2. known project paths
        base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        for d in ['decrypted', 'verify-output', '.']:
            for entry in _os.listdir(_os.path.join(base, d)) if _os.path.isdir(_os.path.join(base, d)) else []:
                full = _os.path.join(base, d, entry)
                db_storage = _os.path.join(full, 'db_storage')
                if _os.path.isdir(db_storage):
                    candidates.append(db_storage)
        # 3. prefer the currently-logged-in account over stale last_db_dir —
        # blindly returning last_db_dir shows the previous account's data
        # after the user switches WeChat accounts.
        live_uid, _live_mtime = self._detect_live_wechat_uid()
        if live_uid:
            live = [c for c in candidates if f'/{live_uid}/' in c.replace('\\', '/')]
            if live:
                self.log(f"  当前登录微信账号: {live_uid}，加载其解密数据")
                candidates = live + [c for c in candidates if c not in live]
            elif candidates:
                raise RuntimeError(
                    f"当前登录的微信账号是 {live_uid}，但本地没有它的解密数据。\n"
                    f"本地已有: {', '.join(candidates)}\n"
                    f"请先在 Windows 上解密该账号后再回来查看。"
                )
        for db_dir in candidates:
            if _os.path.isdir(db_dir) and _os.path.exists(_os.path.join(db_dir, 'contact', 'contact.db')):
                self._db_version = 4
                return db_dir
            if _os.path.isdir(db_dir) and _os.path.exists(_os.path.join(db_dir, 'Msg')):
                self._db_version = 3
                return db_dir
        return None

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

    @staticmethod
    def _read_wx_key_image_key():
        """读 wx_key 缓存的 V2 图片动态 AES 密钥（wx_key.exe「图片密钥」按钮提取）。

        微信 4.1 的图片 AES 密钥按账号动态生成、仅查看图片时驻留内存，
        无法像 xor_key 一样从文件推导 — 只能由 wx_key 从内存提取。缓存文件
        在 Windows %APPDATA% 下；WSL 经 /mnt/c 读取同一文件。
        返回 32 位 hex 字符串或 None。
        """
        import glob as _glob
        import json as _json
        import sys as _sys
        if _sys.platform == 'win32':
            candidates = [os.path.join(os.environ.get('APPDATA', ''),
                                       'com.example', 'wx_key', 'shared_preferences.json')]
        else:
            candidates = _glob.glob('/mnt/c/Users/*/AppData/Roaming/com.example/wx_key/shared_preferences.json')
        for path in candidates:
            try:
                prefs = _json.load(open(path, 'r', encoding='utf-8'))
            except Exception:
                continue
            v = prefs.get('flutter.image_aes_key', '') or prefs.get('image_aes_key', '')
            if isinstance(v, str) and len(v) == 32 and all(c in '0123456789abcdefABCDEF' for c in v):
                return v.lower()
        return None

    def _get_wx_key_passphrase(self, uid, force_refresh=False):
        """自动从 wx_key 工具获取 passphrase。
        先检查缓存文件，没有则启动 wx_key.exe 等待其提取。
        force_refresh=True 时跳过缓存，强制重新运行 wx_key。"""
        import json as _json

        wx_key_prefs = os.path.join(os.environ.get('APPDATA', ''),
                                     'com.example', 'wx_key', 'shared_preferences.json')

        # 1. Try cached key first (skip if force_refresh)
        if not force_refresh and os.path.exists(wx_key_prefs):
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
            # ponytail: record cache mtime BEFORE launching wx_key so we can
            # detect a fresh write (force_refresh must not return the stale key).
            _cache_mtime_before = os.path.getmtime(wx_key_prefs) if os.path.exists(wx_key_prefs) else 0
            os.startfile(wx_key_exe)
        except Exception:
            self.log(f"  无法启动 wx_key.exe")
            return self._ask_passphrase(uid)

        # 3. Wait for wx_key to save a NEW key (max 60 seconds)
        self.log(f"  等待 wx_key 完成提取（最多60秒）...")
        for _ in range(120):
            time.sleep(0.5)
            if os.path.exists(wx_key_prefs):
                try:
                    _mtime = os.path.getmtime(wx_key_prefs)
                    if force_refresh and _mtime <= _cache_mtime_before:
                        # file hasn't been updated yet — wx_key still running
                        try:
                            self.root.update()
                        except Exception:
                            pass
                        continue
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
        self._state = "ready"
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        # 更新账号信息（info.json 在 db_storage/ 下或其父目录，键名是 username）
        info_path = os.path.join(db_dir, "info.json")
        if not os.path.exists(info_path):
            info_path = os.path.join(os.path.dirname(db_dir), "info.json")
        if os.path.exists(info_path):
            try:
                with open(info_path, 'r', encoding='utf-8') as f:
                    info = _json.load(f)
                # ponytail: 账号身份用「昵称 + 短 uid」展示 — 裸 wxid 没人对得上，
                # 换账号后用户无法判断屏上是谁的数据。昵称优先从已加载联系人表里
                # 取本人那一行（info.json 的 nickname 常为空）。
                from memoir import Me
                me_uid = Me().uid or info.get('username', '')
                me_c = next((c for c in self.contacts if c.uid == me_uid), None)
                display = ((me_c and (me_c.remark or me_c.nickname)) or info.get('nickname')
                           or info.get('username')
                           or os.path.basename(os.path.dirname(db_dir.rstrip('/\\'))))
                short_uid = me_uid.replace('wxid_', '')[:12]
                self._lbl_account.configure(
                    text=f"账号: {display}（{short_uid}）" if short_uid else f"账号: {display}")
            except Exception:
                pass

        # 填充联系人列表
        self._populate_contacts()
        self._show_screen("main")
        self._update_adv_menu()
        # ponytail: _compute_stats 全量扫 message_*.db（实测 ~8s），主线程跑会
        # 卡死整个 UI（WSLg 直接判未响应）。它结尾本来就走 _ui_call 回主线程
        # 刷新列表，天生就是为后台线程设计的。
        import threading as _th
        _th.Thread(target=self._compute_stats, daemon=True).start()

    def _on_decrypt_error(self, e):
        """解密失败后显示错误"""
        import os as _os, time as _t
        try:
            with open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'gui_error_caller.log'), 'a', encoding='utf-8') as _f:
                _f.write(f"[{_t.strftime('%H:%M:%S')}] _on_decrypt_error called with e={e!r} type={type(e).__name__} has_tb={hasattr(e, '_gui_traceback')}\n")
                if hasattr(e, '_gui_traceback'):
                    _f.write(f"--- traceback ---\n{e._gui_traceback}\n----\n")
        except Exception:
            pass
        self._state = "startup"  # 复位防重入锁，允许重试
        self._loading_progress.stop()
        self._btn_cancel.pack_forget()
        self._state = "startup"  # 复位防重入锁，允许重试
        # ponytail: prefer the worker-thread-captured traceback (e._gui_traceback);
        # _tb.format_exc() called here returns "NoneType: None" because the
        # except block in run_task has already exited by the time this runs.
        tb = getattr(e, '_gui_traceback', None) or '(no traceback captured)'
        self.log(f"解析失败 ({type(e).__name__}): {e}")
        self.log(tb)
        self.set_loading_status(f"解析失败: {e}")
        self._btn_retry.pack(side="left", pady=(12, 0))
