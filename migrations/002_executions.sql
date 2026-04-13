CREATE TABLE executions (
  nt_execution_id  TEXT NOT NULL,
  account          TEXT NOT NULL,
  instrument       TEXT NOT NULL,
  timestamp        INTEGER NOT NULL,
  side             TEXT NOT NULL CHECK(side IN ('Buy','Sell')),
  original_action  TEXT NOT NULL,
  quantity         INTEGER NOT NULL CHECK(quantity > 0),
  price            REAL NOT NULL,
  commission       REAL NOT NULL DEFAULT 0,
  entry_exit       TEXT NOT NULL CHECK(entry_exit IN ('Entry','Exit')),
  position_after   TEXT,
  source_order_id  TEXT,
  source_filename  TEXT NOT NULL,
  imported_at      INTEGER NOT NULL,
  PRIMARY KEY (nt_execution_id, account)
);

CREATE UNIQUE INDEX idx_executions_nt_execution_id
  ON executions(nt_execution_id);

CREATE INDEX idx_executions_account_instrument_time
  ON executions(account, instrument, timestamp);

CREATE INDEX idx_executions_timestamp
  ON executions(timestamp);

CREATE TABLE import_cursors (
  filename       TEXT PRIMARY KEY,
  byte_offset    INTEGER NOT NULL,
  last_tick_at   INTEGER NOT NULL,
  last_modified  INTEGER NOT NULL
);

CREATE TABLE import_runs (
  tick_id                INTEGER PRIMARY KEY AUTOINCREMENT,
  filename               TEXT NOT NULL,
  started_at             INTEGER NOT NULL,
  finished_at            INTEGER NOT NULL,
  cursor_before          INTEGER NOT NULL,
  cursor_after           INTEGER NOT NULL,
  lines_read             INTEGER NOT NULL,
  rows_parsed            INTEGER NOT NULL,
  rows_inserted          INTEGER NOT NULL,
  rows_skipped_duplicate INTEGER NOT NULL,
  rows_rejected          INTEGER NOT NULL,
  status                 TEXT NOT NULL CHECK(status IN ('ok','partial','failed')),
  error                  TEXT
);

CREATE INDEX idx_import_runs_filename_started
  ON import_runs(filename, started_at DESC);

CREATE TABLE import_rejects (
  reject_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_id      INTEGER NOT NULL REFERENCES import_runs(tick_id),
  line_number  INTEGER NOT NULL,
  raw_line     TEXT NOT NULL,
  reason       TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);
