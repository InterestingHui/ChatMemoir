# ChatMemoir 全量迁移 — 开工指令（新电脑 WorkBuddy 必读）

> 你是新电脑上的 WorkBuddy。用户给你这份文件，要求把 ChatMemoir 项目在**本机**完整还原到可用状态。
> 本文件是完整作业手册。按顺序执行，每一步都有验证点。

---

## 0. 背景知识（先读懂再动手）

- **项目**：ChatMemoir —— 微信聊天记录解密 / 语音转录 / 导出的桌面工具（Python + tkinter GUI，PyInstaller/Nuitka 打包）。
- **GitHub**：https://github.com/InterestingHui/ChatMemoir.git
- **目标环境：Windows 原生（不要装 WSL！）。** 这个项目天生是 Windows 工具：
  - 实时内存密钥提取（`_auto_decrypt_live`，`winreg`/`pymem`/`pywin32`）**只在 win32 可用**——源机放 WSL 是被迫的降级运行，Windows 原生反而是最优路径；
  - 代码里所有 WSL 专属逻辑（`/mnt/c/...`、schtasks 触发、UNC 路径转换）都有平台守卫（`_sys.platform == 'win32'` 分支），在原生 Windows 上自动走原生分支，**代码无需任何修改**；
  - `req_fixed.txt` 里的 `pywin32`、`pymem` 本来就是 Windows 包，原生环境直接装。
- **仓库是"全量自包含"的**（2026-10-21 源机特意补齐后推送，master ≥ `622dbfe`）。**git clone 一次拿到所有代码资产**，包括：
  - 全部代码与历史；
  - **`.workbuddy/memory/`** —— WorkBuddy 项目记忆（工作日志），clone 后即生效，**不要当普通文档忽略**；
  - **`.planning/`** —— 项目规划全套（PROJECT/ROADMAP/STATE/架构分析）；
  - **`req_fixed.txt`** —— 锁定版本的依赖清单，**装依赖必须用它**，别用 `requirements.txt`（未锁版本）；
  - `build.bat`（Nuitka 构建）、`setup-admin-task.bat`（免 UAC 管理员计划任务，可选）。

## 1. 环境准备（Windows 原生）

1. 确认有 **64 位 Python 3.10–3.12**：`py -0` 查看。没有就去 python.org 装（勾选 Add to PATH）。必须 64 位——`pymem` 要求与微信同为 64 位进程。
2. 确认有 git。
3. 确认目标机已安装**微信 PC 版并登录过**（解密数据源）。工具支持微信 4.x（`xwechat_files`）与 3.x。

## 2. 克隆代码（一步到位）

```bat
git clone https://github.com/InterestingHui/ChatMemoir.git %USERPROFILE%\ChatMemoir
cd %USERPROFILE%\ChatMemoir
git log --oneline -3
```

**验证点 A**：顶端提交应为 `622dbfe docs: add migration README...`（或更新），且以下文件全部存在：
```bat
dir .workbuddy\MIGRATION-README.md .workbuddy\memory .planning\PROJECT.md req_fixed.txt build.bat
```

## 3. Python 依赖

```bat
py -m venv venv
venv\Scripts\pip install -r req_fixed.txt
```
- 全部依赖都有 Windows 轮子，原生安装比源机（WSL）更顺。
- **验证点 B**：`venv\Scripts\python -c "import pymem, win32com.client, yara, Crypto; print('deps-ok')"` 输出 `deps-ok`。
- GUI 框架是 **tkinter**（Python 标准库自带），无需额外安装；此前流传的 "import PySide6" 验证是错的，忽略。

## 4. 启动与数据生成

```bat
venv\Scripts\python gui.py
```
- 首次运行：GUI 内一键"自动解密"→ 走 win32 原生内存提取路径（读取微信进程密钥 → 解密数据库 → 加载联系人）。前提：**微信正在运行且已登录**。
- 历史聊天数据不需要从源机搬运——用户已确认在新机重新解密生成。
- 可选：`setup-admin-task.bat` 注册管理员计划任务（免 UAC 的自动解密），需要时再提。

## 5. 会话与记忆对齐

1. 任务/会话历史随用户**同账号登录自动云端同步**，无需处理。
2. `.workbuddy/memory/` 已随 clone 就位——这是项目长期记忆，直接读取沿用。（注意：日志里 "代理 127.0.0.1:7890 + git 直连推送" 等是源机 WSL 环境的上下文，本机不适用就忽略。）
3. 用户跨项目偏好由账号云端配置携带，无需处理。

## 6. 最终验收清单

- [ ] `git log --oneline -1` ≥ `622dbfe`
- [ ] `.workbuddy/memory/`、`.planning/`、`req_fixed.txt`、`build.bat` 齐全
- [ ] 验证点 B 输出 `deps-ok`
- [ ] `gui.py` 能启动出主窗口（微信未登录时允许解密步骤失败，GUI 能开即算过）
- [ ] 向用户报告：clone 了什么、验证结果、首次解密的操作路径

## 7. 红线

- 不要主动 push（除非用户说推）。
- 不要删除源机任何东西——这是复制，不是搬运。
- 不要给项目装 WSL、不要建议打大数据包（历史数据由新机重新解密生成）。
- 落盘路径变更先问用户。
