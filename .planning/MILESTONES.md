# Milestones

## v1.0 WeChatMsg Decrypt Fix (Shipped: 2026-04-25)

**Phases completed:** 3 phases, 5 plans, 9 tasks

**Key accomplishments:**

- Regex-based WCDB hex key scanning with YARA fallback, salt-matching verification, and diagnostic logging for WeChat 4.x database key extraction
- Applied regex-first WCDB hex key extraction with YARA fallback to wxinfo.py, mirroring wx_info_v4.py implementation from Plan 01
- Inline sqlite3 query reads user nickname from decrypted contact/contact.db after decrypt_db_files(), replacing empty memory-scan result with actual database value
- Regex-first WCDB hex key extraction restored in both decrypt files, multiprocessing.Value replaces broken global finish_flag, and process handle leaks fixed via try/finally CloseHandle
- close() fix (manager_v4.py):

---
