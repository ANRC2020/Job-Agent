-- Gives every opportunity its own durable thread, Juno's reasoning about it,
-- and a shame-free record of progress the user has made.

ALTER TABLE conversation ADD COLUMN kind TEXT NOT NULL DEFAULT 'general';
ALTER TABLE conversation ADD COLUMN job_process_id TEXT REFERENCES job_process(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_process
    ON conversation(job_process_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_conversation_kind
    ON conversation(kind, updated_at);

-- Why Juno surfaced this role, what gives her pause, and how the user felt.
ALTER TABLE job_process ADD COLUMN fit_summary TEXT;
ALTER TABLE job_process ADD COLUMN why_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE job_process ADD COLUMN concerns_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE job_process ADD COLUMN standouts_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE job_process ADD COLUMN user_reaction TEXT;

ALTER TABLE person_profile ADD COLUMN onboarding_json TEXT NOT NULL DEFAULT '{}';

-- Progress worth acknowledging, including deciding a role is not worth pursuing.
-- Deliberately has no streak, target, or completion column.
CREATE TABLE IF NOT EXISTS progress_event (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    process_id TEXT REFERENCES job_process(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    headline TEXT NOT NULL,
    detail TEXT,
    occurred_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_progress_event_person_time
    ON progress_event(person_id, occurred_at);
