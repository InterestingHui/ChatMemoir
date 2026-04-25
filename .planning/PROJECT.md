# WeChatMsg 解密修复

## What This Is

修复 WeChatMsg（留痕）项目的微信数据库解密功能，使其兼容微信 4.x 系列（测试版本 4.1.8.29）。WeChatMsg 是一个微信聊天记录提取和导出工具，采用三步流水线：解密数据库 → 查看联系人 → 导出聊天记录。本次修复通过 regex-first 密钥提取替代纯 YARA 方案，解决了微信 4.1.8.29 内存布局变化导致密钥提取失败的问题。

## Core Value

让用户能够成功完成完整的「解密 → 联系人 → 导出」三步流程，特别是能从微信 4.x 系列版本中正确提取数据库解密密钥。

## Requirements

### Validated

- ✓ 修复微信 4.x（含 4.1.8.29）的密钥提取功能 — v1.0: regex-first WCDB hex scanning with YARA fallback
- ✓ 微信 4.0 基本版数据库解密 — 现有代码支持
- ✓ 微信 3.x 数据库解密 — 现有代码支持
- ✓ 多格式导出（HTML、TXT、CSV、DOCX、XLSX、Markdown、JSON）— 现有代码支持
- ✓ 联系人查询和群成员解析 — 现有代码支持
- ✓ 多种消息类型解析（文本、图片、视频、语音、表情包等）— 现有代码支持
- ✓ v3/v4 策略模式切换 — 现有架构
- ✓ 修复微信 4.x 的用户昵称提取 — v1.0: nickname from decrypted contact.db
- ✓ 验证解密后的数据库能被联系人查询正确读取 — v1.0: code verified, human UAT pending
- ✓ 验证联系人数据能被导出器正确处理并生成输出文件 — v1.0: code verified, human UAT pending
- ✓ 兼容微信 4.0 ~ 4.x 系列多个版本 — v1.0: regex-first approach covers 4.0.3 and 4.1.8.29
- ✓ 修复多进程 finish_flag 在子进程中失效的问题 — v1.0: multiprocessing.Value
- ✓ 修复进程句柄泄漏问题 — v1.0: try/finally CloseHandle
- ✓ 最小改动实现修复，不重构现有代码结构 — v1.0

### Active

(Next milestone requirements will be defined via /gsd-new-milestone)

### Out of Scope

- 微信 3.x 版本的修改 — 3.x 解密逻辑独立，不在本次范围内
- GUI 界面修改 — 本次只修后端核心逻辑
- 新增导出格式 — 导出功能本身没有问题
- 新增消息类型解析 — 现有解析器工作正常

## Context

- **架构：** 三阶段流水线（Decrypt → Query → Export），v3/v4 通过策略模式切换
- **解密原理：** Regex-first 扫描 WCDB hex 缓存格式 `x'<64hex><32hex>'`，YARA 作为兜底
- **当前状态：** v1.0 里程碑完成 — 3 phases, 5 plans, 12/12 requirements satisfied。代码级验证通过，Windows 人工 UAT 待完成。
- **技术栈：** Python 3.10+ / psutil / pymem / pywin32 / pycryptodome / yara-python
- **平台：** 解密步骤仅限 Windows（需要读取进程内存）
- **已知技术债：** wxinfo.py 与 wx_info_v4.py 重复代码、read_bytes_from_pid 死代码、get_wx_dir 空 dict 崩溃（见 v1.0 audit）

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 基于 YARA 规则更新方式修复 | 现有架构使用 YARA 扫描内存，保持架构一致性 | ⚠️ Revisit — 被取代 |
| Regex-first, YARA-fallback 密钥提取 | WCDB 内部 `x'<hex>'` 格式跨版本稳定，YARA 仅作为兜底 | ✓ Good — Phase 01 实现，跨版本兼容 |
| 用户信息从解密后数据库读取 | 内存偏移扫描不可靠，解密后直接查 contact.db | ✓ Good — Phase 02 实现 |
| INFO-02/03 延迟处理 | 导出管线只使用 wxid 和 name，手机号和账号名不必要 | ✓ Good — 合理的范围控制 |
| 最小改动原则 | 保持现有代码结构，避免引入新的回归风险 | ✓ Good — 所有修复为针对性修改 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

---
*Last updated: 2026-04-25 after v1.0 milestone completion*
