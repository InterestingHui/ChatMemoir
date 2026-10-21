# Codebase Structure

**Analysis Date:** 2026-04-23

## Directory Layout

```
WeChatMsg/
├── wxManager/              # Core library: decrypt, query, parse WeChat data
│   ├── db_v3/              # WeChat 3.x database access classes
│   ├── db_v4/              # WeChat 4.x database access classes
│   ├── decrypt/            # Encryption key extraction and DB/file decryption
│   ├── log/                # Logging configuration
│   ├── model/              # Data models (Message, Contact, Me, DataBaseBase)
│   ├── parser/             # Message content parsers and factory pattern
│   │   └── util/           # Parser utilities
│   │       └── protocbuf/  # Compiled protobuf definitions
│   ├── __init__.py         # DatabaseConnection facade, public API exports
│   ├── db_main.py          # DataBaseInterface ABC, Context wrapper
│   ├── manager_v3.py       # DataBaseV3 implementation
│   ├── manager_v4.py       # DataBaseV4 implementation
│   └── merge.py            # Incremental database merge utilities
├── exporter/               # Output format exporters
│   └── resources/          # HTML templates, emoji assets, default avatar
├── MemoAI/                 # AI chat server (separate concern)
│   └── qwen2-0.5b/        # Fine-tuning config for Qwen model
├── doc/                    # Documentation (Chinese)
├── example/                # Usage examples (README only)
├── 1-decrypt.py            # Entry point: decrypt WeChat databases
├── 2-contact.py            # Entry point: query contacts
├── 3-exporter.py           # Entry point: export chat history
├── requirements.txt        # Python dependencies
└── readme.md               # Project README
```

## Directory Purposes

### `wxManager/`
- Purpose: Core library for all WeChat data operations
- Contains: Database access, models, parsers, decrypt logic, managers
- Key files: `__init__.py` (public API), `db_main.py` (interface), `manager_v4.py` / `manager_v3.py` (implementations)

### `wxManager/db_v3/`
- Purpose: WeChat 3.x specific database table access classes
- Contains: One file per database/table type (13 files)
- Key files: `micro_msg.py` (contacts), `msg.py` (messages), `media_msg.py` (audio), `hard_link_image.py` / `hard_link_file.py` / `hard_link_video.py` (media files), `misc.py` (avatars), `emotion.py` (emoji), `open_im_*.py` (enterprise WeChat), `public_msg.py` (public accounts), `favorite.py` (favorites), `audio2text.py` (speech-to-text cache), `sns.py` (moments)

### `wxManager/db_v4/`
- Purpose: WeChat 4.x specific database table access classes
- Contains: One file per database/table type (10 files)
- Key files: `contact.py` (contacts), `message.py` (messages), `media.py` (audio/media), `hardlink.py` (unified file/image/video hardlinks), `session.py` (chat sessions), `head_image.py` (avatars), `emotion.py` (emoji), `biz_message.py` (public account messages), `audio2text.py` (speech-to-text cache)

### `wxManager/decrypt/`
- Purpose: Extract WeChat encryption keys from process memory and decrypt databases
- Contains: Version-specific decryptors, key extraction, `.dat` image file decoding
- Key files: `decrypt_v4.py` (AES-256-CBC decryption), `decrypt_v3.py` (sqlcipher decryption), `decrypt_dat.py` (image XOR/AES decoding), `wx_info_v4.py` / `wx_info_v3.py` (memory reading for keys), `get_wx_info.py` / `wxinfo.py` (process info extraction), `get_bias_addr.py` (memory offset calculation), `common.py` (`WeChatInfo` dataclass)

### `wxManager/model/`
- Purpose: Shared data structures used across all layers
- Contains: Dataclass definitions for messages, contacts, database base class
- Key files: `message.py` (`Message` hierarchy with ~15 subclasses, `MessageType` constants), `contact.py` (`Person`, `Contact`, `Me` singleton), `db_model.py` (`DataBaseBase` SQLite wrapper)

### `wxManager/parser/`
- Purpose: Parse raw message content (XML, protobuf, binary) into typed Message objects
- Contains: Version-specific factory registries, content-specific parsers
- Key files: `wechat_v4.py` (v4 `FACTORY_REGISTRY` with 17 factory classes), `wechat_v3.py` (v3 `FACTORY_REGISTRY`), `link_parser.py` (parse links, transfers, voip, position, applets, merged messages, etc.), `audio_parser.py` (parse audio XML), `emoji_parser.py` (parse emoji XML), `file_parser.py` (parse file/video XML)

### `wxManager/parser/util/protocbuf/`
- Purpose: Compiled protobuf Python files for binary data deserialization
- Contains: `.py` files generated from `.proto` definitions
- Key files: `contact_pb2.py` (contact details), `msg_pb2.py` (message data), `roomdata_pb2.py` (chatroom member data), `file_info_pb2.py` (file metadata), `emoji_desc_pb2.py` (emoji descriptions), `packed_info_data*.py` (v4 packed message metadata)

### `wxManager/log/`
- Purpose: Logging configuration
- Key files: `logger.py` (logger setup)

### `exporter/`
- Purpose: Render typed messages into various output formats
- Contains: One exporter class per output format plus shared base
- Key files: `exporter.py` (`ExporterBase` base class with file utilities), `exporter_html.py` (HTML export), `exporter_txt.py` (plain text), `exporter_ai_txt.py` (AI-optimized text), `exporter_docx.py` (Word), `exporter_xlsx.py` (Excel), `exporter_csv.py` (CSV), `exporter_markdown.py` (Markdown), `exporter_json.py` (JSON), `config.py` (`FileType` enum)

### `exporter/resources/`
- Purpose: Static assets used during export
- Contains: HTML template, emoji images, default avatar image
- Key files: `template.html` (HTML export template)

### `MemoAI/`
- Purpose: Separate AI server for chat-related AI features
- Contains: FastAPI server wrapping ChatGLM/Qwen models, merge utility
- Key files: `api_server.py` (OpenAI-compatible API server), `merge_json.py` (data merging)

### `doc/`
- Purpose: Project documentation in Chinese
- Key files: Developer manual, database introduction, AI integration docs

### `example/`
- Purpose: Usage examples
- Key files: `README.md` (example documentation only; Python examples were removed)

## Key File Locations

### Entry Points
- `/mnt/d/WeChatMsg/1-decrypt.py`: Database decryption (step 1 of pipeline)
- `/mnt/d/WeChatMsg/2-contact.py`: Contact querying demo (step 2 of pipeline)
- `/mnt/d/WeChatMsg/3-exporter.py`: Chat export demo (step 3 of pipeline)

### Public API
- `/mnt/d/WeChatMsg/wxManager/__init__.py`: `DatabaseConnection`, `Me`, `MessageType`, `DataBaseInterface`, `DataBaseV4`, `DataBaseV3`, message model classes

### Configuration
- `/mnt/d/WeChatMsg/requirements.txt`: Python dependencies
- `/mnt/d/WeChatMsg/exporter/config.py`: `FileType` enum for export format selection

### Core Logic - Interface
- `/mnt/d/WeChatMsg/wxManager/db_main.py`: `DataBaseInterface` ABC defining the full query API (~40 methods)
- `/mnt/d/WeChatMsg/wxManager/model/db_model.py`: `DataBaseBase` SQLite connection wrapper

### Core Logic - V4 Implementation
- `/mnt/d/WeChatMsg/wxManager/manager_v4.py`: `DataBaseV4` orchestrating all v4 DB modules
- `/mnt/d/WeChatMsg/wxManager/parser/wechat_v4.py`: V4 message factories and `FACTORY_REGISTRY`

### Core Logic - V3 Implementation
- `/mnt/d/WeChatMsg/wxManager/manager_v3.py`: `DataBaseV3` orchestrating all v3 DB modules
- `/mnt/d/WeChatMsg/wxManager/parser/wechat_v3.py`: V3 message factories and `FACTORY_REGISTRY`

### Models
- `/mnt/d/WeChatMsg/wxManager/model/message.py`: All message dataclasses and `MessageType`
- `/mnt/d/WeChatMsg/wxManager/model/contact.py`: `Person`, `Contact`, `Me` (singleton)

### Media Handling
- `/mnt/d/WeChatMsg/wxManager/decrypt/decrypt_dat.py`: Image decryption (.dat -> PNG/JPG)
- `/mnt/d/WeChatMsg/exporter/exporter.py`: `decode_audio_to_mp3()` (Silk -> PCM -> MP3 via ffmpeg)

### Database Merge
- `/mnt/d/WeChatMsg/wxManager/merge.py`: `increase_data()` and `increase_update_data()` for incremental sync

## Naming Conventions

### Files
- Manager files: `manager_v{N}.py` for version-specific orchestrators
- DB module files: Named after their database table or concern (e.g., `message.py`, `contact.py`, `hardlink.py`)
- Parser files: Named after content type (e.g., `link_parser.py`, `audio_parser.py`, `emoji_parser.py`)
- Exporter files: `exporter_{format}.py` (e.g., `exporter_html.py`, `exporter_txt.py`)
- Protobuf files: `{name}_pb2.py` (compiled protobuf naming convention)
- Entry points: `{step_number}-{name}.py` (e.g., `1-decrypt.py`)

### Directories
- `db_v{N}/`: Database access for WeChat version N
- `protocbuf/`: Protobuf-generated Python code (note: spelling is "protocbuf" not "protobuf")
- `resources/`: Static assets bundled with the module

### Classes
- Database classes: `{Concern}DB` (e.g., `MessageDB`, `ContactDB`, `HardLinkDB`)
- Manager classes: `DataBaseV{N}` (e.g., `DataBaseV4`)
- Exporter classes: `{Format}Exporter` (e.g., `HtmlExporter`, `TxtExporter`)
- Message factory classes: `{Type}MessageFactory` (e.g., `TextMessageFactory`, `ImageMessageFactory`)
- Message dataclasses: `{Type}Message` (e.g., `TextMessage`, `ImageMessage`, `QuoteMessage`)

## Where to Add New Code

### New Message Type
1. Define the message dataclass in `wxManager/model/message.py` (inherit from `Message` or a sub-type)
2. Add a `MessageType` constant in `wxManager/model/message.py`
3. Create a parser function in `wxManager/parser/link_parser.py` (or a new parser file)
4. Create a `MessageFactory` subclass in `wxManager/parser/wechat_v4.py` (and `wechat_v3.py` if v3 support needed)
5. Register the factory in `FACTORY_REGISTRY` in the parser file(s)
6. Handle rendering in each exporter that should support the new type

### New Export Format
1. Create `exporter/exporter_{format}.py` with a class inheriting `ExporterBase`
2. Override the `export()` method
3. Add a `FileType` enum value in `exporter/config.py`
4. Import and register in `exporter/__init__.py`

### New WeChat Version Support
1. Create `wxManager/db_v{N}/` directory with DB module files
2. Create `wxManager/manager_v{N}.py` implementing `DataBaseInterface`
3. Create `wxManager/parser/wechat_v{N}.py` with version-specific factory registry
4. Update `wxManager/__init__.py` to import and route to the new version
5. Create `wxManager/decrypt/decrypt_v{N}.py` for version-specific decryption
6. Create `wxManager/decrypt/wx_info_v{N}.py` for version-specific key extraction

### New Database Table Accessor
1. Create a new file in the appropriate `db_v{N}/` directory
2. Define a class inheriting `DataBaseBase`
3. Pass the expected DB file name pattern to `DataBaseBase.__init__()`
4. Use `is_series=True` if the database is split across multiple files (e.g., `media_0.db`, `media_1.db`)
5. Add the instance to the manager's `__init__()` and `init_database()` methods

### New Parser for Content Type
1. Add parsing function in `wxManager/parser/` (use `link_parser.py` for XML-based content)
2. Call the parser from the relevant `MessageFactory.create()` method

### New Utility
- Shared helpers: `wxManager/parser/util/common.py`
- Export utilities: `exporter/exporter.py` (add functions here)

## Special Directories

### `wxManager/parser/util/protocbuf/`
- Purpose: Compiled protobuf Python files for binary deserialization
- Generated: Yes (from `.proto` definitions, not present in repo)
- Committed: Yes
- Note: Spelling "protocbuf" is intentional (not "protobuf")

### `exporter/resources/`
- Purpose: Static template and asset files used during export
- Generated: No
- Committed: Yes
- Contains: `template.html` (split by `/*注意看这是分割线*/` marker), emoji images, default avatar

### `.planning/codebase/`
- Purpose: GSD codebase analysis documents
- Generated: Yes (by `/gsd-map-codebase` command)
- Committed: No (in `.gitignore` ideally)

---

*Structure analysis: 2026-04-23*
