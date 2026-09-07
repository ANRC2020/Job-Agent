-- Append-only rolling summaries preserve continuity beyond the active chat window.
-- Source boundaries keep every summary auditable against immutable messages.

CREATE TABLE IF NOT EXISTS conversation_summary (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    source_start_message_id TEXT NOT NULL REFERENCES message(id) ON DELETE RESTRICT,
    source_end_message_id TEXT NOT NULL REFERENCES message(id) ON DELETE RESTRICT,
    source_message_count INTEGER NOT NULL CHECK (source_message_count > 0),
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(conversation_id, source_end_message_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_summary_latest
    ON conversation_summary(conversation_id, created_at DESC);
