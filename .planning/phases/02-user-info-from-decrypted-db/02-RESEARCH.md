# Phase 2: User Info from Decrypted DB - Research

**Researched:** 2026-04-24
**Domain:** SQLite query on decrypted WeChat v4 contact database
**Confidence:** HIGH

## Summary

This phase requires a single, targeted change: after decrypting all `.db` files in `1-decrypt.py`'s `dump_v4()`, open the freshly decrypted `contact/contact.db` and query `SELECT nick_name FROM contact WHERE username = ?` using the already-known `wxid`. The result gets written to `Me().name` before `info.json` is saved. The current code sets `me.name = wx_info.nick_name` at line 60 of `1-decrypt.py`, which is always empty on WeChat 4.1.8.29 because the YARA `GetPhoneNumberOffset` memory scan fails on that version.

The contact table schema is well-documented in the existing `ContactDB` class (`wxManager/db_v4/contact.py`). The `get_contact_by_username()` method already demonstrates the exact query pattern needed. The `DataBaseBase` class provides SQLite connection lifecycle. No new dependencies or abstractions are required.

**Primary recommendation:** Inline a minimal SQLite query in `dump_v4()` after `decrypt_db_files()` completes. Use `sqlite3.connect()` directly -- no need to instantiate `ContactDB` or `DataBaseBase` for a single one-off query.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Pure DB query approach. After decryption, query `contact/contact.db` with `WHERE username = '{wxid}'`. No memory scanning fallback. If query fails, leave nickname empty and print diagnostic info.
- **D-02:** Do not change `info.json` format. Current `Me.to_json()` fields (`username`, `nickname`, `wx_dir`, `xor_key`) are sufficient.
- **D-03:** Only fill `Me().name` (nickname). `wxid` is already extracted via directory path (`wx_info_v4.py:626`). No new alias or phone fields.
- **D-04:** Read in `1-decrypt.py`'s `dump_v4()`, after `decrypt_v4.decrypt_db_files()` completes but before writing `info.json`.

### Claude's Discretion
- Where to put the helper function (inline in `dump_v4()` vs. separate utility function)
- Exact SQL query (handling multiple-row matches)
- Format of diagnostic output

### Deferred Ideas (OUT OF SCOPE)
- Phone number extraction (`extra_buffer` protobuf contains `phone_info`) -- does not affect export
- Alias (WeChat ID) extraction -- export does not need it
- Adding `load_from_database()` method to `Me` class -- inline query in `1-decrypt.py` is sufficient
- v3 path user info changes -- v3 decrypt logic is independent
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFO-01 | Read user nickname from decrypted database instead of memory offset scanning | SQL: `SELECT nick_name FROM contact WHERE username = ?` on `{output_dir}/db_storage/contact/contact.db` |
| INFO-02 | Read phone number from decrypted database | DEFERRED per CONTEXT.md -- not needed for export |
| INFO-03 | Read account name from decrypted database | DEFERRED per CONTEXT.md -- wxid already extracted from directory path |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 (stdlib) | Python 3.10+ built-in | Query decrypted `contact.db` | Already used throughout `wxManager/db_v4/` and `wxManager/model/db_model.py` [VERIFIED: codebase] |
| os (stdlib) | Python 3.10+ built-in | Construct path to decrypted DB file | Already used in `1-decrypt.py` [VERIFIED: codebase] |

### Supporting
No additional libraries needed. This is a one-query change.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline `sqlite3.connect()` | `ContactDB` class from `wxManager/db_v4/contact.py` | ContactDB pulls in `DataBaseBase` with series DB handling, merge logic, index creation -- overkill for one query. Inline is ~10 lines vs. class instantiation + init + close. |

**Installation:**
No new packages required. `sqlite3` and `os` are stdlib.

## Architecture Patterns

### Current Code Flow (what exists)
```
1-decrypt.py:dump_v4()
  -> get_info_v4()           # returns WeChatInfo (wxid, key, wx_dir, nick_name="")
  -> me.name = wx_info.nick_name  # EMPTY on 4.1.8.29 (YARA scan fails)
  -> decrypt_db_files()      # decrypts all .db -> {wxid}/db_storage/...
  -> write info.json          # saves Me().name="" to JSON
```

### Target Code Flow (what we need)
```
1-decrypt.py:dump_v4()
  -> get_info_v4()           # returns WeChatInfo (wxid, key, wx_dir, nick_name="")
  -> me.name = wx_info.nick_name  # EMPTY on 4.1.8.29 (will be overwritten)
  -> decrypt_db_files()      # decrypts all .db -> {wxid}/db_storage/...
  -> [NEW] open {output_dir}/db_storage/contact/contact.db
  -> [NEW] SELECT nick_name FROM contact WHERE username = {wxid}
  -> [NEW] me.name = result (or keep empty + print diagnostic)
  -> write info.json          # saves Me().name="actual nickname" to JSON
```

### Pattern: Direct SQLite Query in Entry Script
**What:** Open a decrypted DB file with `sqlite3.connect()`, run one query, close immediately.
**When to use:** One-off queries in entry scripts where full DB class instantiation is unnecessary.
**Example:**
```python
import sqlite3
import os

def get_nickname_from_db(output_dir: str, wxid: str) -> str:
    """Query decrypted contact.db for user's own nickname."""
    db_path = os.path.join(output_dir, 'db_storage', 'contact', 'contact.db')
    if not os.path.exists(db_path):
        print(f'[!] contact.db not found at {db_path}')
        return ''
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT nick_name FROM contact WHERE username = ?', [wxid])
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        print(f'[!] No nickname found for wxid={wxid} in contact table')
        return ''
    except Exception as e:
        print(f'[!] Failed to query nickname from contact.db: {e}')
        return ''
```

### Anti-Patterns to Avoid
- **Instantiating ContactDB/DataBaseBase for a single query:** These classes are designed for long-lived DB access with index management, series DB handling, and merge support. For one query, use `sqlite3.connect()` directly.
- **Querying before decryption completes:** The contact.db must be fully decrypted before querying. The query must happen AFTER `decrypt_db_files()` returns.
- **Modifying Me class or info.json format:** Per D-02 and D-03, no structural changes to `Me` or its serialization.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQLite connection | Custom DB wrapper for this one query | `sqlite3.connect()` directly | stdlib, already the project pattern for raw queries |

**Key insight:** The existing `ContactDB.get_contact_by_username()` method already demonstrates the exact query needed. The SQL is `SELECT ... FROM contact WHERE username=?`. For this phase, we only need the `nick_name` column, not all 16 columns.

## Common Pitfalls

### Pitfall 1: Wrong DB Path
**What goes wrong:** Using wrong path to decrypted `contact.db`.
**Why it happens:** The `decrypt_db_files()` preserves the relative directory structure from `src_dir`. Since `src_dir` is the WeChat data root (e.g., `D:\xwechat_files\xxx_123`) and the encrypted files are under `db_storage/contact/contact.db`, the decrypted output is at `{output_dir}/db_storage/contact/contact.db`.
**How to avoid:** Use `os.path.join(output_dir, 'db_storage', 'contact', 'contact.db')` -- this matches the comment on line 70 of `1-decrypt.py`: "导出的数据库在 output_dir/db_storage 文件夹下".
**Warning signs:** `FileNotFoundError` or `sqlite3.OperationalError: unable to open database file`.

### Pitfall 2: Setting me.name Too Early
**What goes wrong:** Setting `me.name` before `decrypt_db_files()` runs.
**Why it happens:** Current code sets `me.name = wx_info.nick_name` at line 60, before decryption at line 69.
**How to avoid:** The new DB query must happen AFTER line 69 (`decrypt_db_files()`). Move `me.name` assignment to after the query, or overwrite it after decryption.
**Warning signs:** `me.name` stays empty string (the pre-decryption value).

### Pitfall 3: info_data Already Captured Before Query
**What goes wrong:** `info_data = me.to_json()` is called at line 62 (BEFORE decryption), so even if `me.name` is updated later, `info_data` still has the old empty value.
**Why it happens:** The current code computes `info_data` at line 62, then writes it at line 71-72. If `me.name` is updated between lines 62 and 71, the `info_data` dict still has the stale value.
**How to avoid:** Either (a) move `info_data = me.to_json()` to AFTER the nickname query, or (b) update both `me.name` and `info_data['nickname']` after the query. Option (a) is cleaner.
**Warning signs:** `info.json` contains `"nickname": ""` despite successful query.

### Pitfall 4: Contact Table May Not Have Self-Entry
**What goes wrong:** The contact table might not contain an entry for the user's own wxid.
**Why it happens:** The contact table in v4 is filtered by `local_type` (see `get_contacts()` SQL: `WHERE (local_type=1 or local_type=2 or local_type=5)`). The self-entry might have a different `local_type` or might not be in the contact table at all.
**How to avoid:** Query WITHOUT `local_type` filter -- just `WHERE username = ?`. The existing `get_contact_by_username()` method does not filter by `local_type`, confirming this is the correct approach. Also handle `None` result gracefully.
**Warning signs:** Query returns `None` for a valid wxid.

### Pitfall 5: Process Pool Not Finished Before Query
**What goes wrong:** `decrypt_db_files()` uses `ProcessPoolExecutor` with `executor.map()` which is blocking -- but the results list is consumed immediately, so this is NOT actually an issue.
**Why it happens:** Looking at the code: `results = list(executor.map(decode_wrapper, decrypt_tasks))` -- `list()` forces evaluation of the lazy iterator, so all tasks complete before the function returns.
**How to avoid:** No action needed -- the current implementation is already synchronous from the caller's perspective.
**Warning signs:** None (this is a non-issue, documented for clarity).

## Code Examples

### Verified Query Pattern (from ContactDB.get_contact_by_username)
```python
# Source: wxManager/db_v4/contact.py lines 88-101
def get_contact_by_username(self, username):
    sql = '''
SELECT username, alias, local_type,flag, remark, nick_name, pin_yin_initial, remark_pin_yin_initial, small_head_url, big_head_url,extra_buffer,head_img_md5,chat_room_notify,is_in_chat_room,description,chat_room_type
FROM contact
WHERE username=?
    '''
    cursor = self.DB.cursor()
    cursor.execute(sql, [username])
    result = cursor.fetchone()
    cursor.close()
    if result:
        return result
    return None
# Column index 5 = nick_name (0-indexed: username=0, alias=1, local_type=2, flag=3, remark=4, nick_name=5)
```

### Minimal Inline Query for dump_v4()
```python
# After decrypt_v4.decrypt_db_files(key, src_dir=wx_dir, dest_dir=output_dir) completes:

import sqlite3

db_path = os.path.join(output_dir, 'db_storage', 'contact', 'contact.db')
if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT nick_name FROM contact WHERE username = ?', [me.wxid])
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            me.name = row[0]
            print(f'[*] 从数据库读取昵称: {me.name}')
        else:
            print(f'[!] 未在 contact 表中找到 wxid={me.wxid} 的昵称')
    except Exception as e:
        print(f'[!] 查询昵称失败: {e}')
else:
    print(f'[!] 未找到解密后的 contact.db: {db_path}')

# Re-generate info_data AFTER nickname lookup
info_data = me.to_json()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Memory offset scanning for nickname (`get_nickname()` with YARA `GetPhoneNumberOffset`) | DB query after decryption | Phase 2 | More reliable, version-independent |

**Deprecated/outdated:**
- YARA `GetPhoneNumberOffset` rule: Pattern `[\x01-\x20]\x00{7}(\x0f|\x1f)\x00{7}[0-9]{11}\x00{5}\x0b\x00{7}\x0f\x00{7}` fails on WeChat 4.1.8.29. This phase replaces its output, not the rule itself (which is still used for the memory scan path).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The decrypted `contact.db` contains a row for the user's own wxid | Architecture Patterns | Medium -- user would see empty nickname, but no crash. Diagnostic print would inform them. |
| A2 | `nick_name` column in the contact table is populated for the self-entry | Architecture Patterns | Low -- the column exists and is queried by existing code. Even if empty, the fallback is graceful. |
| A3 | `decrypt_db_files()` blocks until all files are decrypted before returning | Pitfall 5 | Non-issue -- confirmed by code reading: `list(executor.map(...))` forces synchronous completion. |

**Note:** A1 and A2 are LOW risk because the fallback behavior (empty nickname + diagnostic message) is acceptable per D-01.

## Open Questions

1. **Self-entry in contact table?**
   - What we know: `ContactDB.get_contact_by_username()` queries without `local_type` filter, suggesting any username works. The `get_contacts()` method filters to `local_type IN (1,2,5)` for listing contacts, but the self-entry may have a different type.
   - What's unclear: Whether the user's own wxid always appears in the v4 `contact` table.
   - Recommendation: Implement the query and handle the `None` case gracefully (print diagnostic, leave empty). This is exactly what D-01 specifies.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified). This phase uses only Python stdlib (`sqlite3`, `os`) on decrypted files already produced by Phase 1.

## Sources

### Primary (HIGH confidence)
- `wxManager/db_v4/contact.py` -- Contact table schema, column order, existing query patterns [VERIFIED: codebase]
- `wxManager/model/db_model.py` -- DataBaseBase SQLite lifecycle [VERIFIED: codebase]
- `1-decrypt.py` -- Entry point flow, output directory structure [VERIFIED: codebase]
- `wxManager/decrypt/wx_info_v4.py` -- dump_wechat_info_v4() wx_dir transformation at line 627 [VERIFIED: codebase]
- `wxManager/model/contact.py` -- Me singleton, to_json(), load_from_json() [VERIFIED: codebase]

### Secondary (MEDIUM confidence)
- CONTEXT.md canonical references -- confirmed by direct code reading

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies, pure stdlib SQLite
- Architecture: HIGH - single insertion point in existing well-understood flow
- Pitfalls: HIGH - all verified by reading actual source code
- Contact table schema: HIGH - confirmed from `ContactDB.get_contact_by_username()` column listing

**Research date:** 2026-04-24
**Valid until:** 2026-05-24 (stable -- no external dependencies)
