"""SQLite schema definition and version migrations.

Separated from the store so that sqlite_store.py stays within the project's
file-size guidance, and so the schema can be read without wading through
query code. These functions touch only the connection.
"""

from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  size INTEGER,
  mtime_ns INTEGER,
  sha256 TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  first_seen TEXT,
  last_seen TEXT,
  deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS files_sha_idx ON files(sha256);
CREATE TABLE IF NOT EXISTS aliases (
  file_id TEXT NOT NULL,
  path TEXT NOT NULL,
  first_seen TEXT,
  last_seen TEXT,
  UNIQUE(file_id, path)
);
CREATE TABLE IF NOT EXISTS edges (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  score REAL NOT NULL,
  confidence TEXT NOT NULL,
  mode TEXT NOT NULL,
  adapter TEXT NOT NULL,
  source_path TEXT,
  evidence_json TEXT NOT NULL,
  basis TEXT NOT NULL DEFAULT 'inference',
  assurance TEXT NOT NULL DEFAULT 'candidate',
  scope TEXT NOT NULL DEFAULT 'relationship',
  adapter_version TEXT NOT NULL DEFAULT '1',
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  competing_group TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  observed_at TEXT
);
CREATE INDEX IF NOT EXISTS edges_source_idx ON edges(source_id);
CREATE INDEX IF NOT EXISTS edges_target_idx ON edges(target_id);
CREATE INDEX IF NOT EXISTS edges_source_path_idx ON edges(source_path);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  task TEXT,
  started_at TEXT,
  finished_at TEXT,
  cwd TEXT,
  command_json TEXT,
  exit_code INTEGER,
  status TEXT,
  changes_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS clusters (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  label TEXT NOT NULL,
  reason TEXT NOT NULL,
  members_json TEXT NOT NULL,
  representatives_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at TEXT,
  path TEXT,
  adapter TEXT,
  message TEXT
);
CREATE TABLE IF NOT EXISTS file_text (
  file_id TEXT NOT NULL,
  source TEXT NOT NULL,
  text TEXT NOT NULL,
  encoding TEXT,
  engine TEXT,
  confidence REAL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(file_id, source)
);
CREATE INDEX IF NOT EXISTS file_text_source_idx ON file_text(source);
CREATE INDEX IF NOT EXISTS files_kind_idx ON files(kind,deleted);
CREATE INDEX IF NOT EXISTS files_path_nocase_idx ON files(path COLLATE NOCASE);

-- Schema v2 entities. The legacy files/edges tables remain as a stable
-- compatibility projection for existing clients and are populated together.
CREATE TABLE IF NOT EXISTS logical_artifacts (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  created_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS content_digests (
  id TEXT PRIMARY KEY,
  algorithm TEXT NOT NULL,
  value TEXT NOT NULL,
  bytes INTEGER,
  UNIQUE(algorithm,value)
);
CREATE TABLE IF NOT EXISTS artifact_versions (
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  digest_id TEXT,
  size INTEGER,
  mtime_ns INTEGER,
  observed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(artifact_id,digest_id),
  FOREIGN KEY(artifact_id) REFERENCES logical_artifacts(id)
);
CREATE INDEX IF NOT EXISTS artifact_versions_artifact_idx ON artifact_versions(artifact_id,observed_at);
CREATE TABLE IF NOT EXISTS file_locations (
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  path TEXT NOT NULL,
  first_seen TEXT,
  last_seen TEXT,
  current INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(artifact_id,path),
  FOREIGN KEY(artifact_id) REFERENCES logical_artifacts(id)
);
CREATE INDEX IF NOT EXISTS file_locations_path_idx ON file_locations(path,current);
CREATE TABLE IF NOT EXISTS activities (
  id TEXT PRIMARY KEY,
  activity_type TEXT NOT NULL,
  state TEXT,
  started_at TEXT,
  finished_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  state TEXT NOT NULL,
  observed_at TEXT,
  UNIQUE(run_id,state,observed_at)
);
CREATE TABLE IF NOT EXISTS raw_evidence (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  basis TEXT NOT NULL,
  assurance TEXT NOT NULL,
  scope TEXT NOT NULL,
  adapter TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  mode TEXT NOT NULL,
  facts_json TEXT NOT NULL,
  location_json TEXT,
  signal_group TEXT NOT NULL,
  weight REAL NOT NULL,
  status TEXT NOT NULL,
  observed_at TEXT,
  collected_at TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  basis TEXT NOT NULL,
  assurance TEXT NOT NULL,
  scope TEXT NOT NULL,
  adapter TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  competing_group TEXT,
  status TEXT NOT NULL,
  observed_at TEXT,
  score REAL NOT NULL,
  confidence TEXT NOT NULL,
  source_path TEXT
);
CREATE INDEX IF NOT EXISTS claims_target_idx ON claims(target_id,status,relation);
CREATE INDEX IF NOT EXISTS claims_source_idx ON claims(source_id,status,relation);
CREATE TABLE IF NOT EXISTS output_families (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  rule_json TEXT NOT NULL,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS user_decisions (
  id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  claim_id TEXT,
  source_id TEXT,
  target_id TEXT,
  relation TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  undone_at TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS user_decisions_claim_idx ON user_decisions(claim_id,status);
CREATE TABLE IF NOT EXISTS external_entities (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  label TEXT NOT NULL,
  locator TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS extractor_cache (
  digest_id TEXT NOT NULL,
  adapter TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT,
  PRIMARY KEY(digest_id,adapter,adapter_version)
);
"""


def ensure_schema_v2(connection: sqlite3.Connection) -> None:
    """Upgrade nominal pre-v2 databases that lacked the v2 entities.

    Early alpha databases wrote schema_version=2 while still storing only
    files and edges. Presence checks, rather than a destructive rebuild,
    make that historical mistake recoverable.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(edges)")}
    additions = {
        "basis": "TEXT NOT NULL DEFAULT 'inference'",
        "assurance": "TEXT NOT NULL DEFAULT 'candidate'",
        "scope": "TEXT NOT NULL DEFAULT 'relationship'",
        "adapter_version": "TEXT NOT NULL DEFAULT '1'",
        "evidence_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "competing_group": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "observed_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE edges ADD COLUMN {name} {declaration}")
    connection.execute(
        "INSERT INTO meta(key,value) VALUES('model_revision','artifact-v2') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def migrate(connection: sqlite3.Connection, current: int, target: int) -> None:
    if current < 1:
        raise RuntimeError(f"unsupported lineage schema version: {current}")
    ensure_schema_v2(connection)
    connection.execute(
        "INSERT INTO meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(target),),
    )

