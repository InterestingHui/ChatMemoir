#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/3/11 20:27
@Author      : SiYuan
@Email       : 863909694@qq.com
@File        : memoir-1-decrypt.py
@Description :
"""

import json
import os
import sqlite3
from multiprocessing import freeze_support

from memoir import Me
from memoir.decrypt import get_info_v4, get_info_v3
from memoir.decrypt.decrypt_dat import get_decode_code_v4
from memoir.decrypt import decrypt_v4, decrypt_v3


def dump_v3():
    """
    解析微信3.x版本的数据库
    """
    version_list_path = '../memoir/decrypt/version_list.json'
    with open(version_list_path, "r", encoding="utf-8") as f:
        version_list = json.loads(f.read())
    r_3 = get_info_v3(version_list)  # 微信3.x
    for session_info in r_3:
        print(session_info)
        me = Me()
        me.data_dir = session_info.data_dir
        me.uid = session_info.uid
        me.name = session_info.nick_name
        info_data = me.to_json()
        output_dir = session_info.uid
        key = session_info.key
        if not key:
            print('error! 未找到key，请重启微信后再试')
            continue
        data_dir = session_info.data_dir
        decrypt_v3.decrypt_db_files(key, src_dir=data_dir, dest_dir=output_dir)
        # 导出的数据库在 output_dir/Msg 文件夹下，后面会用到
        with open(os.path.join(output_dir, 'Msg', 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_data, f, ensure_ascii=False, indent=4)
        print(f'数据库解析成功，在{os.path.join(output_dir, "Msg")}路径下')


def dump_v4():
    """
    解析微信4.0版本的数据库
    """
    r_4 = get_info_v4()  # 微信4.0
    for session_info in r_4:
        print(session_info)
        me = Me()
        me.data_dir = session_info.data_dir
        me.uid = session_info.uid
        me.name = session_info.nick_name
        me.xor_key = get_decode_code_v4(session_info.data_dir)
        output_dir = session_info.uid  # 数据库输出文件夹
        key = session_info.key
        if not key:
            print('error! 未找到key，请重启微信后再试')
            continue
        data_dir = session_info.data_dir
        total, failed = decrypt_v4.decrypt_db_files(key, src_dir=data_dir, dest_dir=output_dir,
                                    key_map=session_info.key_map if session_info.key_map else None)
        if failed:
            print(f'[!] {failed}/{total} 个数据库解密失败')
        # 从解密后的 contact.db 读取昵称（替代内存扫描，per D-01）
        db_path = os.path.join(output_dir, 'db_storage', 'contact', 'contact.db')
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute('SELECT nick_name FROM contact WHERE username = ?', [me.uid])
                row = cursor.fetchone()
                conn.close()
                if row and row[0]:
                    me.name = row[0]
                    print(f'[*] 从数据库读取昵称: {me.name}')
                else:
                    print(f'[!] 未在 contact 表中找到 uid={me.uid} 的昵称')
            except Exception as e:
                print(f'[!] 查询昵称失败: {e}')
        else:
            print(f'[!] 未找到解密后的 contact.db: {db_path}')
        info_data = me.to_json()
        # 导出的数据库在 output_dir/db_storage 文件夹下，后面会用到
        with open(os.path.join(output_dir, 'db_storage', 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_data, f, ensure_ascii=False, indent=4)
        print(f'数据库解析成功，在{os.path.join(output_dir, "Msg")}路径下')


if __name__ == '__main__':
    freeze_support()  # 使用多进程必须
    dump_v4() # 微信4.0
    # print(3)
