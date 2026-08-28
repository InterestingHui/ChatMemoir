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
import os as _os
import sys as _sys

block_cipher = None

# ponytail: PyInstaller 6.21's tkinter hook sometimes misses the Tcl/Tk data
# files (especially when run via pythonw.exe + admin task), leaving the exe
# to crash at Tk() creation: "Can't find a usable init.tcl". Pull them
# explicitly from the Python install's tcl/ directory.
_tcl_lib = _os.path.join(_sys.base_prefix, 'tcl', 'tcl8.6')
_tk_lib = _os.path.join(_sys.base_prefix, 'tcl', 'tk8.6')
_extra_datas = []
if _os.path.isdir(_tcl_lib):
    _extra_datas.append((_tcl_lib, '_internal/_tcl_data'))
if _os.path.isdir(_tk_lib):
    _extra_datas.append((_tk_lib, '_internal/_tk_data'))

# protobuf *_pb2.py files import google.protobuf — collect all submodules
hiddenimports = []
hiddenimports += collect_submodules('google.protobuf')
hiddenimports += collect_submodules('memoir.parser.util.protocbuf')
# yara-python and pymem have native exts; PyInstaller usually catches them
# but explicit hidden imports are cheap insurance.
hiddenimports += ['yara', 'pymem', 'pymem.process', 'psutil']
hiddenimports += ['win32api', 'win32com', 'win32com.client', 'winreg', 'pythoncom']
# ponytail: socket family — observed missing in a 6.21 onedir build
# (ModuleNotFoundError: No module named '_socket' from inside
# pyi_rth_multiprocessing during boot). Force-include to be safe.
hiddenimports += ['_socket', 'socket', '_ssl', '_hashlib', 'select', '_multiprocessing']
# pysilk-mod
hiddenimports += ['pysilk']
# Crypto (pycryptodome) — pull all submodules to be safe with PBKDF2 / HMAC
hiddenimports += collect_submodules('Crypto')
hiddenimports += collect_submodules('Crypto.Protocol')
hiddenimports += collect_submodules('Crypto.Hash')
# pypinyin — 词库模块按需延迟导入，全部收进包（gui 联系人拼音检索用）
hiddenimports += collect_submodules('pypinyin')

# Data files that must be bundled next to the exe
datas = list(_extra_datas)
# ffmpeg.exe (audio transcoding for voice messages)
datas += [('scribe/ffmpeg.exe', 'scribe')]
datas += [('scribe/resources/ffmpeg.exe', 'scribe/resources')]
datas += [('scribe/resources/template.html', 'scribe/resources')]
# version_list.json (WeChat 3.x version detection)
datas += [('memoir/decrypt/version_list.json', 'memoir/decrypt')]
# All *_pb2.py files (protobuf compiled) — PyInstaller may treat them as
# data rather than code (they're imported dynamically), so list them
# explicitly as data files going to the right package dir.
import glob as _glob
_pb2_dir = 'memoir/parser/util/protocbuf'
for _pb2 in _glob.glob(_pb2_dir + '/*_pb2.py'):
    datas += [(_pb2, 'memoir/parser/util/protocbuf')]
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
        # ponytail: heavy deps only used by mind/ (Qwen model). Cutting them
        # shrinks dist from 666MB → ~200MB and removes hundreds of binary
        # files that bloat install/copy time. If mind/ is ever wired into
        # the GUI, drop these excludes.
        'torch', 'torchvision', 'torchaudio',
        'numba', 'llvmlite',
        'numpy', 'pandas', 'matplotlib',
        'scipy', 'sklearn', 'skimage',
        'transformers', 'tokenizers', 'safetensors', 'huggingface_hub',
        'dashinfer',
        'tqdm', 'sympy', 'networkx', 'jinjia2',
        'PIL.ImageQt',  # Qt binding not used; PIL itself stays
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
    console=True,  # ponytail: console=False triggers _tkinter DLL load failure in PyInstaller 6.21 admin build; keep console for now (GUI still works, just with a console window beside it)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',  # ponytail: project-bundled .ico
    uac_admin=True,  # ponytail: exe double-click triggers UAC prompt — OpenProcess(Weixin.exe) needs admin
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
