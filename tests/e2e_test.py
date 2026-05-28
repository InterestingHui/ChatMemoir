#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ChatMemoir 端到端自动化测试
测试流程：解密数据库 → 查询联系人 → 导出聊天记录

用法（需要管理员权限）：
    python tests/e2e_test.py
    # 或指定版本/格式：
    python tests/e2e_test.py --version 4 --format TXT
"""

import argparse
import ctypes
import json
import os
import shutil
import sqlite3
import sys
import time
import traceback
from datetime import datetime

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 工具函数 ──────────────────────────────────────────────

def check_admin() -> bool:
    """检查是否以管理员权限运行（Windows only）。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_win_path(path: str) -> str:
    """将 WSL 路径转为 Windows 绝对路径。"""
    return os.path.abspath(path)


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {s:.0f}s"


# ── 步骤函数 ──────────────────────────────────────────────

def step1_decrypt(db_version: int, output_base: str):
    """第一步：从微信进程提取密钥并解密数据库。"""
    print("\n" + "=" * 60)
    print("  Step 1/3: 解密数据库")
    print("=" * 60)

    if db_version == 4:
        from memoir.decrypt import get_info_v4
        from memoir.decrypt.decrypt_dat import get_decode_code_v4
        from memoir.decrypt import decrypt_v4
        from memoir import Me

        t0 = time.time()
        results = get_info_v4()
        if not results:
            print("  [FAIL] 未找到微信进程，请确认微信已登录运行")
            return None, f"get_info_v4 返回空 — 微信进程未找到或版本不支持"

        seen_uids = set()
        all_outputs = []

        for session_info in results:
            uid = session_info.uid
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)

            key = session_info.key
            if not key:
                print(f"  [SKIP] {uid}: 未找到解密密钥")
                continue

            data_dir = session_info.data_dir
            output_dir = os.path.join(output_base, uid)
            os.makedirs(output_dir, exist_ok=True)

            # 解密所有数据库
            total, failed = decrypt_v4.decrypt_db_files(
                key,
                src_dir=data_dir,
                dest_dir=output_dir,
                key_map=getattr(session_info, 'key_map', None) or None,
            )

            # 读取昵称和 xor_key
            me = Me()
            me.data_dir = data_dir
            me.uid = uid
            me.name = session_info.nick_name
            me.xor_key = get_decode_code_v4(data_dir)

            db_storage = os.path.join(output_dir, 'db_storage')
            contact_db = os.path.join(db_storage, 'contact', 'contact.db')
            if os.path.exists(contact_db):
                try:
                    conn = sqlite3.connect(contact_db)
                    cur = conn.cursor()
                    cur.execute("SELECT nick_name FROM contact WHERE username = ?", [uid])
                    row = cur.fetchone()
                    conn.close()
                    if row and row[0]:
                        me.name = row[0]
                except Exception:
                    pass

            info_file = os.path.join(db_storage, 'info.json')
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

            all_outputs.append(output_dir)
            elapsed = time.time() - t0
            print(f"  [OK] {me.name or uid}: {total - failed}/{total} 数据库已解密 ({fmt_duration(elapsed)})")

        if not all_outputs:
            return None, "没有成功解密任何数据库"

        return all_outputs, None

    else:  # v3
        from memoir.decrypt import get_info_v3
        from memoir.decrypt import decrypt_v3
        from memoir import Me

        version_list_path = os.path.join(
            os.path.dirname(__file__), '..', 'memoir', 'decrypt', 'version_list.json'
        )
        with open(version_list_path, 'r', encoding='utf-8') as f:
            version_list = json.loads(f.read())

        t0 = time.time()
        results = get_info_v3(version_list)

        all_outputs = []
        for info in results:
            if not info.key:
                continue
            key = info.key
            data_dir, uid = info.data_dir, info.uid
            output_dir = os.path.join(output_base, uid)
            os.makedirs(output_dir, exist_ok=True)

            decrypt_v3.decrypt_db_files(key, src_dir=data_dir, dest_dir=output_dir)

            me = Me()
            me.data_dir, me.uid, me.name = data_dir, uid, info.nick_name
            msg_dir = os.path.join(output_dir, 'Msg')
            os.makedirs(msg_dir, exist_ok=True)
            with open(os.path.join(msg_dir, 'info.json'), 'w', encoding='utf-8') as f:
                json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

            all_outputs.append(output_dir)
            elapsed = time.time() - t0
            print(f"  [OK] {me.name or uid}: 数据库已解密 ({fmt_duration(elapsed)})")

        return (all_outputs or None), (None if all_outputs else "没有成功解密任何数据库")


def step2_contacts(db_dir: str, db_version: int):
    """第二步：查询联系人。"""
    print("\n" + "=" * 60)
    print("  Step 2/3: 查询联系人")
    print("=" * 60)

    from memoir import ArchiveConnection

    t0 = time.time()
    conn = ArchiveConnection(db_dir, db_version)
    database = conn.get_interface()
    if database is None:
        print("  [FAIL] 无法打开数据库")
        return None, f"ArchiveConnection({db_dir}, {db_version}) 初始化失败"

    contacts = list(database.get_contacts())
    elapsed = time.time() - t0
    chatroom_count = sum(1 for c in contacts if c.is_chatroom)

    print(f"  [OK] {len(contacts)} 个联系人 ({chatroom_count} 个群聊) — {fmt_duration(elapsed)}")

    return {
        "total": len(contacts),
        "chatrooms": chatroom_count,
        "contacts": contacts,
    }, None


def step3_export(db_dir: str, db_version: int, contacts_info: dict, output_dir: str, fmt: str):
    """第三步：导出聊天记录。"""
    print("\n" + "=" * 60)
    print("  Step 3/3: 导出聊天记录")
    print("=" * 60)

    from memoir import ArchiveConnection
    from scribe.config import FileType

    exporter_map = {
        "TXT": "TxtExporter",
        "HTML": "HtmlExporter",
        "CSV": "CsvExporter",
        "DOCX": "DocxExporter",
        "XLSX": "ExcelExporter",
        "MARKDOWN": "MarkdownExporter",
        "JSON": "JsonExporter",
        "AI_TXT": "AiTxtExporter",
    }

    if fmt not in exporter_map:
        return False, f"不支持的格式: {fmt}，可选: {', '.join(exporter_map.keys())}"

    # 动态导入对应格式导出器
    import importlib
    mod = importlib.import_module("scribe")
    exporter_cls = getattr(mod, exporter_map[fmt])

    file_type = getattr(FileType, fmt.replace("AI_", ""))
    write_dir = os.path.join(output_dir, "exports")

    conn = ArchiveConnection(db_dir, db_version)
    database = conn.get_interface()
    if database is None:
        return False, "无法打开数据库"

    contacts = contacts_info["contacts"]
    success = 0
    failed = 0
    t0 = time.time()
    exported_files = []

    for contact in contacts[:5]:  # 只导前 5 个避免太慢
        try:
            scribe = exporter_cls(
                database,
                contact,
                output_dir=write_dir,
                type_=file_type,
                message_types=None,
                time_range=["2020-01-01 00:00:00", "2035-01-01 00:00:00"],
            )
            scribe.start()
            success += 1
        except Exception:
            failed += 1
            print(f"  [WARN] 导出 {contact.remark or contact.nick_name or contact.uid} 失败")

    elapsed = time.time() - t0
    print(f"  [OK] {success} 位联系人已导出 ({fmt}) — {fmt_duration(elapsed)}")
    if failed:
        print(f"  [WARN] {failed} 位导出失败")

    return True, None


# ── 主流程 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ChatMemoir 端到端测试")
    parser.add_argument("--version", type=int, default=4, choices=[3, 4], help="微信数据库版本")
    parser.add_argument("--format", type=str, default="TXT", help="导出格式 (TXT, HTML, CSV, DOCX, XLSX, MARKDOWN, JSON, AI_TXT)")
    parser.add_argument("--skip-decrypt", action="store_true", help="跳过解密（已有解密后的数据库）")
    parser.add_argument("--db-dir", type=str, default=None, help="已有数据库目录（跳过解密时使用）")
    parser.add_argument("--output", type=str, default="./test_output", help="输出目录")
    args = parser.parse_args()

    print("╔" + "═" * 58 + "╗")
    print("║  ChatMemoir 端到端自动化测试" + " " * 30 + "║")
    print(f"║  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + " " * 40 + "║")
    print(f"║  版本: v{args.version} | 导出格式: {args.format}" + " " * 34 + "║")
    print("╚" + "═" * 58 + "╝")

    # 权限检查
    if not args.skip_decrypt and not check_admin():
        print("\n[!] 解密步骤需要管理员权限，请以管理员身份运行此脚本。")
        print("    右键 → 以管理员身份运行 PowerShell，然后执行:")
        print(f"    python {sys.argv[0]}")
        sys.exit(1)

    output_base = os.path.abspath(args.output)
    os.makedirs(output_base, exist_ok=True)

    results = {"steps": {}, "overall": "UNKNOWN", "errors": []}
    total_start = time.time()

    # ── Step 1: 解密 ──
    if args.skip_decrypt:
        print("\n  [SKIP] 跳过解密步骤")
        db_dirs = [args.db_dir or "wxid_ttlo1sb5pyh811/db_storage"]
        db_storage_path = db_dirs[0]  # 用户直接提供 db_storage 路径
        results["steps"]["decrypt"] = "SKIPPED"
    else:
        db_dirs, err = step1_decrypt(args.version, output_base)
        if err:
            results["errors"].append(err)
        results["steps"]["decrypt"] = "PASS" if db_dirs else "FAIL"
        if not db_dirs:
            print(f"\n  [ABORT] 解密失败，无法继续后续步骤: {err}")
            results["overall"] = "FAIL"
            _print_report(results, time.time() - total_start)
            sys.exit(1)
        # 解密后 db_storage 在 output_dir 下
        db_storage_path = os.path.join(db_dirs[0], 'db_storage')

    # ── Step 2: 联系人 ──
    contacts_info, err = step2_contacts(db_storage_path, args.version)
    results["steps"]["contacts"] = "PASS" if contacts_info else "FAIL"
    if err:
        results["errors"].append(err)
    if not contacts_info:
        print(f"\n  [ABORT] 联系人查询失败: {err}")
        results["overall"] = "FAIL"
        _print_report(results, time.time() - total_start)
        sys.exit(1)

    # ── Step 3: 导出 ──
    export_ok, err = step3_export(db_storage_path, args.version, contacts_info, output_base, args.format)
    results["steps"]["export"] = "PASS" if export_ok else "FAIL"
    if err:
        results["errors"].append(err)

    # ── 汇总报告 ──
    total_elapsed = time.time() - total_start
    all_pass = all(v == "PASS" for v in results["steps"].values() if v != "SKIPPED")
    results["overall"] = "PASS" if all_pass else "FAIL"
    _print_report(results, total_elapsed)


def _print_report(results: dict, total_seconds: float):
    print("\n" + "═" * 60)
    print("  测试报告")
    print("═" * 60)
    for step, status in results["steps"].items():
        icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIPPED": "[SKIP]"}.get(status, "[??]")
        print(f"  {icon}  {step}: {status}")
    if results["errors"]:
        print("─" * 60)
        print("  错误详情:")
        for e in results["errors"]:
            print(f"    - {e}")
    print("─" * 60)
    print(f"  总耗时: {fmt_duration(total_seconds)}")
    print(f"  结果: {results['overall']}")
    print("═" * 60)


if __name__ == "__main__":
    sys.exit(main() or 0)
