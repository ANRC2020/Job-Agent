-- Preserve source facts from verified listings separately from Juno's fit assessment.

ALTER TABLE job ADD COLUMN apply_url TEXT;
ALTER TABLE job ADD COLUMN source_kind TEXT;
ALTER TABLE job ADD COLUMN workplace_type TEXT;
ALTER TABLE job ADD COLUMN department TEXT;
ALTER TABLE job ADD COLUMN seniority TEXT;
ALTER TABLE job ADD COLUMN last_verified_at TEXT;
ALTER TABLE job ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('verified', 'partial', 'unverified', 'closed', 'failed'));
ALTER TABLE job ADD COLUMN source_metadata_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_job_verification
    ON job(verification_status, last_verified_at);
CREATE INDEX IF NOT EXISTS idx_job_apply_url
    ON job(apply_url) WHERE apply_url IS NOT NULL;
