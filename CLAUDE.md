<!-- GSD:project-start source:PROJECT.md -->
## Project

**WeChatMsg 解密修复**

修复 WeChatMsg（留痕）项目的微信数据库解密功能，使其兼容微信 4.x 系列（当前测试版本 4.1.8.29）。WeChatMsg 是一个微信聊天记录提取和导出工具，采用三步流水线：解密数据库 → 查看联系人 → 导出聊天记录。当前解密步骤因微信版本更新导致内存特征匹配失败，需要更新密钥提取逻辑。

**Core Value:** 让用户能够成功完成完整的「解密 → 联系人 → 导出」三步流程，特别是能从微信 4.x 系列版本中正确提取数据库解密密钥。

### Constraints

- **平台：** Windows only（解密步骤依赖进程内存读取）
- **权限：** 需要管理员权限打开微信进程（PROCESS_ALL_ACCESS）
- **前提条件：** 微信必须在运行状态
- **技术栈：** Python + ctypes + YARA + pymem
- **测试环境：** 微信 4.1.8.29（用户实际环境）
- **兼容性：** 不能破坏微信 4.0 已有的解密能力
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.10+ (header comment in `wxManager/__init__.py` specifies `Python3.10`; type union syntax `str | bytes` used throughout, requiring 3.10+)
- Used for all core modules: `wxManager/`, `exporter/`, `MemoAI/`, and entry-point scripts
- Protocol Buffers (`.proto` files in `wxManager/parser/util/protocbuf/`) - compiled to Python (`*_pb2.py`)
- YAML (GitHub Actions workflow in `.github/workflows/sync.yml`)
- HTML/CSS/JS (export template in `exporter/resources/template.html`)
- JSON (configuration files, version lists, training data)
## Runtime
- Windows only (critical dependency - uses `ctypes.windll`, `win32api`, `winreg`, `win32com`, `pymem` for process memory inspection of WeChat/Weixin.exe)
- Python 3.10+
- pip
- Requirements file: `requirements.txt` at project root
- Secondary requirements: `MemoAI/qwen2-0.5b/requirements.txt` (AI sub-project)
- No lockfile present (no `pip freeze` output or `Pipfile.lock`)
## Frameworks
- No web framework in the main project
- Pure Python standard library + third-party packages
- Abstract base class pattern for database interface (`wxManager/db_main.py`)
- FastAPI + Uvicorn - OpenAI-compatible API server (`MemoAI/api_server.py`)
- Gradio - UI for Qwen model inference (`MemoAI/qwen2-0.5b/app.py`)
- PyTorch + Transformers (HuggingFace) - Model loading and inference
- DashInfer - Alternative inference engine for Qwen 2.0
## Key Dependencies
- `sqlite3` (stdlib) - All database access uses Python's built-in sqlite3 module directly. No ORM. Raw SQL queries via cursors. Files: `wxManager/model/db_model.py`, `wxManager/merge.py`, all `wxManager/db_v3/*.py` and `wxManager/db_v4/*.py`
- `pycryptodome` (Crypto) - AES-CBC decryption of WeChat database files. Files: `wxManager/decrypt/decrypt_v3.py`, `wxManager/decrypt/decrypt_v4.py`, `wxManager/decrypt/decrypt_dat.py`
- `cryptography` - Additional crypto operations
- `Crypto.Protocol.KDF.PBKDF2` - Key derivation for v4 databases
- `hmac`, `hashlib` (stdlib) - HMAC verification for database integrity
- `pymem==1.14.0` - Read WeChat process memory to extract encryption keys. Files: `wxManager/decrypt/wx_info_v3.py`, `wxManager/decrypt/wx_info_v4.py`
- `psutil~=6.1.1` - Process enumeration (find WeChat PID, memory maps). Files: `wxManager/decrypt/__init__.py`, `wxManager/decrypt/common.py`
- `pywin32==308` - Windows API access (`win32api.GetFileVersionInfo`, `win32com.client.Dispatch`, `winreg`). Files: `wxManager/decrypt/common.py`, `wxManager/decrypt/get_bias_addr.py`
- `yara-python` - Pattern matching for WeChat version detection / memory scanning. File: `wxManager/decrypt/wx_info_v4.py`
- `protobuf==4.25.1` + `google==3.0.0` - Deserialize protobuf-encoded WeChat data (contacts, messages, room data, file info, emoji descriptions). Files: `wxManager/parser/util/protocbuf/*_pb2.py`, `wxManager/parser/emoji_parser.py`, `wxManager/parser/wechat_v3.py`
- `xmltodict~=0.14.2` - Parse XML content in WeChat messages (audio, files, links, emojis). Files: `wxManager/parser/audio_parser.py`, `wxManager/parser/file_parser.py`, `wxManager/parser/wechat_v3.py`, `wxManager/model/message.py`
- `lz4~=4.3.3` - Decompress LZ4-compressed message data. File: `wxManager/parser/wechat_v3.py`
- `zstandard~=0.23.0` - Decompress Zstandard-compressed data (v4 format). File: `wxManager/manager_v4.py`
- `docx` (python-docx) - Word document export. File: `exporter/exporter_docx.py`
- `openpyxl==3.1.5` - Excel spreadsheet export. File: `exporter/exporter_xlsx.py`
- `pillow==11.0.0` (PIL) - Image processing, format detection, thumbnail generation. Files: `exporter/exporter_xlsx.py`, `wxManager/db_v4/head_image.py`
- `pysilk-mod==1.6.4` - SILK audio codec decoding for WeChat voice messages. File: `exporter/exporter.py`
- `requests~=2.32.3` - HTTP requests (emoji downloads, etc.)
- `aiofiles~=24.1.0` - Async file I/O for batch image decryption. File: `wxManager/decrypt/decrypt_dat.py`
- `beautifulsoup4~=4.12.3` - HTML parsing in exporters
- `lxml~=5.3.1` - XML/HTML processing backend
- `soupsieve==2.5` - CSS selector support for BeautifulSoup
- `dateparser~=1.2.1` - Flexible date parsing for message time ranges
- `typing_extensions~=4.12.2` - Backport of type hints
- `ffmpeg.exe` (bundled binary in `exporter/ffmpeg.exe` and `exporter/resources/ffmpeg.exe`) - Audio/video conversion via subprocess
## Database Architecture
# From wxManager/model/db_model.py
- `MicroMsg.db` - Contacts and account info
- `Msg/MSG0.db`, `MSG1.db`, ... (series) - Chat messages
- `MediaMSG0.db`, `MediaMSG1.db`, ... (series) - Media message data
- `Misc.db` - Miscellaneous data
- `Emotion.db` - Emoji/sticker data
- `Audio2Text.db` - Voice-to-text transcriptions
- `PublicMsg.db` - Public account messages
- `Favorite.db` - Favorites
- OpenIM databases for enterprise contacts
- `contact.db` - Contacts
- `message.db` - Messages
- `media.db` - Media data
- `session.db` - Chat sessions
- `head_image.db` - Avatar images
- `hardlink.db` - File/image/video hardlink mapping
- `emotion.db` - Emojis
- `audio2text.db` - Voice transcriptions
- `biz_message.db` - Business/subscription messages
## Configuration
- No `.env` files required
- MemoAI sub-project uses env vars: `MODEL_PATH`, `TOKENIZER_PATH`, `EMBEDDING_PATH`
- Windows Registry access for WeChat version detection (`winreg`)
- No build system (no `setup.py`, `pyproject.toml`, or `setup.cfg`)
- Installed as a source checkout with `pip install -r requirements.txt`
- `ffmpeg.exe` is bundled as pre-built binaries in the repository
## Platform Requirements
- Windows 10/11 (mandatory - uses Windows-specific APIs)
- Python 3.10+
- Microsoft C++ Build Tools (for compiling `yara-python` from source, see `test.bat`)
- WeChat 3.x or 4.0+ installed and logged in (for live key extraction)
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Pipeline architecture: decrypt -> database query -> message parse -> export
- Strategy pattern for WeChat v3 vs v4 support via `DataBaseInterface` abstract class
- Factory pattern for message type parsing (`MessageFactory` subclasses registered in `FACTORY_REGISTRY`)
- Direct SQLite access (no ORM) through a base class `DataBaseBase` that handles multi-database series (e.g., `message_0.db`, `message_1.db`)
- Windows-only for the decrypt step (memory reading via `psutil`/`pymem`/`win32api`); query and export are cross-platform given decrypted databases
## Layers
### Layer 1: Decrypt
- Purpose: Extract encryption keys from running WeChat process memory, decrypt all `.db` files
- Location: `wxManager/decrypt/`
- Contains: Process memory reading, AES decryption, `.dat` image decoding
- Depends on: `psutil`, `pymem`, `pywin32`, `pycryptodome` (Windows-only)
- Used by: Entry point scripts `1-decrypt.py`
### Layer 2: Database Access
- Purpose: Open decrypted SQLite databases, provide typed query methods
- Location: `wxManager/db_v3/`, `wxManager/db_v4/`, `wxManager/db_main.py`, `wxManager/model/db_model.py`
- Contains: Per-table database classes inheriting `DataBaseBase`
- Depends on: `sqlite3` (stdlib), protobuf definitions in `wxManager/parser/util/protocbuf/`
- Used by: Manager layer (`manager_v3.py`, `manager_v4.py`)
### Layer 3: Manager / Business Logic
- Purpose: Orchestrate database queries, message parsing, contact resolution
- Location: `wxManager/manager_v3.py`, `wxManager/manager_v4.py`, `wxManager/__init__.py`
- Contains: `DataBaseV3`, `DataBaseV4` implementing `DataBaseInterface`
- Depends on: Database Access layer, Parser layer, Model layer
- Used by: Entry point scripts, Exporter layer
### Layer 4: Message Parsing
- Purpose: Transform raw database rows into typed `Message` dataclass instances
- Location: `wxManager/parser/`
- Contains: Factory classes per message type (text, image, video, audio, emoji, link, etc.), XML/protobuf content parsers
- Depends on: `wxManager/model/message.py` (dataclasses), `xmltodict`, `protobuf`, `zstandard`
- Used by: Manager layer via `parser_messages()` functions and `FACTORY_REGISTRY`
### Layer 5: Export
- Purpose: Render typed messages into output formats (HTML, TXT, CSV, DOCX, XLSX, Markdown, JSON)
- Location: `exporter/`
- Contains: `ExporterBase` subclasses per format
- Depends on: Manager layer (`DataBaseInterface`), file I/O utilities
- Used by: Entry point scripts `3-exporter.py`
### Layer 6: Model
- Purpose: Define data structures shared across all layers
- Location: `wxManager/model/`
- Contains: `Message` dataclass hierarchy, `Contact`/`Person`/`Me` dataclasses, `DataBaseBase` SQLite wrapper, `MessageType` constants
- Depends on: Nothing (leaf layer)
- Used by: All other layers
## Data Flow
### Decrypt Flow (Step 1)
### Contact Query Flow (Step 2)
### Export Flow (Step 3)
### State Management
- **`Me` singleton** (`wxManager/model/contact.py`): Stores current user's wxid, name, wx_dir, xor_key. Loaded from `info.json` at init.
- **`Singleton` class** (`wxManager/parser/wechat_v4.py`): Shared across all `MessageFactory` instances in a process. Holds a contact cache and a `LimitedDict` message cache (100 entries) for quote resolution.
- **`contacts_map` / `chatroom_members_map`**: In-memory caches on each `DataBaseInterface` instance for contact lookups.
## Key Abstractions
### `DataBaseInterface` (Abstract Base Class)
- Purpose: Defines the full API for querying WeChat data (contacts, messages, media, etc.)
- Examples: `wxManager/db_main.py`
- Pattern: Abstract base class with ~40 methods. Subclassed by `DataBaseV3` and `DataBaseV4`.
- Consumers create via `DatabaseConnection(db_dir, version).get_interface()` in `wxManager/__init__.py`.
### `DataBaseBase` (SQLite Wrapper)
- Purpose: Handles opening/closing SQLite databases, supports series (multi-file) databases
- Examples: `wxManager/model/db_model.py`
- Pattern: All DB classes inherit this. Pass `is_series=True` for split databases (e.g., `message_0.db`, `message_1.db`). Stores `self.DB` as either a single connection or a list of connections.
### `MessageFactory` (Factory Pattern)
- Purpose: Create typed `Message` objects from raw database rows
- Examples: `wxManager/parser/wechat_v4.py` (17 factory classes), `wxManager/parser/wechat_v3.py`
- Pattern: Each message type has a factory class. All factories are registered in `FACTORY_REGISTRY` dict keyed by `MessageType`. The `parser_messages()` generator looks up the factory by message type and calls `create()`.
### `ExporterBase` (Template Method)
- Purpose: Base class for all export formats
- Examples: `exporter/exporter.py`, `exporter/exporter_html.py`, `exporter/exporter_txt.py`
- Pattern: Subclasses override `export()`. Base provides message filtering (by type, time range, group member), avatar management, file copy utilities.
## Entry Points
- Location: `/mnt/d/WeChatMsg/1-decrypt.py`
- Triggers: Manual execution (script)
- Responsibilities: Scans WeChat process, extracts key, decrypts all database files
- Location: `/mnt/d/WeChatMsg/2-contact.py`
- Triggers: Manual execution (script)
- Responsibilities: Demonstrates contact querying, prints all contacts and chatroom members
- Location: `/mnt/d/WeChatMsg/3-exporter.py`
- Triggers: Manual execution (script)
- Responsibilities: Demonstrates single/batch export in multiple formats
- Location: `/mnt/d/WeChatMsg/MemoAI/api_server.py`
- Triggers: Manual execution (FastAPI server)
- Responsibilities: Serves a ChatGLM/Qwen model via OpenAI-compatible API for AI features (separate concern from main pipeline)
## v3 vs v4 Version Support
### Database Schema Differences
- `Misc.db` - Avatars, misc data
- `MicroMsg.db` - Contacts, sessions
- `Multi/MSG0.db`, `Multi/MediaMSG0.db` - Messages and media (series)
- `HardLinkImage.db`, `HardLinkFile.db`, `HardLinkVideo.db` - File hardlinks
- `Emotion.db` - Emojis
- `OpenIMContact.db`, `OpenIMMsg.db`, `OpenIMMedia.db` - Enterprise WeChat
- `PublicMsg.db` - Public account messages
- `contact/contact.db` - Contacts
- `head_image/head_image.db` - Avatars
- `session/session.db` - Chat sessions
- `message/message_0.db`, `message/biz_message_0.db` - Messages (series)
- `message/media_0.db` - Media data (series)
- `hardlink/hardlink.db` - All file/image/video hardlinks (unified)
- `emoticon/emoticon.db` - Emojis
### Implementation Differences
| Aspect | V3 | V4 |
|--------|----|----|
| Manager | `wxManager/manager_v3.py` `DataBaseV3` | `wxManager/manager_v4.py` `DataBaseV4` |
| DB modules | `wxManager/db_v3/` (13 files) | `wxManager/db_v4/` (10 files) |
| Message tables | `MSG0.db` with table `MSG_{localId}` | `message_0.db` with table `Msg_{md5(wxid)}` |
| Contact details | Binary extra buffer parsing (`decodeExtraBuf`) | Protobuf (`contact_pb2.ContactInfo`) |
| Message content | XML/plain text | Zstandard-compressed bytes or XML |
| Message routing | Type + subtype tuple lookup | Direct `MessageType` constant lookup |
| Image encryption | XOR with single byte | AES encryption with versioned keys |
| Decryption | sqlcipher | AES-256-CBC with PBKDF2 key derivation |
| Process name | `WeChat.exe` | `Weixin.exe`, reads `Weixin.dll` |
### How Version Selection Works
## Error Handling
- Most methods wrap operations in bare `except:` clauses and return empty defaults (`[]`, `''`, `None`)
- Logging uses custom logger at `wxManager/log/logger.py`
- Database errors during merge operations trigger rollback and error printing
- Failed media file operations (copy, decode) are silently skipped
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
