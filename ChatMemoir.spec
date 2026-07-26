# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ChatMemoir GUI.

Build: pyinstaller ChatMemoir.spec --noconfirm
Output: dist/ChatMemoir/ChatMemoir.exe (onedir, fast startup)

Notes:
- onedir (not onefile): tkinter startup is ~3s vs ~10s for onefile, and
  PyInstaller handles complex deps (yara-python C ext, pymem, protobuf)
  more reliably in onedir mode.
- Excluded: data/ (chat exports), decrypted/ (decrypted DBs), wxid_*/
  (legacy), wechat-decrypt-tool/ (dead ylytdeng external tool),
  .planning/, doc/images/ (large, unused at runtime).
- UAC: a separate .manifest or rcedit step could embed requireAdministrator
  but we keep UAC out — user runs the exe as admin when decrypting.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# protobuf *_pb2.py files import google.protobuf — collect all submodules
hiddenimports = []
hiddenimports += collect_submodules('google.protobuf')
hiddenimports += collect_submodules('memoir.parser.util.protocbuf')
# yara-python and pymem have native exts; PyInstaller usually catches them
# but explicit hidden imports are cheap insurance.
hiddenimports += ['yara', 'pymem', 'pymem.process', 'psutil']
hiddenimports += ['win32api', 'win32com', 'win32com.client', 'winreg', 'pythoncom']
# pysilk-mod
hiddenimports += ['pysilk']
# Crypto (pycryptodome) — pull all submodules to be safe with PBKDF2 / HMAC
hiddenimports += collect_submodules('Crypto')
hiddenimports += collect_submodules('Crypto.Protocol')
hiddenimports += collect_submodules('Crypto.Hash')

# Data files that must be bundled next to the exe
datas = []
# ffmpeg.exe (audio transcoding for voice messages)
datas += [('scribe/ffmpeg.exe', 'scribe')]
datas += [('scribe/resources/ffmpeg.exe', 'scribe/resources')]
datas += [('scribe/resources/template.html', 'scribe/resources')]
# version_list.json (WeChat 3.x version detection)
datas += [('memoir/decrypt/version_list.json', 'memoir/decrypt')]
# All *_pb2.py files (protobuf compiled)
datas += collect_data_files('memoir.parser.util.protocbuf', include='*.py')
# wx_key.exe (external cache tool, invoked from GUI)
datas += [('tools/wx_key/wx_key.exe', 'tools/wx_key')]

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Skip dead/duplicated content to keep the build lean
        'wechat_decrypt_tool',
        'tests',
        'pytest',
        # AI sub-project — not part of the GUI
        'mind',
        'xiaoyiClaw',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ChatMemoir',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: add .ico when available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ChatMemoir',
)
