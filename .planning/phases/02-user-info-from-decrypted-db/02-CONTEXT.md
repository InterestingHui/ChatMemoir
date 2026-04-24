# Phase 2: User Info from Decrypted DB - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

从解密后的 `contact/contact.db` 读取用户昵称，替代当前脆弱的内存偏移扫描（YARA `GetPhoneNumberOffset` 规则在微信 4.1.8.29 上匹配失败）。只改 `nickname` 填充逻辑，确保导出流程中 `Me().name` 有值。wxid 已可靠提取，手机号和 alias 不在本次范围。

</domain>

<decisions>
## Implementation Decisions

### 兜底策略
- **D-01:** 纯 DB 查询。解密完成后查 `contact/contact.db` 的 `contact` 表 `WHERE username = '{wxid}'`，失败则留空并打印诊断信息。不再依赖内存偏移扫描。
- **Why:** 内存偏移扫描是问题根源，保留它增加复杂度但价值不大。用户明确表示要最简方案。
- **How to apply:** 研究者和计划者不需要考虑内存扫描兜底逻辑，只关注 SQLite 查询。

### info.json 格式
- **D-02:** 不改 info.json 格式。当前 `Me.to_json()` 保存 `username`、`nickname`、`wx_dir`、`xor_key`，足够满足导出需求。
- **Why:** `mobile` 字段在整个导出流程中从未被使用，加它只是增加复杂度。
- **How to apply:** 不需要修改 `Me.to_json()` 或 `Me.load_from_json()` 的字段结构。

### 字段范围
- **D-03:** 只填充 `Me().name`（昵称）。`wxid` 已通过目录路径可靠提取（`wx_info_v4.py:626`），不需要改。不新增 alias 或 phone 字段。
- **Why:** 用户明确说"只想要能导出聊天记录"。导出只用 `Me().wxid` 和 `Me().name`。
- **How to apply:** 计划者的任务只涉及 nickname 填充，不涉及手机号或微信号（alias）。

### 读取时机
- **D-04:** 在 `1-decrypt.py` 的 `dump_v4()` 中，`decrypt_v4.decrypt_db_files()` 完成后、写入 `info.json` 之前，直接打开 `contact/contact.db` 查询。
- **Why:** 数据刚解密完，最自然的读取时机。改动集中在入口脚本，不动 manager 层。
- **How to apply:** 改动文件主要是 `1-decrypt.py`，可能需要一个简单的辅助函数来查 DB。

### Claude's Discretion
- 辅助函数放在哪里（`1-decrypt.py` 内联 vs 新建工具函数）
- SQL 查询的具体写法（是否需要处理多行匹配）
- 诊断信息的具体格式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 用户信息提取
- `wxManager/decrypt/wx_info_v4.py` §567-634 — `dump_wechat_info_v4()` 当前流程：wxid 从目录提取，nickname/phone 从内存扫描
- `wxManager/decrypt/wx_info_v4.py` §497-559 — `get_nickname(pid)` 当前内存偏移扫描实现（Phase 2 要替代的部分）
- `wxManager/decrypt/common.py` — `WeChatInfo` 类定义，包含 `nick_name`、`phone`、`wxid` 等字段

### 数据库表结构
- `wxManager/db_v4/contact.py` — `ContactDB` 类，查询 `contact` 表，有 `username`、`nick_name`、`extra_buffer` 列
- `wxManager/model/contact.py` §149-181 — `Me` 单例 dataclass，`to_json()` 和 `load_from_json()` 方法

### 入口脚本
- `1-decrypt.py` §50-73 — `dump_v4()` 函数：解密流程，创建 `Me()` 实例，写入 `info.json`

### Protobuf 定义（如需从 extra_buffer 提取更多信息）
- `wxManager/parser/util/protocbuf/contact.proto` — `ContactInfo` protobuf 定义

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ContactDB` 类（`wxManager/db_v4/contact.py`）：已有完整的 contact 表查询逻辑，但当前没有"查自己的信息"方法
- `contact_pb2`（`wxManager/parser/util/protocbuf/contact_pb2.py`）：protobuf 解析工具，可用于 extra_buffer（本次不需要）

### Established Patterns
- 所有 DB 类继承 `DataBaseBase`（`wxManager/model/db_model.py`），统一 SQLite 连接管理
- `Me` 单例通过 `info.json` 在 `manager_v4.py:90` 的 `init_database()` 中加载
- wxid 在 `wx_info_v4.py:626` 通过目录路径提取：`'_'.join(wechat_info.wx_dir.split('\\')[-3].split('_')[0:-1])`

### Integration Points
- `1-decrypt.py` 的 `dump_v4()` 中，`decrypt_v4.decrypt_db_files(key, src_dir=wx_dir, dest_dir=output_dir)` 之后，解密的 DB 文件在 `output_dir/db_storage/` 下
- 需要打开 `output_dir/db_storage/contact/contact.db` 查询 nick_name
- 查询结果写入 `Me().name`，然后通过 `Me().to_json()` 保存到 `info.json`

</code_context>

<specifics>
## Specific Ideas

- 用户明确表示"越简单越好，只想要能导出聊天记录"
- 改动范围应尽可能小，能用 SQLite 直接查就不要引入新的依赖或抽象

</specifics>

<deferred>
## Deferred Ideas

- 手机号提取（`extra_buffer` protobuf 中有 `phone_info`）— 不影响导出，留待后续
- alias（微信号）提取 — 导出不需要，留待后续
- 修改 `Me` 类添加 `load_from_database()` 方法 — 当前只需在 `1-decrypt.py` 内联查询
- v3 路径的用户信息改造 — v3 解密逻辑独立，不在本次范围

</deferred>

---

*Phase: 02-user-info-from-decrypted-db*
*Context gathered: 2026-04-24*
