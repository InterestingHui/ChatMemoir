#!/usr/bin/env python3
"""Quick verification: scan D:\Weixin\<version>\Weixin.dll for the internal_db_key
pattern used by WeChat 4.1.10+ for V4 database key obfuscation.

Pattern source: LifeArchiveProject/WeChatDataAnalysis/dll_key_scan.py
4 consecutive `mov rdx, imm64` (opcode 0x48 0xBA + 8 bytes) followed by `test rax, rax`.
"""
import re
import sys
import pefile

DLL = sys.argv[1] if len(sys.argv) > 1 else '/mnt/d/Weixin/4.1.11.24/Weixin.dll'

PATTERN = re.compile(
    rb"^\x48\xBA(.{8})"
    rb".{3,8}?"
    rb"\x48\xBA(.{8})"
    rb".{3,8}?"
    rb"\x48\xBA(.{8})"
    rb".{3,8}?"
    rb"\x48\xBA(.{8})"
    rb".{3,8}?"
    rb"\x48\x85\xC0",
    re.DOTALL,
)

CODE_SECTION_CHARACTERISTIC = 0x20000000

pe = pefile.PE(DLL, fast_load=True)
image_base = int(pe.OPTIONAL_HEADER.ImageBase)
print(f"ImageBase: 0x{image_base:X}")
matches = []
for section in pe.sections:
    if not (int(section.Characteristics) & CODE_SECTION_CHARACTERISTIC):
        continue
    sec_name = section.Name.rstrip(b'\x00').decode('ascii', errors='replace')
    sec_size = int(section.SizeOfRawData)
    sec_file_offset = int(section.PointerToRawData)
    sec_va = image_base + int(section.VirtualAddress)
    print(f"Scanning section {sec_name}: VA=0x{sec_va:X} size={sec_size}")
    with open(DLL, 'rb') as f:
        f.seek(sec_file_offset)
        data = f.read(sec_size)
    offset = 0
    while True:
        idx = data.find(b"\x48\xBA", offset)
        if idx == -1:
            break
        m = PATTERN.match(data[idx:idx + 85])
        if m:
            key = m.group(1) + m.group(2) + m.group(3) + m.group(4)
            va = sec_va + idx
            file_off = sec_file_offset + idx
            spaced = " ".join(f"{b:02X}" for b in key)
            print(f"  MATCH VA=0x{va:X} file_off=0x{file_off:X}")
            print(f"    key_hex = {key.hex()}")
            print(f"    spaced  = {spaced}")
            matches.append((va, file_off, key))
            offset = idx + len(m.group(0))
        else:
            offset = idx + 1

print(f"\nTotal matches: {len(matches)}")
if matches:
    print("\nCandidate internal_db_key values (try each):")
    for i, (va, off, key) in enumerate(matches, 1):
        print(f"  [{i}] {key.hex()}")
