---
phase: quick
plan: 260629-klj
type: tdd
wave: 1
depends_on: []
files_modified:
  - tests/test_decrypt_v4.py
autonomous: true
requirements:
  - "为 dump_session_info_v4 添加 7 个分支的集成测试覆盖"
must_haves:
  truths:
    - "open_process 返回 None 时，dump_session_info_v4 立即返回 errcode=404（默认）的 SessionInfo"
    - "get_wx_dir 返回空字符串时，函数提前返回 errcode=404 的 SessionInfo"
    - "regex_scan_keys 成功返回 key_map 时，session_info.key 被填充，key_map 按 relative_path 映射，errcode=200"
    - "YARA fallback 返回 raw key（is_passphrase=False）时，session_info.key 被设置，errcode=200"
    - "YARA fallback 返回 passphrase（is_passphrase=True）时，每个 DB 的派生 key 填充 key_map，errcode=200"
    - "所有路径都失败（get_key 返回 None）时，session_info.errcode=404"
    - "成功路径下，从 queue 读取的 nickname/phone/account_name 被写入 SessionInfo"
  artifacts:
    - path: "tests/test_decrypt_v4.py"
      provides: "TestDumpSessionInfoV4 类，7 个测试方法覆盖 dump_session_info_v4 全部分支"
      contains: "class TestDumpSessionInfoV4"
  key_links:
    - from: "tests/test_decrypt_v4.py::TestDumpSessionInfoV4"
      to: "memoir.decrypt.session_v4.dump_session_info_v4"
      via: "unittest.mock.patch 多个模块级符号"
      pattern: "dump_session_info_v4"
---

<objective>
为 `memoir/decrypt/session_v4.py::dump_session_info_v4`（line 632）添加集成测试，覆盖全部 7 个执行分支。

Purpose: dump_session_info_v4 是 v4 解密流水线的关键入口，目前测试套件对其零覆盖。7 个分支涉及 5+ 个外部依赖（进程句柄、YARA、multiprocessing、文件系统、PBKDF2），需要用 mock 隔离每个分支单独验证。这是纯测试增量任务，不修改产品代码。

Output: `tests/test_decrypt_v4.py` 中新增 `TestDumpSessionInfoV4` 类，含 7 个测试方法，所有测试在 WSL/Linux headless 环境下通过 `python -m pytest tests/test_decrypt_v4.py -v` 运行。
</objective>

<execution_context>
@/home/lianghui/.claude/get-shit-done/workflows/execute-plan.md
@/home/lianghui/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@/home/ChatMemoir/CLAUDE.md
@/home/ChatMemoir/.planning/STATE.md

# 目标源码（只读参考，不要修改）
@/home/ChatMemoir/memoir/decrypt/session_v4.py
@/home/ChatMemoir/memoir/decrypt/common.py

# 已有测试基础设施（mock 模式定义在文件顶部 line 1-83，复用相同模式）
@/home/ChatMemoir/tests/test_decrypt_v4.py

<interfaces>
<!-- dump_session_info_v4 依赖的模块级符号（全部在 memoir/decrypt/session_v4.py 顶层定义，可用 unittest.mock.patch 直接替换） -->

模块路径: `memoir.decrypt.session_v4`

需要 patch 的符号（按分支场景选择子集）:

```python
# 进程句柄相关（所有分支都需要）
open_process          # (pid) -> handle | None；分支 1 返回 None
get_version           # (pid) -> str；返回 "4.1.8.29" 固定字符串
CloseHandle           # (handle) -> None；MagicMock 即可

# 数据目录发现
get_wx_dir            # (handle) -> str；分支 2 返回 ""，其他分支返回 fake path

# 正则扫描路径
regex_scan_keys       # (pid, handle, data_dir) -> dict[salt_hex, enc_key_hex]
                      # 分支 3 返回 {"aabb...": "ccdd..."}；分支 4-7 返回 {}

# YARA fallback 路径
get_key               # (pid, handle, buf) -> (key_hex|None, is_passphrase: bool)
                      # 分支 4: ("rawhex", False)
                      # 分支 5: ("passphrase_hex", True)
                      # 分支 6: (None, False)

# 文件系统辅助
collect_db_salts      # (data_dir) -> dict[salt_hex, db_path]；分支 3、5 需要

# multiprocessing（worker 子进程读取 nickname）
multiprocessing.Process  # 用 MagicMock 替换，避免真正 fork
multiprocessing.Queue    # 用 fake queue，hold 一个 nickname dict
```

SessionInfo 关键字段（来自 memoir/decrypt/common.py:25-36）:

```python
class SessionInfo:
    def __init__(self):
        self.pid = 0
        self.version = '0.0.0.0'
        self.account_name = ''
        self.nick_name = ''
        self.phone = ''
        self.data_dir = ''
        self.key = ''
        self.key_map = {}        # db_relative_path -> enc_key_hex
        self.uid = ''
        self.errcode: int = 404  # 默认；成功时改为 200
        self.errmsg: str = '错误！请登录微信。'
```

dump_session_info_v4 关键执行路径（line 632-735）:

| Line | 动作 | 失败时 |
|------|------|--------|
| 633-636 | 初始化 SessionInfo，set pid + version | - |
| 638-642 | `open_process(pid)` → 若 falsy 直接 return（errcode 保持 404） | 分支 1 |
| 644-646 | 启动 multiprocessing.Process 调 worker | - |
| 648-653 | `get_wx_dir(handle)` → 若空字符串 CloseHandle + join + return | 分支 2 |
| 657-672 | `regex_scan_keys` → 若返回非空 map，构建 key_map + set key | 分支 3 |
| 673-715 | fallback：找 db 文件 → `get_key(pid, handle, buf)` | 分支 4/5/6 |
| 717-719 | CloseHandle；提取 uid；trim data_dir（移除末尾两段） | - |
| 720-725 | process.join；queue 非空则读 nickname/phone/account_name | - |
| 726-734 | 若 `session_info.key` 为空 → errcode=404；否则 errcode=200 | 分支 6/7 |

uid 提取逻辑（line 718，对测试断言重要）:

```python
session_info.uid = '_'.join(session_info.data_dir.split('\\')[-3].split('_')[0:-1])
```

data_dir trim 逻辑（line 719）:

```python
session_info.data_dir = '\\'.join(session_info.data_dir.split('\\')[:-2])
```

注意：uid/trim 在 line 718-719 执行，**只有走到 CloseHandle 之后**（即分支 3-7）才会运行。分支 1、2 在 trim 之前 return，所以 data_dir 保持原值。
</interfaces>

<mock_strategy>
所有 patch 通过 `unittest.mock.patch` 装饰器或 context manager 应用到 `memoir.decrypt.session_v4` 模块上。注意以下要点：

1. **patch 目标路径**：必须 patch 模块自身引用的符号，而不是源模块。例如 `open_process` 在 `session_v4.py` 顶层 `from memoir.decrypt.common import get_version`，但 `open_process` 是同模块定义的函数，所以 patch `memoir.decrypt.session_v4.open_process`。

2. **multiprocessing.Process + Queue 的处理**：
   - `dump_session_info_v4` 在 line 644-646 创建 `multiprocessing.Queue()` 和 `multiprocessing.Process(target=worker, args=(pid, queue))` 并调用 `process.start()`。
   - 在 WSL 测试中真正 fork 子进程会失败（worker 内部调用 `get_nickname` 又会调 `open_process`）。
   - **方案**：patch `memoir.decrypt.session_v4.multiprocessing` 整个模块为 MagicMock。让 `multiprocessing.Process(...)` 返回一个 mock，其 `.start()`、`.join()` 为 no-op。让 `multiprocessing.Queue()` 返回一个 fake queue 对象，该对象实现 `.empty()` 返回 False 和 `.get()` 返回预设的 nickname dict。

3. **get_key 内部调用 multiprocessing.Pool**（line 516-520）：被 patch 整个 `get_key` 函数后不会触发，无需额外处理。

4. **collect_db_salts 在分支 3 被调用两次**（line 658 和 line 664）：patch 一次即可覆盖两次调用，第二次调用仍返回相同 dict。

5. **get_key 在分支 4-5 中需要 buf**：dump_session_info_v4 在 line 695-696 从磁盘读 db 文件。分支 4-5 的测试需要在 tmp 目录下创建一个至少 PAGE_SIZE（4096）字节的 .db 文件，路径要匹配 line 678 的候选列表（如 `session/session.db`），并让 get_wx_dir 返回该 tmp 目录路径。这样函数会找到该文件并调用 get_key。

6. **分支 6（get_key 返回 None）**：仍需 .db 文件存在，否则 line 714-715 走 "No .db file found" 分支，session_info.key 保持空，结果相同（errcode=404），但路径不同。为了精确覆盖 line 693-697 的 db_file_path 非空分支，需要创建 .db 文件。

7. **data_dir 路径格式**：get_wx_dir 的真实返回形如 `C:\Users\x\xwechat_files\wxid_y\db_storage\`（末尾带反斜杠）。测试中使用类似格式：`r"C:\Users\test\xwechat_files\wxid_abc123\db_storage\\"`，这样 line 718 的 uid 提取（`split('\\')[-3]` 取倒数第三段 `wxid_abc123`，再 `split('_')[0:-1]` 取 `['wxid', 'abc']`，join 得 `wxid_abc`）可被精确断言。简化起见，断言 uid 非空字符串即可。
</mock_strategy>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: 为 dump_session_info_v4 添加 7 个分支的集成测试</name>
  <files>tests/test_decrypt_v4.py</files>
  <behavior>
    测试在 `class TestDumpSessionInfoV4` 下编写，复用文件顶部已有的 Windows mock 基础设施（line 1-83 的 sys.modules patch）。

    每个 test 方法用 `@mock.patch.multiple` 或多个 `@mock.patch` 装饰器叠加，按分支场景配置 mock 返回值，然后调用 `dump_session_info_v4(pid=1234)` 并断言返回的 `SessionInfo` 字段。

    - Test 1 (open_process 返回 None)：patch `open_process` 返回 None。断言：返回的 SessionInfo.errcode == 404，pid == 1234，version == "4.1.8.29"（来自 get_version mock），key 为空字符串，data_dir 为空。
    - Test 2 (get_wx_dir 返回空)：patch `open_process` 返回 fake handle（truthy），`get_wx_dir` 返回 ""。断言：errcode == 404，key 为空，data_dir 为空（因为 line 653 在 trim 之前 return）。
    - Test 3 (regex_scan_keys 成功)：patch `open_process` truthy，`get_wx_dir` 返回 `r"C:\Users\test\xwechat_files\wxid_abc\db_storage\\"`，`regex_scan_keys` 返回 `{"aabbccdd...": "eeff0011..."}`（任意 salt_hex→key_hex），`collect_db_salts` 返回 `{"aabbccdd...": r"C:\Users\test\xwechat_files\wxid_abc\db_storage\contact\contact.db"}`。mock multiprocessing 为 MagicMock，Queue 返回 fake 对象（empty 返回 True）。断言：errcode == 200，key == "eeff0011..."（map 的 first value），key_map 非空且包含 contact.db 相关 relative_path。
    - Test 4 (YARA fallback raw key)：patch `regex_scan_keys` 返回 {}，在 tmp 目录创建 `session/session.db`（4096 字节随机内容），`get_wx_dir` 返回该 tmp 路径（带 db_storage\\ 后缀），`get_key` 返回 `("rawkeyhex", False)`。断言：errcode == 200，key == "rawkeyhex"，key_map 为空（raw key 模式不构建 key_map）。
    - Test 5 (YARA fallback passphrase + PBKDF2 派生)：patch `regex_scan_keys` 返回 {}，tmp 目录创建 db 文件，`get_key` 返回 `("passphrasehex", True)`，`collect_db_salts` 返回 `{"salt_hex": "<tmp_db_path>"}`。断言：errcode == 200，key == "passphrasehex"，key_map 非空且每个 relative_path 对应一个 PBKDF2 派生 key（断言 key_map 长度 == salt map 长度即可，无需精确计算派生 key）。
    - Test 6 (全失败 errcode=404)：patch `regex_scan_keys` 返回 {}，tmp 目录创建 db 文件，`get_key` 返回 `(None, False)`。断言：errcode == 404，key 为空字符串。
    - Test 7 (成功 + nickname)：在 Test 3 或 Test 4 基础上，让 fake queue 的 `.empty()` 返回 False、`.get()` 返回 `{"nick_name": "TestUser", "phone": "13800000000", "account_name": "test_user"}`。断言：session_info.nick_name == "TestUser"，phone == "13800000000"，account_name == "test_user"，errcode == 200。

    所有测试只读 SessionInfo 字段，不直接断言 mock 调用次数（脆弱）。
  </behavior>
  <action>
    实现 `TestDumpSessionInfoV4` 类。具体步骤：

    1. 在 `tests/test_decrypt_v4.py` 顶部 import 块（line 57-68 的 session_v4 import）追加导入：
       `from memoir.decrypt.session_v4 import dump_session_info_v4` 以及 `from memoir.decrypt.common import SessionInfo`。

    2. 在文件末尾（line 581 之后）追加新类 `class TestDumpSessionInfoV4:`。

    3. 定义类级 helper：`_fake_nickname_queue(nickname_dict=None)`，返回一个 MagicMock，其 `.empty()` 返回 `nickname_dict is None`，`.get()` 返回 nickname_dict 或 {}。再定义 `_build_fake_multiprocessing(nickname_dict=None)`，返回一个 MagicMock 模拟 `multiprocessing` 模块：`multiprocessing.Queue()` 调用时返回 fake queue，`multiprocessing.Process(...)` 返回一个 MagicMock（start/join 为 no-op）。

    4. 为每个 test 方法使用 `@mock.patch(...)` 装饰器叠加配置：
       - 通用 patch（所有 test）：`memoir.decrypt.session_v4.get_version` 返回 "4.1.8.29"；`memoir.decrypt.session_v4.CloseHandle` 为 MagicMock；`memoir.decrypt.session_v4.multiprocessing` 为 fake。
       - Test 1：额外 patch `open_process` 返回 None。
       - Test 2-7：额外 patch `open_process` 返回 `mock.MagicMock()`（truthy）。
       - Test 2：额外 patch `get_wx_dir` 返回 ""。
       - Test 3、7：patch `get_wx_dir` 返回 `r"C:\Users\test\xwechat_files\wxid_abc\db_storage\\"`，`regex_scan_keys` 返回 `{"salt1hex": "key1hex"}`，`collect_db_salts` 返回 `{"salt1hex": r"C:\Users\test\xwechat_files\wxid_abc\db_storage\contact\contact.db"}`。
       - Test 4-6：使用 `tempfile.TemporaryDirectory()` 创建 tmp，在 `tmp/session/` 下创建 `session.db`（用 `os.urandom(PAGE_SIZE)` 写 4096 字节），`get_wx_dir` 返回 `tmp + r"\db_storage\\"`（注意：因为 get_wx_dir 返回的路径会被 line 719 的 `split('\\')[:-2]` trim 两段，所以为了让 line 679 `os.path.join(data_dir, candidate)` 找到 db 文件，db 文件需要位于 `tmp/db_storage/session/session.db` —— 即在 tmp 下创建 `db_storage/session/session.db`）。具体构造：`os.makedirs(os.path.join(tmp, "db_storage", "session"))`，写 `session.db`。get_wx_dir mock 返回 `os.path.join(tmp, "db_storage") + "\\"`（Windows 风格反斜杠；在 Linux 上 os.path.join 会用 `/`，所以用 `f"{tmp}\\db_storage\\"` 或字符串拼接模拟 Windows 路径）。**注意**：因为代码用 `os.path.join` 和 `os.path.exists`，在 Linux 上 os.path.join 用 `/`，所以测试构造路径时也应该用 `os.path.join`，让 os 自己选分隔符。**但** line 718-719 硬编码 `split('\\')`，在 Linux 上这不会 split 出多段，data_dir 不会被 trim。这是已知的 Linux 测试局限。**解决**：测试中 mock `get_wx_dir` 返回 Windows 风格字符串（如 `r"C:\Users\test\xwechat_files\wxid_abc\db_storage\\"`），但为了 line 680 的 `os.path.exists(candidate_path)` 在 Linux 上能找到文件，需要单独 patch `os.path.exists` 或 `os.path.getsize` 返回 True。**简化方案**：直接 patch `os.path.exists` 在 session_v4 模块中返回 True（用 side_effect 或固定 True），以及 `builtins.open` mock 返回一个 fake file（其 `.read()` 返回 `os.urandom(PAGE_SIZE)`），这样完全绕开真实文件系统。

    5. 推荐的最简实现（避免真实文件 IO 复杂性）：用 `@mock.patch("memoir.decrypt.session_v4.os.path.exists", return_value=True)` 和 `@mock.patch("builtins.open", new_callable=mock.mock_open, read_data=b"\x00" * PAGE_SIZE)`。注意 read_data 必须是 PAGE_SIZE 字节，否则 line 696 `f.read()` 返回的 buf 长度不够。但 mock_open 的 read_data 是文件级共享的，line 695-696 `with open(db_file_path, 'rb') as f: buf = f.read()` 会读到 PAGE_SIZE 字节的 b"\x00"。Test 4-6 都可以走这个路径。

    6. Test 5 中 `collect_db_salts` 返回 `{"salt_hex": "<any_path>"}`。PBKDF2 派生需要真实的 salt 字节，所以 salt_hex 必须是 32 字符（16 字节）合法 hex。用 `"00" * 16` 即可。line 707 `salt = bytes.fromhex(salt_hex)` 会得到 16 字节零。

    7. 所有 test 用 `pid=1234` 调用 `dump_session_info_v4(1234)`。

    8. 注意 `multiprocessing` patch：因为 `multiprocessing` 已在 session_v4.py line 13 `import multiprocessing`，patch 目标是 `memoir.decrypt.session_v4.multiprocessing`。

    9. 不要修改 `memoir/decrypt/session_v4.py`。如果某个 test 在当前实现下意外失败，调整 mock 配置使其通过（产品代码已经工作，这是纯覆盖增量）。
  </action>
  <verify>
    <automated>cd /home/ChatMemoir && python -m pytest tests/test_decrypt_v4.py::TestDumpSessionInfoV4 -v</automated>
  </verify>
  <done>
    7 个 test 方法全部 PASS；不修改任何产品代码；现有 TestReadHelpers / TestCollectDbSalts / 等类测试仍然全部通过（运行 `python -m pytest tests/test_decrypt_v4.py -v` 整体绿）。
  </done>
</task>

</tasks>

<verification>
- `python -m pytest tests/test_decrypt_v4.py -v` 全部通过（原有 ~50 个 test + 新增 7 个 test）。
- `python -m pytest tests/test_decrypt_v4.py::TestDumpSessionInfoV4 -v` 单独运行 7 个 test 全部 PASS。
- 产品代码 `memoir/decrypt/session_v4.py` 未被修改（`git diff memoir/decrypt/session_v4.py` 输出为空）。
- 新增测试覆盖 errcode=200 与 errcode=404 两条主路径，以及 regex_scan / YARA fallback / passphrase 三种 key 提取模式。
</verification>

<success_criteria>
- TestDumpSessionInfoV4 类包含至少 7 个 test 方法，分别对应 7 个分支。
- 每个方法明确断言 SessionInfo.errcode（200 或 404）以及关键字段（key、key_map、data_dir、nickname 字段）。
- 所有测试在 WSL Linux headless 环境下运行通过，无真实进程/文件系统/YARA 依赖。
- 提交粒度：单个 commit，message 形如 `test: add 7 integration tests for dump_session_info_v4 branches`。
</success_criteria>

<output>
完成后创建 `.planning/quick/260629-klj-dump-session-info-v4-7-open-process-none/260629-klj-SUMMARY.md`，记录：
- 新增的 test 方法清单
- 7 个分支的覆盖证据（每个 test 对应哪个分支）
- 运行结果（pytest 输出 summary）
- 任何意外发现或注意点（如 Linux 上 split('\\') 局限）
</output>
