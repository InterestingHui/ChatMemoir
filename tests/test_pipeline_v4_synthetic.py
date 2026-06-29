"""End-to-end v4 pipeline integration test on synthetic SQLite DBs.

Builds a minimal but schema-correct v4 database layout (contact.db, message_0.db,
and the supporting cast of stub DB files) under a pytest tmp_path, then drives the
real production code path:

    ArchiveConnection(db_dir, 4) -> get_interface()
        -> get_contacts()        [contact.db SELECT + create_contact]
        -> get_messages(uid)     [message_0.db JOIN + parser_v4 factories]
        -> TxtExporter(...).start()  [scribe export]

If any link in this chain breaks (Me singleton init, series DB file naming,
md5-hashed table routing, parser fallback for non-zstd content, exporter file
naming), one of the three tests fails. The fixture is schema-correct by
construction (per the plan's <interfaces> block), so a failure points at a real
production gap rather than a test-harness bug.

Runs in WSL without WeChat installed and without Windows. Windows-only modules
are mocked at the top of the module before any memoir/scribe import.
"""

# ── Windows-module mocking (MUST precede any memoir/scribe import) ──────────
# pymem must be a real package-like module so that `import pymem.process`
# (reached transitively via scribe/__init__.py -> exporter_html ->
# memoir.decrypt -> session_v3) resolves to a mocked submodule rather than
# raising ModuleNotFoundError. MagicMock() does not support dotted-submodule
# imports, so we register pymem and its known submodules explicitly.
import sys
import types
from unittest import mock

_PMEM = types.ModuleType('pymem')
_PMEM.__path__ = []  # mark as a package so `import pymem.process` works
sys.modules['pymem'] = _PMEM
sys.modules['pymem.process'] = mock.MagicMock()

for _mod_name in ['yara', 'win32api', 'winreg', 'win32com',
                   'win32com.client', 'psutil', 'pythoncom', 'pysilk']:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()

if 'ctypes.windll' not in sys.modules:
    import ctypes as _ctypes
    _mw = types.ModuleType('ctypes.windll')
    _mw.kernel32 = mock.MagicMock()
    sys.modules['ctypes.windll'] = _mw
    # Production code (e.g. memoir/decrypt/session_v3.py) accesses
    # `ctypes.windll.kernel32.ReadProcessMemory` at module-load time. Setting
    # sys.modules['ctypes.windll'] is insufficient — we must attach `windll`
    # as an attribute on the real ctypes module so the dotted access resolves.
    _ctypes.windll = _mw
    # session_v4.py calls `ctypes.WinDLL('kernel32', use_last_error=True)` at
    # module load. On Linux, ctypes has no WinDLL — patch a stand-in.
    if not hasattr(_ctypes, 'WinDLL'):
        _ctypes.WinDLL = lambda *a, **k: mock.MagicMock()

# ── Real imports (production code path under test) ─────────────────────────
import hashlib
import json
import os
import sqlite3

import pytest

from memoir import ArchiveConnection, MessageType
from scribe.exporter_txt import TxtExporter


# ── Module-level constants ──────────────────────────────────────────────────

CONTACT_UID = 'wxid_abc'
CONTACT_UID_2 = 'bob_xyz'
CHATROOM_UID = '12345@chatroom'
ME_UID = 'me_self_uid'

CONTACT_TABLE = f"Msg_{hashlib.md5(CONTACT_UID.encode('utf-8')).hexdigest()}"
# Equals: Msg_cdebbea2056901bfd390f03a4e892e6e

MSG_CONTENT_1 = "Hello from Alice 1"  # sent by them
MSG_CONTENT_2 = "Hi from me"          # sent by me
MSG_CONTENT_3 = "Hello from Alice 2"  # sent by them

# contact.db columns (matches ContactDB.get_contacts SELECT order)
_CONTACT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS contact (
    username TEXT,
    alias TEXT,
    local_type INTEGER,
    flag INTEGER,
    remark TEXT,
    nick_name TEXT,
    pin_yin_initial TEXT,
    remark_pin_yin_initial TEXT,
    small_head_url TEXT,
    big_head_url TEXT,
    extra_buffer BLOB,
    head_img_md5 TEXT,
    chat_room_notify INTEGER,
    is_in_chat_room INTEGER,
    description TEXT,
    chat_room_type INTEGER,
    remark_quan_pin TEXT,
    quan_pin TEXT
)
'''

# message_0.db Msg_<md5(uid)> table (matches MessageDB.columns SELECT)
_MSG_TABLE_SCHEMA = f'''
CREATE TABLE IF NOT EXISTS {CONTACT_TABLE} (
    local_id INTEGER,
    server_id INTEGER,
    local_type INTEGER,
    sort_seq INTEGER,
    real_sender_id INTEGER,
    create_time INTEGER,
    status INTEGER,
    upload_status INTEGER,
    server_seq INTEGER,
    origin_source BLOB,
    source TEXT,
    message_content TEXT,
    compress_content BLOB,
    packed_info_data BLOB
)
'''


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def _build_v4_layout(tmp_path):
    """Construct a synthetic v4 db_dir with all required DB files.

    Only contact.db and message_0.db carry real schema+data; the rest are
    empty stub files (sqlite3.connect auto-creates an empty DB, and the
    production code paths exercised here never query them).
    """
    db_dir = str(tmp_path)

    # Directory tree required by ArchiveV4.init_database
    for sub in ('contact', 'head_image', 'session', 'message', 'hardlink', 'emoticon'):
        os.makedirs(os.path.join(db_dir, sub), exist_ok=True)

    # info.json — MUST exist before ArchiveConnection (Me singleton reads it)
    info_path = os.path.join(db_dir, 'info.json')
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump({
            'username': ME_UID,
            'nickname': 'Me User',
            'data_dir': db_dir,
            'xor_key': '00',
        }, f, ensure_ascii=False)

    # ── contact.db ──────────────────────────────────────────────────────────
    contact_db_path = os.path.join(db_dir, 'contact', 'contact.db')
    conn = sqlite3.connect(contact_db_path)
    cur = conn.cursor()
    cur.execute(_CONTACT_SCHEMA)
    # Index created defensively here (production code also creates it).
    cur.execute('CREATE INDEX IF NOT EXISTS contact_username ON contact(username);')

    contact_rows = [
        # (username, alias, local_type, flag, remark, nick_name,
        #  pin_yin_initial, remark_pin_yin_initial, small_head_url, big_head_url,
        #  extra_buffer, head_img_md5, chat_room_notify, is_in_chat_room,
        #  description, chat_room_type, remark_quan_pin, quan_pin)
        (CONTACT_UID, 'alice_wx', 1, 0, 'Alice', 'Alice Nick',
         'A', 'A', 'http://small/alice', 'http://big/alice',
         b'', '', 0, 0, '', 0, 'alice', 'alice'),
        (CONTACT_UID_2, 'bob_wx', 1, 0, 'Bob', 'Bob Nick',
         'B', 'B', 'http://small/bob', 'http://big/bob',
         b'', '', 0, 0, '', 0, 'bob', 'bob'),
        # Chatroom row (local_type=2 passes the WHERE filter).
        # Note: ME_UID is intentionally NOT inserted as a contact row — the
        # parser path pre-loads Me into Singleton.contacts via
        # parser_messages -> Singleton.set_contacts({Me().uid: ...}), so the
        # sender lookup in common_attribute hits the cache without a DB row.
        (CHATROOM_UID, '', 2, 0, 'My Group', 'My Group',
         'M', 'M', '', '',
         b'', '', 0, 1, '', 0, 'mygroup', 'mygroup'),
    ]
    cur.executemany('INSERT INTO contact VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', contact_rows)
    conn.commit()
    conn.close()

    # ── message_0.db ────────────────────────────────────────────────────────
    msg_db_path = os.path.join(db_dir, 'message', 'message_0.db')
    conn = sqlite3.connect(msg_db_path)
    cur = conn.cursor()
    # Name2Id: explicit rowid so we control the JOIN (real_sender_id -> rowid).
    cur.execute('CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT)')
    cur.execute('INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)', (1, CONTACT_UID))
    cur.execute('INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)', (2, ME_UID))
    cur.execute(_MSG_TABLE_SCHEMA)

    msg_rows = [
        # (local_id, server_id, local_type, sort_seq, real_sender_id, create_time,
        #  status, upload_status, server_seq, origin_source, source,
        #  message_content, compress_content, packed_info_data)
        (1, 100, MessageType.Text, 1, 1, 1700000000,
         0, 0, 0, b'', '', MSG_CONTENT_1, b'', b''),
        (2, 101, MessageType.Text, 2, 2, 1700000060,
         0, 0, 0, b'', '', MSG_CONTENT_2, b'', b''),
        (3, 102, MessageType.Text, 3, 1, 1700000120,
         0, 0, 0, b'', '', MSG_CONTENT_3, b'', b''),
    ]
    cur.executemany(
        f'INSERT INTO {CONTACT_TABLE} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        msg_rows,
    )
    conn.commit()
    conn.close()

    # ── Stub (empty) DB files ───────────────────────────────────────────────
    # For series DBs, the base filename must end in _0.db so ArchiveBase's
    # '0'->str(i) replacement loop discovers them.
    stub_files = [
        os.path.join(db_dir, 'message', 'biz_message_0.db'),
        os.path.join(db_dir, 'message', 'media_0.db'),
        os.path.join(db_dir, 'head_image', 'head_image.db'),
        os.path.join(db_dir, 'session', 'session.db'),
        os.path.join(db_dir, 'hardlink', 'hardlink.db'),
        os.path.join(db_dir, 'emoticon', 'emoticon.db'),
        os.path.join(db_dir, 'Audio2Text.db'),
    ]
    for stub in stub_files:
        # sqlite3.connect auto-creates a valid (empty) SQLite DB file.
        c = sqlite3.connect(stub)
        c.close()

    return db_dir


@pytest.fixture
def database(_build_v4_layout):
    """Return an initialized ArchiveV4 interface (real production code path)."""
    db_dir = _build_v4_layout
    interface = ArchiveConnection(db_dir, 4).get_interface()
    assert interface is not None, (
        'init_database failed — see fixture; this is a real production gap '
        'if the schema is correct per the plan <interfaces> block.'
    )
    yield interface
    try:
        interface.close()
    except Exception:
        pass


# ── Tests ───────────────────────────────────────────────────────────────────

class TestV4PipelineSynthetic:
    """Three integration tests exercising the full v4 read+export chain."""

    def test_get_contacts_returns_expected_persons(self, database):
        """get_contacts() returns 3 contacts (2 normal + 1 chatroom) with
        uids/remarks populated; the chatroom row reports is_chatroom() True."""
        contacts = database.get_contacts()

        assert isinstance(contacts, list)
        assert len(contacts) == 3, f'expected 3 contacts, got {len(contacts)}'

        uids = {c.uid for c in contacts}
        assert uids == {CONTACT_UID, CONTACT_UID_2, CHATROOM_UID}, (
            f'unexpected uids: {uids}'
        )

        # Remarks survive create_contact (no whitespace/illegal chars in our values,
        # so the sanitizing regex leaves them intact).
        by_uid = {c.uid: c for c in contacts}
        assert by_uid[CONTACT_UID].remark == 'Alice'
        assert by_uid[CONTACT_UID_2].remark == 'Bob'

        # Chatroom detection is uid-based (endsswith '@chatroom') AND local_type==2
        # sets ContactType.Chatroom. Both signals agree for this row.
        chatroom = by_uid[CHATROOM_UID]
        assert chatroom.is_chatroom() is True
        # Non-chatroom contacts must report False.
        assert by_uid[CONTACT_UID].is_chatroom() is False

    def test_get_messages_returns_parsed_text_messages(self, database):
        """get_messages('wxid_abc') returns 3 TextMessage rows; content matches
        inserted strings; is_sender True for exactly the message I sent."""
        messages = database.get_messages(CONTACT_UID)

        assert isinstance(messages, list)
        assert len(messages) == 3, f'expected 3 messages, got {len(messages)}'

        # Every message is a Text type
        assert all(m.type == MessageType.Text for m in messages), (
            f'types: {[m.type for m in messages]}'
        )

        # Concatenated content includes all three inserted strings
        all_content = '\n'.join(m.content for m in messages)
        assert MSG_CONTENT_1 in all_content
        assert MSG_CONTENT_2 in all_content
        assert MSG_CONTENT_3 in all_content

        # is_sender True for exactly one message (the one whose Name2Id.user_name
        # == Me().uid, i.e. real_sender_id == 2 -> ME_UID).
        sender_flags = [m.is_sender for m in messages]
        assert sender_flags.count(True) == 1, (
            f'expected exactly 1 is_sender=True, got {sender_flags}'
        )
        # And that one message carries the "Hi from me" content.
        sent_by_me = [m for m in messages if m.is_sender]
        assert len(sent_by_me) == 1
        assert sent_by_me[0].content == MSG_CONTENT_2

    def test_txt_exporter_generates_nonempty_file(self, database, tmp_path_factory):
        """TxtExporter writes a non-empty .txt under the output dir whose path
        follows the 聊天记录/<remark>(<uid>)/<remark>.txt convention and whose
        contents include the inserted text."""
        output_dir = str(tmp_path_factory.mktemp('output'))

        contacts = database.get_contacts()
        contact = next(c for c in contacts if c.uid == CONTACT_UID)
        assert contact is not None, 'wxid_abc contact missing from get_contacts()'

        TxtExporter(database, contact, output_dir).start()

        expected_path = os.path.join(
            output_dir, '聊天记录', f'Alice({CONTACT_UID})', 'Alice.txt'
        )
        assert os.path.exists(expected_path), (
            f'expected export file at {expected_path}; '
            f'dir contents: {os.listdir(os.path.dirname(expected_path)) if os.path.exists(os.path.dirname(expected_path)) else "parent missing"}'
        )
        assert os.path.getsize(expected_path) > 0, 'export file is empty'

        with open(expected_path, encoding='utf-8') as f:
            text = f.read()
        assert MSG_CONTENT_1 in text, (
            f'"{MSG_CONTENT_1}" not in export; got (first 200 chars): {text[:200]!r}'
        )
