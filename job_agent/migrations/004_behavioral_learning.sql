-- Hardens durable conversation scope and adds the metadata needed for
-- evidence-backed, reviewable learning without introducing a second event ledger.

-- Merge any opportunity threads created concurrently before uniqueness existed.
UPDATE message
SET conversation_id = (
    SELECT canonical.id
    FROM conversation AS canonical
    WHERE canonical.person_id = (
        SELECT duplicate.person_id FROM conversation AS duplicate
        WHERE duplicate.id = message.conversation_id
    )
      AND canonical.job_process_id = (
        SELECT duplicate.job_process_id FROM conversation AS duplicate
        WHERE duplicate.id = message.conversation_id
    )
    ORDER BY canonical.started_at, canonical.rowid
    LIMIT 1
)
WHERE conversation_id IN (
    SELECT duplicate.id
    FROM conversation AS duplicate
    WHERE duplicate.job_process_id IS NOT NULL
      AND duplicate.id != (
          SELECT canonical.id
          FROM conversation AS canonical
          WHERE canonical.person_id = duplicate.person_id
            AND canonical.job_process_id = duplicate.job_process_id
          ORDER BY canonical.started_at, canonical.rowid
          LIMIT 1
      )
);

DELETE FROM conversation
WHERE job_process_id IS NOT NULL
  AND id != (
      SELECT canonical.id
      FROM conversation AS canonical
      WHERE canonical.person_id = conversation.person_id
        AND canonical.job_process_id = conversation.job_process_id
      ORDER BY canonical.started_at, canonical.rowid
      LIMIT 1
  );

-- The global Juno chat also has exactly one durable thread per person.
UPDATE message
SET conversation_id = (
    SELECT canonical.id
    FROM conversation AS canonical
    WHERE canonical.person_id = (
        SELECT duplicate.person_id FROM conversation AS duplicate
        WHERE duplicate.id = message.conversation_id
    )
      AND canonical.kind = 'juno'
      AND canonical.job_process_id IS NULL
    ORDER BY canonical.started_at, canonical.rowid
    LIMIT 1
)
WHERE conversation_id IN (
    SELECT duplicate.id
    FROM conversation AS duplicate
    WHERE duplicate.kind = 'juno'
      AND duplicate.job_process_id IS NULL
      AND duplicate.id != (
          SELECT canonical.id
          FROM conversation AS canonical
          WHERE canonical.person_id = duplicate.person_id
            AND canonical.kind = 'juno'
            AND canonical.job_process_id IS NULL
          ORDER BY canonical.started_at, canonical.rowid
          LIMIT 1
      )
);

DELETE FROM conversation
WHERE kind = 'juno'
  AND job_process_id IS NULL
  AND id != (
      SELECT canonical.id
      FROM conversation AS canonical
      WHERE canonical.person_id = conversation.person_id
        AND canonical.kind = 'juno'
        AND canonical.job_process_id IS NULL
      ORDER BY canonical.started_at, canonical.rowid
      LIMIT 1
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_unique_process
    ON conversation(person_id, job_process_id)
    WHERE job_process_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_unique_juno
    ON conversation(person_id)
    WHERE kind = 'juno' AND job_process_id IS NULL;

ALTER TABLE learning ADD COLUMN process_id TEXT REFERENCES job_process(id) ON DELETE SET NULL;
ALTER TABLE learning ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'hypothesis'
    CHECK (lifecycle_state IN ('hypothesis', 'pattern', 'confirmed', 'disputed', 'retired'));
ALTER TABLE learning ADD COLUMN decay_policy TEXT NOT NULL DEFAULT 'standard'
    CHECK (decay_policy IN ('none', 'slow', 'standard', 'fast'));
ALTER TABLE learning ADD COLUMN last_evidence_at TEXT;
ALTER TABLE learning ADD COLUMN last_decayed_at TEXT;
ALTER TABLE learning ADD COLUMN reviewed_at TEXT;
ALTER TABLE learning ADD COLUMN review_note TEXT;

UPDATE learning
SET lifecycle_state = CASE
    WHEN review_state IN ('confirmed', 'edited') THEN 'confirmed'
    WHEN review_state = 'disputed' OR status = 'disputed' THEN 'disputed'
    WHEN review_state = 'rejected' OR status = 'archived' THEN 'retired'
    ELSE 'hypothesis'
END;

-- Recover opportunity scope only when legacy evidence points to a real process.
UPDATE learning
SET process_id = (
        SELECT candidate.process_id
        FROM (
            SELECT e.entity_id AS process_id, e.created_at
            FROM learning_evidence e
            JOIN job_process p ON p.id = e.entity_id
            WHERE e.learning_id = learning.id AND e.entity_type = 'job_process'
            UNION ALL
            SELECT i.process_id, e.created_at
            FROM learning_evidence e
            JOIN job_interaction i ON i.id = e.entity_id
            WHERE e.learning_id = learning.id AND e.entity_type = 'job_interaction'
            UNION ALL
            SELECT s.process_id, e.created_at
            FROM learning_evidence e
            JOIN job_stage_event s ON s.id = e.entity_id
            WHERE e.learning_id = learning.id AND e.entity_type = 'job_stage_event'
            UNION ALL
            SELECT m.process_id, e.created_at
            FROM learning_evidence e
            JOIN application_material m ON m.id = e.entity_id
            WHERE e.learning_id = learning.id AND e.entity_type = 'application_material'
            UNION ALL
            SELECT p.process_id, e.created_at
            FROM learning_evidence e
            JOIN progress_event p ON p.id = e.entity_id
            WHERE e.learning_id = learning.id AND e.entity_type = 'progress_event'
        ) AS candidate
        WHERE candidate.process_id IS NOT NULL
        ORDER BY candidate.created_at
        LIMIT 1
    )
WHERE scope = 'opportunity' AND process_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_learning_scope_process
    ON learning(person_id, scope, process_id, status);
CREATE INDEX IF NOT EXISTS idx_learning_stale
    ON learning(status, lifecycle_state, last_evidence_at);
CREATE INDEX IF NOT EXISTS idx_learning_evidence_learning
    ON learning_evidence(learning_id, created_at);

CREATE TABLE IF NOT EXISTS tool_action (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    model_run_id TEXT REFERENCES model_run(id) ON DELETE SET NULL,
    tool_name TEXT NOT NULL,
    activity TEXT,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_summary TEXT,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('pending', 'approved', 'completed', 'failed', 'rejected')),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_action_conversation_time
    ON tool_action(conversation_id, occurred_at);

CREATE TABLE IF NOT EXISTS pending_action (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person_profile(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversation(id) ON DELETE CASCADE,
    action_name TEXT NOT NULL,
    action_class TEXT NOT NULL DEFAULT 'approval_required',
    arguments_json TEXT NOT NULL DEFAULT '{}',
    explanation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'completed', 'failed')),
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_action_person_status
    ON pending_action(person_id, status, requested_at);
