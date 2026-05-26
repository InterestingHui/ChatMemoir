#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@Time        : 2025/3/11 20:46 
@Author      : SiYuan 
@Email       : 863909694@qq.com 
@File        : memoir-2-contact.py 
@Description : 
"""
import time

from memoir import ArchiveConnection

db_dir = 'wxid_ttlo1sb5pyh811/db_storage'  # 第一步解析后的数据库路径，例如：./wxid_xxxx/db_storage
db_version = 4  # 数据库版本，4 or 3

conn = ArchiveConnection(db_dir, db_version)  # 创建数据库连接
database = conn.get_interface()  # 获取数据库接口

st = time.time()
cnt = 0
contacts = database.get_contacts()
for contact in contacts:
    print(contact)
    contact.small_head_img_blog = database.get_avatar_buffer(contact.uid)
    cnt += 1
    if contact.is_chatroom:
        print('*' * 80)
        print(contact)
        chatroom_members = database.get_chatroom_members(contact.uid)
        print(contact.uid, '群成员个数：', len(chatroom_members))
        for uid, chatroom_member in chatroom_members.items():
            chatroom_member.small_head_img_blog = database.get_avatar_buffer(uid)
            print(chatroom_member)
            cnt += 1

et = time.time()

print(f'联系人个数：{cnt} 耗时：{et - st:.2f}s')
