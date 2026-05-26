# -*- coding: utf-8 -*-
"""
@File    : __init__.py.py
@Author  : Shuaikang Zhou
@Time    : 2023/1/5 0:10
@IDE     : Pycharm
@Version : Python3.10
@comment : ···
"""
from .log import logger
from .model import Me, MessageType, Message, Person, Contact, TextMessage, ImageMessage
from .db_main import ArchiveInterface
from .manager_v4 import ArchiveV4
from .manager_v3 import ArchiveV3

__version__ = '3.0.0'


class ArchiveConnection:
    def __init__(self, db_dir, db_version=4):
        self.db_dir = db_dir
        self.db_version = db_version
        self.database_interface = self._initialize_database()

    def _initialize_database(self) -> ArchiveInterface:
        if self.db_version == 4:
            database0 = ArchiveV4()
        else:
            database0 = ArchiveV3()
        if database0.init_database(self.db_dir):
            return database0
        else:
            logger.error(f'数据库初始化失败, 请检查路径或数据库版本是否正确, db_dir:{self.db_dir},db_version:{self.db_version}')
            return None

    def get_interface(self) -> ArchiveInterface:
        return self._initialize_database()


"""
使用示例：
conn = ArchiveConnection(USER_DB_DIR, 4)
database: ArchiveInterface = conn.get_interface()
"""
