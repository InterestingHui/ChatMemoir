# Phase 3: Pipeline Validation and Code Health - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

验证完整的 decrypt→contact→export 三步流水线在微信 4.1.8.29 上端到端工作，并修复直接影响流水线运行的代码缺陷。包含：恢复被意外回退的 Phase 1 regex 密钥提取代码、修复多进程 finish_flag 跨进程失效、修复进程句柄泄漏、修复 favorite_db 未初始化、修复 DataBaseV4.close() 空操作。不重构现有代码结构（CODE-03 最小改动原则）。

</domain>

<decisions>
## Implementation Decisions

### Phase 1 回退修复
- **D-01:** Cherry-pick Phase 1 原始提交 (`819903e` 给 `wx_info_v4.py`，`fc9f38f` 给 `wxinfo.py`) 恢复 regex 密钥提取代码，然后手动合并 Phase 2 的昵称查询改动。保留原始提交历史追溯。
- **Why:** Phase 2 worktree 合并意外覆盖了 Phase 1 的 regex_scan_keys、collect_db_salts、_verify_key_stdlib 函数和 dump_wechat_info_v4 的 regex-first 控制流。当前代码退回到 YARA-only 状态，无法在 4.1.8.29 上提取密钥。
- **How to apply:** 研究者和计划者需先 cherry-pick 恢复 regex 代码，确保不丢失 Phase 2 在 dump_v4() 中添加的昵称查询逻辑。冲突解决时 Phase 1 的 regex 函数 + Phase 2 的昵称查询都要保留。

### 管道验证策略
- **D-02:** 人工 Windows 验证。Claude 确保代码逻辑正确（代码审查 + 路径可达性分析），用户在 Windows 实际环境运行 1-decrypt.py → 2-contact.py → 3-exporter.py 完整流水线并报告结果。
- **Why:** 当前开发环境是 WSL2 Linux，无法运行微信进程。自动化测试无法覆盖解密步骤（需要活体微信进程）。
- **How to apply:** 计划者需生成一份人工验证步骤清单（HUMAN-UAT），列出每一步的预期输出。Phase 完成标准基于代码逻辑正确性 + 用户确认。

### Bug 修复范围
- **D-03:** 最小修复集 = CODE-01 (finish_flag 多进程共享) + CODE-02 (句柄泄漏) + favorite_db 未初始化 + DataBaseV4.close() 空操作。其余 bare except、ProcessPoolExecutor 重复开 DB、eval() 替换、权限降级等留待 v2 requirements。
- **Why:** 只修直接影响流水线能否跑通的 bug。bare except 和性能问题不影响功能正确性，属于代码质量改进。
- **How to apply:**
  - finish_flag: `wx_info_v4.py:47` 和 `wxinfo.py:49` 的全局 `finish_flag = False` 改为 `multiprocessing.Value` 或在 `check_chunk`/`get_key_` 中使用 Pool 的共享状态
  - 句柄泄漏: 确认 `wx_info_v4.py:487` 和 `wxinfo.py:523` 的 `CloseHandle(process_handle)` 被调用，检查异常路径是否有泄漏
  - favorite_db: 在 `DataBaseV3.__init__` 和 `DataBaseV4.__init__` 中初始化 `self.favorite_db`
  - close(): `DataBaseV4.close()` (`manager_v4.py:107-111`) 取消注释，添加所有数据库 close 调用

### Claude's Discretion
- Cherry-pick 冲突的具体解决方式
- finish_flag 共享机制的具体实现（multiprocessing.Value vs 其他方案）
- favorite_db 初始化的 SQL 查询参数
- close() 中需要关闭的完整数据库列表
- 诊断信息的具体格式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 回退修复（最高优先级）
- `wxManager/decrypt/wx_info_v4.py` — Phase 1 commit `819903e` 添加了 regex_scan_keys、collect_db_salts、_verify_key_stdlib；当前被 Phase 2 commit `7ab0fec` 覆盖
- `wxManager/decrypt/wxinfo.py` — Phase 1 commit `fc9f38f` 添加了同样的 regex 函数；同样被覆盖
- `.planning/phases/01-regex-key-extraction/01-01-PLAN.md` — Phase 1 regex 实现的完整计划
- `.planning/phases/01-regex-key-extraction/01-01-SUMMARY.md` — Phase 1 实现总结

### 多进程 finish_flag bug
- `wxManager/decrypt/wx_info_v4.py` §47 — `finish_flag = False` 全局变量（不跨进程共享）
- `wxManager/decrypt/wx_info_v4.py` §222-258 — `is_ok()` 和 `check_chunk()` 使用 `global finish_flag`
- `wxManager/decrypt/wx_info_v4.py` §275-285 — `get_key_()` 使用 Pool.starmap + check_chunk
- `wxManager/decrypt/wx_info_v4.py` §261-272 — `verify_key()` 已正确使用 `multiprocessing.Value`
- `wxManager/decrypt/wxinfo.py` §49, §248-287 — 同样的 finish_flag 问题

### 句柄泄漏
- `wxManager/decrypt/wx_info_v4.py` §72-73 — `open_process()` 使用 `PROCESS_ALL_ACCESS`
- `wxManager/decrypt/wx_info_v4.py` §487 — `CloseHandle(process_handle)` 在主路径调用
- `wxManager/decrypt/wx_info_v4.py` §182-210 — `read_bytes_from_pid()` 内的 CloseHandle 路径
- `.planning/codebase/CONCERNS.md` §CRITICAL: Process Memory Reading — PROCESS_ALL_ACCESS 权限过大

### favorite_db 和 close() bug
- `wxManager/manager_v4.py` §107-111 — `close()` 是空操作，实际 close 调用被注释
- `wxManager/manager_v3.py` §665, `wxManager/manager_v4.py` §450 — `favorite_db` 未初始化但被调用
- `.planning/codebase/CONCERNS.md` §HIGH: V4 Manager close() is Empty
- `.planning/codebase/CONCERNS.md` §HIGH: favorite_db Attribute Used but Never Initialized

### 入口脚本（管道验证）
- `1-decrypt.py` §51-92 — `dump_v4()` 解密 + 昵称查询流程
- `2-contact.py` §16-40 — 联系人查询演示
- `3-exporter.py` §20-46 — 导出演示

### 管道连接点
- `wxManager/__init__.py` — `DatabaseConnection` 工厂，根据 db_version 创建 V3/V4 接口
- `wxManager/manager_v4.py` — `DataBaseV4`，v4 管道核心
- `wxManager/decrypt/decrypt_v4.py` — v4 数据库解密

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `verify_key()` 函数 (`wx_info_v4.py:261`) 已正确使用 `multiprocessing.Value('b', False)` 实现跨进程共享 flag — finish_flag 修复可复用此模式
- Phase 1 commit `819903e` 的 diff 是 regex 代码的权威来源 — cherry-pick 即可恢复，无需重写
- `DataBaseBase` 基类 (`wxManager/model/db_model.py`) 提供统一的 close() 模式，DataBaseV4.close() 应遵循

### Established Patterns
- 全局 `finish_flag` 模式在 `wx_info_v4.py` 和 `wxinfo.py` 中完全对称 — 修复需同时应用于两文件
- `is_ok()` 函数 (§221-249) 同时被 `check_chunk`（Pool 路径）和 `verify_key`（Value 路径）调用 — finish_flag 改为 Value 时需确保两路径兼容
- V4 manager 的数据库列表在构造函数中硬编码 (`manager_v4.py:79-87`) — close() 需遍历所有 self.XXX_db 属性

### Integration Points
- 管道入口：`1-decrypt.py` 调用 `dump_v4()` → `get_info_v4()` → `decrypt_v4.decrypt_db_files()` → 写 `info.json`
- 管道中间：`2-contact.py` 用 `DatabaseConnection(db_dir, 4)` → `get_interface()` → `get_contacts()`
- 管道出口：`3-exporter.py` 用 `DatabaseConnection` + `HtmlExporter.start()` 生成输出
- favorite_db 的调用路径：`get_favorite_items()` ← 仅在收藏功能相关流程中使用，但未初始化会导致 AttributeError

</code_context>

<specifics>
## Specific Ideas

- 用户明确表示"越简单越好，只想要能导出聊天记录"（Phase 2 上下文）
- CODE-03 要求以最小改动实现修复，不重构现有代码结构
- Cherry-pick 是恢复 Phase 1 代码的最干净方式，保留了原始实现细节和提交历史

</specifics>

<deferred>
## Deferred Ideas

- 115 处 bare `except:` 替换为 `except Exception:` — 代码质量改进，不影响流水线功能
- `ProcessPoolExecutor` 重复开 DB 连接 — 性能优化，不影响功能正确性
- `eval()` 替换为 `float()` — 安全改进，不影响流水线功能
- `PROCESS_ALL_ACCESS` 降级为最小权限 — 安全改进，不影响功能
- `DataBaseBase.cursor` 歧义（list vs single）— 架构问题，当前不影响 V4 路径
- v3 路径的同类 bug 修复 — 范围仅限 v4

</deferred>

---

*Phase: 03-pipeline-validation-and-code-health*
*Context gathered: 2026-04-24*
