-- Phase 1 tenant columns. Applied at startup via ensure_tenant_schema() as well.
-- workspace_id 0 is the shared research feed. Laravel workspace ids start at 1.

ALTER TABLE monitored_instruments ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collection_status ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collection_jobs ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE system_events ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE monitored_instruments DROP CONSTRAINT IF EXISTS uq_monitored_symbol_tf;
ALTER TABLE collection_status DROP CONSTRAINT IF EXISTS uq_status_symbol_tf;
ALTER TABLE model_versions DROP CONSTRAINT IF EXISTS model_versions_version_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_monitored_ws_symbol_tf
    ON monitored_instruments (workspace_id, symbol, timeframe);
CREATE UNIQUE INDEX IF NOT EXISTS uq_status_ws_symbol_tf
    ON collection_status (workspace_id, symbol, timeframe);
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_ws_version
    ON model_versions (workspace_id, version);
