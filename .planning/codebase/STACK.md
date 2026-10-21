# Technology Stack

**Analysis Date:** 2026-04-23

## Languages

**Primary:**
- Python 3.10+ (header comment in `wxManager/__init__.py` specifies `Python3.10`; type union syntax `str | bytes` used throughout, requiring 3.10+)
- Used for all core modules: `wxManager/`, `exporter/`, `MemoAI/`, and entry-point scripts

**Secondary:**
- Protocol Buffers (`.proto` files in `wxManager/parser/util/protocbuf/`) - compiled to Python (`*_pb2.py`)
- YAML (GitHub Actions workflow in `.github/workflows/sync.yml`)
- HTML/CSS/JS (export template in `exporter/resources/template.html`)
- JSON (configuration files, version lists, training data)

## Runtime

**Environment:**
- Windows only (critical dependency - uses `ctypes.windll`, `win32api`, `winreg`, `win32com`, `pymem` for process memory inspection of WeChat/Weixin.exe)
- Python 3.10+

**Package Manager:**
- pip
- Requirements file: `requirements.txt` at project root
- Secondary requirements: `MemoAI/qwen2-0.5b/requirements.txt` (AI sub-project)
- No lockfile present (no `pip freeze` output or `Pipfile.lock`)

## Frameworks

**Core (none - this is a library/CLI tool):**
- No web framework in the main project
- Pure Python standard library + third-party packages
- Abstract base class pattern for database interface (`wxManager/db_main.py`)

**AI Sub-project (MemoAI):**
- FastAPI + Uvicorn - OpenAI-compatible API server (`MemoAI/api_server.py`)
- Gradio - UI for Qwen model inference (`MemoAI/qwen2-0.5b/app.py`)
- PyTorch + Transformers (HuggingFace) - Model loading and inference
- DashInfer - Alternative inference engine for Qwen 2.0

## Key Dependencies

**Database:**
- `sqlite3` (stdlib) - All database access uses Python's built-in sqlite3 module directly. No ORM. Raw SQL queries via cursors. Files: `wxManager/model/db_model.py`, `wxManager/merge.py`, all `wxManager/db_v3/*.py` and `wxManager/db_v4/*.py`

**Encryption & Crypto:**
- `pycryptodome` (Crypto) - AES-CBC decryption of WeChat database files. Files: `wxManager/decrypt/decrypt_v3.py`, `wxManager/decrypt/decrypt_v4.py`, `wxManager/decrypt/decrypt_dat.py`
- `cryptography` - Additional crypto operations
- `Crypto.Protocol.KDF.PBKDF2` - Key derivation for v4 databases
- `hmac`, `hashlib` (stdlib) - HMAC verification for database integrity

**Process & Memory:**
- `pymem==1.14.0` - Read WeChat process memory to extract encryption keys. Files: `wxManager/decrypt/wx_info_v3.py`, `wxManager/decrypt/wx_info_v4.py`
- `psutil~=6.1.1` - Process enumeration (find WeChat PID, memory maps). Files: `wxManager/decrypt/__init__.py`, `wxManager/decrypt/common.py`
- `pywin32==308` - Windows API access (`win32api.GetFileVersionInfo`, `win32com.client.Dispatch`, `winreg`). Files: `wxManager/decrypt/common.py`, `wxManager/decrypt/get_bias_addr.py`
- `yara-python` - Pattern matching for WeChat version detection / memory scanning. File: `wxManager/decrypt/wx_info_v4.py`

**Data Parsing:**
- `protobuf==4.25.1` + `google==3.0.0` - Deserialize protobuf-encoded WeChat data (contacts, messages, room data, file info, emoji descriptions). Files: `wxManager/parser/util/protocbuf/*_pb2.py`, `wxManager/parser/emoji_parser.py`, `wxManager/parser/wechat_v3.py`
- `xmltodict~=0.14.2` - Parse XML content in WeChat messages (audio, files, links, emojis). Files: `wxManager/parser/audio_parser.py`, `wxManager/parser/file_parser.py`, `wxManager/parser/wechat_v3.py`, `wxManager/model/message.py`
- `lz4~=4.3.3` - Decompress LZ4-compressed message data. File: `wxManager/parser/wechat_v3.py`
- `zstandard~=0.23.0` - Decompress Zstandard-compressed data (v4 format). File: `wxManager/manager_v4.py`

**Export Formats:**
- `docx` (python-docx) - Word document export. File: `exporter/exporter_docx.py`
- `openpyxl==3.1.5` - Excel spreadsheet export. File: `exporter/exporter_xlsx.py`
- `pillow==11.0.0` (PIL) - Image processing, format detection, thumbnail generation. Files: `exporter/exporter_xlsx.py`, `wxManager/db_v4/head_image.py`
- `pysilk-mod==1.6.4` - SILK audio codec decoding for WeChat voice messages. File: `exporter/exporter.py`

**Networking & Async:**
- `requests~=2.32.3` - HTTP requests (emoji downloads, etc.)
- `aiofiles~=24.1.0` - Async file I/O for batch image decryption. File: `wxManager/decrypt/decrypt_dat.py`

**HTML/Scraping:**
- `beautifulsoup4~=4.12.3` - HTML parsing in exporters
- `lxml~=5.3.1` - XML/HTML processing backend
- `soupsieve==2.5` - CSS selector support for BeautifulSoup

**Utilities:**
- `dateparser~=1.2.1` - Flexible date parsing for message time ranges
- `typing_extensions~=4.12.2` - Backport of type hints

**Audio/Video:**
- `ffmpeg.exe` (bundled binary in `exporter/ffmpeg.exe` and `exporter/resources/ffmpeg.exe`) - Audio/video conversion via subprocess

## Database Architecture

**Engine:** SQLite (WeChat's native storage format)

**Access Pattern:** Direct `sqlite3` module, no ORM:
```python
# From wxManager/model/db_model.py
DB = sqlite3.connect(db_path, check_same_thread=False)
cursor = DB.cursor()
cursor.execute(sql, args)
```

**Database Files (v3 - WeChat 3.x):**
- `MicroMsg.db` - Contacts and account info
- `Msg/MSG0.db`, `MSG1.db`, ... (series) - Chat messages
- `MediaMSG0.db`, `MediaMSG1.db`, ... (series) - Media message data
- `Misc.db` - Miscellaneous data
- `Emotion.db` - Emoji/sticker data
- `Audio2Text.db` - Voice-to-text transcriptions
- `PublicMsg.db` - Public account messages
- `Favorite.db` - Favorites
- OpenIM databases for enterprise contacts

**Database Files (v4 - WeChat 4.0+):**
- `contact.db` - Contacts
- `message.db` - Messages
- `media.db` - Media data
- `session.db` - Chat sessions
- `head_image.db` - Avatar images
- `hardlink.db` - File/image/video hardlink mapping
- `emotion.db` - Emojis
- `audio2text.db` - Voice transcriptions
- `biz_message.db` - Business/subscription messages

**Encryption:** All database files are AES-256-CBC encrypted by WeChat. Keys are extracted from WeChat's process memory at runtime.

## Configuration

**Environment:**
- No `.env` files required
- MemoAI sub-project uses env vars: `MODEL_PATH`, `TOKENIZER_PATH`, `EMBEDDING_PATH`
- Windows Registry access for WeChat version detection (`winreg`)

**Build:**
- No build system (no `setup.py`, `pyproject.toml`, or `setup.cfg`)
- Installed as a source checkout with `pip install -r requirements.txt`
- `ffmpeg.exe` is bundled as pre-built binaries in the repository

## Platform Requirements

**Development:**
- Windows 10/11 (mandatory - uses Windows-specific APIs)
- Python 3.10+
- Microsoft C++ Build Tools (for compiling `yara-python` from source, see `test.bat`)
- WeChat 3.x or 4.0+ installed and logged in (for live key extraction)

**Production:**
- Windows only (process memory reading, win32api, winreg)
- No cross-platform support

## Project Structure Summary

| Component | Purpose | Key Files |
|-----------|---------|-----------|
| `wxManager/` | Core library: decrypt, parse, query WeChat databases | `__init__.py`, `db_main.py`, `manager_v3.py`, `manager_v4.py` |
| `wxManager/decrypt/` | Extract encryption keys from WeChat process, decrypt DBs | `wx_info_v3.py`, `wx_info_v4.py`, `decrypt_v3.py`, `decrypt_v4.py`, `decrypt_dat.py` |
| `wxManager/db_v3/` | Database access layer for WeChat 3.x schema | `msg.py`, `micro_msg.py`, `media_msg.py`, etc. |
| `wxManager/db_v4/` | Database access layer for WeChat 4.0 schema | `message.py`, `contact.py`, `media.py`, etc. |
| `wxManager/model/` | Data models (Contact, Message, Me, MessageType) | `message.py`, `contact.py`, `db_model.py` |
| `wxManager/parser/` | Message content parsers (XML, protobuf, audio, emoji, links) | `wechat_v3.py`, `wechat_v4.py`, `link_parser.py` |
| `exporter/` | Export to HTML, DOCX, XLSX, TXT, Markdown, JSON, CSV, AI-TXT | `exporter.py`, `exporter_html.py`, `exporter_docx.py`, etc. |
| `MemoAI/` | AI chatbot sub-project (optional, separate deployment) | `api_server.py`, `qwen2-0.5b/app.py` |
| `1-decrypt.py` | Entry point: decrypt WeChat databases | Top-level script |
| `2-contact.py` | Entry point: list contacts | Top-level script |
| `3-exporter.py` | Entry point: export conversations | Top-level script |

---

*Stack analysis: 2026-04-23*
