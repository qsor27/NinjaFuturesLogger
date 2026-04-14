CREATE TABLE chart_defaults (
  id                       INTEGER PRIMARY KEY CHECK(id = 1),
  default_timeframe        TEXT NOT NULL DEFAULT '5m'
    CHECK(default_timeframe IN ('1m','5m','15m','1h','4h','1d')),
  volume_visible_default   INTEGER NOT NULL DEFAULT 1,
  updated_at               INTEGER NOT NULL
);
INSERT INTO chart_defaults (id, updated_at) VALUES (1, strftime('%s','now'));

CREATE TABLE custom_fields (
  field_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL UNIQUE,
  field_type     TEXT NOT NULL
    CHECK(field_type IN ('text','number','dropdown','date','boolean')),
  is_active      INTEGER NOT NULL DEFAULT 1,
  display_order  INTEGER NOT NULL DEFAULT 0,
  created_at     INTEGER NOT NULL
);

CREATE TABLE custom_field_options (
  option_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  field_id       INTEGER NOT NULL
    REFERENCES custom_fields(field_id) ON DELETE CASCADE,
  value          TEXT NOT NULL,
  display_order  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (field_id, value)
);
CREATE INDEX idx_custom_field_options_field ON custom_field_options(field_id);

CREATE TABLE execution_custom_field_values (
  execution_id   TEXT NOT NULL,
  field_id       INTEGER NOT NULL
    REFERENCES custom_fields(field_id) ON DELETE CASCADE,
  value          TEXT NOT NULL,
  updated_at     INTEGER NOT NULL,
  PRIMARY KEY (execution_id, field_id),
  FOREIGN KEY (execution_id)
    REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);
CREATE INDEX idx_execution_custom_field_values_field
  ON execution_custom_field_values(field_id);
