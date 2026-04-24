# Phase 3: Pipeline Validation and Code Health - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 03-pipeline-validation-and-code-health
**Areas discussed:** Phase 1 回退修复, 管道验证策略, Bug 修复范围

---

## Phase 1 回退修复

| Option | Description | Selected |
|--------|-------------|----------|
| Cherry-pick + 合并冲突 | 用 git cherry-pick 819903e 和 fc9f38f 恢复 regex 代码，然后手动合并 Phase 2 的昵称查询改动 | ✓ |
| 重新实现 regex 函数 | 直接重新写 regex_scan_keys 等函数到当前文件中 | |
| Reset 到 Phase 1 状态再重做 Phase 2 | 回退到 819903e，重新应用 Phase 2 改动 | |

**User's choice:** Cherry-pick + 合并冲突
**Notes:** Phase 2 worktree 合并意外覆盖了 Phase 1 的 regex_scan_keys、collect_db_salts、_verify_key_stdlib 函数。当前 wx_info_v4.py 和 wxinfo.py 都退回到 YARA-only 状态。

---

## 管道验证策略

| Option | Description | Selected |
|--------|-------------|----------|
| 人工 Windows 验证 | Phase 3 代码完成后，用户在 Windows 上手动运行三步流水线，报告结果 | ✓ |
| 部分自动化测试 | 用已有解密 DB 跑步骤 2、3，步骤 1 只做代码审查 | |
| 纯代码审查 | 代码审查 + 路径可达性分析，不依赖运行时 | |

**User's choice:** 人工 Windows 验证
**Notes:** WSL2 无法运行微信进程，自动化测试无法覆盖解密步骤。

---

## Bug 修复范围

| Option | Description | Selected |
|--------|-------------|----------|
| 最小修复集 | CODE-01 + CODE-02 + favorite_db + close() | ✓ |
| 最小集 + 权限降级 | 在最小集基础上降级 PROCESS_ALL_ACCESS | |
| 严格按 ROADMAP 范围 | 只修 CODE-01 和 CODE-02 | |

**User's choice:** 最小修复集
**Notes:** favorite_db 未初始化和 close() 空操作会直接导致流水线失败（AttributeError 和资源泄漏），必须纳入。bare except、ProcessPoolExecutor、eval 等留待 v2。

---

## Claude's Discretion

- Cherry-pick 冲突解决方式
- finish_flag 共享机制实现细节
- favorite_db 初始化参数
- close() 中数据库列表
- 诊断信息格式

## Deferred Ideas

- 115 处 bare except 替换
- ProcessPoolExecutor 重复开 DB 优化
- eval() 安全替换
- PROCESS_ALL_ACCESS 权限降级
- DataBaseBase.cursor 歧义修复
- v3 路径同类 bug
