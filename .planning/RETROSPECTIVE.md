# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — WeChatMsg Decrypt Fix

**Shipped:** 2026-04-25
**Phases:** 3 | **Plans:** 5 | **Tasks:** 9

### What Was Built
- Regex-first WCDB hex key scanning with YARA fallback, replacing fragile YARA-only approach for WeChat 4.x
- User nickname populated from decrypted contact.db after decryption, replacing empty memory-scan result
- Multiprocessing.Value for cross-process finish_flag, CloseHandle fixes for handle leaks, DataBaseV4.close() for all 9 DB connections
- HUMAN-UAT.md checklist for Windows validation of the full three-step pipeline

### What Worked
- Regex-first approach proved stable across WeChat 4.0-4.1.8.29 — the WCDB hex format is version-independent
- GSD workflow kept the project on track: discuss → research → plan → execute → verify cycle caught bugs early
- Phase 3 cherry-pick strategy recovered lost Phase 1 work quickly without manual re-implementation
- Integration checker caught a cosmetic but user-facing bug (wrong directory in success message)

### What Was Inefficient
- Phase 2 worktree merge accidentally reverted Phase 1 changes, requiring Phase 3 cherry-pick recovery — better merge conflict handling would have prevented this
- wxinfo.py is a full duplicate of wx_info_v4.py — every fix must be applied symmetrically, doubling review effort
- REQUIREMENTS.md checkboxes never updated during execution — audit had to infer completion from SUMMARY.md frontmatter
- No automated tests possible for Windows-only decryption code — all verification was code-level analysis

### Patterns Established
- Regex-first, YARA-fallback key extraction as the stable approach for WeChat 4.x
- User info from decrypted databases (not memory offsets) as the reliable pattern
- Minimal-change principle: targeted fixes without restructuring

### Key Lessons
1. Worktree merges can silently revert prior work — always verify key files exist after merge, not just that the merge completed
2. Duplicate files (wxinfo.py vs wx_info_v4.py) create maintenance debt — symmetric fixes are error-prone and should be consolidated
3. REQUIREMENTS.md checkbox updates should be automated as part of phase completion, not left to manual tracking
4. Windows-only tools benefit from code-level verification (grep, AST analysis) since runtime testing requires a separate environment

### Cost Observations
- Model mix: primarily sonnet for executor/verifier agents
- Sessions: ~4 sessions across 2 days
- Notable: Phase 3 (restore + fix) took significant context due to cherry-pick conflict resolution; small project scope (3 phases, 4 files) kept overhead manageable

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~4 | 3 | Initial GSD workflow setup; regex-first decryption approach established |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|-------------------|
| v1.0 | 0 (Windows-only) | 12/12 requirements | 0 (minimal-change principle) |

### Top Lessons (Verified Across Milestones)

1. Regex-based WCDB hex scanning is version-stable for WeChat 4.x key extraction
2. Minimal changes to existing code structure reduces regression risk in production tools
