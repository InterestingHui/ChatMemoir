# Roadmap: WeChatMsg 解密修复

## Overview

Fix WeChatMsg's database decryption for WeChat 4.x (tested against 4.1.8.29) by replacing fragile YARA memory scanning with Python regex-based WCDB hex key pattern extraction. The journey goes: (1) replace key extraction so keys are no longer None, (2) read user info from decrypted databases instead of broken memory offsets, (3) validate the full decrypt-query-export pipeline end-to-end and fix latent code bugs that affect correctness.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Regex Key Extraction** - Replace YARA with Python regex WCDB hex pattern scanning, add diagnostic logging, keep YARA as fallback
- [ ] **Phase 2: User Info from Decrypted DB** - Read nickname from decrypted contact.db instead of memory offsets
- [ ] **Phase 3: Pipeline Validation and Code Health** - End-to-end pipeline test on 4.1.8.29 plus fix multiprocessing and handle leak bugs

## Phase Details

### Phase 1: Regex Key Extraction
**Goal**: Users running WeChat 4.x get a valid database decryption key instead of None
**Depends on**: Nothing (first phase)
**Requirements**: KEY-01, KEY-02, KEY-03, KEY-04, KEY-05
**Success Criteria** (what must be TRUE):
  1. Key extraction returns a valid hex key (not None) when WeChat 4.1.8.29 is running and logged in
  2. Key extraction returns a valid hex key when WeChat 4.0.3 is running and logged in (backward compat)
  3. Key verification via HMAC-SHA512 passes for extracted keys against actual encrypted DB files
  4. When key extraction fails, console/log shows diagnostic message explaining what was tried and what failed (not silent None)
  5. YARA-based extraction still runs as fallback when regex finds no candidates
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Add regex-based WCDB hex key extraction to wx_info_v4.py (regex-first, YARA fallback, diagnostic logging, multi-file verification, remove if-True-or bypass)
- [x] 01-02-PLAN.md — Apply same regex key extraction changes to wxinfo.py (duplicate file sync)

### Phase 2: User Info from Decrypted DB
**Goal**: Users see their own nickname populated from the decrypted contact database instead of an empty string
**Depends on**: Phase 1
**Requirements**: INFO-01, INFO-02, INFO-03
**Success Criteria** (what must be TRUE):
  1. User's nickname is populated from decrypted database (not empty and not garbage from memory offsets)
  2. ~~User's phone number is populated from decrypted database~~ — Deferred: export pipeline only uses wxid and name (per D-03)
  3. ~~User's account name (wxid or alias) is populated from decrypted database~~ — Deferred: wxid already populated from memory scan, not needed from DB (per D-03)
**Plans**: 1 plan

Plans:
- [x] 02-01-PLAN.md — Query nickname from decrypted contact/contact.db after decrypt_db_files(), fix info.json ordering bug

### Phase 3: Pipeline Validation and Code Health
**Goal**: The complete decrypt-to-export pipeline works end-to-end on WeChat 4.1.8.29, and latent code bugs are fixed
**Depends on**: Phase 2
**Requirements**: PIPE-01, PIPE-02, PIPE-03, CODE-01, CODE-02, CODE-03
**Success Criteria** (what must be TRUE):
  1. Decrypted databases are opened and read successfully by the contact query step (no "file is not a database" errors)
  2. Contact data flows through to the export step and generates at least one output file (e.g., HTML or TXT) without errors
  3. The full three-step pipeline (decrypt, query contacts, export messages) runs on WeChat 4.1.8.29 data from start to finish without unhandled exceptions
  4. Process handles are properly closed after decryption (no handle leaks visible in Task Manager across repeated runs)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Regex Key Extraction | 0/2 | Not started | - |
| 2. User Info from Decrypted DB | 0/1 | Not started | - |
| 3. Pipeline Validation and Code Health | 0/2 | Not started | - |
