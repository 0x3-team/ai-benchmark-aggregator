#!/usr/bin/env python3
"""Initialize Software Orchestrator durable store (SQLite)."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  version TEXT NOT NULL,
  harness TEXT NOT NULL DEFAULT 'unknown',
  reasoning_setting TEXT NOT NULL DEFAULT '',
  modalities TEXT,
  context_window INTEGER,
  pricing_json TEXT,
  privacy_json TEXT,
  metadata_json TEXT,
  last_verified TEXT,
  PRIMARY KEY (model_id, provider, version, harness, reasoning_setting)
);

CREATE TABLE IF NOT EXISTS capability_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  version TEXT NOT NULL,
  harness TEXT NOT NULL,
  reasoning_setting TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,
  stack_key TEXT NOT NULL DEFAULT '',
  sample_count INTEGER NOT NULL DEFAULT 0,
  success_alpha REAL NOT NULL DEFAULT 1.0,
  success_beta REAL NOT NULL DEFAULT 1.0,
  pass_first REAL,
  eventual_success REAL,
  retry_rate REAL,
  takeover_rate REAL,
  mean_review REAL,
  latency_ewma_ms REAL,
  cost_ewma_usd REAL,
  reliability REAL,
  strengths_json TEXT,
  weaknesses_json TEXT,
  failure_modes_json TEXT,
  drift_status TEXT DEFAULT 'unknown',
  updated_at TEXT NOT NULL,
  UNIQUE(model_id, provider, version, harness, category, stack_key, reasoning_setting)
);

CREATE TABLE IF NOT EXISTS outcome_events (
  event_id TEXT PRIMARY KEY,
  timestamp TEXT NOT NULL,
  project_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  project_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_state (
  project_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outcomes_task ON outcome_events(task_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_project ON outcome_events(project_id);
CREATE INDEX IF NOT EXISTS idx_profiles_model ON capability_profiles(model_id, category);
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--path", required=True, help="SQLite DB path")
    args = p.parse_args()
    path = Path(args.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        con.commit()
    finally:
        con.close()
    print(f"initialized {path}")


if __name__ == "__main__":
    main()
