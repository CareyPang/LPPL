CREATE TABLE preview_jobs (
  job_id TEXT PRIMARY KEY NOT NULL,
  symbol TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  source_sha TEXT NOT NULL,
  status TEXT NOT NULL,
  run_id TEXT,
  result_json TEXT,
  error_code TEXT,
  day_key TEXT NOT NULL,
  UNIQUE(symbol, day_key, source_sha)
);
--> statement-breakpoint
CREATE TABLE preview_receipts (
  result_hash TEXT PRIMARY KEY NOT NULL,
  first_served_at TEXT NOT NULL
);
