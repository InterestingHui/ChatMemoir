# Phase 2: User Info from Decrypted DB - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 02-user-info-from-decrypted-db
**Areas discussed:** 兜底策略, info.json 格式, 字段范围, 读取时机

---

## 兜底策略

| Option | Description | Selected |
|--------|-------------|----------|
| DB 优先 + 内存兜底 | 先查 DB，查不到再跑内存扫描。两层保险，代码复杂度高。 | |
| 纯 DB，失败留空 | 只从 DB 读，失败留空并打印诊断信息。简单明了。 | ✓ |
| 内存优先 + DB 兜底 | 先试内存扫描，失败再查 DB。内存扫描本身就是问题根源。 | |

**User's choice:** 纯 DB，失败留空
**Notes:** 用户明确要求"越简单越好"

---

## info.json 格式

| Option | Description | Selected |
|--------|-------------|----------|
| 不改格式 | 当前 to_json() 不保存 mobile，导出流程也不需要 | ✓ |
| 添加 phone/alias | 扩展 info.json 和 load_from_json，增加复杂度 | |

**User's choice:** 不改格式
**Notes:** mobile 字段在整个导出流程中从未使用，加了没意义

---

## 字段范围

| Option | Description | Selected |
|--------|-------------|----------|
| 只填 nickname | Me().name 从 DB nick_name 列填充 | ✓ |
| nickname + phone | 同时提取手机号 | |
| nickname + phone + alias | 完整用户信息 | |

**User's choice:** 只填 nickname
**Notes:** 用户说"只想要能导出聊天记录"，导出只用 wxid 和 name

---

## 读取时机

| Option | Description | Selected |
|--------|-------------|----------|
| 解密后立即读 | 在 1-decrypt.py 中 decrypt_v4 之后、写 info.json 之前查 DB | ✓ |
| Manager 初始化时读 | 在 manager_v4.py init_database() 中读，更集中但改 manager 层 | |

**User's choice:** 解密后立即读
**Notes:** 数据刚解密完，最自然的时机，改动集中

---

## Claude's Discretion

- 辅助函数放哪里（内联 vs 新建工具函数）
- SQL 查询的具体写法
- 诊断信息的格式

## Deferred Ideas

- 手机号提取 — 不影响导出，留后续
- alias 提取 — 导出不需要
- Me.load_from_database() — 当前只需内联查询
- v3 路径改造 — v3 逻辑独立，不在范围
