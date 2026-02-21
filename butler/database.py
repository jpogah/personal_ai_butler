"""Database initialization and schema management."""
import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,           -- 'telegram' | 'whatsapp'
    sender_id   TEXT NOT NULL,           -- channel-specific user identifier
    created_at  REAL NOT NULL,
    last_active REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,       -- 'user' | 'assistant' | 'tool_result'
    content         TEXT NOT NULL,       -- JSON-encoded content block(s)
    tokens          INTEGER DEFAULT 0,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id          TEXT PRIMARY KEY,        -- UUID
    sender_id   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    risk_level  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    resolved    INTEGER DEFAULT 0,       -- 0=pending, 1=approved, 2=denied
    resolved_at REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    action      TEXT NOT NULL,           -- tool name or event type
    args_json   TEXT,
    risk_level  TEXT,
    approved    INTEGER,                 -- NULL if no approval needed
    result      TEXT,                    -- 'success' | 'error' | 'denied'
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    content     TEXT NOT NULL,           -- compact summary text
    first_msg_id INTEGER NOT NULL,       -- first message ID covered
    last_msg_id  INTEGER NOT NULL,       -- last message ID covered
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    key         TEXT NOT NULL,           -- short label e.g. "preferred_language"
    value       TEXT NOT NULL,           -- the remembered fact
    updated_at  REAL NOT NULL,
    UNIQUE(sender_id, channel, key) ON CONFLICT REPLACE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_sender ON conversations(sender_id, last_active);
CREATE INDEX IF NOT EXISTS idx_audit_sender ON audit_log(sender_id, created_at);
CREATE INDEX IF NOT EXISTS idx_summaries_conv ON summaries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_sender ON user_memory(sender_id, channel);
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Initialize database, create tables, return open connection."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    logger.info("Database initialized at %s", db_path)
    return conn
