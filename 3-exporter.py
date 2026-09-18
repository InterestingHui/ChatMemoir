#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/3/11 20:50 
@Author      : SiYuan 
@Email       : 863909694@qq.com 
@File        : memoir-3-scribe.py
@Description : 
"""

import sys
import time
from multiprocessing import freeze_support

from scribe.config import FileType
from scribe import HtmlExporter, TxtExporter, AiTxtExporter, DocxExporter, MarkdownExporter, ExcelExporter
from memoir import ArchiveConnection, MessageType


def export():
    st = time.time()

    # ponytail: db_dir and target uid from argv so the script works for any
    # decrypted account. Defaults preserve old behavior.
    db_dir = sys.argv[1] if len(sys.argv) > 1 else 'decrypted/wxid_ka89oj7i1mz622/db_storage'
    uid = sys.argv[2] if len(sys.argv) > 2 else None  # required: target friend wxid
    db_version = 4
    output_dir = './data/'  # 输出文件夹

    conn = ArchiveConnection(db_dir, db_version)  # 创建数据库连接
    database = conn.get_interface()  # 获取数据库接口

    if not uid:
        # No uid specified — list contacts so the user can pick one next run.
        print('No uid specified. Available contacts (first 20):')
        for i, c in enumerate(database.get_contacts()):
            if i >= 20:
                print('... (truncated, pass uid as argv[2])')
                break
            print(f'  {c.uid}\t{c.nickname}')
        return
    contact = database.get_contact_by_username(uid)  # 查找某个联系人

    conn = ArchiveConnection(db_dir, db_version)  # 创建数据库连接
    database = conn.get_interface()  # 获取数据库接口

    contact = database.get_contact_by_username(uid)  # 查找某个联系人
    scribe = TxtExporter(
        database,
        contact,
        output_dir=output_dir,
        type_=FileType.TXT,
        message_types=None,  # 要导出的消息类型，默认全导出
        time_range=['2020-01-01 00:00:00', '2035-03-12 00:00:00'],  # 要导出的日期范围，默认全导出
        group_members=None  # 指定导出群聊里某个或者几个群成员的聊天记录
    )

    scribe.start()
    et = time.time()
    print(f'耗时：{et - st:.2f}s')


def batch_export():
    """
    批量导出HTML
    :return:
    """
    st = time.time()

    # argv layout: [prog, 'batch', <db_dir?>]; 'batch' is the mode selector.
    db_dir = sys.argv[2] if len(sys.argv) > 2 else 'decrypted/wxid_ka89oj7i1mz622/db_storage'
    db_version = 4  # 数据库版本，4 or 3
    output_dir = './data/'  # 输出文件夹

    conn = ArchiveConnection(db_dir, db_version)  # 创建数据库连接
    database = conn.get_interface()  # 获取数据库接口

    contacts = database.get_contacts()  # 查找某个联系人

    # 语音转文字：尽力回填（读已有 Audio2Text.db 缓存；更多转写请单独跑
    # voice2text_batch.py）。失败不阻塞导出。
    import os as _os
    try:
        from voice2text_batch import run as _v2t_run
        import argparse as _argparse
        _v2t_args = _argparse.Namespace(
            uid=None, model='small', limit=0,
            jsonl=_os.path.join(output_dir, 'voice_ledger.jsonl'),
            db=_os.path.join(db_dir, 'Audio2Text.db'),
            db_dir=db_dir, smoke=False)
        _v2t_run(_v2t_args)
    except Exception as _e:
        print(f'[voice2text] 回填跳过: {_e}')

    for contact in contacts:
        scribe = HtmlExporter(
            database,
            contact,
            output_dir=output_dir,
            type_=FileType.HTML,
            message_types=None,  # 要导出的消息类型，None=全部（含语音/视频/文件）
            time_range=['2020-01-01 00:00:00', '2035-03-12 00:00:00'],  # 要导出的日期范围，默认全导出
            group_members=None  # 指定导出群聊里某个或者几个群成员的聊天记录
        )

        scribe.start()
    et = time.time()
    print(f'耗时：{et - st:.2f}s')


def batch_export_by_fmt():
    """
    批量导出多种格式
    :return:
    """
    st = time.time()

    db_dir = 'wxid_ttlo1sb5pyh811/db_storage'  # 解析后的数据库路径，例如：./db_storage
    db_version = 4  # 数据库版本，4 or 3

    uid = 'wxid_034440iur9f312'  # 要导出好友的wxid
    output_dir = './data/'  # 输出文件夹

    conn = ArchiveConnection(db_dir, db_version)  # 创建数据库连接
    database = conn.get_interface()  # 获取数据库接口

    contact = database.get_contact_by_username(uid)  # 查找某个联系人
    scribes = {
        FileType.HTML: HtmlExporter,
        FileType.TXT: TxtExporter,
        FileType.AI_TXT: AiTxtExporter,
        FileType.MARKDOWN: MarkdownExporter,
        FileType.XLSX: ExcelExporter,
        FileType.DOCX: DocxExporter
    }
    for file_type, scribe in scribes.items():
        execute = scribe(
            database,
            contact,
            output_dir=output_dir,
            type_=file_type,
            message_types=None,  # 要导出的消息类型，默认全导出
            time_range=['2020-01-01 00:00:00', '2035-03-12 00:00:00'],  # 要导出的日期范围，默认全导出
            group_members=None  # 指定导出群聊里某个或者几个群成员的聊天记录
        )

        execute.start()
    et = time.time()
    print(f'耗时：{et - st:.2f}s')


if __name__ == '__main__':
    freeze_support()
    # Default: export single friend (uid from argv[2], or list contacts if absent).
    # Use 'batch' as argv[1] to batch-export all contacts as HTML.
    if len(sys.argv) > 1 and sys.argv[1] == 'batch':
        batch_export()
    else:
        export()
