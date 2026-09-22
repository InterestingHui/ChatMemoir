#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AiHtmlExporter — AI 整理 HTML 导出

导出一段时间内的聊天记录为「AI 整理 + 完整附录」的自包含 HTML：
  1. AI 分批整理 → 各段主题/要点/金句/事件（JSON 严格格式，容错解析）
  2. AI 汇总 → 全期概览 + 主题脉络 + 待办/约定时间线
  3. 完整附录：按日折叠的全量原始消息（含语音转录文字），信息零遗漏
  4. 版式：奢侈极简（70% 留白、字重对比、单一强调色）

AI 通道复用 GUI 配置（.gui_config.json 的 ai.*），支持环境变量
CHATMEMOIR_AI_API_KEY 覆盖；未配置或调用失败自动降级为规则统计版，
功能永不阻塞。
"""

import json
import os
import re
from collections import defaultdict

import requests

from memoir import Message
from memoir.log import logger
from scribe.exporter_base import ExporterBase, get_new_filename, remove_privacy_info, safe_makedirs

AI_ENV_KEY = "CHATMEMOIR_AI_API_KEY"
AI_ENV_BASE = "CHATMEMOIR_AI_BASE_URL"
AI_ENV_MODEL = "CHATMEMOIR_AI_MODEL"

AI_DEFAULTS = {
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "",
    "model": "glm-4-flash",
}

BATCH_CHARS = 9000           # 每批正文字符数——控制输出 JSON 体量，避免截断
MAX_AI_RETRIES = 1           # 单批失败重试次数
SUMMARY_BATCH_RETRIES = 2


def _ai_cfg_from_config(cfg: dict) -> dict:
    """GUI config dict → AI 配置（env 优先）。"""
    out = dict(AI_DEFAULTS)
    out.update(cfg.get("ai") or {})
    if os.environ.get(AI_ENV_KEY):
        out["api_key"] = os.environ[AI_ENV_KEY]
    if os.environ.get(AI_ENV_BASE):
        out["base_url"] = os.environ[AI_ENV_BASE]
    if os.environ.get(AI_ENV_MODEL):
        out["model"] = os.environ[AI_ENV_MODEL]
    return out


def _chat(cfg: dict, system: str, user: str, temperature: float = 0.3, timeout: int = 180) -> str:
    """OpenAI 兼容 chat/completions → 文本。失败抛异常。"""
    resp = requests.post(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model"],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": 4000,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict:
    """容错解析 AI 返回的 JSON（剥 markdown fence、截取首尾大括号）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        t = t[start:end + 1]
    return json.loads(t)


BATCH_SYSTEM = """你是聊天记录整理助手。输入是某联系人在一段时间内微信聊天记录的连续一段，
每行格式「MM-DD HH:MM | 名字: 内容」（可能包含【语音】转录文字、【图片】【视频】等标记）。
任务：把这段内容整理成结构化 JSON，供最终汇总。要求：
1. 不编造：所有信息来自原文；引用的「quote」必须是原文原句（≤60字）
2. 不遗漏：覆盖该段所有主要话题；具体数字、金额、日期、人名、约定必须保留
3. 口语转书面表达，但保留原意的语气与细节
只输出 JSON，格式：
{"topics":[{"title":"话题名(≤16字)","dates":["MM-DD"],"summary":"2-4句概括","points":["要点",...]}],
 "highlights":[{"date":"MM-DD","quote":"原文原句","note":"一句话说明"}],
 "events":[{"date":"MM-DD","event":"具体事件/决定/约定(含数字与人名)"}]}"""

FINAL_SYSTEM = """你是聊天记录整理主编。输入：某联系人全时段聊天记录的分批整理简报(JSON)与基础统计。
任务：只做两件事——①写 overview（3-6 句概括整体脉络与关系基调）②写 promises（未完成的约定/待办清单，没有则空数组）。
主题/金句/事件由系统自动合并，你不需要输出它们（输出空数组占位即可）。
只输出紧凑 JSON（不要 markdown、不要注释、字符串内不要换行）：
{"overview":"...","stats_note":"一段话点评活跃度与沟通特点","topics":[],"highlights":[],"events":[],"promises":["..."]}"""


def _fmt_day_line(m: Message) -> str:
    txt = remove_privacy_info(m.to_text())
    txt = txt.replace('\n', ' ')
    return f"{m.str_time[5:16]} | {(m.display_name or '?')}: {txt}"


class AiHtmlExporter(ExporterBase):
    """AI 整理 HTML 导出器（时间范围由 time_range 控制，语音文字来自 Audio2Text 缓存）。"""

    def export(self):
        print(f"【开始导出 AI 整理 HTML {self.contact.remark}】")
        safe_makedirs(self.origin_path)
        name = self.contact.remark or self.contact.uid
        tr = self.time_range or ['', '']
        tag = f"{(tr[0] or '早')[:10]}_{(tr[1] or '今')[:10]}".replace(':', '')
        filename = os.path.join(self.origin_path, f"{name}_AI整理_{tag}.html")
        filename = get_new_filename(filename)

        messages = self.database.get_messages(self.contact.uid, time_range=self.time_range)
        selected = [m for m in messages if self.is_selected(m)]
        total_steps = max(len(selected), 1)

        # ── 1. 组装按日 transcript ──
        grouped = defaultdict(list)
        voice_total = voice_texted = 0
        for m in selected:
            line = _fmt_day_line(m)
            if '【语音' in line:
                voice_total += 1
                if not line.rstrip().endswith('【语音】'):
                    voice_texted += 1
            grouped[m.str_time[:10]].append(line)

        days = sorted(grouped.keys())
        # 平铺成批
        batches, cur, cur_len = [], [], 0
        for d in days:
            chunk = f"【{d}】\n" + "\n".join(grouped[d])
            if cur_len + len(chunk) > BATCH_CHARS and cur:
                batches.append("\n\n".join(cur))
                cur, cur_len = [], 0
            cur.append(chunk)
            cur_len += len(chunk)
        if cur:
            batches.append("\n\n".join(cur))

        cfg = _ai_cfg_from_config(getattr(self, 'gui_config', None) or {})
        ai_mode = bool(cfg.get("api_key"))
        batch_results, ai_error, final = [], None, None

        if ai_mode:
            # ── 2. 分批 AI 整理（单批失败对半拆分重试，不整体放弃） ──
            skipped_ranges = []

            def run_batch(batch_text, tag):
                """返回整理 dict 或 None（重试+对半拆分后仍失败）。"""
                self._set_status_safe(f"AI 整理 {tag}...")
                for attempt in range(MAX_AI_RETRIES + 1):
                    try:
                        return _parse_json(_chat(cfg, BATCH_SYSTEM, batch_text))
                    except Exception as e:
                        logger.error(f'AI {tag} attempt {attempt}: {e}')
                        ai_error = str(e)[:200]
                # 对半拆分重试（仅当拆得动时）
                lines = batch_text.split('\n')
                if len(lines) >= 8:
                    mid = len(lines) // 2
                    a = run_batch('\n'.join(lines[:mid]), tag + 'a')
                    b = run_batch('\n'.join(lines[mid:]), tag + 'b')
                    if a or b:
                        merged = {"topics": [], "highlights": [], "events": []}
                        for part in (a, b):
                            if part:
                                for k in merged:
                                    merged[k].extend(part.get(k) or [])
                        return merged
                return None

            bi = 0
            while bi < len(batches):
                self.update_progress_callback(0.05 + 0.65 * bi / max(len(batches), 1))
                got = run_batch(batches[bi], f"批次 {bi + 1}/{len(batches)}")
                if got is not None:
                    batch_results.append(got)
                else:
                    skipped_ranges.append(f"批次 {bi + 1}")
                bi += 1
            if skipped_ranges and batch_results:
                self._set_status_safe(f"部分批次未整理（{','.join(skipped_ranges)}），已降级合并")
            if not batch_results:
                ai_mode = False

            # ── 3. 汇总：主题取各批并集（保信息量），overview/promises 由 AI 基于
            #       每批主题标题+摘要（轻量输入）提炼，避免长输入丢内容 ──
            final = None
            if ai_mode and batch_results:
                all_topics = []
                all_highlights = []
                all_events = []
                for br in batch_results:
                    all_topics.extend(br.get('topics') or [])
                    all_highlights.extend(br.get('highlights') or [])
                    all_events.extend(br.get('events') or [])
                # 事件按日期排序
                all_events.sort(key=lambda e: e.get('date') or '')
                # 金句保留前 12 条（各批均匀）
                step = max(1, len(all_highlights) // 12)
                all_highlights = all_highlights[:12 * step:step] if all_highlights else []

                stats = {
                    "contact": name,
                    "time_range": [tr[0] or "最早", tr[1] or "最新"],
                    "total_messages": len(selected),
                    "days": len(days),
                    "voices": {"total": voice_total, "transcribed": voice_texted},
                }
                # 轻量输入：每批只给主题标题+首条摘要
                brief = [{"topics": [{"title": t.get('title'), "summary": (t.get('summary') or '')[:80]}
                                     for t in (br.get('topics') or [])]}
                         for br in batch_results]
                self._set_status_safe("AI 汇总全期脉络...")
                try:
                    raw = _chat(cfg, FINAL_SYSTEM,
                                json.dumps({"stats": stats, "batch_briefs": brief},
                                           ensure_ascii=False))
                    final = _parse_json(raw)
                except Exception as e:
                    logger.error(f'AI final: {e}')
                    ai_error = str(e)[:200]

                if final:
                    # AI 重新排序/合并主题失败时回退为各批并集原样
                    merged = final.get('topics')
                    if not merged:
                        final['topics'] = all_topics
                    else:
                        # AI 返回的重排主题若信息量明显缩水（缺 points），用并集补齐
                        union_by_title = {t.get('title'): t for t in all_topics}
                        enriched = []
                        for t in merged:
                            src_t = union_by_title.get(t.get('title'))
                            if src_t:
                                merged_t = dict(src_t)
                                if t.get('summary'):
                                    merged_t['summary'] = t['summary']
                                enriched.append(merged_t)
                            else:
                                enriched.append(t)
                        seen = {t.get('title') for t in enriched}
                        for t in all_topics:
                            if t.get('title') not in seen:
                                enriched.append(t)
                        final['topics'] = enriched
                    final.setdefault('highlights', all_highlights)
                    if not final.get('highlights'):
                        final['highlights'] = all_highlights
                    final.setdefault('events', all_events)
                    if not final.get('events'):
                        final['events'] = all_events
                else:
                    # 汇总失败但批次成功：并集直接作为结果，AI 模式保留
                    final = {
                        "overview": "", "stats_note": "",
                        "topics": all_topics, "highlights": all_highlights,
                        "events": all_events, "promises": [],
                    }

        # ── 4. 渲染（AI 或 降级） ──
        self._set_status_safe("渲染 HTML...")
        html = render_ai_html(
            name=name, contact_uid=self.contact.uid,
            time_range=[tr[0] or "最早记录", tr[1] or "最新记录"],
            grouped=grouped, days=days,
            total_messages=len(selected),
            voice_total=voice_total, voice_texted=voice_texted,
            ai_mode=ai_mode, final=final, batch_results=batch_results,
            ai_error=ai_error, model=cfg.get("model") or "",
        )
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)

        self.update_progress_callback(1)
        mode_note = "AI 整理" if ai_mode else "AI 未启用（降级为规整统计版）"
        print(f"【完成导出 AI 整理 HTML {name}】{len(selected)} 条 · {mode_note}")
        self.finish_callback(self.scribe_id)

    def _set_status_safe(self, msg):
        cb = getattr(self, 'status_callback', None)
        if cb:
            try:
                cb(msg)
            except Exception:
                pass
        else:
            print(f'  {msg}')


# ────────────────────────── HTML 渲染（Build 奢侈极简） ──────────────────────────

ACCENT = "#9C4A1E"      # 单一强调色：焦糖
INK = "#17150F"
MUTED = "#8A8578"
HAIRLINE = "#E8E4DC"
PAPER = "#FBFAF7"


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def render_ai_html(*, name, contact_uid, time_range, grouped, days,
                   total_messages, voice_total, voice_texted,
                   ai_mode, final, batch_results, ai_error, model):
    """渲染自包含 AI 整理 HTML。final=None 时为降级统计版。"""
    stats_note = (final or {}).get('stats_note', '')
    overview = (final or {}).get('overview', '')
    topics = (final or {}).get('topics', [])
    highlights = (final or {}).get('highlights', [])
    events = (final or {}).get('events', [])
    promises = (final or {}).get('promises', [])

    if not ai_mode:
        # 降级：规则统计（无 AI 结论，只做规整统计 + 完整附录）
        overview = ''
        topics = []
        day_counts = [(d, len(grouped[d])) for d in days]
        peak = max(day_counts, key=lambda x: x[1]) if day_counts else ('-', 0)
        events = [{"date": d, "event": f"{len(grouped[d])} 条消息"} for d in days[:12]]
        stats_note = (f"AI 整理未启用（{('缺少 API Key：请在 GUI 设置中配置' if not ai_error else 'AI 调用失败：' + ai_error)}）。"
                      f"本页为规整统计版：全部消息按日保留于下方附录，零遗漏。")
        highlights = []

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} · AI 整理</title>
<style>
  :root {{ --accent:{ACCENT}; --ink:{INK}; --muted:{MUTED}; --hair:{HAIRLINE}; --paper:{PAPER}; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ scroll-behavior: smooth; }}
  body {{ background: var(--paper); color: var(--ink);
          font: 300 16px/1.9 "Segoe UI", "Microsoft YaHei", sans-serif;
          -webkit-font-smoothing: antialiased; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 88px 28px 140px; }}
  .kicker {{ font-size: 11px; letter-spacing: .34em; color: var(--muted); text-transform: uppercase; }}
  h1 {{ font-family: Georgia, "Noto Serif SC", "SimSun", serif; font-weight: 400;
        font-size: 34px; line-height: 1.3; margin: 18px 0 10px; }}
  .range {{ color: var(--muted); font-size: 14px; font-weight: 300; letter-spacing: .06em; }}
  .rule {{ border: 0; border-top: 1px solid var(--hair); margin: 44px 0; }}
  h2 {{ font-size: 12px; font-weight: 600; letter-spacing: .3em; color: var(--muted);
        text-transform: uppercase; margin-bottom: 26px; }}
  h2 b {{ color: var(--accent); font-weight: 600; }}
  .overview {{ font-size: 19px; font-weight: 300; line-height: 2; }}
  .overview em {{ font-style: normal; color: var(--accent); font-weight: 500; }}
  .metrics {{ display: flex; gap: 44px; flex-wrap: wrap; margin: 40px 0 0; }}
  .m b {{ display: block; font-size: 30px; font-weight: 200; letter-spacing: -.02em; }}
  .m span {{ font-size: 12px; color: var(--muted); letter-spacing: .18em; }}
  .card {{ border-top: 1px solid var(--hair); padding: 26px 0 6px; margin-top: 30px; }}
  .card h3 {{ font-size: 17px; font-weight: 600; letter-spacing: .02em; }}
  .card .dates {{ font-size: 11px; color: var(--accent); letter-spacing: .2em; margin: 4px 0 10px; }}
  .card p {{ color: #3A362C; font-size: 15px; }}
  .card ul {{ list-style: none; margin-top: 10px; }}
  .card li {{ font-size: 14.5px; color: #55503F; padding: 3px 0 3px 18px; position: relative; }}
  .card li:before {{ content: "—"; position: absolute; left: 0; color: var(--accent); }}
  blockquote {{ border-left: 2px solid var(--accent); padding: 2px 0 2px 20px; margin: 26px 0; }}
  blockquote .q {{ font-family: Georgia, "Noto Serif SC", "SimSun", serif; font-size: 16.5px;
                   font-weight: 400; line-height: 1.8; }}
  blockquote .n {{ font-size: 12.5px; color: var(--muted); margin-top: 6px; }}
  .events li, .promises li {{ list-style: none; display: flex; gap: 18px; padding: 7px 0;
                              border-bottom: 1px dotted var(--hair); font-size: 14.5px; }}
  .events .d, .promises .d {{ color: var(--accent); font-variant-numeric: tabular-nums;
                              min-width: 46px; font-weight: 500; }}
  details {{ border-top: 1px solid var(--hair); }}
  details:last-of-type {{ border-bottom: 1px solid var(--hair); }}
  summary {{ cursor: pointer; list-style: none; display: flex; align-items: baseline; gap: 16px;
             padding: 15px 4px; font-size: 14px; }}
  summary:hover {{ background: #F4F1EA; }}
  summary .d {{ font-weight: 600; min-width: 92px; }}
  summary .c {{ color: var(--muted); font-size: 12px; }}
  summary::-webkit-details-marker {{ display: none; }}
  summary:after {{ content: "+"; margin-left: auto; color: var(--accent); font-weight: 300; font-size: 18px; }}
  details[open] summary:after {{ content: "–"; }}
  .log {{ padding: 4px 4px 20px; }}
  .log p {{ font-size: 13px; line-height: 1.85; padding: 1.5px 0; color: #4A4536; word-break: break-word; }}
  .log p b {{ font-weight: 500; color: var(--ink); }}
  .log p.me {{ }}
  .log .t {{ color: var(--muted); font-size: 11px; margin-right: 8px; font-variant-numeric: tabular-nums; }}
  .notice {{ background: #F4F1EA; padding: 16px 20px; font-size: 13px; color: #6B6553;
             border-left: 2px solid var(--accent); margin: 26px 0; }}
  footer {{ margin-top: 90px; color: var(--muted); font-size: 12px; letter-spacing: .08em; }}
  @media print {{ .wrap {{ padding: 20px; }} details {{ open: true; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">ChatMemoir · AI 整理</div>
  <h1>{_esc(name)}</h1>
  <div class="range">{_esc(time_range[0][:10])} — {_esc(time_range[1][:10])}{(' · 模型 ' + _esc(model)) if ai_mode and model else ''}</div>
  <hr class="rule">
""")

    # 概览
    parts.append('  <h2><b>01</b> 概览</h2>')
    if ai_mode and overview:
        ov = _esc(overview)
        parts.append(f'  <p class="overview">{ov}</p>')
    else:
        parts.append(f'  <p class="overview">{_esc(stats_note)}</p>')
    parts.append(f"""  <div class="metrics">
    <div class="m"><b>{total_messages}</b><span>消息</span></div>
    <div class="m"><b>{len(days)}</b><span>活跃天</span></div>
    <div class="m"><b>{voice_texted}<i style="font-size:14px;color:var(--muted)">/{voice_total}</i></b><span>语音已转文字</span></div>
  </div>""")

    # 主题脉络
    if topics:
        parts.append('  <hr class="rule">\n  <h2><b>02</b> 主题脉络</h2>')
        for t in topics:
            dts = ' · '.join(t.get('dates') or [])
            pts = ''.join(f'<li>{_esc(p)}</li>' for p in (t.get('points') or []))
            parts.append(f"""  <div class="card">
    <h3>{_esc(t.get('title') or '')}</h3>
    <div class="dates">{_esc(dts)}</div>
    <p>{_esc(t.get('summary') or '')}</p>
    {('<ul>' + pts + '</ul>') if pts else ''}
  </div>""")

    # 金句
    if highlights:
        parts.append('  <hr class="rule">\n  <h2><b>03</b> 原文摘录</h2>')
        for hgt in highlights:
            parts.append(f"""  <blockquote>
    <div class="q">「{_esc(hgt.get('quote') or '')}」</div>
    <div class="n">{_esc(hgt.get('date') or '')} · {_esc(hgt.get('note') or '')}</div>
  </blockquote>""")

    # 事件时间线（超长时截前 40 条并提示）
    if events:
        events = events[:40]
        for ev in events:
            parts.append(f'    <li><span class="d">{_esc(ev.get("date") or "")}</span><span>{_esc(ev.get("event") or "")}</span></li>')
        parts.append('  </ul>')

    # 待办
    if promises:
        parts.append('  <hr class="rule">\n  <h2><b>05</b> 未完成的约定</h2><ul class="promises">')
        for pr in promises:
            parts.append(f'    <li><span class="d">·</span><span>{_esc(pr)}</span></li>')
        parts.append('  </ul>')

    if not ai_mode:
        parts.append(f'  <div class="notice">{_esc(stats_note)}</div>')

    # 附录（全量，零遗漏）
    parts.append('  <hr class="rule">\n  <h2><b>06</b> 完整记录</h2>')
    parts.append(f'  <p style="color:var(--muted);font-size:13px;margin:-14px 0 22px">'
                 f'共 {total_messages} 条 · {len(days)} 天 · 逐条保留（含语音转录文字）。点开任意日期查看。</p>')
    open_first = ' open' if len(days) <= 3 else ''
    for d in days:
        lines = []
        for raw in grouped[d]:
            # "MM-DD HH:MM | 名字: 内容"
            try:
                head, body = raw.split(' | ', 1)
                t_, who = head.split(' ', 1)
                who = who.rstrip(':')
            except ValueError:
                t_, who, body = '', '?', raw
            cls = ' me' if who.startswith('我') else ''
            lines.append(f'    <p class="{cls.strip()}"><span class="t">{_esc(t_)}</span><b>{_esc(who)}</b>：{_esc(body)}</p>')
        parts.append(f"""  <details{open_first}>
    <summary><span class="d">{_esc(d)}</span><span class="c">{len(grouped[d])} 条</span></summary>
    <div class="log">
{chr(10).join(lines)}
    </div>
  </details>""")

    parts.append(f"""  <footer>ChatMemoir AI 整理 · {_esc(time_range[0][:10])}–{_esc(time_range[1][:10])} ·
  {'AI: ' + _esc(model) if ai_mode else '规整统计版（未启用 AI）'}</footer>
</div>
</body>
</html>""")
    return '\n'.join(parts)
