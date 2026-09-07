CREATE UNIQUE INDEX IF NOT EXISTS idx_job_org_external
    ON job(organization_id, external_id)
    WHERE organization_id IS NOT NULL AND external_id IS NOT NULL;
