CREATE TABLE bars (
  instrument TEXT NOT NULL,
  timeframe  TEXT NOT NULL,
  time       INTEGER NOT NULL,
  open       REAL NOT NULL,
  high       REAL NOT NULL,
  low        REAL NOT NULL,
  close      REAL NOT NULL,
  volume     INTEGER NOT NULL,
  source     TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  PRIMARY KEY (instrument, timeframe, time)
);

CREATE INDEX idx_bars_instrument_tf_time
  ON bars(instrument, timeframe, time);
