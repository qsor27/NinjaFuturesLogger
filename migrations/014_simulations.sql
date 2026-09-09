-- migrations/014_simulations.sql
-- Simulation Analysis: saved rule sets. Results are never stored; every run
-- recomputes from positions. No FKs in either direction so imports and
-- rollbacks never touch this table.
CREATE TABLE simulations (
  simulation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  rules_json    TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);
