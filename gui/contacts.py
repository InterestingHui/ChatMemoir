"""ChatMemoir GUI 联系人列表与详情。"""

import glob
import hashlib
import os
import sqlite3

# 拼音检索：WSLg 下 Linux Tk 窗口收不到 Windows 搜狗输入法注入（OS 层限制），
# 用户只能键入英文 — 全拼/首字母匹配中文昵称是应用层的解法。
try:
    from pypinyin import lazy_pinyin
except ImportError:  # 未安装时退回纯文本/uid 匹配
    lazy_pinyin = None


def _pinyin_haystacks(name):
    """返回 (全拼, 首字母) 小写检索串，如 '张三' -> ('zhangsan', 'zs')。
    非汉字段原样透传（ABC张三 -> ('ABCzhangsan', 'ABCzs')）。
    汉字经 lazy_pinyin 输出必为纯小写字母段 — 以此区分拼音段（取首字母）
    与原样透传段（整体保留）。"""
    if not lazy_pinyin or not name:
        return '', ''
    parts = lazy_pinyin(name)
    full = ''.join(parts)
    initials = ''.join(seg if not seg.islower() else seg[:1] for seg in parts)
    return full.lower(), initials.lower()


class ContactMixin:
    """Mixin providing contact list and detail methods for ChatMemoirApp."""

    # ── 联系人列表 ────────────────────────────────────────

    def _populate_contacts(self):
        self._contact_tree.delete(*self._contact_tree.get_children())
        self._all_contact_items = []
        for c in self.contacts:
            name = c.remark or c.nickname or c.uid
            msg_count = self.contact_msg_counts.get(c.uid, 0)
            count_str = f"{msg_count}条" if msg_count > 0 else ""
            item_id = self._contact_tree.insert("", "end", values=(name, count_str))
            full_py, initials = _pinyin_haystacks(name)
            self._all_contact_items.append((item_id, c.uid, name, full_py, initials))
        self._lbl_contact_count.configure(text=f"共 {len(self.contacts)} 个联系人")
        self.set_status(f"已加载 {len(self.contacts)} 个联系人")

    def _filter_contacts(self):
        keyword = self._search_var.get().strip().lower()
        self._contact_tree.delete(*self._contact_tree.get_children())
        for item_id, uid, name, full_py, initials in self._all_contact_items:
            if (not keyword or keyword in name.lower() or keyword in uid.lower()
                    or keyword in full_py or keyword in initials):
                msg_count = self.contact_msg_counts.get(uid, 0)
                count_str = f"{msg_count}条" if msg_count > 0 else ""
                new_id = self._contact_tree.insert("", "end", values=(name, count_str))
                # Update the item reference
                for i, (old_id, u, n, fp, ini) in enumerate(self._all_contact_items):
                    if old_id == item_id:
                        self._all_contact_items[i] = (new_id, uid, name, full_py, initials)
                        break

    # ── 联系人详情 ────────────────────────────────────────

    def _on_contact_select(self, event):
        sel = self._contact_tree.selection()
        if not sel:
            return
        # 找到对应的 uid
        uid = None
        for item_id, u, name, _fp, _ini in self._all_contact_items:
            if item_id == sel[0]:
                uid = u
                break
        if not uid:
            return
        self.selected_contact = self.database.get_contact_by_username(uid)
        c = self.selected_contact
        if c is None:
            return

        # 显示详情内容，隐藏占位提示
        self._detail_placeholder.pack_forget()
        self._detail_content.pack(fill="x")

        self._detail_labels["昵称"].configure(text=c.nickname or "-")
        self._detail_labels["uid"].configure(text=c.uid)
        self._detail_labels["备注"].configure(text=c.remark or "(无)")
        type_str = "群聊" if c.is_chatroom else "好友"
        self._detail_labels["类型"].configure(text=type_str)
        self._detail_labels["消息数"].configure(text=str(self.contact_msg_counts.get(c.uid, 0)))
        voice = self.contact_voice_counts.get(c.uid, 0)
        voiced = self.voice_transcribed_counts.get(c.uid, 0)
        self._detail_labels["语音数"].configure(text=str(voice))
        self._detail_labels["已转写"].configure(text=f"{voiced}/{voice}")

        self.set_status(f"已选择: {c.remark or c.nickname or c.uid}")

    # ── 消息/语音统计 ──────────────────────────────────────

    def _compute_stats(self):
        self.contact_msg_counts.clear()
        self.contact_voice_counts.clear()
        self.voice_transcribed_counts.clear()

        try:
            msg_dir = os.path.join(self.db_dir_actual, "message")
            if not os.path.isdir(msg_dir):
                return

            tbl_to_uid = {}
            for contact in self.contacts:
                tbl_to_uid[f"Msg_{hashlib.md5(contact.uid.encode()).hexdigest()}"] = contact.uid

            a2t_path = os.path.join(self.db_dir_actual, "Audio2Text.db")
            transcribed = set()
            if os.path.exists(a2t_path):
                conn = sqlite3.connect(a2t_path)
                transcribed = set(r[0] for r in conn.execute("SELECT msgSvrId FROM Audio2Text").fetchall())
                conn.close()

            db_files = sorted(glob.glob(os.path.join(msg_dir, "message_?.db")))
            for db_file in db_files:
                try:
                    conn = sqlite3.connect(db_file)
                    tables = [r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    for tbl in tables:
                        uid = tbl_to_uid.get(tbl)
                        if not uid:
                            continue
                        row = conn.execute(f"SELECT count(*) FROM [{tbl}]").fetchone()
                        total = row[0] if row else 0
                        vrows = conn.execute(f"SELECT server_id FROM [{tbl}] WHERE local_type=34").fetchall()
                        voice = len(vrows)
                        voiced = sum(1 for r in vrows if r[0] in transcribed)
                        self.contact_msg_counts[uid] = self.contact_msg_counts.get(uid, 0) + total
                        self.contact_voice_counts[uid] = self.contact_voice_counts.get(uid, 0) + voice
                        self.voice_transcribed_counts[uid] = self.voice_transcribed_counts.get(uid, 0) + voiced
                    conn.close()
                except Exception:
                    pass

            self._ui_call(self._populate_contacts)
        except Exception:
            pass


if __name__ == "__main__":
    # 自检：拼音检索串生成
    assert _pinyin_haystacks("张三") == ("zhangsan", "zs"), _pinyin_haystacks("张三")
    assert _pinyin_haystacks("退堂鼓手") == ("tuitanggushou", "ttgs")
    assert _pinyin_haystacks("12355青年之声") == ("12355qingnianzhisheng", "12355qnzs")
    assert _pinyin_haystacks("wxid_abc123")[0] == "wxid_abc123"  # uid 形态全拼完整
    assert _pinyin_haystacks("") == ("", "")
    print("contacts pinyin self-check OK (pypinyin:", bool(lazy_pinyin), ")")
