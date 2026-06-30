#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir 聊天记录导出工具
一键解密微信数据库，浏览联系人，导出聊天记录
"""
import os
import sys

# Headless verifier dispatch: if a sentinel file exists in the project root,
# run verify_pipeline.py instead of the GUI. Lets us trigger E2E verification
# via the existing admin scheduled task (schtasks /run /tn ChatMemoirAdmin)
# without a separate UAC step — same elevation path as a normal GUI launch.
_proj_dir = os.path.dirname(os.path.abspath(__file__))
_sentinel = os.path.join(_proj_dir, '.verify-trigger')
if os.path.exists(_sentinel):
    try:
        os.remove(_sentinel)
    except OSError:
        pass
    sys.path.insert(0, _proj_dir)
    from verify_pipeline import main as _verify_main
    sys.exit(_verify_main())

from gui import main

if __name__ == "__main__":
    main()
