-- Review deck: hindsight-free replay of the user's own closed positions.
-- entry_execution_id is the position natural-key component verbatim and may
-- carry a #open suffix (reversal-opened positions) that has no executions
-- row; the FK cascade therefore lives on real_execution_id (suffix stripped).
CREATE TABLE review_sessions (
  session_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   INTEGER NOT NULL,
  ended_at     INTEGER
);

CREATE TABLE review_attempts (
  attempt_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id          INTEGER NOT NULL
    REFERENCES review_sessions(session_id) ON DELETE CASCADE,
  account             TEXT NOT NULL,
  instrument          TEXT NOT NULL,
  entry_execution_id  TEXT NOT NULL,
  real_execution_id   TEXT NOT NULL
    REFERENCES executions(nt_execution_id) ON DELETE CASCADE,
  call                TEXT NOT NULL CHECK(call IN ('valid','invalid')),
  outcome_pnl         REAL NOT NULL,
  created_at          INTEGER NOT NULL
);

CREATE INDEX idx_review_attempts_session ON review_attempts(session_id);
CREATE INDEX idx_review_attempts_entry   ON review_attempts(entry_execution_id);
