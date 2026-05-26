#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
语音转文字脚本
从聊天数据库提取 SILK 语音 → 转 WAV → Whisper 识别 → 写入 Audio2Text.db
"""

import os
import sqlite3
import struct
import sys

import numpy as np
import pysilk
import whisper


def silk_to_audio(silk_data: bytes) -> np.ndarray:
    """SILK 数据 → numpy float32 数组（16000Hz 单声道），不依赖 ffmpeg"""
    pcm_buf = pysilk.decode(silk_data, to_wav=False, sample_rate=16000)
    # PCM s16le → float32 numpy array
    samples = np.frombuffer(pcm_buf, dtype=np.int16).astype(np.float32) / 32768.0
    return samples


def main():
    db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'wxid_ttlo1sb5pyh811', 'db_storage')
    media_db_path = os.path.join(db_dir, 'message', 'media_0.db')
    msg_dir = os.path.join(db_dir, 'message')
    audio2text_db_path = os.path.join(db_dir, 'Audio2Text.db')

    # 支持命令行参数指定 uid，不指定则转写全部
    target_uid = sys.argv[1] if len(sys.argv) > 1 else None

    if not os.path.exists(media_db_path):
        print(f'找不到媒体数据库: {media_db_path}')
        sys.exit(1)

    if target_uid:
        # 只转写指定联系人的语音
        import hashlib
        tbl = f'Msg_{hashlib.md5(target_uid.encode()).hexdigest()}'
        import glob
        voice_ids = set()
        for f in sorted(glob.glob(os.path.join(msg_dir, 'message_?.db'))):
            c = sqlite3.connect(f)
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if tbl in tables:
                for r in c.execute(f'SELECT server_id FROM [{tbl}] WHERE local_type=34').fetchall():
                    voice_ids.add(r[0])
            c.close()
        media_conn = sqlite3.connect(media_db_path)
        rows = []
        for vid in voice_ids:
            row = media_conn.execute(
                'SELECT svr_id, voice_data FROM VoiceInfo WHERE svr_id=?', [vid]).fetchone()
            if row and row[1]:
                rows.append(row)
        media_conn.close()
        print(f'联系人 {target_uid} 语音: {len(rows)} 条')
    else:
        # 转写全部
        media_conn = sqlite3.connect(media_db_path)
        rows = media_conn.execute('SELECT svr_id, voice_data FROM VoiceInfo').fetchall()
        media_conn.close()
        print(f'共找到 {len(rows)} 条语音')

    # 检查已有的转写
    if os.path.exists(audio2text_db_path):
        a2t_conn = sqlite3.connect(audio2text_db_path)
        existing = set(r[0] for r in a2t_conn.execute(
            'SELECT msgSvrId FROM Audio2Text').fetchall())
        a2t_conn.close()
    else:
        existing = set()

    todo = [(svr_id, data) for svr_id, data in rows if svr_id not in existing]
    print(f'已转写 {len(existing)} 条，待转写 {len(todo)} 条')

    if not todo:
        print('无需转写')
        return

    # 加载 Whisper 模型
    print('加载 Whisper 模型 (base)...')
    model = whisper.load_model('base')
    print('模型加载完成')

    # 准备 Audio2Text 数据库
    a2t_conn = sqlite3.connect(audio2text_db_path)
    a2t_conn.execute('''CREATE TABLE IF NOT EXISTS Audio2Text (
        ID INTEGER PRIMARY KEY,
        msgSvrId INTEGER UNIQUE,
        Text TEXT NOT NULL
    )''')
    a2t_conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_id ON Audio2Text (msgSvrId)')
    a2t_conn.commit()

    success = 0
    for i, (svr_id, silk_data) in enumerate(todo):
        try:
            audio_np = silk_to_audio(silk_data)
            result = model.transcribe(audio_np, language='zh', fp16=False)
            text = result['text'].strip()
            if text:
                a2t_conn.execute(
                    'INSERT OR IGNORE INTO Audio2Text (msgSvrId, Text) VALUES (?, ?)',
                    [svr_id, text])
                a2t_conn.commit()
                success += 1
            print(f'[{i+1}/{len(todo)}] {svr_id}: {text[:50]}')
        except Exception as e:
            print(f'[{i+1}/{len(todo)}] {svr_id}: 错误 - {e}')

    a2t_conn.close()
    print(f'\n转写完成: {success}/{len(todo)} 条成功')


if __name__ == '__main__':
    main()
