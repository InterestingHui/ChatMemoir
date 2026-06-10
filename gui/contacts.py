"""ChatMemoir GUI 联系人列表与详情。"""

import glob
import hashlib
import os
import sqlite3


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
            self._all_contact_items.append((item_id, c.uid, name))
        self._lbl_contact_count.configure(text=f"共 {len(self.contacts)} 个联系人")
        self.set_status(f"已加载 {len(self.contacts)} 个联系人")

    def _filter_contacts(self):
        keyword = self._search_var.get().strip().lower()
        self._contact_tree.delete(*self._contact_tree.get_children())
        for item_id, uid, name in self._all_contact_items:
            if not keyword or keyword in name.lower() or keyword in uid.lower():
                msg_count = self.contact_msg_counts.get(uid, 0)
                count_str = f"{msg_count}条" if msg_count > 0 else ""
                new_id = self._contact_tree.insert("", "end", values=(name, count_str))
                # Update the item reference
                for i, (_, u, n) in enumerate(self._all_contact_items):
                    if u == uid:
                        self._all_contact_items[i] = (new_id, uid, name)
                        break

    # ── 联系人详情 ────────────────────────────────────────

    def _on_contact_select(self, event):
        sel = self._contact_tree.selection()
        if not sel:
            return
        # 找到对应的 uid
        uid = None
        for item_id, u, name in self._all_contact_items:
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

            self.root.after(0, self._populate_contacts)
        except Exception:
            pass
