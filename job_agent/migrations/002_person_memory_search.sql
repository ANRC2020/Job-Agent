CREATE VIRTUAL TABLE IF NOT EXISTS person_memory_fts USING fts5(
    entity_type UNINDEXED,
    entity_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

INSERT INTO person_memory_fts(entity_type, entity_id, content)
SELECT 'profile_fact', id, statement
FROM profile_fact
WHERE NOT EXISTS (
    SELECT 1 FROM person_memory_fts
    WHERE entity_type = 'profile_fact' AND entity_id = profile_fact.id
);

INSERT INTO person_memory_fts(entity_type, entity_id, content)
SELECT
    'experience',
    id,
    trim(
        COALESCE(kind, '') || ' ' ||
        COALESCE(organization, '') || ' ' ||
        COALESCE(title, '') || ' ' ||
        COALESCE(narrative, '')
    )
FROM experience
WHERE NOT EXISTS (
    SELECT 1 FROM person_memory_fts
    WHERE entity_type = 'experience' AND entity_id = experience.id
);

INSERT INTO person_memory_fts(entity_type, entity_id, content)
SELECT 'person_document', id, COALESCE(filename, '') || ' ' || COALESCE(text_content, '')
FROM person_document
WHERE NOT EXISTS (
    SELECT 1 FROM person_memory_fts
    WHERE entity_type = 'person_document' AND entity_id = person_document.id
);

CREATE TRIGGER IF NOT EXISTS person_fact_memory_insert AFTER INSERT ON profile_fact BEGIN
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES ('profile_fact', new.id, new.statement);
END;
CREATE TRIGGER IF NOT EXISTS person_fact_memory_update AFTER UPDATE OF statement ON profile_fact BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'profile_fact' AND entity_id = old.id;
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES ('profile_fact', new.id, new.statement);
END;
CREATE TRIGGER IF NOT EXISTS person_fact_memory_delete AFTER DELETE ON profile_fact BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'profile_fact' AND entity_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS experience_memory_insert AFTER INSERT ON experience BEGIN
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES (
        'experience',
        new.id,
        trim(
            COALESCE(new.kind, '') || ' ' ||
            COALESCE(new.organization, '') || ' ' ||
            COALESCE(new.title, '') || ' ' ||
            COALESCE(new.narrative, '')
        )
    );
END;
CREATE TRIGGER IF NOT EXISTS experience_memory_update
AFTER UPDATE OF kind, organization, title, narrative ON experience BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'experience' AND entity_id = old.id;
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES (
        'experience',
        new.id,
        trim(
            COALESCE(new.kind, '') || ' ' ||
            COALESCE(new.organization, '') || ' ' ||
            COALESCE(new.title, '') || ' ' ||
            COALESCE(new.narrative, '')
        )
    );
END;
CREATE TRIGGER IF NOT EXISTS experience_memory_delete AFTER DELETE ON experience BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'experience' AND entity_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS document_memory_insert AFTER INSERT ON person_document BEGIN
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES (
        'person_document',
        new.id,
        COALESCE(new.filename, '') || ' ' || COALESCE(new.text_content, '')
    );
END;
CREATE TRIGGER IF NOT EXISTS document_memory_update
AFTER UPDATE OF filename, text_content ON person_document BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'person_document' AND entity_id = old.id;
    INSERT INTO person_memory_fts(entity_type, entity_id, content)
    VALUES (
        'person_document',
        new.id,
        COALESCE(new.filename, '') || ' ' || COALESCE(new.text_content, '')
    );
END;
CREATE TRIGGER IF NOT EXISTS document_memory_delete AFTER DELETE ON person_document BEGIN
    DELETE FROM person_memory_fts WHERE entity_type = 'person_document' AND entity_id = old.id;
END;
