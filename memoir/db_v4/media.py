#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2024/12/12 17:06 
@Author      : SiYuan 
@Email       : 863909694@qq.com 
@File        : MemoTrace-media.py 
@Description : 
"""
import os
import shutil
import subprocess
import sys
import traceback

from memoir.merge import increase_update_data, increase_data
from memoir.model import ArchiveBase
from memoir.log import logger


def get_ffmpeg_path():
    from scribe.exporter_base import get_ffmpeg_path as _get_ffmpeg_path
    return _get_ffmpeg_path()


class MediaDB(ArchiveBase):
    def get_media_buffer(self, server_id) -> bytes:
        sql = '''
        select voice_data
        from VoiceInfo
        where svr_id = ?
        '''
        if not self.DB:
            return b''
        for db in self.DB:
            cursor = db.cursor()
            cursor.execute(sql, [server_id])
            result = cursor.fetchone()
            if result:
                return result[0]
        return b''

    def get_audio_path(self, server_id, output_dir, filename=''):
        if filename:
            return f'{output_dir}/{filename}.mp3'
        else:
            return f'{output_dir}/{server_id}.mp3'

    def get_audio(self, server_id, output_dir, filename=''):
        if not filename:
            filename = server_id
        silk_path = f"{output_dir}/{filename}.silk"
        pcm_path = f"{output_dir}/{filename}.pcm"
        mp3_path = f"{output_dir}/{filename}.mp3"
        if os.path.exists(mp3_path):
            return mp3_path
        buf = self.get_media_buffer(server_id)
        if not buf:
            return ''
        with open(silk_path, "wb") as f:
            f.write(buf)
        # open(silk_path, "wb").write()
        try:
            decode(silk_path, pcm_path, 44100)
            # 调用系统上的 ffmpeg 可执行文件
            # 获取 FFmpeg 可执行文件的路径
            ffmpeg_path = get_ffmpeg_path()
            if not os.path.exists(ffmpeg_path):
                ffmpeg_path = os.path.join(os.getcwd(), 'app', 'resources', 'data', 'ffmpeg.exe')
            ffmpeg_args = [ffmpeg_path, '-loglevel', 'quiet', '-y', '-f', 's16le', '-i', pcm_path, '-ar', '44100', '-ac', '1', mp3_path]
            subprocess.run(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(silk_path):
                os.remove(silk_path)
            if os.path.exists(pcm_path):
                os.remove(pcm_path)
        except Exception as e:
            logger.error(f'语音错误\n{traceback.format_exc()}')
            ffmpeg_path = os.path.join(os.getcwd(), 'app', 'resources', 'data', 'ffmpeg.exe')
            ffmpeg_args = [ffmpeg_path, '-loglevel', 'quiet', '-y', '-f', 's16le', '-i', pcm_path, '-ar', '44100', '-ac', '1', mp3_path]
            subprocess.run(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finally:
            return mp3_path

    def merge(self, db_path):
        # todo 判断数据库对应情况
        if not (os.path.exists(db_path) or os.path.isfile(db_path)):
            print(f'{db_path} 不存在')
            return
        if not self.DB:
            shutil.copy(db_path,os.path.join(self.db_dir,self.db_file_name))
        else:
            for db in self.DB:
                cursor = db.cursor()
                try:
                    # 获取列名
                    increase_data(db_path, cursor, db, 'VoiceInfo', 'svr_id')
                    increase_data(db_path, cursor, db, 'Name2Id', 'user_name')
                    increase_update_data(db_path, cursor, db, 'Timestamp', 'timestamp')
                except Exception:
                    print(f"数据库操作错误: {traceback.format_exc()}")
                    db.rollback()


if __name__ == '__main__':
    pass
