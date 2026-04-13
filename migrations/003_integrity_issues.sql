CREATE TABLE integrity_issues (
  issue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  account         TEXT NOT NULL,
  instrument      TEXT NOT NULL,
  execution_id    TEXT NOT NULL,
  severity        TEXT NOT NULL CHECK(severity IN ('low','medium','high')),
  type            TEXT NOT NULL,
  description     TEXT NOT NULL,
  detected_at     INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,
  resolved_at     INTEGER,
  resolved_by     TEXT CHECK(resolved_by IN ('system','user') OR resolved_by IS NULL),
  resolution_note TEXT,
  ignored         INTEGER NOT NULL DEFAULT 0,
  ignore_note     TEXT,
  UNIQUE (account, instrument, execution_id, type)
);

CREATE INDEX idx_integrity_open
  ON integrity_issues(account, instrument, severity)
  WHERE resolved_at IS NULL AND ignored = 0;
