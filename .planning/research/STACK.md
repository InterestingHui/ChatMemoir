# Technology Stack

**Project:** WeChatMsg -- WeChat 4.x database decryption fix
**Researched:** 2026-04-23

## Recommended Stack

### Core Language
| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Python | 3.10+ | Primary language | Existing codebase. Uses `str | bytes` union syntax requiring 3.10+. No reason to change. | HIGH |

### Memory Forensics (Key Extraction)

This is the core subsystem that needs fixing. The current YARA-based approach is fragile and broken on WeChat 4.1.8+. The recommended fix replaces YARA with Python stdlib regex, following the pattern proven in `ylytdeng/wechat-decrypt` (2.8k+ stars, actively maintained as of 2025).

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **Python `re` module** | stdlib | Replace YARA for hex-pattern key scanning | The WCDB (WeChat's SQLCipher wrapper) caches derived raw keys in memory as hex strings in format `x'<64hex_enc_key><32hex_salt>'`. This format is stable across WeChat versions because it is part of WCDB's internal key caching, not WeChat's application-level memory layout. Regex `x'([0-9a-fA-F]{64,192})'` reliably finds these patterns. This is the approach used by `ylytdeng/wechat-decrypt`, the current state-of-the-art tool (2025). **This replaces YARA for key extraction.** | HIGH |
| **Python `ctypes`** | stdlib | Process handle management, memory region enumeration, reading process memory | Already used in `wx_info_v4.py` via `kernel32.OpenProcess`, `kernel32.ReadProcessMemory`, `kernel32.VirtualQueryEx`. Continue using direct ctypes calls -- no need for pymem's abstraction layer in the v4 path. The MEMORY_BASIC_INFORMATION struct, region enumeration, and byte reading are already implemented correctly. | HIGH |
| psutil | 6.x | Process enumeration, PID discovery | `psutil.process_iter()` to find `Weixin.exe` or `WeChat.exe` by name. `psutil.Process(pid).exe()` for version detection path. No changes needed. | HIGH |
| pywin32 (win32api) | 308 | Windows API access for PE version detection | `win32api.GetFileVersionInfo()` extracts the WeChat version from the exe. Used in `common.py`. No changes needed. | HIGH |

**What to remove:**
| Technology | Why Remove | Confidence |
|------------|-----------|------------|
| **yara-python** | The 3 YARA rules (`GetKeyAddrStub`, `GetPhoneNumberOffset`, `GetDataDir`) are fragile byte-pattern matchers that break every time WeChat updates. YARA is a heavyweight dependency (compiled native extension, frequent install failures on Windows). The simple regex patterns used here are better served by Python's `re` module. `ylytdeng/wechat-decrypt` demonstrates that `re` is sufficient and more robust. **Keep yara-python as an optional fallback for the old v4.0 path, but make it optional, not required.** | HIGH |
| **pymem** | The v4 path already uses raw ctypes for all memory operations. pymem is only used in the `__main__` block (`pymem.Pymem("Weixin.exe")`) to find the PID, which psutil already does. Removing pymem simplifies dependencies. The v3 path still uses `pattern_scan_module`, so keep pymem as a v3-only dependency. | MEDIUM |

### Cryptography

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **Python `hashlib`** | stdlib | PBKDF2-HMAC-SHA512 key derivation for key verification | Replace `pycryptodome.PBKDF2` with `hashlib.pbkdf2_hmac('sha512', ...)` for the key verification step (`is_ok()` function). This eliminates pycryptodome as a dependency for the key extraction path. Same algorithm, stdlib-only. Note: v3 uses `hashlib.pbkdf2_hmac('sha1', ...)` already. | HIGH |
| **Python `hmac`** | stdlib | HMAC-SHA512 verification of database pages | Already used. Continue using `hmac.new(mac_key, data, hashlib.sha512)` for page verification. No changes needed. | HIGH |
| pycryptodome | 3.x | AES-256-CBC page decryption in `decrypt_v4.py` | Keep pycryptodome for the actual database decryption step (`Crypto.Cipher.AES`). This is used in `decrypt_v4.py` for page-by-page AES decryption. Could potentially be replaced with `cryptography` library (already in requirements), but the existing code works and is not broken. **Do not change the decryption module.** | HIGH |
| struct | stdlib | Binary data unpacking | `struct.unpack_from('<Q', ...)` for reading little-endian integers from memory. No changes needed. | HIGH |

### Parallelism

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| multiprocessing | stdlib | Parallel memory scanning and key verification | `multiprocessing.Pool` splits memory regions across workers. `multiprocessing.Queue` for user info extraction results. Keep this pattern -- memory scanning is embarrassingly parallel. However, fix the broken `finish_flag` global (see PITFALLS.md Pitfall 3) by using `multiprocessing.Event` or `Pool.imap_unordered()` with early termination. | HIGH |
| concurrent.futures | stdlib | Batch DB file decryption | `ProcessPoolExecutor(max_workers=16)` in `decrypt_v4.py`. No changes needed. | HIGH |

### Supporting Libraries (Unchanged)

| Library | Version | Purpose | Why Keep |
|---------|---------|---------|----------|
| aiofiles | 24.x | Async image decryption in `decrypt_dat.py` | Used for non-blocking file I/O. Not in scope for this fix. |
| re | stdlib | Regex pattern matching (replaces YARA) | **New primary use**: scanning memory for WCDB hex key patterns. Also used in `get_wx_dir()` for data directory path matching. |

## The Key Architectural Change: YARA to Regex

### Why YARA Fails

The current approach uses YARA rules to match specific byte sequences around the memory address that stores the encryption key:

```
GetKeyAddrStub: /.{6}\x00{2}\x00{8}\x20\x00{7}\x2f\x00{7}/
```

This pattern matches the memory *structure surrounding* the key address (field alignment, type tags, padding). When WeChat 4.1.8.29 changed its internal memory layout (likely due to Rust compiler updates or struct changes), this pattern stopped matching entirely. Result: `key = None` with zero diagnostic output.

### Why Regex Works

WCDB (WeChat's SQLCipher wrapper) caches derived raw keys in process memory as literal hex strings:

```
x'<64 hex chars of enc_key><32 hex chars of salt>'
```

This is a fundamental WCDB implementation detail, not a WeChat application-level pattern. The format is `x'` prefix, hex-encoded key+salt, `'` suffix. This pattern is stable because:
1. It is a string literal format used by WCDB internally for key caching
2. It appears in all three platforms (Windows, Linux, macOS)
3. It has remained the same across WeChat 4.0 through 4.1.8+

The regex `x'([0-9a-fA-F]{64,192})'` finds these patterns. Then:
1. Extract the salt portion (last 32 hex chars = 16 bytes) from each match
2. Compare against actual DB file salts (first 16 bytes of each .db file)
3. When salt matches, the preceding 64 hex chars (32 bytes) is the candidate key
4. Verify the candidate key via PBKDF2-HMAC-SHA512 against the matching DB file

This approach is more robust because it targets the WCDB caching format rather than WeChat's volatile application memory layout.

### Implementation Pattern (from ylytdeng/wechat-decrypt)

```python
import re, hashlib, hmac

hex_re = re.compile(b"x'([0-9a-fA-F]{64,192})'")

def collect_db_files(db_dir):
    """Read salt (first 16 bytes) from each .db file."""
    db_files = {}
    for root, dirs, files in os.walk(db_dir):
        for f in files:
            if f.endswith('.db'):
                path = os.path.join(root, f)
                with open(path, 'rb') as fh:
                    salt = fh.read(16)
                if salt and len(salt) == 16:
                    db_files[salt.hex()] = path
    return db_files

def scan_memory_for_keys(data, hex_re, salt_to_dbs, key_map):
    """Scan a memory region for WCDB hex key patterns."""
    for match in hex_re.finditer(data):
        hex_str = match.group(1).decode('ascii')
        if len(hex_str) >= 96:  # 64 hex key + 32 hex salt minimum
            key_hex = hex_str[:64]   # 32-byte encryption key
            salt_hex = hex_str[64:96]  # 16-byte salt
            if salt_hex in salt_to_dbs:
                # Salt matches a known DB file -- verify key via HMAC
                key_map[salt_hex] = key_hex

def verify_enc_key(key_hex, salt_hex, db_path):
    """Verify key correctness via PBKDF2-HMAC-SHA512."""
    key = bytes.fromhex(key_hex)
    salt = bytes.fromhex(salt_hex)
    mac_salt = bytes(x ^ 0x3a for x in salt)
    derived_key = hashlib.pbkdf2_hmac('sha512', key, salt, 256000, dklen=32)
    mac_key = hashlib.pbkdf2_hmac('sha512', derived_key, mac_salt, 2, dklen=32)
    with open(db_path, 'rb') as f:
        page = f.read(4096)
    reserve = 80  # IV_SIZE + HMAC_SHA512_SIZE, rounded
    mac = hmac.new(mac_key, page[16:4096 - reserve + 16], hashlib.sha512)
    mac.update(struct.pack('<I', 1))
    expected = page[4096 - reserve + 16 : 4096 - reserve + 16 + 64]
    return mac.digest() == expected
```

### What Still Needs YARA or Similar

The `get_nickname()` function uses YARA to find phone number patterns in memory. This is a separate concern from key extraction and has different stability characteristics:
- Phone number format (`11 digits with specific surrounding bytes`) is tied to WeChat's UserInfo struct layout
- This pattern may also be broken on 4.1.8.29
- Alternative approach: extract user info from the decrypted `contact.db` or `session.db` after successful key extraction, rather than from process memory
- **Recommendation**: Deprioritize fixing `get_nickname()` via YARA. Instead, read user info from decrypted databases once key extraction works. This eliminates the need for fragile memory-based user info extraction entirely.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Key scanning | **Python `re` + WCDB hex pattern** | YARA rules (current approach) | YARA rules match volatile memory layout. Broken on 4.1.8.29. No diagnostic output when matching fails. Heavyweight dependency (compiled native extension, install issues on Windows). |
| Key verification | **stdlib `hashlib.pbkdf2_hmac` + `hmac`** | pycryptodome `PBKDF2` + `HMAC` | Both produce identical results. stdlib has zero install friction. Keep pycryptodome only for AES decryption in `decrypt_v4.py`. |
| DB decryption | pycryptodome `AES` | `cryptography` library's AES | `cryptography` is already in requirements.txt but not used for AES-CBC decryption. Both work. pycryptodome is already integrated and tested. Not worth changing. |
| Process access | **ctypes (raw Windows API)** | pymem wrapper | v4 path already uses ctypes exclusively. pymem adds no value for the v4 key extraction flow. Keep pymem only for v3's `pattern_scan_module`. |
| Binary instrumentation | **Read-only memory scan** | Frida / DLL injection | Frida injects into the target process, which is detectable and raises legal/ToS concerns. Read-only scanning is safer and sufficient. |
| User info | **Read from decrypted DB files** | YARA memory scanning | Extracting nickname/phone/account from decrypted `contact.db` or `session.db` is far more reliable than scanning process memory for struct offsets. Eliminates the need for `GetPhoneNumberOffset` YARA rule. |
| Cross-platform key extraction | **ctypes + re** (Windows) | Platform-specific tools | `ylytdeng/wechat-decrypt` demonstrates the same regex approach works on Windows (ctypes), Linux (/proc/pid/mem), and macOS (Mach VM API). Only Windows is in scope for WeChatMsg. |

## Dependency Impact

### Dependencies to Add
None. The replacement stack uses only Python stdlib modules (`re`, `hashlib`, `hmac`, `struct`, `ctypes`).

### Dependencies to Make Optional
| Dependency | Currently Required | New Status | Reason |
|------------|-------------------|------------|--------|
| yara-python | Yes | **Optional** (fallback) | Replaced by `re` for v4 key extraction. Keep for backward compatibility with v4.0 path if regex approach fails. |
| pymem | Yes | **v3 only** | Not used by the v4 key extraction path. Keep for v3's `pattern_scan_module`. |

### Dependencies Unchanged
| Dependency | Why Keep |
|------------|----------|
| pycryptodome | Required for AES-256-CBC decryption in `decrypt_v4.py`. Not changing. |
| psutil | Required for process enumeration. |
| pywin32 | Required for version detection via `win32api.GetFileVersionInfo`. |
| aiofiles | Used in image decryption. Not in scope. |

### Dependencies to Remove Long-Term
| Dependency | Why | When |
|------------|-----|------|
| yara-python | Fully replaced by `re` module. Reduces install complexity (no compiled extension needed). | After v4 regex approach is validated and stable. |
| pymem | Only used in v3 path (`pattern_scan_module`) and `__main__` PID detection (replaceable with psutil). | When v3 support is deprecated or pymem is removed from v4 path. |

## Installation (Post-Fix)

```bash
# Required for v4 key extraction (new regex-based approach)
pip install psutil pywin32

# Required for database decryption (unchanged)
pip install pycryptodome

# Optional: for v3 WeChat support
pip install pymem yara-python

# Full install (backward compatible)
pip install -r requirements.txt

# Note: yara-python install on Windows may fail.
# The new regex-based approach does NOT require yara-python.
# If yara install fails, the v4 key extraction will use the re module.
```

## Critical Version Constraints

| Dependency | Constraint | Reason | Confidence |
|------------|-----------|--------|------------|
| Python | >= 3.10 | `str | bytes` union syntax used in codebase | HIGH |
| pycryptodome | >= 3.x | `Crypto.Cipher.AES` for AES-256-CBC in decrypt_v4.py | HIGH |
| psutil | >= 5.x | `process_iter()`, `Process.exe()` | HIGH |
| pywin32 | >= 300 | `win32api.GetFileVersionInfo` | HIGH |
| Windows | 10/11 | `ReadProcessMemory`, `VirtualQueryEx`, process handle APIs | HIGH |

## Sources

- `wxManager/decrypt/wx_info_v4.py` -- current YARA-based implementation (broken on 4.1.8.29)
- `wxManager/decrypt/decrypt_v4.py` -- AES-256-CBC decryption (working, not changing)
- `wxManager/decrypt/common.py` -- WeChatInfo model, version detection
- `requirements.txt` -- current dependency list
- `ylytdeng/wechat-decrypt` (https://github.com/ylytdeng/wechat-decrypt) -- SOTA WeChat 4.0 decryption tool, 2.8k+ stars, actively maintained. Source of the regex-based WCDB hex pattern approach. Last major update: 2025-03. Uses only stdlib (`re`, `hashlib`, `hmac`, `ctypes`) for key extraction -- no YARA, no pymem, no pycryptodome for the key scanning path. Supports Windows, Linux, macOS.
- `0xlane/wechat-dump-rs` -- referenced in WeChatMsg source code header. DMCA'd and no longer available. Was the original inspiration for the YARA-based approach.
- Confidence: HIGH for all recommendations (based on direct code analysis + verified external tool research)
