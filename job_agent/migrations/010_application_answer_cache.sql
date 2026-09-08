CREATE TABLE IF NOT EXISTS application_answer (
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    answer_key TEXT NOT NULL,
    field_label TEXT NOT NULL,
    field_type TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    use_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (person_id, answer_key)
);
