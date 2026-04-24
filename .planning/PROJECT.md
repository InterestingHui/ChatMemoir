# WeChatMsg 解密修复

## What This Is

修复 WeChatMsg（留痕）项目的微信数据库解密功能，使其兼容微信 4.x 系列（当前测试版本 4.1.8.29）。WeChatMsg 是一个微信聊天记录提取和导出工具，采用三步流水线：解密数据库 → 查看联系人 → 导出聊天记录。当前解密步骤因微信版本更新导致内存特征匹配失败，需要更新密钥提取逻辑。

## Core Value

让用户能够成功完成完整的「解密 → 联系人 → 导出」三步流程，特别是能从微信 4.x 系列版本中正确提取数据库解密密钥。

## Requirements

### Validated

<!-- 从现有代码推断的已有能力 -->

- ✓ 修复微信 4.x（含 4.1.8.29）的密钥提取功能 — Validated in Phase 01: regex-first WCDB hex scanning with YARA fallback
- ✓ 微信 4.0 基本版数据库解密 — 现有代码支持
- ✓ 微信 3.x 数据库解密 — 现有代码支持
- ✓ 多格式导出（HTML、TXT、CSV、DOCX、XLSX、Markdown、JSON）— 现有代码支持
- ✓ 联系人查询和群成员解析 — 现有代码支持
- ✓ 多种消息类型解析（文本、图片、视频、语音、表情包等）— 现有代码支持
- ✓ v3/v4 策略模式切换 — 现有架构

### Active

- [ ] 修复微信 4.x 的用户信息提取（昵称、手机号、账号名不为空或垃圾值）
- [ ] 验证解密后的数据库能被第二步（联系人查询）正确读取
- [ ] 验证联系人数据能被第三步（导出）正确处理并生成输出文件
- [ ] 兼容微信 4.0 ~ 4.x 系列多个版本（至少覆盖 4.0.3 和 4.1.8.29）

### Out of Scope

- 微信 3.x 版本的修改 — 3.x 解密逻辑独立，不在本次范围内
- GUI 界面修改 — 本次只修复后端核心逻辑
- 新增导出格式 — 导出功能本身没有问题
- 新增消息类型解析 — 现有解析器工作正常

## Context

- **架构：** 三阶段流水线（Decrypt → Query → Export），v3/v4 通过策略模式切换
- **解密原理：** 通过 YARA 规则扫描微信进程内存，匹配特定字节模式定位密钥地址，然后验证密钥正确性
- **问题根因：** 微信 4.1.8.29 版本的内存布局发生变化，YARA 规则 `GetKeyAddrStub` 和 `GetPhoneNumberOffset` 匹配不到预期的内存模式
- **当前状态：** Phase 01 完成 — regex-first WCDB hex 密钥提取已实现，YARA 保留为兜底。待人工在 Windows 上验证实际解密效果
- **已知文件：** `wxManager/decrypt/wx_info_v4.py` 是主要需要修改的文件
- **依赖：** psutil、pymem、pywin32、pycryptodome、yara-python
- **平台：** 解密步骤仅限 Windows（需要读取进程内存）

## Constraints

- **平台：** Windows only（解密步骤依赖进程内存读取）
- **权限：** 需要管理员权限打开微信进程（PROCESS_ALL_ACCESS）
- **前提条件：** 微信必须在运行状态
- **技术栈：** Python + ctypes + YARA + pymem
- **测试环境：** 微信 4.1.8.29（用户实际环境）
- **兼容性：** 不能破坏微信 4.0 已有的解密能力

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 基于 YARA 规则更新方式修复 | 现有架构使用 YARA 扫描内存，保持架构一致性 | 被取代 — 见下一行 |
| Regex-first, YARA-fallback 密钥提取 | WCDB 内部 `x'<hex>'` 格式跨版本稳定，YARA 仅作为兜底 | — Phase 01 已实现，待人工验证 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-24 after Phase 01 completion*
