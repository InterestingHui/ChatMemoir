---
phase: 03-pipeline-validation-and-code-health
plan: 02
subsystem: wxManager
tags: [bug-fix, resource-leak, validation]
dependency_graph:
  requires: []
  provides: [close-method-fix, favorite-db-guard, human-uat-checklist]
  affects: [wxManager/manager_v4.py, wxManager/manager_v3.py]
tech_stack:
  added: []
  patterns: [None-guard pattern for optional database attributes]
key_files:
  created:
    - path: .planning/phases/03-pipeline-validation-and-code-health/HUMAN-UAT.md
      purpose: Manual validation checklist for full pipeline testing on Windows
  modified:
    - path: wxManager/manager_v4.py
      purpose: Fixed close() to release all 9 DB connections; added favorite_db None guard
    - path: wxManager/manager_v3.py
      purpose: Added favorite_db None guard to prevent AttributeError
decisions:
  - Used hasattr + None guard pattern for favorite_db instead of initializing a stub
metrics:
  duration: 7m 30s
  completed: "2026-04-24"
  tasks_total: 2
  tasks_completed: 2
  files_modified: 3
  files_created: 1
---

# Phase 03 Plan 02: Fix close() and favorite_db + HUMAN-UAT Summary

Properly close all 9 database connections in DataBaseV4.close(), guard against uninitialized favorite_db in both V3/V4 managers, and create a manual validation checklist for Windows pipeline testing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix DataBaseV4.close() and favorite_db guards | 4802268 | wxManager/manager_v4.py, wxManager/manager_v3.py |
| 2 | Generate HUMAN-UAT.md validation checklist | 1d2b6f5 | .planning/phases/03-pipeline-validation-and-code-health/HUMAN-UAT.md |

## Changes Made

### Task 1: DataBaseV4.close() and favorite_db guards

**close() fix (manager_v4.py):**
- Replaced empty `pass` body with 9 `.close()` calls covering all database attributes: contact_db, head_image_db, session_db, message_db, biz_message_db, media_db, hardlink_db, emotion_db, audio2text_db
- Removed commented-out incomplete close lines

**favorite_db guard (both managers):**
- Added `if not hasattr(self, 'favorite_db') or self.favorite_db is None: return []` guard to `get_favorite_items()` in both `DataBaseV3` and `DataBaseV4`
- Neither manager initializes `self.favorite_db` in `__init__` or `init_database`, so calling `get_favorite_items()` would previously raise `AttributeError`

### Task 2: HUMAN-UAT.md

- Created comprehensive manual validation checklist covering all 3 pipeline steps
- Each step has specific expected outputs with PASS/FAIL checkboxes
- Includes post-validation resource leak checks to verify the close() fix
- References actual console messages from the codebase for accurate validation

## Verification Results

All 4 plan-level verification checks passed:

1. `grep -c "\.close()" wxManager/manager_v4.py` returns 9
2. `grep "favorite_db is None"` matches in both manager files
3. HUMAN-UAT.md exists at correct path
4. PASS/FAIL checkboxes present (26 checkbox lines)

## Deviations from Plan

None - plan executed exactly as written.

## Threat Flags

No new threat surface introduced. The close() fix mitigates T-03-04 (DoS via unclosed connections) as planned.

## Self-Check: PASSED

- FOUND: wxManager/manager_v4.py
- FOUND: wxManager/manager_v3.py
- FOUND: .planning/phases/03-pipeline-validation-and-code-health/HUMAN-UAT.md
- FOUND: .planning/phases/03-pipeline-validation-and-code-health/03-02-SUMMARY.md
- FOUND: commit 4802268 (Task 1)
- FOUND: commit 1d2b6f5 (Task 2)
