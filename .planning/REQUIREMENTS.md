# Requirements: WeChatMsg 解密修复

**Defined:** 2026-04-23
**Core Value:** 让用户能成功完成「解密 → 联系人 → 导出」完整流程，兼容微信 4.x 系列

## v1 Requirements

### Key Extraction

- [ ] **KEY-01**: 用 Python 正则扫描 WCDB hex 密钥缓存格式 `x'<64hex><32hex>'`，替代 YARA 作为主提取方式
- [ ] **KEY-02**: 保留 YARA 作为备用方案，正则优先、YARA 兜底，确保向后兼容
- [ ] **KEY-03**: 保持 HMAC-SHA512 密钥验证机制不变，确保提取的密钥正确性
- [ ] **KEY-04**: 兼容微信 4.0 ~ 4.x 系列（至少覆盖 4.0.3 和 4.1.8.29）
- [ ] **KEY-05**: 密钥提取失败时输出诊断信息，而非静默返回 None

### User Info

- [ ] **INFO-01**: 从解密后的数据库读取用户昵称，替代内存偏移扫描
- [ ] **INFO-02**: 从解密后的数据库读取手机号，替代内存偏移扫描
- [ ] **INFO-03**: 从解密后的数据库读取账号名，替代内存偏移扫描

### Pipeline

- [ ] **PIPE-01**: 解密后的数据库能被联系人查询（步骤2）正确打开和读取
- [ ] **PIPE-02**: 联系人数据能被导出器（步骤3）正确处理并生成输出文件
- [ ] **PIPE-03**: 完整三步流水线在微信 4.1.8.29 上端到端运行无报错

### Code Health

- [ ] **CODE-01**: 修复多进程 `finish_flag` 在子进程中失效的问题
- [ ] **CODE-02**: 修复进程句柄泄漏问题
- [ ] **CODE-03**: 以最小改动实现修复，不重构现有代码结构

## v2 Requirements

Deferred to future work.

### Code Health

- **CODE-04**: 合并 `wxinfo.py` 和 `wx_info_v4.py` 重复代码
- **CODE-05**: 将 yara-python 和 pymem 改为可选依赖
- **CODE-06**: 替换 `decrypt_dat.py` 中的 6 处 `eval()` 调用

## Out of Scope

| Feature | Reason |
|---------|--------|
| 微信 3.x 解密修改 | 3.x 解密逻辑独立，不在本次范围 |
| GUI 界面修改 | 本次只修后端核心逻辑 |
| 新增导出格式 | 导出功能本身没有问题 |
| 新增消息类型解析 | 现有解析器工作正常 |
| 解密架构重写 | 最小改动原则，保持现有结构 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| KEY-01 | — | Pending |
| KEY-02 | — | Pending |
| KEY-03 | — | Pending |
| KEY-04 | — | Pending |
| KEY-05 | — | Pending |
| INFO-01 | — | Pending |
| INFO-02 | — | Pending |
| INFO-03 | — | Pending |
| PIPE-01 | — | Pending |
| PIPE-02 | — | Pending |
| PIPE-03 | — | Pending |
| CODE-01 | — | Pending |
| CODE-02 | — | Pending |
| CODE-03 | — | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14 ⚠️

---
*Requirements defined: 2026-04-23*
*Last updated: 2026-04-23 after initial definition*
