# Feature Landscape

**Domain:** WeChat database decryption and chat history extraction tools
**Researched:** 2026-04-23
**Confidence:** HIGH (based on direct code analysis, competitive landscape review, and ecosystem research)

## Table Stakes

Features users expect. Missing = product feels incomplete or fails at its primary purpose.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| WeChat process detection | Without finding the running WeChat process, nothing else works. Users expect the tool to "just find WeChat." | Low | psutil iterates `process_iter()` matching `WeChat.exe` (v3) or `Weixin.exe` (v4). Already works. |
| Version detection | Users need to know if their WeChat version is supported. Error messaging depends on it. | Low | `get_version()` via `win32api.GetFileVersionInfo`. Already works. |
| Database encryption key extraction from process memory | This IS the core problem. Without the key, no decryption is possible. Users expect the tool to extract the key automatically. | High | YARA-based memory scanning. Currently broken on 4.1.8.29. The hardest feature to maintain because it depends on reverse-engineered memory layouts that change with every WeChat update. |
| Key verification against a known encrypted DB file | Users expect certainty. The tool must confirm the extracted key actually works before proceeding. | Medium | PBKDF2-HMAC-SHA512 (256K rounds) verification in `is_ok()`. Already works once a candidate key is found. |
| User info extraction (nickname, phone, account name) | Users expect to see their own WeChat profile info as confirmation that the tool found the right account. | High | YARA-based phone number pattern matching with fixed relative offsets. Broken on 4.1.8.29 alongside key extraction. |
| wxid extraction | The wxid is needed to identify which user's data to decrypt. It is also used in directory path construction. | Medium | v3: pattern scan for `\Msg\FTSContact` path. v4: parsed from `wx_dir` path. v4 approach is more reliable. |
| Data directory discovery | The tool must locate the `xwechat_files` (v4) or `WeChat Files` (v3) directory containing encrypted databases. | Medium | v4: YARA regex scanning for `xwechat_files\...\db_storage\` path in memory. v3: registry + file heuristics. v4 approach currently works for path detection. |
| AES-256-CBC database file decryption | After key extraction, the actual DB files must be decrypted to standard SQLite format. | Medium | `decrypt_v4.py` handles this. Well-understood algorithm. Not currently broken. |
| Batch decryption of all DB files | Users have dozens of database files (contacts, messages, media, favorites, etc.) and expect all of them to be decrypted in one step. | Low | `decrypt_db_files()` walks directory tree, uses `ProcessPoolExecutor(max_workers=16)`. Already works. |
| Multi-format chat export (HTML, TXT, CSV, DOCX, XLSX, Markdown, JSON) | Users want their chat history in a format they can read, archive, or process. | Medium | `exporter/` module handles 7 formats. Already works. Not in scope for this fix. |
| Contact list query and display | After decryption, users expect to browse their contacts and select which conversations to export. | Medium | `wxManager/db_v4/contact.py` handles this. Depends on successful decryption. |
| Message type parsing (text, image, video, voice, emoji, etc.) | Chat messages contain diverse content types. Users expect all of them to be parsed correctly. | High | `wxManager/db_v4/message.py`, `media.py`, `emotion.py`, etc. Multiple message types with complex binary formats. Depends on successful decryption. |

## Differentiators

Features that set the product apart from other WeChat data extraction approaches. Not expected by users, but highly valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| YARA-based memory scanning (vs hardcoded offsets) | YARA rules are more expressive than simple byte patterns. They can use regex, wildcards, and hex patterns to match structured data in memory. This is more resilient than the v3 approach of hardcoded bias addresses from `version_list.json`. | High | The current approach, but it needs updating for 4.1.8.29. The key advantage over v3 is that one YARA rule can theoretically cover multiple WeChat versions, whereas v3 needs a new entry in `version_list.json` for every single version. |
| Brute-force candidate key enumeration | The tool does not assume the first candidate address is correct. It scans all memory, collects every 32-byte sequence that looks like a key, and verifies each one against a real database file. This is robust against memory layout changes. | High | `get_key_inner()` collects candidates, `get_key_()` verifies via multiprocessing Pool. The verification is the expensive part (256K PBKDF2 rounds per candidate). |
| Parallel multiprocessing for memory scanning | Scanning all process memory regions is slow. Splitting the work across CPU cores makes extraction practical (seconds instead of minutes). | Medium | `get_key()` splits memory regions into up to 40 chunks, each processed by a separate worker. `get_key_()` uses a Pool for key verification. |
| Version-independent architecture (v3/v4 strategy pattern) | The codebase handles both WeChat 3.x and 4.x through separate extraction paths (`wx_info_v3.py` vs `wx_info_v4.py`). The dispatch logic in `get_wx_info.py` auto-detects which version is running. | Medium | Already implemented. The tradeoff is dual codebase maintenance (see Pitfalls), but the benefit is that a v4 fix does not risk breaking v3. |
| Offline decryption support | Once the key is extracted, decryption can be performed later on a different machine. The key is a hex string that can be saved and reused. | Low | `decrypt_db_file_v4()` takes a key string and file paths. No running WeChat process needed for decryption itself. |
| Image decryption (XOR + AES-ECB for v4) | WeChat encrypts images with a different scheme than databases. v4 images use AES-ECB with hardcoded keys plus XOR obfuscation. Supporting this makes exported chat histories visually complete. | Medium | `decrypt_dat.py` handles both v3 (simple XOR) and v4 (AES-ECB + XOR). The v4 XOR key is derived from thumbnail file analysis. |
| Async image batch decryption | For large chat histories with thousands of images, async processing prevents the UI from freezing. | Low | `decode_dat_v4_async()` uses `aiofiles`. Parallel batch processing via `ProcessPoolExecutor`. |
| Most-frequent-match strategy for data directory | Instead of trusting a single YARA match, `get_wx_dir()` counts how many times each path appears across memory regions and picks the most frequent one. This is robust against stale memory copies. | Low | `wx_dir_cnt` dict with `max(key=wx_dir_cnt.get)`. Simple but effective. |
| Cross-version database format auto-detection | The v3 and v4 databases use different encryption parameters (SHA1/64K vs SHA512/256K rounds). The tool needs to detect which format a given DB file uses. | Low | Currently handled by the v3/v4 dispatch. Could be improved by reading the DB file header to auto-detect. |

## Anti-Features

Features to explicitly NOT build. These are outside the project's scope or would compromise its purpose.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| DLL injection or function hooking | WeChatFerry and similar tools inject `sdk.dll` into the WeChat process to hook internal functions. This is detectable by WeChat's anti-cheat, can cause crashes, and has legal risk (violates WeChat's terms of service). It also requires maintaining hooks for every WeChat version. | Read-only memory scanning. Never inject code or modify the WeChat process. The current approach of `ReadProcessMemory` is passive and less likely to trigger anti-tampering. |
| Real-time message interception | Monitoring WeChat messages as they arrive requires hooking internal functions or reading message databases in real-time. This crosses the line from "backup your own data" to "surveillance tool." | Offline batch extraction only. Decrypt static database files after the user requests it. |
| Message sending capability | Any ability to send messages through WeChat programmatically is bot functionality, not data extraction. It is also the fastest way to get an account banned. | Extract and export only. No write capability to WeChat's databases or network. |
| Automated WeChat interaction (bot mode) | Some tools (WeChatFerry) support programmatic friend adding, group management, auto-reply. This is completely outside the scope of a data extraction tool and carries severe legal and ToS risk. | Focus exclusively on the "decrypt, query, export" pipeline. |
| Cloud-based decryption service | Sending user's encrypted databases or memory dumps to a remote server for decryption creates massive privacy concerns. Users' WeChat data contains highly personal conversations. | All processing must be local. The key extraction and decryption happen entirely on the user's machine. |
| Rooted/jailbroken phone support | Some tools extract WeChat data from phone backups or rooted devices. This is a different domain entirely and would double the codebase scope. | Focus on Windows desktop WeChat only. The mobile database format is different (Android uses SQLCipher directly, not the same AES-CBC scheme). |
| GUI modifications for this fix | The problem is in the backend decryption logic. The GUI does not need changes to support the fix. | Fix the backend (`wx_info_v4.py`). The GUI already displays whatever the backend returns via `WeChatInfo`. |
| New export formats | The existing 7 export formats cover all common use cases. Adding more formats does not fix the core problem. | Focus on making decryption work. Export is downstream and already functional. |
| Machine learning or AI-based pattern detection | Using ML to find keys in memory is massive overkill for what is essentially a regex matching problem. It would add huge dependencies (PyTorch/TensorFlow), require training data, and be slower than byte-pattern matching. | Update YARA rules or use Python `re` module. The patterns are deterministic byte sequences, not ambiguous signals. |
| Version list maintenance for v4 | The v3 approach of maintaining `version_list.json` with hardcoded offsets for every WeChat version does not scale. There are 100+ v3 versions in the list, and adding v4 versions would require reverse engineering every single update. | Use version-independent YARA rules that work across minor version updates. Accept that major version changes may need rule updates, but minor updates should be covered by the same rules. |

## Feature Dependencies

```
Process Detection (WeChat.exe / Weixin.exe)
  |
  +--> Version Detection
  |      |
  |      +--> [determines v3 vs v4 path]
  |
  +--> Data Directory Discovery (wx_dir)
  |      |
  |      +--> wxid Extraction (v4: parsed from path)
  |
  +--> Key Extraction (YARA memory scan)
  |      |
  |      +--> Key Verification (PBKDF2 against known DB)
  |
  +--> User Info Extraction (nickname, phone, account)
  |
  +--> Database Decryption (AES-256-CBC)
         |
         +--> Contact Query
         |      |
         |      +--> Message Query
         |             |
         |             +--> Message Type Parsing (text, image, video, etc.)
         |             |      |
         |             |      +--> Image Decryption (XOR + AES-ECB)
         |             |
         |             +--> Multi-format Export (HTML, TXT, CSV, DOCX, XLSX, MD, JSON)
         |
         +--> Batch Decryption (all DB files in directory tree)
```

**Critical path:** Process Detection -> Key Extraction -> Key Verification -> Database Decryption -> everything else

**Parallelizable paths:**
- User Info Extraction runs independently of Key Extraction (already parallelized via `multiprocessing.Process`)
- Data Directory Discovery runs independently of Key Extraction
- After decryption: Contact Query, Message Query, and Export can run in parallel for different conversations

**Blocking dependencies:**
- Key Extraction BLOCKS everything downstream (no key = no decryption = no contacts = no export)
- User Info Extraction does NOT block decryption (it is informational only)
- Data Directory Discovery BLOCKS Key Verification (needs a DB file from `wx_dir` for verification)

## MVP Recommendation

For this specific fix (WeChat 4.1.8.29 compatibility), prioritize:

1. **Fix YARA rule `GetKeyAddrStub`** -- The key extraction rule must match the new memory layout. This is the single most impactful fix. Without it, nothing else matters.
2. **Fix YARA rule `GetPhoneNumberOffset`** -- User info extraction depends on this. Secondary priority because the tool can still decrypt without it, but users expect to see their profile info.
3. **Add diagnostic logging** -- When rules fail to match, log which step failed, how many regions were scanned, and what version was detected. This is the difference between "the tool is broken" and "your WeChat version 4.1.8.29 is not yet supported, here is what to do."

Defer:
- **Multiprocessing `finish_flag` fix**: Important for performance but does not affect correctness. The key will still be found; it just takes longer than necessary.
- **Address validation cleanup (`if True or`)**: The bypass works. Removing it is correct but risky without understanding why it was added.
- **Dual codebase consolidation**: Refactoring can wait until the fix is verified.

## Key Extraction Technique Comparison

The core technical question for this project: how do you extract the AES-256 encryption key from a running WeChat process?

| Technique | Used By | Robustness | Maintenance Burden | Legal Risk | Speed |
|-----------|---------|------------|-------------------|------------|-------|
| YARA regex memory scan | WeChatMsg (this project) | MEDIUM -- breaks on memory layout changes | MEDIUM -- update rules when layout changes | LOW -- read-only | Slow (full memory scan) |
| Hardcoded DLL offsets (version_list.json) | WeChatMsg v3, PyWxDump (deleted) | LOW -- breaks on every version | HIGH -- new entry per version | LOW -- read-only | Fast (direct offset read) |
| Phone type string anchoring | WeChatMsg v3 (`get_key()` in `get_wx_info.py`) | MEDIUM -- breaks if phone strings move | MEDIUM -- rescan on version change | LOW -- read-only | Medium (module scan + walk) |
| Public key string anchoring | WeChatMsg v3 (`get_key_bias1()`) | MEDIUM -- breaks if key storage changes | MEDIUM | LOW | Medium (global scan + module scan) |
| DLL injection + function hooking | WeChatFerry (archived) | HIGH -- hooks call internal APIs directly | HIGH -- hooks break on any internal change | HIGH -- injects code, violates ToS | Fast (direct call) |
| Frida dynamic instrumentation | Academic/security research | HIGH -- can adapt at runtime | HIGH -- needs scripts per version | HIGH -- modifies process | Fast |
| Screenshot + OCR (proposed by maintainer) | Future direction for WeChatMsg | LOW -- depends on OCR accuracy, slow | LOW -- UI layout changes less often | LOW -- screenshots are user's data | Very slow |

**Recommendation:** Stay with YARA-based memory scanning (the current approach). It offers the best balance of robustness, legal safety, and maintenance burden. The alternative (DLL injection) is more robust but carries unacceptable legal and stability risks. The v3 approach (hardcoded offsets) does not scale.

The specific fix needed: update the `GetKeyAddrStub` and `GetPhoneNumberOffset` YARA rules to match WeChat 4.1.8.29's memory layout. This requires reverse-engineering the new layout, which is a manual binary analysis task (use x64dbg or similar on the target WeChat version).

## Ecosystem Context

**Competitive landscape (2026):**

| Tool | Status | Key Technique | Stars/Reach |
|------|--------|---------------|-------------|
| WeChatMsg (this project) | Semi-active (maintainer says "won't update") | YARA memory scan | 36k+ stars, most popular |
| PyWxDump (xaoyaoo) | DELETED -- author removed after legal notice (Oct 2025) | Hardcoded offsets + version_list.json | Was 9.8k stars |
| wechat-dump-rs (0xlane) | DMCA takedown | Rust-based memory scanning | Was referenced in this codebase |
| WeChatFerry | ARCHIVED | DLL injection + hooking | Was popular for bot use cases |
| Various forks of the above | Scattered, most outdated | Copy techniques from above | Low individual reach |

**Key observation:** The legal environment is hostile to WeChat decryption tools. Multiple high-profile projects have been taken down. This project should:
1. Focus on personal data backup (framing matters)
2. Avoid features that enable surveillance or bot use
3. Not depend on any centralized service

## Sources

- Direct code analysis: `wxManager/decrypt/wx_info_v4.py`, `wx_info_v3.py`, `get_wx_info.py`, `decrypt_v4.py`, `decrypt_v3.py`, `decrypt_dat.py`, `get_bias_addr.py`, `common.py`, `__init__.py`
- Project context: `.planning/PROJECT.md`
- Competitive analysis: PyWxDump (deleted, via web archive), wechat-dump-rs (DMCA'd), WeChatFerry (archived)
- WeChatMsg GitHub issues and commit history for version adaptation patterns
- Confidence: HIGH for all features listed (based on direct code inspection), MEDIUM for competitive landscape (some tools are deleted/archived, info from secondary sources)
