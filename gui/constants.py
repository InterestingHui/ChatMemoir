#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import sys

# 配置文件路径（frozen 模式使用 %APPDATA% 可写目录）
if getattr(sys, 'frozen', False):
    _CONFIG_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ChatMemoir')
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, '.gui_config.json')
else:
    _CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.gui_config.json')


def _resource_path(relative_path):
    """获取资源绝对路径，兼容开发模式和 Nuitka onefile 模式"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def _load_config():
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    try:
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 配色 ──────────────────────────────────────────────────

PRIMARY = "#07C160"
PRIMARY_HOVER = "#06AD56"
BG = "#F0F2F5"
CARD_BG = "#FFFFFF"
TEXT_PRIMARY = "#191919"
TEXT_SECONDARY = "#8E8E93"
BORDER = "#E5E5EA"
DANGER = "#FA5151"
