# Architecture

**Analysis Date:** 2026-04-23

## Pattern Overview

**Overall:** Layered pipeline with version-strategy pattern

The system is a three-stage pipeline: **Decrypt** -> **Query** -> **Export**. Each stage operates on SQLite databases produced by WeChat. A strategy pattern selects between v3 and v4 implementations based on the WeChat version being targeted.

**Key Characteristics:**
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

1. `1-decrypt.py` calls `get_info_v4()` or `get_info_v3()` to scan running WeChat processes
2. Memory reading extracts: PID, wxid, nickname, data directory path, encryption key
3. `decrypt_v4.decrypt_db_files()` walks the WeChat data directory, decrypts every `.db` file using AES-256-CBC (v4) or sqlcipher (v3)
4. Decrypted databases are written to an output directory preserving subfolder structure
5. User info is saved as `info.json` in the output directory

### Contact Query Flow (Step 2)

1. `2-contact.py` creates `DatabaseConnection(db_dir, db_version)`
2. `DatabaseConnection._initialize_database()` selects `DataBaseV4` or `DataBaseV3` based on version
3. Each manager opens all sub-databases (contact, messages, media, hardlinks, etc.) via `DataBaseBase.init_database()`
4. `database.get_contacts()` queries the contact DB, creates `Contact` dataclass instances
5. Contact details (gender, region, signature) are parsed from protobuf (v4) or binary extra buffer (v3)

### Export Flow (Step 3)

1. `3-exporter.py` creates `DatabaseConnection`, gets interface, fetches a `Contact`
2. Creates an exporter (e.g., `HtmlExporter(database, contact, ...)`)
3. Exporter calls `self.database.get_messages(wxid)` which:
   - Queries message DB tables (table name is `Msg_{md5(wxid)}` in v4)
   - Multi-database series are queried in parallel via `ThreadPoolExecutor`
   - Raw rows are passed to `parser_messages()` which uses `FACTORY_REGISTRY` to create typed `Message` objects
   - For large message sets (>20k), parsing is parallelized via `ProcessPoolExecutor`
4. Each `MessageFactory.create()` parses XML/protobuf content, resolves media paths, creates the appropriate `Message` subclass
5. Exporter iterates typed messages, renders to output format, copies/decodes media files

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

**`1-decrypt.py`:**
- Location: `/mnt/d/WeChatMsg/1-decrypt.py`
- Triggers: Manual execution (script)
- Responsibilities: Scans WeChat process, extracts key, decrypts all database files

**`2-contact.py`:**
- Location: `/mnt/d/WeChatMsg/2-contact.py`
- Triggers: Manual execution (script)
- Responsibilities: Demonstrates contact querying, prints all contacts and chatroom members

**`3-exporter.py`:**
- Location: `/mnt/d/WeChatMsg/3-exporter.py`
- Triggers: Manual execution (script)
- Responsibilities: Demonstrates single/batch export in multiple formats

**`MemoAI/api_server.py`:**
- Location: `/mnt/d/WeChatMsg/MemoAI/api_server.py`
- Triggers: Manual execution (FastAPI server)
- Responsibilities: Serves a ChatGLM/Qwen model via OpenAI-compatible API for AI features (separate concern from main pipeline)

## v3 vs v4 Version Support

The project supports two major WeChat versions with fundamentally different database schemas and encryption.

### Database Schema Differences

**V3** (WeChat 3.x): Data stored in flat files under a `Msg/` directory:
- `Misc.db` - Avatars, misc data
- `MicroMsg.db` - Contacts, sessions
- `Multi/MSG0.db`, `Multi/MediaMSG0.db` - Messages and media (series)
- `HardLinkImage.db`, `HardLinkFile.db`, `HardLinkVideo.db` - File hardlinks
- `Emotion.db` - Emojis
- `OpenIMContact.db`, `OpenIMMsg.db`, `OpenIMMedia.db` - Enterprise WeChat
- `PublicMsg.db` - Public account messages

**V4** (WeChat 4.x): Data stored in structured subdirectories:
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

1. User specifies `db_version` (3 or 4) when creating `DatabaseConnection` in `wxManager/__init__.py`
2. `DatabaseConnection._initialize_database()` instantiates `DataBaseV4()` or `DataBaseV3()`
3. Each manager opens version-specific DB files and delegates to version-specific DB classes
4. Message parsing uses version-specific `FACTORY_REGISTRY` and `parser_messages()` functions defined in `wxManager/parser/wechat_v4.py` and `wxManager/parser/wechat_v3.py`

## Error Handling

**Strategy:** Broad exception catching with logging; graceful degradation

**Patterns:**
- Most methods wrap operations in bare `except:` clauses and return empty defaults (`[]`, `''`, `None`)
- Logging uses custom logger at `wxManager/log/logger.py`
- Database errors during merge operations trigger rollback and error printing
- Failed media file operations (copy, decode) are silently skipped

## Cross-Cutting Concerns

**Logging:** Custom logger wrapping Python logging at `wxManager/log/logger.py`. Used via `from wxManager.log import logger`. Logs to both console and file (`combined.log`).

**Validation:** No formal validation layer. Type hints used throughout but not enforced at runtime. `Time_range` parameters are converted from strings/dates to Unix timestamps in DB query methods.

**Authentication:** Not applicable for the library itself. Decryption requires access to the running WeChat process memory (Windows-only).

**Concurrency:** Heavy use of `ProcessPoolExecutor` for large message parsing (>20k messages splits into batches of ~10k). `ThreadPoolExecutor` used for parallel DB queries across series databases and for batch file operations.

**Media Decoding:** Images encrypted as `.dat` files (v3: XOR, v4: AES) are decoded via `wxManager/decrypt/decrypt_dat.py`. Audio in Silk format decoded to MP3 via `pysilk` + `ffmpeg`.

---

*Architecture analysis: 2026-04-23*
