CREATE TABLE instrument_coverage (
  instrument TEXT PRIMARY KEY,
  state TEXT NOT NULL
    CHECK (state IN ('active','winding_down','retired')),
  last_execution_at INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  retired_at INTEGER,
  updated_at INTEGER NOT NULL
);

CREATE INDEX idx_instrument_coverage_state ON instrument_coverage(state);
