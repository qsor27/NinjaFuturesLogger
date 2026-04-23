CREATE TABLE fetch_attempts (
  id              TEXT PRIMARY KEY,
  trigger         TEXT NOT NULL,
  instrument      TEXT NOT NULL,
  timeframe       TEXT NOT NULL,
  range_start     INTEGER NOT NULL,
  range_end       INTEGER NOT NULL,
  started_at      INTEGER NOT NULL,
  completed_at    INTEGER,
  gaps_found      INTEGER NOT NULL DEFAULT 0,
  bars_written    INTEGER NOT NULL DEFAULT 0,
  final_status    TEXT,
  error           TEXT
);
CREATE INDEX idx_fetch_attempts_instr_tf_started
  ON fetch_attempts(instrument, timeframe, started_at DESC);
CREATE INDEX idx_fetch_attempts_started
  ON fetch_attempts(started_at DESC);

CREATE TABLE fetch_source_attempts (
  id              INTEGER PRIMARY KEY,
  attempt_id      TEXT NOT NULL REFERENCES fetch_attempts(id) ON DELETE CASCADE,
  gap_start       INTEGER NOT NULL,
  gap_end         INTEGER NOT NULL,
  source          TEXT NOT NULL,
  outcome         TEXT NOT NULL,
  bars_returned   INTEGER NOT NULL DEFAULT 0,
  duration_ms     INTEGER,
  http_status     INTEGER,
  error_class     TEXT,
  error           TEXT
);
CREATE INDEX idx_fsa_attempt ON fetch_source_attempts(attempt_id);

CREATE TABLE ohlc_gap_reports (
  id                INTEGER PRIMARY KEY,
  instrument        TEXT NOT NULL,
  timeframe         TEXT NOT NULL,
  gap_start         INTEGER NOT NULL,
  gap_end           INTEGER NOT NULL,
  first_seen_at     INTEGER NOT NULL,
  last_attempt_at   INTEGER,
  last_attempt_id   TEXT REFERENCES fetch_attempts(id) ON DELETE SET NULL,
  attempt_count     INTEGER NOT NULL DEFAULT 0,
  next_retry_at     INTEGER NOT NULL,
  state             TEXT NOT NULL DEFAULT 'open',
  resolved_at       INTEGER,
  UNIQUE(instrument, timeframe, gap_start, gap_end)
);
CREATE INDEX idx_gap_reports_state_next_retry
  ON ohlc_gap_reports(state, next_retry_at);

CREATE TABLE ohlc_breaker_state (
  source                    TEXT PRIMARY KEY,
  state                     TEXT NOT NULL,
  consecutive_failures      INTEGER NOT NULL,
  consecutive_trips         INTEGER NOT NULL,
  current_cooldown_seconds  INTEGER NOT NULL,
  opened_at                 INTEGER,
  next_retry_at             INTEGER,
  last_failure_at           INTEGER,
  last_success_at           INTEGER,
  last_error                TEXT,
  last_failure_class        TEXT,
  updated_at                INTEGER NOT NULL
);
