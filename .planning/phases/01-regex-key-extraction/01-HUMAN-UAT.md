---
status: partial
phase: 01-regex-key-extraction
source: [01-VERIFICATION.md]
started: 2026-04-24T09:50:00+08:00
updated: 2026-04-24T09:50:00+08:00
---

## Current Test

[awaiting human testing]

## Tests

### 1. WeChat 4.1.8.29 Key Extraction End-to-End
expected: Run `python 1-decrypt.py` with WeChat 4.1.8.29 running and logged in on Windows with admin privileges. Key extraction returns a valid hex key. Console shows regex scan progress and success message.
result: [pending]

### 2. WeChat 4.0.3 Backward Compatibility
expected: Run `python 1-decrypt.py` with WeChat 4.0.3 running. Key extraction succeeds via regex or YARA fallback.
result: [pending]

### 3. HMAC Verification Consistency
expected: Both `is_ok` (pycryptodome) and `_verify_key_stdlib` (stdlib) agree on the same key+DB pair.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
