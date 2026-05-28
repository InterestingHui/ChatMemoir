import logging
import os
import sys
import time
import traceback
from functools import wraps

# 日志目录：frozen 模式使用 %APPDATA% 可写目录
if getattr(sys, 'frozen', False):
    _log_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ChatMemoir', 'logs')
else:
    _log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(_log_dir, exist_ok=True)

filename = time.strftime("%Y-%m-%d", time.localtime(time.time()))
logger = logging.getLogger('test')
logger.setLevel(level=logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s')
file_handler = logging.FileHandler(os.path.join(_log_dir, f'{filename}-log.log'), encoding='utf-8')

file_handler.setLevel(level=logging.INFO)
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def log(func):
    @wraps(func)
    def log_(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(
                f"\n{func.__qualname__} is error,params:{(args, kwargs)},here are details:\n{traceback.format_exc()}")
    return log_
