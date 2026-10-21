# ChatMemoir 全量迁移 — 开工指令（新电脑 WorkBuddy 必读）

> 你是新电脑上的 WorkBuddy。用户给你这份文件，要求把 ChatMemoir 项目在**本机**完整还原到可用开发状态。
> 本文件是完整作业手册。按顺序执行，每一步都有验证点。

---

## 0. 背景知识（先读懂再动手）

- **项目**：ChatMemoir —— 微信聊天记录解密 / 语音转录 / 导出的桌面工具（Python + PySide GUI + Nuitka 打包）。
- **GitHub**：https://github.com/InterestingHui/ChatMemoir.git
- **源环境**：Windows 11 + WSL2 (Ubuntu)，项目原路径 `/home/ChatMemoir`（WSL 内）。
- **⚠️ 重要：这个仓库是"全量自包含"的**（2026-10-21 由源机特意补齐后推送，master ≥ `77295e9`）。也就是说 **git clone 一次就拿到了所有代码资产**，包括：
  - 全部代码与历史（master 含源机最后的未提交修改快照 `bb70aa7`）；
  - **`.workbuddy/memory/`** —— WorkBuddy 项目记忆（工作日志），clone 后即生效，**不要当普通文档忽略**；
  - **`.planning/`** —— 项目规划全套（PROJECT/ROADMAP/STATE/架构分析/历史任务 PLAN-SUMMARY）；
  - **`req_fixed.txt`** —— 源机锁好版本的依赖清单，**装依赖必须用它**，别用 `requirements.txt`（未锁版本）；
  - `build.bat`、`dev.json` —— Windows 构建脚本与（空）配置。
  这些文件原本被 `.gitignore` 挡着，是源机用 `git add -f` 强制入库的。**因此本迁移不需要任何额外数据包**，除非用户明确要求搬运历史聊天数据（见第 4 节）。

## 1. 环境准备

1. 确认本机有 WSL2（Ubuntu）。若无：`wsl --install -d Ubuntu`（管理员 PowerShell，需重启）。
2. 确认 git、python3 可用：`wsl -d Ubuntu -- bash -c "git --version && python3 --version"`。
3. 落盘位置默认 `$TARGET=/home/ChatMemoir`（与源机一致）。用户指定其他路径则同步替换。

## 2. 克隆代码（一步到位）

```bash
wsl -d Ubuntu -- bash -c "git clone https://github.com/InterestingHui/ChatMemoir.git $TARGET && cd $TARGET && git log --oneline -3"
```

**验证点 A**：顶端提交应为 `77295e9 chore: track project memory...`（或更新），且以下文件全部存在：
```bash
wsl -d Ubuntu -- bash -c "cd $TARGET && ls .workbuddy/memory/ .planning/PROJECT.md req_fixed.txt build.bat dev.json"
```

## 3. Python 依赖

```bash
wsl -d Ubuntu -- bash -c "cd $TARGET && python3 -m venv venv && ./venv/bin/pip install -r req_fixed.txt"
```
- 用 `req_fixed.txt`（源机修好的锁定版本），不要用 `requirements.txt`。
- 缺系统库（PySide6/soundfile 等的依赖）按报错 `apt install`。

## 4. 历史聊天数据（默认跳过！）

`decrypted/`(解密库)、`data/`(语音图片)、`dist/`(成品程序)、`doc/` 不在 git 里。**用户已确认**：新机登录微信后跑 GUI 重新解密一遍即可重建，**不需要搬运**，也不要主动提起打大数据包的事。
仅当用户明确说"要把旧数据搬过来"时，才提示：源机有一条现成命令可打包（`decrypted data dist doc backup_ka89_20260831.tar.gz` 合计约 3.8G），届时再要命令。

## 5. 会话与记忆对齐

1. 任务/会话历史随用户**同账号登录自动云端同步**，无需处理。
2. `.workbuddy/memory/` 已随 clone 就位——这就是本项目的长期记忆，直接读取沿用，延续源机的工作上下文（例如：代理 `127.0.0.1:7890` 挂掉时用 `git -c http.proxy= -c https.proxy= -c http.sslBackend=openssl push` 直连推送）。
3. 用户跨项目偏好由账号云端配置携带，无需处理。

## 6. 最终验收清单

- [ ] `git log --oneline -1` ≥ `77295e9`
- [ ] `.workbuddy/memory/`、`.planning/`、`req_fixed.txt`、`build.bat` 齐全
- [ ] venv 内 `python3 -c "import PySide6"` 成功
- [ ] 向用户报告：clone 了什么、验证结果、GUI 首次跑解密需要注意什么

## 7. 红线

- 不要主动 push（除非用户说推）。
- 不要删除源机任何东西——这是复制，不是搬运。
- 落盘路径变更先问用户。
- **不要建议打大数据包**（用户已决定重新解密生成），除非用户主动要。
