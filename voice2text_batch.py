#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
voice2text_batch.py — 批量语音转写工具（ChatMemoir）

从解密数据库读取 SILK 语音 → pysilk 解码 → Whisper 转写 → 写回 Audio2Text.db
（HTML/TXT 等导出器会自动读取该缓存，把文字渲染在语音下方）。

特性：
  - 增量：只转写 Audio2Text.db 里还没有的语音（已有微信自带转写的自动跳过）
  - 台账：每条语音一行 JSONL，含来源、时长、耗时、状态（OK / EMPTY / FAILED）、
    时间戳分段；转录失败显式记录，不静默跳过
  - 可中断续跑：进度按条写入缓存库，随时 Ctrl+C 后重跑自动续

用法（在 WSL /home/ChatMemoir 下）：
  python3 voice2text_batch.py --uid wxid_9zv9emyoyx7y12 --limit 20
  python3 voice2text_batch.py --uid wxid_xxx --model small --jsonl data/voice_ledger.jsonl
  python3 voice2text_batch.py --all                 # 全库（耗时长，建议挂机）
  python3 voice2text_batch.py --smoke               # 结构自检（不加载模型）

依赖（WSL 已具备）：openai-whisper、pysilk、numpy、torch、ffmpeg（可选兜底）
"""

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_DIR = os.path.join(BASE, 'decrypted', 'wxid_ttlo1sb5pyh811', 'db_storage')
LEDGER_DEFAULT = os.path.join(BASE, 'data', 'voice_ledger.jsonl')

STATUS_OK = 'OK'            # 转写成功且有文字
STATUS_EMPTY = 'EMPTY'      # 解码成功但无语音内容（静音/极短）
STATUS_FAILED = 'FAILED'    # 数据损坏/解码失败/转写异常


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def resolve_md5(uid):
    return 'Msg_' + hashlib.md5(uid.encode()).hexdigest()


def iter_voice_ids(msg_dir, uids=None):
    """yield (server_id, uid, create_time)；uids=None 表示全库"""
    tables = {}
    for f in sorted(glob.glob(os.path.join(msg_dir, 'message_*.db'))):
        conn = sqlite3.connect(f)
        tabs = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in tabs:
            if not t.startswith('Msg_'):
                continue
            if uids is not None and t not in {resolve_md5(u) for u in uids}:
                continue
            try:
                rows = conn.execute(
                    "SELECT server_id, create_time FROM [%s] WHERE local_type=34" % t
                ).fetchall()
                tables.setdefault(t, []).extend(rows)
            except Exception as e:
                log(f'WARN 扫描 {t} 失败: {e}')
        conn.close()
    for t, rows in tables.items():
        uid_md5 = t[4:]
        uid = None
        for u in (uids or []):
            if resolve_md5(u) == t:
                uid = u
                break
        for sid, ct in rows:
            yield sid, uid or uid_md5, ct


def transcribe_one(model, media_conn, server_id, language='zh'):
    """转写单条语音 → (status, text, segments, duration, error)"""
    row = media_conn.execute(
        'SELECT voice_data FROM VoiceInfo WHERE svr_id=?', [server_id]).fetchone()
    if not row or not row[0] or len(row[0]) < 100:
        return STATUS_FAILED, '', [], 0.0, 'voice_data missing or too short (<100B)'

    import numpy as np
    import pysilk
    silk = row[0]
    try:
        pcm = pysilk.decode(silk, to_wav=False, sample_rate=16000)
    except Exception as e:
        return STATUS_FAILED, '', [], 0.0, f'silk decode: {type(e).__name__}: {e}'

    try:
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception as e:
        return STATUS_FAILED, '', [], 0.0, f'pcm convert: {type(e).__name__}: {e}'

    duration = len(arr) / 16000.0
    if duration < 0.4:
        return STATUS_EMPTY, '', [], duration, 'no speech content (duration < 0.4s)'

    try:
        result = model.transcribe(arr, language=language, fp16=False)
        text = (result.get('text') or '').strip()
        segments = [
            {
                'start': round(float(s.get('start', 0.0)), 2),
                'end': round(float(s.get('end', 0.0)), 2),
                'text': (s.get('text') or '').strip(),
            }
            for s in (result.get('segments') or [])
        ]
        if not text:
            return STATUS_EMPTY, '', segments, duration, 'transcriber returned empty text'
        return STATUS_OK, text, segments, duration, ''
    except Exception as e:
        return STATUS_FAILED, '', [], duration, f'whisper: {type(e).__name__}: {e}'


def append_ledger(path, record):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def run(args):
    msg_dir = os.path.join(args.db_dir, 'message')
    if not os.path.isdir(msg_dir):
        log(f'ERROR 消息库目录不存在: {msg_dir}')
        return 1
    media_path = os.path.join(msg_dir, 'media_0.db')
    if not os.path.exists(media_path):
        log(f'ERROR 媒体库不存在: {media_path}')
        return 1

    db_path = args.db
    a2t_exists = os.path.exists(db_path)
    a2t = sqlite3.connect(db_path)
    if not a2t_exists:
        a2t.execute('''CREATE TABLE IF NOT EXISTS Audio2Text (
            ID INTEGER PRIMARY KEY,
            msgSvrId INTEGER UNIQUE,
            Text TEXT NOT NULL)''')
        a2t.commit()
    cached = set(r[0] for r in a2t.execute('SELECT msgSvrId FROM Audio2Text').fetchall())

    uids = None
    if args.uid:
        uids = args.uid if isinstance(args.uid, list) else [args.uid]

    log(f'扫描语音清单（uids={uids or "全库"}）...')
    voices = list(iter_voice_ids(msg_dir, uids))
    missing = [(sid, uid, ct) for sid, uid, ct in voices if sid not in cached]
    missing.sort(key=lambda r: (r[2] or 0))  # oldest first: deterministic --limit
    log(f'语音总数 {len(voices)}，已有转写 {len(voices) - len(missing)}，待转写 {len(missing)}')
    if args.limit and len(missing) > args.limit:
        missing = missing[:args.limit]
        log(f'--limit 生效：本轮只转 {args.limit} 条')

    if args.smoke:
        stats = {'total': len(voices), 'missing': len(missing)}
        print('SMOKE ' + json.dumps(stats, ensure_ascii=False))
        a2t.close()
        return 0

    if not missing:
        log('没有待转写语音，完成。')
        a2t.close()
        return 0

    log(f'加载 Whisper 模型 {args.model}（首次运行会自动下载）...')
    import whisper
    t0 = time.time()
    model = whisper.load_model(args.model)
    log(f'模型加载完成（{time.time() - t0:.1f}s）')

    media_conn = sqlite3.connect(media_path)
    ledger = args.jsonl
    ok_n = empty_n = fail_n = 0
    t_start = time.time()

    for i, (sid, uid, ct) in enumerate(missing, 1):
        t0 = time.time()
        status, text, segments, duration, err = transcribe_one(model, media_conn, sid)
        dt = time.time() - t0

        rec = {
            'msgSvrId': sid,
            'uid': uid,
            'create_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ct)) if ct else '',
            'duration_sec': round(duration, 2),
            'transcribe_sec': round(dt, 2),
            'model': args.model,
            'status': status,
            'text': text,
            'segments': segments,
            'error': err,
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        if ledger:
            append_ledger(ledger, rec)

        if status == STATUS_OK:
            try:
                a2t.execute('INSERT INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)', [sid, text])
                a2t.commit()
                ok_n += 1
            except sqlite3.IntegrityError:
                pass
            except Exception as e:
                fail_n += 1
                rec['status'] = STATUS_FAILED
                rec['error'] = f'db write: {e}'
                if ledger:
                    append_ledger(ledger, rec)
        elif status == STATUS_EMPTY:
            # 空语音也写缓存，避免每次重跑重复解码；文本留空，导出端兜底占位
            try:
                a2t.execute('INSERT INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)', [sid, ''])
                a2t.commit()
            except sqlite3.IntegrityError:
                pass
            empty_n += 1
        else:
            # FAILED 只记台账，不写缓存——数据修复或换模型后重跑可重试
            fail_n += 1

        if i % 10 == 0 or i == len(missing):
            done = i
            rate = done / max(time.time() - t_start, 1e-6)
            eta = (len(missing) - done) / max(rate, 1e-6) / 60.0
            log(f'进度 {done}/{len(missing)}  OK={ok_n} EMPTY={empty_n} FAILED={fail_n}  '
                f'{rate:.2f}条/s  剩余约 {eta:.0f} 分钟')

    log(f'完成：OK={ok_n} EMPTY={empty_n} FAILED={fail_n}，'
        f'耗时 {(time.time() - t_start) / 60:.1f} 分钟')
    if ledger:
        log(f'台账已写入 {ledger}')
    media_conn.close()
    a2t.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description='批量语音转写（SILK→Whisper→Audio2Text.db）')
    ap.add_argument('--uid', action='append', help='目标联系人/群 wxid，可多次传；不传=全库')
    ap.add_argument('--model', default='small', help='whisper 模型: tiny/base/small/medium/large-v3')
    ap.add_argument('--limit', type=int, default=0, help='本轮最多转写条数（0=不限）')
    ap.add_argument('--jsonl', default=LEDGER_DEFAULT, help='台账 JSONL 输出路径')
    ap.add_argument('--db', default=os.path.join(DEFAULT_DB_DIR, 'Audio2Text.db'),
                    help='Audio2Text.db 路径')
    ap.add_argument('--db-dir', default=DEFAULT_DB_DIR, help='解密库根目录')
    ap.add_argument('--smoke', action='store_true', help='只做结构自检，不加载模型')
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n用户中断——已完成的转写都已入库，重跑自动续。', flush=True)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
