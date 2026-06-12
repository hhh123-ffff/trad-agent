ALTER TABLE stealth_scan_tasks ADD COLUMN IF NOT EXISTS requested_include_watchlist BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE stealth_scan_tasks ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE stealth_scan_tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_stealth_scan_tasks_queue ON stealth_scan_tasks (status, created_at);
CREATE INDEX IF NOT EXISTS idx_stealth_scan_tasks_lease ON stealth_scan_tasks (status, lease_expires_at);
