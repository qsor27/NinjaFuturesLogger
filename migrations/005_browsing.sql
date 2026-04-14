CREATE TABLE execution_notes (
  execution_id TEXT PRIMARY KEY,
  note         TEXT NOT NULL,
  updated_at   INTEGER NOT NULL,
  FOREIGN KEY (execution_id) REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);

CREATE TABLE execution_flags (
  execution_id TEXT PRIMARY KEY,
  reviewed     INTEGER NOT NULL DEFAULT 0,
  reviewed_at  INTEGER,
  FOREIGN KEY (execution_id) REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);

CREATE TABLE link_groups (
  link_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label         TEXT,
  created_at    INTEGER NOT NULL
);

CREATE TABLE position_links (
  link_group_id      INTEGER NOT NULL REFERENCES link_groups(link_group_id) ON DELETE CASCADE,
  account            TEXT NOT NULL,
  instrument         TEXT NOT NULL,
  entry_execution_id TEXT NOT NULL,
  ordinal            INTEGER NOT NULL,
  PRIMARY KEY (link_group_id, account, instrument, entry_execution_id)
);

CREATE INDEX idx_position_links_group_ordinal
  ON position_links(link_group_id, ordinal);
