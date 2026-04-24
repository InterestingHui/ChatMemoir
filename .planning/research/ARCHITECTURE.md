# Architecture Patterns

**Domain:** WeChat 4.x database decryption fix for WeChatMsg
**Researched:** 2026-04-23

## Recommended Architecture

The decryption stage is a sub-pipeline within the larger three-stage system (Decrypt -> Query -> Export). The fix scope is entirely within the Decrypt stage, specifically the "info extraction" sub-pipeline that reads the WeChat process memory to find encryption keys and user information.

```
                    DECRYPT STAGE (Windows-only)
+------------------------------------------------------------------+
|                                                                  |
|  1. Process Discovery          2. Info Extraction                |
|  +-----------------------+    +---------------------------+      |
|  | psutil finds          |    | Memory Region Enum.       |      |
|  | Weixin.exe process    |--->| YARA Pattern Matching     |      |
|  | Gets PID, checks      |    | Candidate Key Extraction  |      |
|  | Weixin.dll loaded     |    | Key Verification (HMAC)   |      |
|  +-----------------------+    | User Info Extraction       |      |
|                               +-------------+-------------+      |
|                                             |                    |
|                               3. DB File Decryption               |
|                               +---------------------------+      |
|                               | Walk wx_dir for .db files |<-----+
|                               | AES-256-CBC page decrypt  |      |
|                               | Write decrypted output    |      |
|                               +---------------------------+      |
|                                                                  |
|  4. Image Decryption (parallel concern)                          |
|  +---------------------------+                                   |
|  | .dat -> image decode      |  (versioned AES keys + XOR)      |
|  +---------------------------+                                   |
+------------------------------------------------------------------+
                              |
                              v
                    QUERY STAGE (cross-platform)
              +---------------------------+
              | Open decrypted SQLite DBs  |
              | Contact/Media/Msg queries  |
              +---------------------------+
                              |
                              v
                    EXPORT STAGE (cross-platform)
              +---------------------------+
              | Render messages to format  |
              | HTML/TXT/CSV/DOCX/etc.     |
              +---------------------------+
```

### Component Boundaries

| Component | File(s) | Responsibility | Communicates With |
|-----------|---------|---------------|-------------------|
| Process Discovery | `wxManager/decrypt/__init__.py` | Find running WeChat process, get PID, verify DLL loaded | Calls `dump_wechat_info_v4()` or `dump_wechat_info_v3()` |
| Version Detection | `wxManager/decrypt/common.py` (`get_version`) | Extract WeChat version number from PE file | Used by Process Discovery, Info Extraction |
| Memory Region Enumeration | `wxManager/decrypt/wx_info_v4.py` (`get_memory_regions`) | Walk process virtual address space, collect committed private regions | Called by every YARA-based scanner |
| Key Extraction (YARA) | `wxManager/decrypt/wx_info_v4.py` (`get_key`, `get_key_inner`) | Scan memory for key address stubs, extract 32-byte candidate keys | Uses YARA rules, calls Key Verification |
| Key Verification | `wxManager/decrypt/wx_info_v4.py` (`is_ok`, `check_chunk`) | Validate candidate key against encrypted DB file using PBKDF2+HMAC | Reads actual .db file from disk |
| User Info Extraction | `wxManager/decrypt/wx_info_v4.py` (`get_nickname`) | Scan memory for phone number pattern, extract nickname/account at fixed offsets | Uses YARA rules, separate child process |
| Data Dir Extraction | `wxManager/decrypt/wx_info_v4.py` (`get_wx_dir`) | Find WeChat data directory path in memory | Uses YARA rules, frequency counting |
| Orchestrator | `wxManager/decrypt/wx_info_v4.py` (`dump_wechat_info_v4`) | Coordinate all extraction steps, populate WeChatInfo | Calls all above components |
| DB Decryption | `wxManager/decrypt/decrypt_v4.py` | Decrypt all .db files using verified key | Reads encrypted DBs, writes decrypted output |
| Image Decryption | `wxManager/decrypt/decrypt_dat.py` | Decrypt .dat image files (separate concern) | Independent of key extraction |
| Info Model | `wxManager/decrypt/common.py` (`WeChatInfo`) | Data class holding all extracted info | Returned by orchestrator |

### Data Flow

```
1. Entry: get_info_v4() in __init__.py
   |
   +-- psutil.process_iter() finds "Weixin.exe"
   +-- Checks for "Weixin.dll" module in process memory maps
   |
   v
2. dump_wechat_info_v4(pid) [ORCHESTRATOR]
   |
   +-- [PARALLEL BRANCH A: User Info]
   |   |-- multiprocessing.Process -> get_nickname(pid)
   |   |   |-- Opens process handle
   |   |   |-- Enumerates memory regions
   |   |   |-- YARA scan with GetPhoneNumberOffset rule
   |   |   |-- At each match: extract phone (fixed offset +0x10)
   |   |   |                     nickname (fixed offset -0x20)
   |   |   |                     account (fixed offset -0x40)
   |   |   +-- Returns {nick_name, phone, account_name} via Queue
   |   +-- [continues in parallel]
   |
   +-- [BRANCH B: Data Directory]
   |   |-- get_wx_dir(process_handle)
   |   |   |-- YARA scan with GetDataDir rule across all regions
   |   |   |-- Frequency count of matched paths
   |   |   +-- Returns most frequent path (e.g., "C:\...\xwechat_files\wxid_xxx\db_storage\")
   |   |
   |   +-- Derives wxid from path components
   |
   +-- [BRANCH C: Key Extraction]
   |   |-- Opens a reference .db file from wx_dir (favorite_fts.db or head_image.db)
   |   |-- get_key(pid, process_handle, buf)
   |   |   |-- get_memory_regions() -> list of (base, size) tuples
   |   |   |-- Splits regions into ~40 chunks
   |   |   |-- multiprocessing.Pool -> get_key_inner() for each chunk
   |   |   |   |-- YARA scan with GetKeyAddrStub rule
   |   |   |   |-- At each match: read 8 bytes at match offset as address
   |   |   |   |-- Read 32 bytes from that address as candidate key
   |   |   |   +-- Returns list of candidate keys
   |   |   |-- get_key_(candidates, buf) -> parallel verification
   |   |   |   |-- multiprocessing.Pool -> check_chunk() per candidate
   |   |   |   |   |-- is_ok(candidate, db_page_1)
   |   |   |   |   |   |-- PBKDF2-SHA512(candidate, salt, 256000 iters) -> key
   |   |   |   |   |   |-- PBKDF2-SHA512(key, mac_salt, 2 iters) -> mac_key
   |   |   |   |   |   |-- HMAC-SHA512(mac_key, page_data) == stored_hmac?
   |   |   |   |   |   +-- Returns True if match (correct key found)
   |   |   |   +-- Returns hex string of verified key
   |   |   +-- Returns key or None
   |   |
   |   +-- Sets errcode 200 (success) or 404 (key not found)
   |
   +-- [MERGE: Collect results from all branches]
       |-- WeChatInfo populated with: pid, version, wx_dir, wxid, key, nick_name, phone, account_name
       +-- Returns WeChatInfo to caller

3. Downstream: 1-decrypt.py uses WeChatInfo.key
   |-- decrypt_db_files(key, wx_dir + "db_storage", output_dir)
   |   |-- Walks all .db files in db_storage subdirectories
   |   |-- ProcessPoolExecutor(16 workers) -> decrypt_db_file_v4() per file
   |   |   |-- Page-by-page: read salt, derive key via PBKDF2, verify HMAC, AES-256-CBC decrypt
   |   |   +-- Writes decrypted SQLite to output dir (preserving structure)
   |   +-- Returns nothing (side-effect: files written)
   +-- Saves info.json in output directory
```

## Patterns to Follow

### Pattern 1: YARA Rule Isolation
**What:** Each YARA rule is a regex string compiled and applied independently. Rules should be versioned alongside the WeChat version they target.
**When:** Any time a new WeChat version changes memory layout.
**Why:** This is the core fragility point. The existing code embeds rules as inline string literals in the function body. When a rule breaks, there is no fallback, no logging of what was expected, and no mechanism to try alternative rules.
**Example:**
```python
# CURRENT (fragile): Single rule, no fallback
rules_v4_key = r'''
    rule GetKeyAddrStub {
        strings:
            $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
        condition:
            all of them
    }
'''
rules = yara.compile(source=rules_v4_key)

# RECOMMENDED: Version-aware rule set with fallback
KEY_RULES = {
    # WeChat 4.0.x - 4.1.x (original pattern)
    "4.0": r'''
        rule GetKeyAddrStub {
            strings:
                $a = /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
            condition:
                all of them
        }
    ''',
    # WeChat 4.1.8+ (new memory layout)
    "4.1.8": r'''
        rule GetKeyAddrStub {
            strings:
                $a = /NEW_PATTERN_HERE/
            condition:
                all of them
        }
    ''',
}

def get_yara_rules_for_version(version_str):
    """Select YARA rules based on WeChat version, with fallback."""
    major_minor = '.'.join(version_str.split('.')[:2])
    for version_prefix, rule_source in sorted(KEY_RULES.items(), reverse=True):
        if major_minor >= version_prefix:
            return yara.compile(source=rule_source)
    # Fallback: try all rules
    return try_all_rules(KEY_RULES)
```

### Pattern 2: Multiprocessing Boundary at Memory Scans
**What:** The code already uses multiprocessing.Pool to parallelize memory region scanning. Each worker opens its own process handle and reads memory independently.
**When:** Always -- memory region scanning is embarrassingly parallel.
**Why:** The current pattern of splitting memory regions across workers is sound. Keep this.
**Example:**
```python
# Current pattern in get_key() is correct:
pool = multiprocessing.Pool(processes=cpu_count() // 2)
results = pool.starmap(get_key_inner, ((pid, chunk) for chunk in split_list(regions, 40)))
```

### Pattern 3: Key Verification Against Real DB File
**What:** The `is_ok()` function validates candidate keys by attempting HMAC verification against the first page of an actual encrypted database file.
**When:** Always -- this is what makes the approach robust despite noisy memory scans.
**Why:** Without verification, any 32 bytes that happen to match the YARA pattern would be returned as the key. The HMAC check against a known-good encrypted file eliminates false positives definitively.
**Example:**
```python
# is_ok() is the ground truth mechanism:
# 1. Read salt from DB file header (first 16 bytes)
# 2. Derive key via PBKDF2-SHA512(candidate, salt, 256000 iterations)
# 3. Derive mac_key via PBKDF2-SHA512(key, mac_salt, 2 iterations)
# 4. Compute HMAC-SHA512 over page data + page number
# 5. Compare with stored HMAC in the DB page
# This is computationally expensive per candidate (~256k PBKDF2 iterations),
# which is why multiprocessing is used for verification too.
```

### Pattern 4: Versioned Constants (Existing in decrypt_dat.py)
**What:** `decrypt_dat.py` already uses a `AES_KEY_MAP` dictionary with V1 and V2 keys. This pattern should be applied to YARA rules and offset constants.
**When:** Anywhere version-specific constants appear.
**Example:**
```python
# From decrypt_dat.py - good pattern to emulate:
AES_KEY_MAP = {
    "V1": bytes([...]),
    "V2": bytes([...]),
}
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Hard-Coded Memory Offsets
**What:** The `get_nickname()` function uses hard-coded offsets like `phone_addr - 0x20`, `phone_addr - 0x40`, `phone_addr - 0x30`, `phone_addr - 0x60` relative to the YARA match point.
**Why bad:** When WeChat updates change their internal structures, all these offsets shift simultaneously. The current code has no way to detect which version's layout to use.
**Instead:** Create a version-to-offset mapping. At minimum, wrap offsets in named constants keyed by version. Better: use the version string to select the correct offset set at runtime.
```python
# BAD:
nick_name = read_string(target_data, phone_addr - 0x20, nick_name_length)

# BETTER:
NICKNAME_OFFSETS = {
    "4.0": -0x20,
    "4.1.8": -0x??,  # determined by reverse engineering
}
offset = NICKNAME_OFFSETS.get(version_prefix, -0x20)
nick_name = read_string(target_data, phone_addr + offset, nick_name_length)
```

### Anti-Pattern 2: Silent Failure on YARA Rule Miss
**What:** When a YARA rule fails to match, the code returns empty results (`None`, `''`, `[]`) with no diagnostic logging. The user just sees "key: None".
**Why bad:** Makes debugging extremely difficult. There is no way to tell whether: (a) the rule pattern is wrong for this version, (b) WeChat is not fully loaded, (c) the process is being read incorrectly, or (d) something else entirely.
**Instead:** Log which rules matched, how many candidates were found, and at which stages failures occurred. Return structured error information, not just None.

### Anti-Pattern 3: Duplicate Code Across Files
**What:** `wx_info_v4.py` and `wxinfo.py` contain near-identical code (same YARA rules, same offset logic, same verification functions). They differ only in: (1) the DB file used for key verification (`favorite_fts.db` vs `biz.db`), (2) whether the address range check has `if True or` bypassing it, (3) minor path handling.
**Why bad:** Fixes must be applied in two places. The files will diverge further over time.
**Instead:** Consolidate into a single `wx_info_v4.py` and delete `wxinfo.py`. Use a parameter for the DB file selection strategy.

### Anti-Pattern 4: Global Mutable State for Coordination
**What:** `finish_flag` is a module-level global variable used to short-circuit key verification once a key is found.
**Why bad:** Breaks in multiprocessing scenarios because each child process has its own copy of the global. The `verify_key()` function tries to use `multiprocessing.Value` for inter-process coordination, but `check_chunk()` in `get_key_()` uses the plain global, which does not propagate across processes.
**Instead:** Use `multiprocessing.Event` or `multiprocessing.Value` consistently, or restructure to use `Pool.imap()` with early termination.

## Scalability Considerations

| Concern | At 1 user (current) | At maintenance scale | Notes |
|---------|---------------------|---------------------|-------|
| YARA rule maintenance | Update inline strings per version | Rules should be externalized to a config file or database | Each WeChat update potentially requires new rules |
| Offset table maintenance | Hard-coded per version | Should be data-driven, loadable from JSON | Similar to existing `version_list.json` for v3 |
| Memory scan performance | ~30 seconds on typical PC | Parallelism already implemented; room for early-exit optimization | `finish_flag` coordination bug wastes CPU |
| False positive candidates | 10-50 per scan | Filtering can be improved with additional heuristics | e.g., skip regions without specific marker strings |
| Version coverage | 4.0.3, 4.1.8.29 | Need systematic approach for new versions | Community-contributed rules + automated testing |

## Build Order Implications for Roadmap

The components have strict dependencies that dictate implementation order:

```
Phase 1: Diagnosis and Tooling
  |-- Memory dump analysis tool (new utility)
  |-- YARA rule testing harness
  |-- No dependency on other components
  |
Phase 2: Key Extraction Fix (highest priority)
  |-- Depends on: Phase 1 tooling
  |-- Fixes: GetKeyAddrStub YARA rule for 4.1.8+
  |-- Validates against: real encrypted DB file (existing is_ok mechanism)
  |-- Does NOT depend on: User info extraction (parallel concern)
  |
Phase 3: User Info Extraction Fix
  |-- Depends on: Phase 1 tooling (needs memory dumps to find new offsets)
  |-- Fixes: GetPhoneNumberOffset YARA rule + hard-coded offsets for 4.1.8+
  |-- Independent of: Key extraction fix
  |-- BUT should come after Phase 2 because: user info is less critical (decryption still works without it)
  |
Phase 4: End-to-End Validation
  |-- Depends on: Phase 2 + Phase 3
  |-- Validates: decrypt -> query -> export pipeline
  |-- Tests against: actual WeChat 4.1.8.29 data
  |
Phase 5: Hardening and Maintainability
  |-- Depends on: Phase 4 (working baseline)
  |-- Refactors: version-aware rule/offset system
  |-- Removes: duplicate code (wxinfo.py)
  |-- Adds: diagnostic logging, structured errors
```

**Key insight for roadmap:** Phases 2 and 3 are technically independent (different YARA rules, different memory patterns, different code paths). However, Phase 2 is more critical because without a valid key, nothing else works. Phase 3 (user info) is nice-to-have -- the system can function with just a key and wxid.

## Architecture Risks for the Fix

### Risk 1: YARA Pattern Discovery Requires Live WeChat Instance
The fundamental challenge is that new YARA patterns cannot be determined from code analysis alone. Someone must:
1. Run the target WeChat version (4.1.8.29)
2. Dump the process memory
3. Manually identify the new memory layout patterns
4. Craft new YARA rules that match reliably

This is a reverse-engineering task, not a programming task. The architecture should support rapid iteration of YARA rules without code changes.

### Risk 2: Version Proliferation
Each WeChat minor update may change memory layouts. The architecture needs a sustainable versioning strategy rather than one-off rule patches. The v3 approach (offset table in `version_list.json`) is a model, but v4's YARA-based approach is inherently more fragile than v3's simple module-offset approach because YARA patterns match structural byte sequences rather than fixed addresses.

### Risk 3: Multiprocessing Correctness
The current code has a subtle bug: `get_key_inner()` in `wx_info_v4.py` uses `if True or` to bypass the address-range validation that `wxinfo.py` enforces. This was likely a debugging workaround that got committed. The `finish_flag` global variable does not actually coordinate across multiprocessing Pool workers in `get_key_()`, wasting CPU on verification after a key is already found.

## Sources

- Primary source: `wxManager/decrypt/wx_info_v4.py` (main file needing modification)
- Supporting: `wxManager/decrypt/decrypt_v4.py` (DB decryption, shows expected key format)
- Supporting: `wxManager/decrypt/common.py` (WeChatInfo model, version detection)
- Supporting: `wxManager/decrypt/__init__.py` (process discovery, entry point)
- Supporting: `wxManager/decrypt/wxinfo.py` (duplicate/older version of v4 info extraction)
- Supporting: `wxManager/decrypt/decrypt_dat.py` (versioned key pattern to emulate)
- Architecture doc: `.planning/codebase/ARCHITECTURE.md` (existing system analysis)
- Note: Referenced project `wechat-dump-rs` (credited in source code) was taken down via DMCA
- Note: Referenced project `PyWxDump` received a cease-and-desist from WeChat legal
- Confidence: HIGH (based on direct code analysis, not external sources)
