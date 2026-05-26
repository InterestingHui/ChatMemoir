import hmac
import os
import stat
import struct
from concurrent.futures import ProcessPoolExecutor

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512

# Constants
IV_SIZE = 16
HMAC_SHA256_SIZE = 64
KEY_SIZE = 32
AES_BLOCK_SIZE = 16
ROUND_COUNT = 256000
PAGE_SIZE = 4096
SALT_SIZE = 16
SQLITE_HEADER = b"SQLite format 3"


def decrypt_db_file_v4(pkey, in_db_path, out_db_path):
    if not os.path.exists(in_db_path):
        print(f"【!!!】{in_db_path} does not exist.")
        return False

    # 移除已有输出文件的只读属性，避免 PermissionError
    if os.path.exists(out_db_path):
        os.chmod(out_db_path, stat.S_IWRITE | stat.S_IREAD)

    success = False
    try:
        with open(in_db_path, 'rb') as f_in, open(out_db_path, 'wb') as f_out:
            # Read salt from the first SALT_SIZE bytes
            salt = f_in.read(SALT_SIZE)
            if not salt:
                print("File is empty or corrupted.")
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

            # Reserve space for IV_SIZE + HMAC_SHA256_SIZE, rounded to a multiple of AES_BLOCK_SIZE
            reserve = IV_SIZE + HMAC_SHA256_SIZE
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
                    print(f'Key error for {in_db_path}')
                    return False

                # AES-256-CBC decryption
                iv = page[end - reserve:end - reserve + IV_SIZE]
                cipher = AES.new(key, AES.MODE_CBC, iv)
                decrypted_data = cipher.decrypt(page[offset:end - reserve])

                # Write decrypted data and HMAC/IV to output
                f_out.write(decrypted_data)
                f_out.write(page[end - reserve:end])

                cur_page += 1

        print("Decryption completed.")
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


def decrypt_db_files(key, src_dir: str, dest_dir: str, key_map: dict = None, skip_existing: bool = True):
    """Decrypt all .db files under src_dir.
    key: default key (used if key_map doesn't cover a file)
    key_map: optional dict of relative_path -> enc_key_hex for per-database keys
    skip_existing: if True, skip files where dest already exists, src hasn't been modified,
                   and dest is not a corrupt stub (< PAGE_SIZE bytes)
    Returns: (total, failed) counts for caller diagnostics.
    """
    if not os.path.exists(src_dir):
        print(f"源文件夹 {src_dir} 不存在")
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
        print(f"跳过 {skipped} 个未变化的数据库文件")
    if not decrypt_tasks:
        print("所有数据库已是最新，无需重新解密")
        return skipped, 0
    with ProcessPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(decode_wrapper, decrypt_tasks))
    failed = sum(1 for r in results if r is not True)
    if failed:
        print(f"警告: {failed}/{len(results)} 个数据库解密失败")
    return len(results), failed
