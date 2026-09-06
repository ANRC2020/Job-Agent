PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_source (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    uri TEXT,
    captured_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_profile (
    id TEXT PRIMARY KEY,
    display_name TEXT,
    preferred_name TEXT,
    email TEXT,
    phone TEXT,
    location_json TEXT NOT NULL DEFAULT '{}',
    timezone TEXT,
    consent_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_fact (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    value_json TEXT NOT NULL DEFAULT '{}',
    sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK (sensitivity IN ('normal', 'sensitive', 'highly_sensitive')),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    valid_from TEXT,
    valid_to TEXT,
    confirmed_at TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profile_fact_person_category
    ON profile_fact(person_id, category, status);

CREATE TABLE IF NOT EXISTS experience (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    organization TEXT,
    title TEXT,
    narrative TEXT,
    start_date TEXT,
    end_date TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    achievements_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'app',
    title TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    embedding_ref TEXT,
    model_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_message_conversation_time
    ON message(conversation_id, occurred_at);

CREATE TABLE IF NOT EXISTS communication_preference (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    dimension TEXT NOT NULL,
    value_json TEXT NOT NULL,
    explicit INTEGER NOT NULL DEFAULT 0 CHECK (explicit IN (0, 1)),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (person_id, dimension, status)
);

CREATE TABLE IF NOT EXISTS person_document (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    text_content TEXT,
    sha256 TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    mime_type TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (person_id, kind, sha256)
);

CREATE TABLE IF NOT EXISTS organization (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    website TEXT,
    locations_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_name_website
    ON organization(name, COALESCE(website, ''));

CREATE TABLE IF NOT EXISTS job (
    id TEXT PRIMARY KEY,
    organization_id TEXT REFERENCES organization(id) ON DELETE SET NULL,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    requirements_json TEXT NOT NULL DEFAULT '[]',
    compensation_json TEXT NOT NULL DEFAULT '{}',
    location_json TEXT NOT NULL DEFAULT '{}',
    employment_type TEXT,
    source_url TEXT,
    posted_at TEXT,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'closed', 'removed', 'unknown', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_org_status ON job(organization_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_source_url
    ON job(source_url) WHERE source_url IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_process (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    current_stage TEXT NOT NULL DEFAULT 'discovered',
    priority INTEGER NOT NULL DEFAULT 0,
    fit_score REAL CHECK (fit_score IS NULL OR fit_score BETWEEN 0 AND 1),
    started_at TEXT NOT NULL,
    outcome TEXT,
    next_action TEXT,
    next_action_at TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'closed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (person_id, job_id, started_at)
);

CREATE INDEX IF NOT EXISTS idx_job_process_person_stage
    ON job_process(person_id, current_stage, status);
CREATE INDEX IF NOT EXISTS idx_job_process_next_action
    ON job_process(next_action_at) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS job_stage_event (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES job_process(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    reason TEXT,
    actor TEXT NOT NULL DEFAULT 'user',
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stage_event_process_time
    ON job_stage_event(process_id, occurred_at);

CREATE TABLE IF NOT EXISTS job_contact (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES job_process(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    phone TEXT,
    profile_url TEXT,
    relationship_context TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_interaction (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES job_process(id) ON DELETE CASCADE,
    contact_id TEXT REFERENCES job_contact(id) ON DELETE SET NULL,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    direction TEXT CHECK (direction IS NULL OR direction IN ('inbound', 'outbound', 'internal')),
    occurred_at TEXT NOT NULL,
    summary TEXT,
    raw_content TEXT,
    follow_up_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_interaction_process_time
    ON job_interaction(process_id, occurred_at);

CREATE TABLE IF NOT EXISTS application_material (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES job_process(id) ON DELETE CASCADE,
    source_document_id TEXT REFERENCES person_document(id) ON DELETE SET NULL,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    filename TEXT,
    storage_uri TEXT,
    content TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    submitted_at TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'submitted', 'superseded', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (process_id, kind, version)
);

CREATE TABLE IF NOT EXISTS job_artifact (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES job_process(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    filename TEXT,
    storage_uri TEXT NOT NULL,
    sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_run (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT,
    input_hash TEXT,
    output_json TEXT,
    latency_ms INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    model_run_id TEXT REFERENCES model_run(id) ON DELETE SET NULL,
    domain TEXT NOT NULL CHECK (domain IN ('communication', 'job_preference', 'application', 'consistency', 'other')),
    scope TEXT NOT NULL DEFAULT 'person',
    claim TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    valid_until TEXT,
    review_state TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_state IN ('unreviewed', 'confirmed', 'edited', 'disputed', 'rejected')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'disputed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_person_domain
    ON learning(person_id, domain, status);

CREATE TABLE IF NOT EXISTS learning_evidence (
    id TEXT PRIMARY KEY,
    learning_id TEXT NOT NULL REFERENCES learning(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    polarity TEXT NOT NULL CHECK (polarity IN ('supports', 'contradicts', 'neutral')),
    weight REAL NOT NULL DEFAULT 1 CHECK (weight >= 0),
    excerpt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (learning_id, entity_type, entity_id, polarity)
);

CREATE TABLE IF NOT EXISTS preference_signal (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES job(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES data_source(id) ON DELETE SET NULL,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    sentiment TEXT NOT NULL CHECK (sentiment IN ('positive', 'negative', 'neutral', 'mixed')),
    strength REAL NOT NULL CHECK (strength BETWEEN 0 AND 1),
    explicit INTEGER NOT NULL DEFAULT 0 CHECK (explicit IN (0, 1)),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_preference_person_dimension
    ON preference_signal(person_id, dimension, occurred_at);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES job(id) ON DELETE SET NULL,
    model_run_id TEXT REFERENCES model_run(id) ON DELETE SET NULL,
    recommendation_type TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('accepted', 'rejected', 'ignored', 'edited', 'acted_on')),
    feedback_text TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_experiment (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    hypothesis TEXT NOT NULL,
    domain TEXT NOT NULL,
    variant TEXT NOT NULL,
    baseline TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    adopted INTEGER NOT NULL DEFAULT 0 CHECK (adopted IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('planned', 'running', 'completed', 'cancelled', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS performance_metric (
    id TEXT PRIMARY KEY,
    experiment_id TEXT REFERENCES strategy_experiment(id) ON DELETE CASCADE,
    process_id TEXT REFERENCES job_process(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    measured_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_performance_metric_name_time
    ON performance_metric(name, measured_at);

CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    message_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
    document_id UNINDEXED,
    filename,
    text_content,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS job_fts USING fts5(
    job_id UNINDEXED,
    title,
    description,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS interaction_fts USING fts5(
    interaction_id UNINDEXED,
    summary,
    raw_content,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS learning_fts USING fts5(
    learning_id UNINDEXED,
    claim,
    tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS message_fts_insert AFTER INSERT ON message BEGIN
    INSERT INTO message_fts(message_id, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS message_fts_update AFTER UPDATE OF content ON message BEGIN
    DELETE FROM message_fts WHERE message_id = old.id;
    INSERT INTO message_fts(message_id, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS message_fts_delete AFTER DELETE ON message BEGIN
    DELETE FROM message_fts WHERE message_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS document_fts_insert AFTER INSERT ON person_document BEGIN
    INSERT INTO document_fts(document_id, filename, text_content)
    VALUES (new.id, new.filename, COALESCE(new.text_content, ''));
END;
CREATE TRIGGER IF NOT EXISTS document_fts_update AFTER UPDATE OF filename, text_content ON person_document BEGIN
    DELETE FROM document_fts WHERE document_id = old.id;
    INSERT INTO document_fts(document_id, filename, text_content)
    VALUES (new.id, new.filename, COALESCE(new.text_content, ''));
END;
CREATE TRIGGER IF NOT EXISTS document_fts_delete AFTER DELETE ON person_document BEGIN
    DELETE FROM document_fts WHERE document_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS job_fts_insert AFTER INSERT ON job BEGIN
    INSERT INTO job_fts(job_id, title, description)
    VALUES (new.id, new.title, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS job_fts_update AFTER UPDATE OF title, description ON job BEGIN
    DELETE FROM job_fts WHERE job_id = old.id;
    INSERT INTO job_fts(job_id, title, description)
    VALUES (new.id, new.title, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS job_fts_delete AFTER DELETE ON job BEGIN
    DELETE FROM job_fts WHERE job_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS interaction_fts_insert AFTER INSERT ON job_interaction BEGIN
    INSERT INTO interaction_fts(interaction_id, summary, raw_content)
    VALUES (new.id, COALESCE(new.summary, ''), COALESCE(new.raw_content, ''));
END;
CREATE TRIGGER IF NOT EXISTS interaction_fts_update AFTER UPDATE OF summary, raw_content ON job_interaction BEGIN
    DELETE FROM interaction_fts WHERE interaction_id = old.id;
    INSERT INTO interaction_fts(interaction_id, summary, raw_content)
    VALUES (new.id, COALESCE(new.summary, ''), COALESCE(new.raw_content, ''));
END;
CREATE TRIGGER IF NOT EXISTS interaction_fts_delete AFTER DELETE ON job_interaction BEGIN
    DELETE FROM interaction_fts WHERE interaction_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS learning_fts_insert AFTER INSERT ON learning BEGIN
    INSERT INTO learning_fts(learning_id, claim) VALUES (new.id, new.claim);
END;
CREATE TRIGGER IF NOT EXISTS learning_fts_update AFTER UPDATE OF claim ON learning BEGIN
    DELETE FROM learning_fts WHERE learning_id = old.id;
    INSERT INTO learning_fts(learning_id, claim) VALUES (new.id, new.claim);
END;
CREATE TRIGGER IF NOT EXISTS learning_fts_delete AFTER DELETE ON learning BEGIN
    DELETE FROM learning_fts WHERE learning_id = old.id;
END;
