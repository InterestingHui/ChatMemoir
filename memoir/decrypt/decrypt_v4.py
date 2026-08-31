import hmac
import os
import stat
import struct

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512

from memoir.log import logger

# Constants
IV_SIZE = 16
HMAC_SHA512_SIZE = 64
KEY_SIZE = 32
AES_BLOCK_SIZE = 16
ROUND_COUNT = 256000
PAGE_SIZE = 4096
SALT_SIZE = 16
SQLITE_HEADER = b"SQLite format 3"


def _sync_pages_incremental(pkey, in_db_path, out_db_path):
    """增量页同步：比对每页 80B IV+HMAC 尾巴，未变的页跳过。

    返回 True=同步完成 / False=密钥错误（保留 dst 旧快照）/ None=前置条件不满足
    （调用方落回全量重写）。异常不在此兜底 — 由调用方整体转全量路径。

    ponytail: 解密输出的每页尾巴与密文源逐字节相同（页 0 只把前 16B salt 换成
    SQLite 头，尾巴在 80B reserve 区原样拷贝），所以尾巴相同 ⇔ 该页密文未变 —
    免 AES、免 HMAC、免写入，只多花一次本地 dst 随机读。
    """
    src_size = os.path.getsize(in_db_path)
    if not os.path.exists(out_db_path):
        return None
    dst_size = os.path.getsize(out_db_path)
    # 页对齐 + 只增不减；否则交给全量路径按旧语义处理
    if (dst_size < PAGE_SIZE or dst_size % PAGE_SIZE
            or src_size % PAGE_SIZE or src_size < dst_size):
        return None

    # Reserve space for IV_SIZE + HMAC_SHA512_SIZE, rounded to a multiple of AES_BLOCK_SIZE
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE

    changed = 0
    # ponytail: 1MB 读缓冲 — 9p(/mnt/c) 上默认 8KB 缓冲的逐页读实测只有
    # ~10MB/s，1MB 块读 ~141MB/s；改缓冲不改语义
    with open(in_db_path, 'rb', buffering=1 << 20) as f_in, open(out_db_path, 'r+b') as f_out:
        salt = f_in.read(SALT_SIZE)
        if not salt:
            return None  # 空文件，落回全量路径报错

        mac_salt = bytes(x ^ 0x3a for x in salt)
        key = bytes.fromhex(pkey)
        mac_key = PBKDF2(key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)

        dst_page_count = dst_size // PAGE_SIZE
        cur_page = 0
        while True:
            # 与全量路径相同的顺序读法（9p 随机 seek 极慢，保持顺序流）
            if cur_page == 0:
                page = f_in.read(PAGE_SIZE - SALT_SIZE)
                if not page:
                    break
                page = salt + page
            else:
                page = f_in.read(PAGE_SIZE)
            if not page:
                break
            offset = SALT_SIZE if cur_page == 0 else 0
            end = len(page)

            # 已有页且尾巴相同 → 密文未变，跳过
            if cur_page < dst_page_count:
                f_out.seek(cur_page * PAGE_SIZE)
                dst_page = f_out.read(PAGE_SIZE)
                if dst_page[end - reserve:] == page[end - reserve:]:
                    cur_page += 1
                    continue

            # 全零页不加密、原样写回
            if all(x == 0 for x in page):
                f_out.seek(cur_page * PAGE_SIZE)
                f_out.write(page)
                changed += 1
                cur_page += 1
                continue

            # HMAC 校验：不通过即密钥错误 — dst 仍是旧的完整快照，直接返回
            mac = hmac.new(mac_key, page[offset:end - reserve + IV_SIZE], SHA512)
            mac.update(struct.pack('<I', cur_page + 1))
            hash_mac = mac.digest()
            hash_mac_start_offset = end - reserve + IV_SIZE
            if hash_mac != page[hash_mac_start_offset:hash_mac_start_offset + len(hash_mac)]:
                logger.info(f'Key error for {in_db_path}')
                return False

            iv = page[end - reserve:end - reserve + IV_SIZE]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted_data = cipher.decrypt(page[offset:end - reserve])

            f_out.seek(cur_page * PAGE_SIZE)
            if cur_page == 0:
                f_out.write(SQLITE_HEADER)
                f_out.write(b'\x00')
            f_out.write(decrypted_data)
            f_out.write(page[end - reserve:end])
            changed += 1
            cur_page += 1

        # 追加页时对齐最终大小；尺寸已一致时跳过 truncate，避免无谓触碰 mtime
        final_size = cur_page * PAGE_SIZE
        if final_size != dst_size:
            f_out.truncate(final_size)

    logger.info(f"增量页同步完成: {cur_page - changed}/{cur_page} 页未变。")
    return True


def decrypt_db_file_v4(pkey, in_db_path, out_db_path):
    if not os.path.exists(in_db_path):
        logger.info(f"【!!!】{in_db_path} does not exist.")
        return False

    # 移除已有输出文件的只读属性，避免 PermissionError
    if os.path.exists(out_db_path):
        os.chmod(out_db_path, stat.S_IWRITE | stat.S_IREAD)

    # 增量页同步优先：True/False 直接返回（False=密钥错误，保留 dst 旧快照）；
    # None（前置条件不满足）或任何异常 → 落回下面的全量重写
    try:
        result = _sync_pages_incremental(pkey, in_db_path, out_db_path)
    except Exception as e:
        logger.info(f"增量同步失败，转全量重写 {in_db_path}: {e!r}")
        result = None
    if result is not None:
        return result

    success = False
    try:
        with open(in_db_path, 'rb', buffering=1 << 20) as f_in, \
                open(out_db_path, 'wb', buffering=1 << 20) as f_out:
            # Read salt from the first SALT_SIZE bytes
            salt = f_in.read(SALT_SIZE)
            if not salt:
                logger.info("File is empty or corrupted.")
                return False

            mac_salt = bytes(x ^ 0x3a for x in salt)

            # Convert pkey from hex to bytes — this is the derived enc_key, not a passphrase
            key = bytes.fromhex(pkey)

            # key is already derived via PBKDF2 (cached by WCDB in memory) — use directly.
            # Only derive mac_key with 2-iteration PBKDF2.
            mac_key = PBKDF2(key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)

            # Write SQLITE_HEADER to the output file
            f_out.write(SQLITE_HEADER)
            f_out.write(b'\x00')

            # Reserve space for IV_SIZE + HMAC_SHA512_SIZE, rounded to a multiple of AES_BLOCK_SIZE
            reserve = IV_SIZE + HMAC_SHA512_SIZE
            reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE

            # Process each page
            cur_page = 0
            while True:

                # For the first page, include SALT_SIZE adjustment
                if cur_page == 0:
                    # Read one full PAGE_SIZE starting from after the salt
                    page = f_in.read(PAGE_SIZE - SALT_SIZE)
                    if not page:
                        break  # No more data
                    page = salt + page  # Include the salt in the first page data
                else:
                    page = f_in.read(PAGE_SIZE)
                if not page:
                    break  # End of file
                # print(f'第{cur_page + 1}页')
                offset = SALT_SIZE if cur_page == 0 else 0
                end = len(page)

                # If the page is all zero bytes, write it as-is and continue
                # (zero pages are normal free/unused pages in SQLite)
                if all(x == 0 for x in page):
                    f_out.write(page)
                    cur_page += 1
                    continue

                # Perform HMAC check
                mac = hmac.new(mac_key, page[offset:end - reserve + IV_SIZE], SHA512)
                mac.update(struct.pack('<I', cur_page + 1))  # Add page number
                hash_mac = mac.digest()

                # Check if HMAC matches
                hash_mac_start_offset = end - reserve + IV_SIZE
                if hash_mac != page[hash_mac_start_offset:hash_mac_start_offset + len(hash_mac)]:
                    logger.info(f'Key error for {in_db_path}')
                    return False

                # AES-256-CBC decryption
                iv = page[end - reserve:end - reserve + IV_SIZE]
                cipher = AES.new(key, AES.MODE_CBC, iv)
                decrypted_data = cipher.decrypt(page[offset:end - reserve])

                # Write decrypted data and HMAC/IV to output
                f_out.write(decrypted_data)
                f_out.write(page[end - reserve:end])

                cur_page += 1

        logger.info("Decryption completed.")
        success = True
        return True
    finally:
        if not success and os.path.exists(out_db_path):
            try:
                os.remove(out_db_path)
            except OSError:
                pass


def decode_wrapper(tasks):
    """用于包装解码函数的顶层定义"""
    return decrypt_db_file_v4(*tasks)


def decrypt_db_files(key, src_dir: str, dest_dir: str, key_map: dict = None,
                     skip_existing: bool = True, progress_callback=None):
    """Decrypt all .db files under src_dir.
    key: default key (used if key_map doesn't cover a file)
    key_map: optional dict of relative_path -> enc_key_hex for per-database keys
    skip_existing: if True, skip files where dest already exists, src hasn't been modified,
                   and dest is not a corrupt stub (< PAGE_SIZE bytes)
    progress_callback: optional callable(current, total, filename) called per file
    Returns: (total, failed) counts for caller diagnostics.
    """
    if not os.path.exists(src_dir):
        logger.info(f"源文件夹 {src_dir} 不存在")
        return 0, 0

    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

    # Collect unique keys to try for fallback
    all_keys = set()
    if key_map:
        all_keys = set(key_map.values())
    if key:
        all_keys.add(key)

    skipped = 0
    decrypt_tasks = []
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if file.endswith(".db"):
                src_file_path = os.path.join(root, file)
                src_size = os.path.getsize(src_file_path)
                if src_size < PAGE_SIZE:
                    continue

                relative_path = os.path.relpath(root, src_dir)
                dest_sub_dir = os.path.join(dest_dir, relative_path)
                dest_file_path = os.path.join(dest_sub_dir, file)

                if not os.path.exists(dest_sub_dir):
                    os.makedirs(dest_sub_dir)

                # 增量解密：跳过源文件未变化的已解密数据库
                # 但如果目标文件小于一页（说明上次解密失败），强制重新解密
                if skip_existing and os.path.exists(dest_file_path):
                    dst_size = os.path.getsize(dest_file_path)
                    if dst_size < PAGE_SIZE:
                        pass  # corrupt stub, re-decrypt
                    else:
                        src_mtime = os.path.getmtime(src_file_path)
                        dst_mtime = os.path.getmtime(dest_file_path)
                        if src_mtime <= dst_mtime:
                            skipped += 1
                            continue

                print(dest_file_path)

                # Look up per-database key from key_map
                db_rel = os.path.join(relative_path, file)
                if key_map and db_rel in key_map:
                    db_key = key_map[db_rel]
                else:
                    db_key = key
                decrypt_tasks.append((db_key, src_file_path, dest_file_path))
    if skipped:
        logger.info(f"跳过 {skipped} 个未变化的数据库文件")
    if not decrypt_tasks:
        logger.info("所有数据库已是最新，无需重新解密")
        return skipped, 0

    total = len(decrypt_tasks)
    if progress_callback:
        progress_callback(0, total, "")

    # ponytail: sequential loop, not ProcessPoolExecutor. The pool spawned 16
    # pythonw children from a UNC-launched pythonw parent; on Windows + WSL
    # the workers re-import __main__ (gui.py) and the parent process died
    # silently mid-decrypt. 26 small DBs at ~1-2s each is fast enough; the
    # pool's parallelism wasn't worth the fragility.
    completed = 0
    failed = 0
    for db_key, src_file_path, dest_file_path in decrypt_tasks:
        # ponytail: 撕裂读防护 — 微信边写边读时顺序扫页可能抓到两个事务状态的
        # 混合，产出 malformed 库。前后各 stat 一次，src 在解密期间被写过就重试
        # 一次；还在写就接受结果并告警（下次刷新自愈）。stat 判据零成本。
        for attempt in (1, 2):
            try:
                _st = os.stat(src_file_path)
                before = (_st.st_mtime, _st.st_size)
                result = decode_wrapper((db_key, src_file_path, dest_file_path))
            except Exception as e:
                logger.info(f"解密异常 {os.path.basename(dest_file_path)}: {e!r}")
                result = False
                break
            try:
                _st = os.stat(src_file_path)
                after = (_st.st_mtime, _st.st_size)
            except OSError:
                break  # src 没了，结果作数与否由 result 决定
            if result is not True or before == after:
                break
            if attempt == 1:
                logger.info(f"{os.path.basename(src_file_path)} 在解密期间被微信写入，重试以防撕裂读")
            else:
                logger.info(f"警告: {os.path.basename(src_file_path)} 解密期间持续被写入，结果可能不完整，下次刷新自愈")
        completed += 1
        if result is not True:
            failed += 1
        if progress_callback:
            progress_callback(completed, total, os.path.basename(dest_file_path))

    if failed:
        logger.info(f"警告: {failed}/{total} 个数据库解密失败")
    return total, failed
