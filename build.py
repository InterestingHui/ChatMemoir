#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir Nuitka Build Script
将 Python 项目编译为独立 Windows EXE（Python → C → 机器码）

使用方法：
    python build.py

前置条件：
    1. Windows 10/11 + Python 3.10+
    2. pip install nuitka
    3. C 编译器：MSVC (Visual Studio Build Tools) 或 MinGW64
    4. pip install -r requirements.txt

编译产物在 dist/ 目录下，将整个 dist 文件夹打包为 ZIP 即可分发。
"""

import os
import shutil
import subprocess
import sys

# ── 配置 ────────────────────────────────────────────────────
APP_NAME = "ChatMemoir"
MAIN_SCRIPT = "gui.py"
VERSION = "3.0.0"
COMPANY_NAME = "ChatMemoir"
COPYRIGHT = "Copyright 2026 ChatMemoir. All rights reserved."

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(PROJECT_DIR, "build_nuitka")
DIST_DIR = os.path.join(PROJECT_DIR, "dist")

# 资源文件映射：源路径 → dist 内目标路径
DATA_FILES = [
    "scribe/resources/ffmpeg.exe",
    "scribe/resources/template.html",
    "scribe/resources/default_avatar.png",
    "memoir/decrypt/version_list.json",
]

DATA_DIRS = [
    "scribe/resources/emoji",
]

# protobuf 编译文件（Nuitka --follow-import-to 会自动处理 .py，
# 但 _pb2.py 有动态导入，显式包含更保险）
PB2_FILES = [
    f for f in os.listdir(os.path.join(PROJECT_DIR, "memoir/parser/util/protocbuf"))
    if f.endswith("_pb2.py")
]


def build_nuitka_command():
    cmd = [
        sys.executable, "-m", "nuitka",

        # 输出模式：onefile（单个 EXE，首次启动解压到临时目录，约 5-10 秒）
        "--onefile",

        # 输出目录和文件名
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={APP_NAME}.exe",

        # 防逆向：Nuitka 将 Python 编译为 C 再编译为机器码
        # 无法通过改后缀 .zip 解压获取源码
        "--remove-output",
        "--assume-yes-for-downloads",

        # 插件
        "--enable-plugin=tk-inter",
        "--enable-plugin=anti-bloat",

        # 性能
        "--lto=yes",
        "--jobs=0",

        # 递归编译业务代码
        "--follow-import-to=memoir",
        "--follow-import-to=scribe",

        # 排除不需要的模块
        "--nofollow-import-to=mind",
        "--nofollow-import-to=voice_to_text",
        "--nofollow-import-to=xiaoyiClaw",
        "--nofollow-import-to=whisper",
        "--nofollow-import-to=torch",
        "--nofollow-import-to=numba",
        "--nofollow-import-to=llvmlite",
        "--nofollow-import-to=mpmath",
        "--nofollow-import-to=sympy",
        "--nofollow-import-to=openai",

        # 原生 C 扩展：不要让 Nuitka 尝试重新编译，直接复制预编译的 .pyd
        # cryptography 甚至未使用（全部用 pycryptodome），但被 pip 传递依赖拉入
        "--nofollow-import-to=cryptography",
        "--nofollow-import-to=yara",
        "--nofollow-import-to=pymem",
        "--nofollow-import-to=lz4",
        "--nofollow-import-to=zstandard",
        "--nofollow-import-to=lxml",
        "--nofollow-import-to=PIL",

        "--noinclude-numba-mode=nofollow",
        "--module-parameter=torch-disable-jit=yes",

        # Windows 设置
        "--windows-console-mode=disable",
        "--windows-uac-admin",
        f"--windows-icon-from-ico={os.path.join(PROJECT_DIR, 'app_icon.ico')}",

        # 版本信息（Nuitka 4.x 无 --windows- 前缀）
        f"--product-name={APP_NAME}",
        f"--file-version={VERSION}",
        f"--product-version={VERSION}",
        f"--file-description=WeChat Chat History Export Tool",
        f"--company-name={COMPANY_NAME}",
        f"--copyright={COPYRIGHT}",
    ]

    # 嵌入资源文件
    for rel_path in DATA_FILES:
        src = os.path.join(PROJECT_DIR, rel_path)
        if os.path.exists(src):
            cmd.append(f"--include-data-file={src}={rel_path}")
        else:
            print(f"  WARNING: resource not found: {rel_path}")

    # 嵌入资源目录
    for rel_path in DATA_DIRS:
        src = os.path.join(PROJECT_DIR, rel_path)
        if os.path.exists(src):
            cmd.append(f"--include-data-dir={src}={rel_path}")
        else:
            print(f"  WARNING: resource dir not found: {rel_path}")

    # 主入口
    cmd.append(os.path.join(PROJECT_DIR, MAIN_SCRIPT))
    return cmd


def main():
    # 检查 Nuitka 是否安装
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True
        )
        print(f"Nuitka version: {result.stdout.strip()}")
    except Exception:
        print("ERROR: Nuitka not installed. Run: pip install nuitka")
        sys.exit(1)

    # 检查必要文件
    icon_path = os.path.join(PROJECT_DIR, "app_icon.ico")
    if not os.path.exists(icon_path):
        print(f"ERROR: app_icon.ico not found at {icon_path}")
        sys.exit(1)

    # 清理上次构建
    if os.path.exists(BUILD_DIR):
        print(f"Cleaning previous build: {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    # 执行编译
    cmd = build_nuitka_command()
    print("\n" + "=" * 60)
    print("Starting Nuitka compilation...")
    print("=" * 60)
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    if result.returncode != 0:
        print(f"\nERROR: Nuitka failed with return code {result.returncode}")
        sys.exit(result.returncode)

    # 复制到 dist 目录
    onefile_exe = os.path.join(BUILD_DIR, f"{APP_NAME}.exe")
    if not os.path.exists(onefile_exe):
        print(f"\nERROR: Build output not found at {onefile_exe}")
        sys.exit(1)

    os.makedirs(DIST_DIR, exist_ok=True)
    exe_path = os.path.join(DIST_DIR, f"{APP_NAME}.exe")
    if os.path.exists(exe_path):
        os.remove(exe_path)
    shutil.copy2(onefile_exe, exe_path)

    print("\n" + "=" * 60)
    print("Build successful!")
    print(f"  EXE: {exe_path}")
    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"  Size: {size_mb:.1f} MB")
    print("=" * 60)
    print(f"\nSingle file — copy ChatMemoir.exe anywhere and double-click to run.")
    print("First launch takes ~5-10 seconds to extract (subsequent launches use cache).")


if __name__ == "__main__":
    main()
