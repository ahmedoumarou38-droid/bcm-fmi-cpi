ALTER TABLE cpi.metadata ADD COLUMN IF NOT EXISTS geographical_coverage TEXT;
ALTER TABLE cpi.metadata ADD COLUMN IF NOT EXISTS license TEXT;
ALTER TABLE cpi.metadata ADD COLUMN IF NOT EXISTS suggested_citation TEXT;

