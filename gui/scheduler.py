"""ChatMemoir GUI 定时任务：定时刷新数据 → 指定会话 AI 分析 → HTML 报告。"""

import html as _html
import json
import os
import threading
import time
from datetime import datetime
from tkinter import ttk

from gui.constants import _save_config

# AI 默认走智谱 OpenAI 兼容接口，可在设置里改
AI_DEFAULTS = {
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "",
    "model": "glm-4-flash",
}

INTERVALS = [("每30分钟", 30), ("每1小时", 60), ("每3小时", 180),
             ("每6小时", 360), ("每12小时", 720), ("每24小时", 1440)]

REPORT_DIR = "schedule_reports"


class SchedulerMixin:
    """Mixin providing scheduled AI analysis tasks for ChatMemoirApp."""

    # ── 调度线程 ──────────────────────────────────────────

    def _start_scheduler(self):
        self._sched_lock = threading.Lock()
        self._sched_stop = threading.Event()
        threading.Thread(target=self._sched_loop, daemon=True).start()

    def _sched_loop(self):
        # ponytail: 30s 轮询足够（最小间隔30分钟），无需更精细的调度器
        while not self._sched_stop.wait(30):
            try:
                self._sched_tick()
            except Exception:
                pass

    def _sched_tick(self):
        if self.running:  # 用户操作进行中，让路
            return
        now = time.time()
        for task in self._sched_tasks():
            if not task.get("enabled", True):
                continue
            if now - task.get("last_run", 0) >= task["interval_min"] * 60:
                if self._sched_lock.acquire(blocking=False):
                    # 锁由任务线程释放（见 _run_sched_task_safe）
                    threading.Thread(
                        target=self._run_sched_task_safe,
                        args=(task,), daemon=True).start()
                break  # 一次只跑一个

    def _run_sched_task_safe(self, task):
        try:
            self._run_sched_task(task)
        except Exception as e:
            self._sched_log(f"定时任务失败 [{task.get('name')}]: {e}")
        finally:
            task["last_run"] = time.time()
            self._sched_save_tasks()
            self._sched_lock.release()

    def _sched_log(self, msg):
        self.log(f"[定时] {msg}")
        try:
            self.root.after(0, lambda m=msg: self.set_status(m))
        except Exception:
            pass

    # ── 配置 ─────────────────────────────────────────────

    def _sched_tasks(self):
        return self._config.setdefault("schedule_tasks", [])

    def _sched_save_tasks(self):
        _save_config(self._config)
        try:
            self.root.after(0, self._refresh_task_tree)
        except Exception:
            pass

    def _ai_cfg(self):
        cfg = dict(AI_DEFAULTS)
        cfg.update(self._config.get("ai") or {})
        return cfg

    # ── 任务执行：刷新 → 取消息 → AI → HTML ───────────────

    def _run_sched_task(self, task):
        uid, name = task["uid"], task.get("name", task["uid"])
        self._sched_log(f"开始分析: {name}")

        # 1. 静默刷新数据（增量重解密 + 重载数据库；UI 更新走 root.after，不打扰当前屏）
        self._auto_decrypt()

        window_start = datetime.fromtimestamp(
            task.get("window_start_ts", task.get("last_run", 0) or
                     time.time() - 24 * 3600)
        ).strftime("%Y-%m-%d %H:%M:%S")
        window_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. 拉取该会话窗口内消息
        messages = self.database.get_messages(uid, time_range=[window_start, window_end])
        messages = [m for m in messages if (m.to_text() or "").strip()]
        if not messages:
            self._sched_log(f"[{name}] 窗口内无新消息，跳过")
            return
        task["window_start_ts"] = time.time()

        # 3. 本地统计 + AI 分析
        stats = self._sched_stats(messages)
        ai_result = None
        if self._ai_cfg().get("api_key"):
            ai_result = self._sched_ai_analyze(name, messages, stats)
        else:
            self._sched_log(f"[{name}] 未配置 AI，仅生成统计报告")

        # 4. 写 HTML 报告
        path = self._sched_write_report(name, window_start, window_end,
                                        messages, stats, ai_result)
        self._sched_log(f"[{name}] 报告已生成: {os.path.basename(path)}")

        # 刷新联系人列表（消息数变了）
        try:
            self.root.after(0, lambda: (self._populate_contacts(), self._compute_stats()))
        except Exception:
            pass

    def _sched_stats(self, messages):
        per_sender = {}
        for m in messages:
            key = m.display_name or m.sender_id
            per_sender[key] = per_sender.get(key, 0) + 1
        return {
            "total": len(messages),
            "per_sender": dict(sorted(per_sender.items(), key=lambda kv: -kv[1])),
        }

    # ── AI 调用 ───────────────────────────────────────────

    def _sched_ai_analyze(self, name, messages, stats):
        import requests

        # ponytail: 截断保护 — 取末尾600条/10万字符（保留最新内容）
        transcript_lines = [
            f"{m.display_name or m.sender_id}: {m.to_text().strip()}"
            for m in messages
        ]
        transcript = "\n".join(transcript_lines[-600:])[-100000:]

        cfg = self._ai_cfg()
        system = (
            "你是一位聊天记录分析助手。分析用户提供的微信聊天记录（可能是一对一或群聊），"
            "总结各方观点。只输出一个 JSON 对象，不要输出其他任何文字，格式：\n"
            '{"overview": "整体话题概述(2-3句)", '
            '"viewpoints": [{"holder": "发言人", "viewpoint": "核心观点", "evidence": "原文依据摘录"}], '
            '"topics": ["话题1", "话题2"], '
            '"conclusion": "结论与展望(1-2句)"}\n'
            "viewpoints 最多8条，覆盖主要参与者，evidence 尽量引用原文。"
        )
        user = f"会话对象: {name}\n参与人数统计: {json.dumps(stats['per_sender'], ensure_ascii=False)}\n\n聊天记录:\n{transcript}"

        try:
            resp = requests.post(
                cfg["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "temperature": 0.3,
                },
                timeout=180,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            self._sched_log(f"AI 调用失败: {e}")
            return None

        return self._parse_ai_json(content) or {"raw": content}

    @staticmethod
    def _parse_ai_json(content):
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return None

    # ── HTML 报告 ─────────────────────────────────────────

    def _sched_write_report(self, name, t_start, t_end, messages, stats, ai):
        out_root = self._output_dir.get() if hasattr(self, "_output_dir") else None
        if not out_root:
            out_root = os.path.join(self._script_dir, "data")
        report_dir = os.path.join(out_root if os.path.isabs(out_root)
                                  else os.path.join(self._script_dir, out_root), REPORT_DIR)
        os.makedirs(report_dir, exist_ok=True)
        safe_name = "".join(c for c in name if c not in r'\/:*?"<>|')[:40] or "chat"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(report_dir, f"{safe_name}_{ts}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._build_report_html(name, t_start, t_end, stats, ai))
        return path

    @staticmethod
    def _build_report_html(name, t_start, t_end, stats, ai):
        e = _html.escape
        per_sender_rows = "".join(
            f'<tr><td>{e(k)}</td><td style="text-align:right">{v}</td></tr>'
            for k, v in stats["per_sender"].items())

        def sec(title, body):
            return f'<section><h2>{e(title)}</h2>{body}</section>' if body else ""

        ai_html = ""
        if ai:
            if ai.get("overview"):
                ai_html += sec("话题概览", f"<p>{e(ai['overview'])}</p>")
            if ai.get("viewpoints"):
                rows = "".join(
                    f'<div class="vp"><div class="holder">{e(v.get("holder", ""))}</div>'
                    f'<div class="body"><p class="pt">{e(v.get("viewpoint", ""))}</p>'
                    f'<p class="ev">依据：{e(v.get("evidence", ""))}</p></div></div>'
                    for v in ai["viewpoints"] if isinstance(v, dict))
                ai_html += sec("观点总结", rows or "<p>无</p>")
            if ai.get("topics"):
                tags = "".join(f'<span class="tag">{e(t)}</span>' for t in ai["topics"])
                ai_html += sec("主要话题", f'<p>{tags}</p>')
            if ai.get("conclusion"):
                ai_html += sec("结论", f"<p>{e(ai['conclusion'])}</p>")
            if ai.get("raw"):
                ai_html += sec("AI 原始输出", f"<pre>{e(ai['raw'])}</pre>")
        else:
            ai_html = sec("AI 分析", '<p class="muted">未配置 AI 或调用失败 — 在「AI 设置」中填写 API Key 后可获得观点总结。</p>')

        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 分析报告 - {e(name)}</title>
<style>
:root {{ --primary:#07C160; --bg:#F0F2F5; --card:#fff; --text:#191919; --muted:#8E8E93; }}
* {{ box-sizing:border-box; margin:0; }}
body {{ font-family:"Microsoft YaHei UI",system-ui,sans-serif; background:var(--bg); color:var(--text); padding:24px; }}
.wrap {{ max-width:860px; margin:0 auto; }}
header {{ background:var(--primary); color:#fff; border-radius:12px; padding:24px 28px; margin-bottom:16px; }}
header h1 {{ font-size:22px; margin-bottom:8px; }}
header p {{ opacity:.9; font-size:13px; line-height:1.7; }}
section {{ background:var(--card); border-radius:12px; padding:20px 24px; margin-bottom:16px; }}
h2 {{ font-size:16px; margin-bottom:12px; border-left:4px solid var(--primary); padding-left:10px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
td {{ padding:6px 4px; border-bottom:1px solid #f0f0f0; }}
.vp {{ display:flex; gap:12px; padding:10px 0; border-bottom:1px dashed #eee; }}
.holder {{ flex:0 0 88px; font-weight:600; color:var(--primary); }}
.pt {{ font-size:14px; line-height:1.7; }}
.ev {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.tag {{ display:inline-block; background:#e8f8ef; color:var(--primary); border-radius:4px; padding:2px 10px; margin:2px; font-size:13px; }}
pre {{ white-space:pre-wrap; font-size:13px; line-height:1.6; }}
.muted {{ color:var(--muted); font-size:13px; }}
footer {{ text-align:center; color:var(--muted); font-size:12px; padding:8px; }}
</style></head><body><div class="wrap">
<header><h1>AI 分析报告 · {e(name)}</h1>
<p>时间范围：{e(t_start)} ~ {e(t_end)}<br>
消息总数：{stats['total']} · 生成时间：{e(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</p></header>
{sec("发言统计", f"<table>{per_sender_rows}</table>")}
{ai_html}
<footer>ChatMemoir 留痕 · 定时分析报告</footer>
</div></body></html>"""

    # ── UI：主屏卡片 ──────────────────────────────────────

    def _build_schedule_card(self, parent):
        card = ttk.LabelFrame(parent, text="定时分析与 AI 报告", padding=12)
        card.pack(fill="x", pady=(0, 12))

        row1 = ttk.Frame(card, style="Card.TFrame")
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="分析间隔:", width=10, anchor="e", style="Card.TLabel").pack(side="left")
        self._sched_interval = ttk.Combobox(row1, values=[n for n, _ in INTERVALS],
                                            state="readonly", width=10)
        self._sched_interval.pack(side="left", padx=(4, 0))
        self._sched_interval.set("每1小时")
        self._btn_add_task = ttk.Button(row1, text="添加当前联系人",
                                        command=self._on_add_schedule)
        self._btn_add_task.pack(side="left", padx=(8, 0))
        ttk.Button(row1, text="AI 设置", command=self._on_ai_settings).pack(side="right")
        ttk.Button(row1, text="立即分析", style="Accent.TButton",
                   command=self._on_run_now).pack(side="right", padx=(0, 6))

        self._task_tree = ttk.Treeview(card, columns=("name", "interval", "lastrun"),
                                       show="headings", height=3)
        self._task_tree.heading("name", text="会话")
        self._task_tree.heading("interval", text="间隔")
        self._task_tree.heading("lastrun", text="上次运行")
        self._task_tree.column("name", width=200)
        self._task_tree.column("interval", width=80, anchor="center")
        self._task_tree.column("lastrun", width=130, anchor="center")
        self._task_tree.pack(fill="x", pady=(8, 0))

        row2 = ttk.Frame(card, style="Card.TFrame")
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text="删除选中", command=self._on_del_schedule).pack(side="left")
        ttk.Button(row2, text="打开报告目录", command=self._on_open_report_dir).pack(side="left", padx=(6, 0))
        self._sched_hint = ttk.Label(row2, text="", foreground="#8E8E93", style="Card.TLabel")
        self._sched_hint.pack(side="right")

        self._refresh_task_tree()

    def _refresh_task_tree(self):
        if not hasattr(self, "_task_tree"):
            return
        self._task_tree.delete(*self._task_tree.get_children())
        interval_names = dict((m, n) for n, m in INTERVALS)
        for task in self._sched_tasks():
            last = task.get("last_run", 0)
            last_str = datetime.fromtimestamp(last).strftime("%m-%d %H:%M") if last else "未运行"
            if not task.get("enabled", True):
                last_str += " (已停)"
            self._task_tree.insert("", "end", iid=task["uid"],
                                   values=(task.get("name", task["uid"]),
                                           interval_names.get(task["interval_min"], f"{task['interval_min']}分钟"),
                                           last_str))
        cfg = self._ai_cfg()
        if hasattr(self, "_sched_hint"):
            self._sched_hint.configure(
                text=f"AI: {cfg['model'] if cfg['api_key'] else '未配置'}")

    # ── UI 事件 ───────────────────────────────────────────

    def _on_add_schedule(self):
        if not self.selected_contact:
            from tkinter import messagebox
            messagebox.showwarning("提示", "请先在左侧选择联系人或群聊")
            return
        c = self.selected_contact
        interval_min = dict((n, m) for n, m in INTERVALS).get(self._sched_interval.get(), 60)
        tasks = self._sched_tasks()
        if any(t["uid"] == c.uid for t in tasks):
            from tkinter import messagebox
            messagebox.showinfo("提示", "该会话已在定时任务中")
            return
        tasks.append({"uid": c.uid, "name": c.remark or c.nickname or c.uid,
                      "interval_min": interval_min, "last_run": 0, "enabled": True})
        self._sched_save_tasks()

    def _on_del_schedule(self):
        sel = self._task_tree.selection()
        if not sel:
            return
        uid = sel[0]
        self._config["schedule_tasks"] = [t for t in self._sched_tasks() if t["uid"] != uid]
        self._sched_save_tasks()

    def _on_run_now(self):
        if not self.selected_contact:
            from tkinter import messagebox
            messagebox.showwarning("提示", "请先选择联系人")
            return
        if self.running:
            return
        c = self.selected_contact
        task = {"uid": c.uid, "name": c.remark or c.nickname or c.uid,
                "interval_min": 60, "last_run": 0, "enabled": True}
        if not self._sched_lock.acquire(blocking=False):
            from tkinter import messagebox
            messagebox.showinfo("提示", "已有分析任务在运行中")
            return
        self.set_status("正在分析（刷新数据 → AI 总结 → 生成报告）...")
        threading.Thread(target=self._run_sched_task_safe, args=(task,), daemon=True).start()

    def _on_open_report_dir(self):
        out_root = self._output_dir.get() if hasattr(self, "_output_dir") else None
        base = out_root or os.path.join(self._script_dir, "data")
        report_dir = os.path.join(base if os.path.isabs(base) else os.path.join(self._script_dir, base), REPORT_DIR)
        os.makedirs(report_dir, exist_ok=True)
        try:
            os.startfile(report_dir)
        except Exception:
            pass

    def _on_ai_settings(self):
        import tkinter as tk
        from tkinter import ttk as _ttk

        cfg = self._ai_cfg()
        dlg = tk.Toplevel(self.root)
        dlg.title("AI 设置")
        dlg.geometry("480x220")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        vars_ = {}
        for i, (key, label) in enumerate([
                ("base_url", "接口地址"), ("api_key", "API Key"), ("model", "模型")]):
            _ttk.Label(dlg, text=f"{label}:").grid(row=i, column=0, padx=(16, 8),
                                                   pady=12, sticky="e")
            v = tk.StringVar(value=cfg[key])
            entry = _ttk.Entry(dlg, textvariable=v, width=44,
                               show="*" if key == "api_key" else "")
            entry.grid(row=i, column=1, padx=(0, 16))
            vars_[key] = v

        def _save():
            self._config["ai"] = {k: v.get().strip() for k, v in vars_.items()}
            _save_config(self._config)
            self._refresh_task_tree()
            dlg.destroy()

        btns = _ttk.Frame(dlg)
        btns.grid(row=3, column=0, columnspan=2, pady=14)
        _ttk.Button(btns, text="保存", style="Accent.TButton", command=_save).pack(side="left", padx=8)
        _ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="left", padx=8)


if __name__ == "__main__":
    # 自检：报告生成 + AI JSON 解析
    rep = SchedulerMixin._build_report_html(
        "测试群", "2026-08-17 00:00:00", "2026-08-17 12:00:00",
        {"total": 3, "per_sender": {"张三": 2, "李四": 1}},
        {"overview": "讨论了发布", "viewpoints": [
            {"holder": "张三", "viewpoint": "应该延期", "evidence": "「我建议延期」"}],
         "topics": ["发布"], "conclusion": "待定"})
    assert "测试群" in rep and "张三" in rep and "应该延期" in rep
    assert SchedulerMixin._parse_ai_json('```json\n{"overview": "x"}\n```') == {"overview": "x"}
    assert SchedulerMixin._parse_ai_json("前置废话 {\"a\": 1} 后置") == {"a": 1}
    assert SchedulerMixin._parse_ai_json("不是json") is None
    print("scheduler self-check OK")
