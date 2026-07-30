from __future__ import annotations

import difflib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import SCHEMA_VERSION
from ..model import Edge, Evidence, Node
from ..scoring import aggregate

FUZZY_MATCH_MINIMUM_RATIO = 0.35


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


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(DDL)
        self._ensure_schema_v2()
        self.fts_available = False
        try:
            self.connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS file_text_fts USING fts5(file_id UNINDEXED, source UNINDEXED, text)")
            self.fts_available = True
        except sqlite3.OperationalError:
            self.fts_available = False
        current = self.get_meta("schema_version")
        if current is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        elif int(current) > SCHEMA_VERSION:
            raise RuntimeError(f"index schema {current} is newer than supported {SCHEMA_VERSION}")
        elif int(current) < SCHEMA_VERSION:
            self._migrate(int(current), SCHEMA_VERSION)
        self._backfill_schema_v2()
        self.connection.commit()

    def _ensure_schema_v2(self) -> None:
        """Upgrade nominal pre-v2 databases that lacked the v2 entities.

        Early alpha databases wrote schema_version=2 while still storing only
        files and edges. Presence checks, rather than a destructive rebuild,
        make that historical mistake recoverable.
        """
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(edges)")}
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
                self.connection.execute(f"ALTER TABLE edges ADD COLUMN {name} {declaration}")
        self.connection.execute(
            "INSERT INTO meta(key,value) VALUES('model_revision','artifact-v2') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    def _migrate(self, current: int, target: int) -> None:
        if current < 1:
            raise RuntimeError(f"unsupported lineage schema version: {current}")
        self._ensure_schema_v2()
        self.connection.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(target),),
        )

    def _backfill_schema_v2(self) -> None:
        for row in self.connection.execute("SELECT * FROM files"):
            item = dict(row)
            self._sync_artifact_projection(
                item["id"], item["path"], item["kind"], item["label"], item.get("size"),
                item.get("mtime_ns"), item.get("sha256"), json.loads(item.get("metadata_json") or "{}"),
                item.get("last_seen") or item.get("first_seen"), current=not bool(item.get("deleted")),
            )
        for row in self.connection.execute("SELECT * FROM runs"):
            item = dict(row)
            self.connection.execute(
                "INSERT OR IGNORE INTO activities(id,activity_type,state,started_at,finished_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (item["id"], "run", item.get("status"), item.get("started_at"), item.get("finished_at"), item.get("metadata_json") or "{}"),
            )
        legacy_edges = [dict(row) for row in self.connection.execute("SELECT * FROM edges")]
        for item in legacy_edges:
            if self.connection.execute("SELECT 1 FROM claims WHERE id=?", (item["id"],)).fetchone():
                continue
            parsed: list[Evidence] = []
            for value in json.loads(item.get("evidence_json") or "[]"):
                allowed = {
                    key: value[key]
                    for key in Evidence.__dataclass_fields__
                    if key in value
                }
                try:
                    parsed.append(Evidence(**allowed))
                except TypeError:
                    continue
            if not parsed:
                parsed.append(
                    Evidence(
                        kind="legacy-edge-record", adapter=item.get("adapter") or "legacy",
                        mode=item.get("mode") or "inferred", facts={"legacy_edge_id": item["id"]},
                        collected_at=item.get("observed_at") or "", weight=min(float(item.get("score") or 0.0), 0.99),
                    )
                )
            self.add_edge(
                Edge(
                    item["source_id"], item["target_id"], item["relation"], parsed,
                    item.get("adapter") or "legacy", item.get("mode") or "inferred", item.get("source_path"),
                    id=item["id"], scope=item.get("scope") or "relationship",
                    competing_group=item.get("competing_group"), status=item.get("status") or "active",
                )
            )

    def _sync_artifact_projection(
        self, artifact_id: str, path: str, kind: str, label: str, size: int | None,
        mtime_ns: int | None, sha256: str | None, metadata: dict[str, Any], seen_at: str | None,
        *, current: bool = True,
    ) -> str | None:
        self.connection.execute(
            "INSERT INTO logical_artifacts(id,kind,label,created_at,metadata_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,label=excluded.label,metadata_json=excluded.metadata_json",
            (artifact_id, kind, label, seen_at, json.dumps(metadata, sort_keys=True)),
        )
        location_id = f"location:{uuid.uuid5(uuid.NAMESPACE_URL, artifact_id + ':' + path)}"
        self.connection.execute(
            "INSERT INTO file_locations(id,artifact_id,path,first_seen,last_seen,current) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(artifact_id,path) DO UPDATE SET last_seen=excluded.last_seen,current=excluded.current",
            (location_id, artifact_id, path, seen_at, seen_at, int(current)),
        )
        digest_id = None
        if sha256:
            digest_id = f"digest:sha256:{sha256}"
            self.connection.execute(
                "INSERT OR IGNORE INTO content_digests(id,algorithm,value,bytes) VALUES(?,?,?,?)",
                (digest_id, "sha256", sha256, size),
            )
        version_basis = digest_id or f"metadata:{size}:{mtime_ns}"
        version_id = f"version:{uuid.uuid5(uuid.NAMESPACE_URL, artifact_id + ':' + version_basis)}"
        self.connection.execute(
            "INSERT OR IGNORE INTO artifact_versions(id,artifact_id,digest_id,size,mtime_ns,observed_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
            (version_id, artifact_id, digest_id, size, mtime_ns, seen_at, json.dumps(metadata, sort_keys=True)),
        )
        return version_id

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.connection.commit()

    def files(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM files" + ("" if include_deleted else " WHERE deleted=0") + " ORDER BY path"
        return [self._file_dict(row) for row in self.connection.execute(query)]

    def file_by_path(self, path: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM files WHERE path=? AND deleted=0", (path,)).fetchone()
        return self._file_dict(row) if row else None

    def file_by_id(self, file_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return self._file_dict(row) if row else None

    def file_by_alias(self, path: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT f.* FROM aliases a JOIN files f ON f.id=a.file_id WHERE a.path=? ORDER BY a.last_seen DESC LIMIT 1",
            (path,),
        ).fetchone()
        return self._file_dict(row) if row else None

    def files_by_hash(self, sha256: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM files WHERE sha256=? AND deleted=0", (sha256,))
        return [self._file_dict(row) for row in rows]

    @staticmethod
    def _file_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def upsert_file(
        self,
        path: str,
        kind: str,
        label: str,
        size: int | None,
        mtime_ns: int | None,
        sha256: str | None,
        metadata: dict[str, Any],
        seen_at: str,
        file_id: str | None = None,
    ) -> str:
        existing = self.file_by_path(path)
        if existing:
            file_id = existing["id"]
        file_id = file_id or f"file:{uuid.uuid4()}"
        self.connection.execute(
            """INSERT INTO files(id,path,kind,label,size,mtime_ns,sha256,metadata_json,first_seen,last_seen,deleted)
               VALUES(?,?,?,?,?,?,?,?,?,?,0)
               ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,label=excluded.label,size=excluded.size,
               mtime_ns=excluded.mtime_ns,sha256=excluded.sha256,metadata_json=excluded.metadata_json,
               last_seen=excluded.last_seen,deleted=0""",
            (file_id, path, kind, label, size, mtime_ns, sha256, json.dumps(metadata, sort_keys=True), seen_at, seen_at),
        )
        self._sync_artifact_projection(file_id, path, kind, label, size, mtime_ns, sha256, metadata, seen_at)
        return file_id

    def rename_file(self, file_id: str, old_path: str, new_path: str, seen_at: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO aliases(file_id,path,first_seen,last_seen) VALUES(?,?,?,?)",
            (file_id, old_path, seen_at, seen_at),
        )
        self.connection.execute(
            "UPDATE files SET path=?, label=?, last_seen=?, deleted=0 WHERE id=?",
            (new_path, Path(new_path).name, seen_at, file_id),
        )
        self.connection.execute(
            "UPDATE file_locations SET current=0,last_seen=? WHERE artifact_id=? AND path=?",
            (seen_at, file_id, old_path),
        )
        location_id = f"location:{uuid.uuid5(uuid.NAMESPACE_URL, file_id + ':' + new_path)}"
        self.connection.execute(
            "INSERT INTO file_locations(id,artifact_id,path,first_seen,last_seen,current) VALUES(?,?,?,?,?,1) "
            "ON CONFLICT(artifact_id,path) DO UPDATE SET last_seen=excluded.last_seen,current=1",
            (location_id, file_id, new_path, seen_at, seen_at),
        )

    def mark_deleted(self, path: str, seen_at: str) -> None:
        self.connection.execute("UPDATE files SET deleted=1,last_seen=? WHERE path=?", (seen_at, path))
        self.connection.execute("UPDATE file_locations SET current=0,last_seen=? WHERE path=?", (seen_at, path))

    def ensure_virtual(self, node: Node) -> str:
        row = self.connection.execute("SELECT id FROM files WHERE id=?", (node.id,)).fetchone()
        if not row:
            self.connection.execute(
                "INSERT INTO files(id,path,kind,label,metadata_json,deleted) VALUES(?,?,?,?,?,0)",
                (node.id, node.path or node.id, node.kind, node.label, json.dumps(node.metadata, sort_keys=True)),
            )
            self._sync_artifact_projection(node.id, node.path or node.id, node.kind, node.label, None, None, None, node.metadata, None)
        return node.id

    def delete_evidence_for_source(self, source_path: str) -> None:
        self.connection.execute("UPDATE claims SET status='superseded' WHERE source_path=? AND status='active'", (source_path,))
        self.connection.execute("DELETE FROM edges WHERE source_path=?", (source_path,))

    def replace_text(self, file_id: str, records: list[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM file_text WHERE file_id=?", (file_id,))
        if self.fts_available:
            self.connection.execute("DELETE FROM file_text_fts WHERE file_id=?", (file_id,))
        for record in records:
            source = record.get("source", "native")
            text = record.get("text") or ""
            self.connection.execute(
                """INSERT OR REPLACE INTO file_text(file_id,source,text,encoding,engine,confidence,metadata_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    file_id,
                    source,
                    text,
                    record.get("encoding"),
                    record.get("engine"),
                    record.get("confidence"),
                    json.dumps(record.get("metadata", {}), sort_keys=True),
                ),
            )
            if self.fts_available:
                self.connection.execute("INSERT INTO file_text_fts(file_id,source,text) VALUES(?,?,?)", (file_id, source, text))

    def extractor_cache(self, digest_id: str, adapter: str, adapter_version: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload_json FROM extractor_cache WHERE digest_id=? AND adapter=? AND adapter_version=?",
            (digest_id, adapter, adapter_version),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put_extractor_cache(
        self, digest_id: str, adapter: str, adapter_version: str, payload: dict[str, Any], created_at: str
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO extractor_cache(digest_id,adapter,adapter_version,payload_json,created_at) VALUES(?,?,?,?,?)",
            (digest_id, adapter, adapter_version, json.dumps(payload, sort_keys=True), created_at),
        )

    def text_records(self, file_id: str, source: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM file_text WHERE file_id=?"
        params: tuple[Any, ...] = (file_id,)
        if source is not None:
            query += " AND source=?"
            params += (source,)
        query += " ORDER BY source"
        result = []
        for row in self.connection.execute(query, params):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def text_for_file(self, file_id: str, source: str = "native") -> str:
        row = self.connection.execute("SELECT text FROM file_text WHERE file_id=? AND source=?", (file_id, source)).fetchone()
        return row[0] if row else ""

    def search_text(self, query: str, source: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if self.fts_available:
            sql = """SELECT t.file_id,t.source,t.text,f.path,f.kind
                     FROM file_text_fts t JOIN files f ON f.id=t.file_id
                     WHERE file_text_fts MATCH ? AND f.deleted=0"""
            params: list[Any] = [query]
            if source:
                sql += " AND t.source=?"
                params.append(source)
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)
            try:
                rows = self.connection.execute(sql, tuple(params))
                return [{**dict(row), "text": dict(row)["text"][:500]} for row in rows]
            except sqlite3.OperationalError:
                pass
        sql = """SELECT t.file_id,t.source,t.text,f.path,f.kind
                 FROM file_text t JOIN files f ON f.id=t.file_id
                 WHERE lower(t.text) LIKE ? AND f.deleted=0"""
        params = [f"%{query.casefold()}%"]
        if source:
            sql += " AND t.source=?"
            params.append(source)
        sql += " ORDER BY f.path,t.source LIMIT ?"
        params.append(limit)
        return [{**dict(row), "text": dict(row)["text"][:500]} for row in self.connection.execute(sql, tuple(params))]

    def add_edge(self, edge: Edge) -> str:
        score, confidence = aggregate(edge.evidence)
        edge.score, edge.confidence = score, confidence
        active_evidence = [item for item in edge.evidence if item.status == "active"]
        bases = {item.basis for item in active_evidence}
        if "confirmation" in bases:
            edge.basis = "confirmation"
        elif "declaration" in bases and len(bases) == 1:
            edge.basis = "declaration"
        elif "observation" in bases and bases <= {"observation", "declaration"}:
            edge.basis = "observation"
        else:
            edge.basis = "inference"
        edge.assurance = "verified" if confidence == "exact" else {
            "strong": "strong-candidate", "probable": "candidate", "weak": "weak-signal", "unknown": "insufficient",
        }.get(confidence, "candidate")
        edge.observed_at = edge.observed_at or max(
            (item.observed_at or item.collected_at for item in active_evidence), default=None
        )
        if edge.competing_group is None and edge.relation in {
            "was_generated_by", "confirmed_export", "can_generate", "generated", "content_matches",
            "embedded_bytes_match", "candidate_export", "exported_to", "observed_created_during",
            "observed_modified_during", "created_during", "modified_during",
        }:
            edge.competing_group = f"origin:{edge.target}"
        edge.evidence_ids = [item.id for item in edge.evidence if item.id]
        canonical = json.dumps(
            [
                edge.source,
                edge.target,
                edge.relation,
                edge.adapter,
                edge.source_path,
                [
                    {
                        "kind": item.kind,
                        "facts": item.facts,
                        "location": item.location,
                        "signal_group": item.signal_group,
                        "basis": item.basis,
                        "scope": item.scope,
                    }
                    for item in edge.evidence
                ],
            ],
            sort_keys=True,
        )
        edge_id = edge.id or f"edge:{uuid.uuid5(uuid.NAMESPACE_URL, canonical)}"
        if self.connection.execute(
            "SELECT 1 FROM user_decisions WHERE status='active' AND action='reject' AND "
            "(claim_id=? OR (source_id=? AND target_id=? AND relation=?)) LIMIT 1",
            (edge_id, edge.source, edge.target, edge.relation),
        ).fetchone():
            edge.status = "rejected"
        for item in edge.evidence:
            evidence_id = item.id or f"evidence:{uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(item.to_dict(), sort_keys=True, default=str))}"
            self.connection.execute(
                """INSERT OR REPLACE INTO raw_evidence(
                   id,kind,basis,assurance,scope,adapter,adapter_version,mode,facts_json,location_json,
                   signal_group,weight,status,observed_at,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    evidence_id, item.kind, item.basis, item.assurance, item.scope, item.adapter,
                    item.adapter_version, item.mode, json.dumps(item.facts, sort_keys=True),
                    json.dumps(item.location, sort_keys=True) if item.location else None,
                    item.signal_group, item.weight, item.status, item.observed_at, item.collected_at,
                ),
            )
        self.connection.execute(
            """INSERT OR REPLACE INTO edges(
               id,source_id,target_id,relation,score,confidence,mode,adapter,source_path,evidence_json,
               basis,assurance,scope,adapter_version,evidence_ids_json,competing_group,status,observed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edge_id,
                edge.source,
                edge.target,
                edge.relation,
                score,
                confidence,
                edge.mode,
                edge.adapter,
                edge.source_path,
                json.dumps([e.to_dict() for e in edge.evidence], sort_keys=True),
                edge.basis,
                edge.assurance,
                edge.scope,
                edge.adapter_version,
                json.dumps(edge.evidence_ids, sort_keys=True),
                edge.competing_group,
                edge.status,
                edge.observed_at,
            ),
        )
        self.connection.execute(
            """INSERT OR REPLACE INTO claims(
               id,source_id,target_id,relation,basis,assurance,scope,adapter,adapter_version,evidence_ids_json,
               competing_group,status,observed_at,score,confidence,source_path)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edge_id, edge.source, edge.target, edge.relation, edge.basis, edge.assurance, edge.scope,
                edge.adapter, edge.adapter_version, json.dumps(edge.evidence_ids, sort_keys=True),
                edge.competing_group, edge.status, edge.observed_at, score, confidence, edge.source_path,
            ),
        )
        return edge_id

    def edges(self, minimum: float = 0.0, include_inactive: bool = False) -> list[dict[str, Any]]:
        active = "" if include_inactive else " AND status='active'"
        rows = self.connection.execute(f"SELECT * FROM edges WHERE score>=?{active} ORDER BY score DESC,id", (minimum,))
        return [self._edge_dict(row) for row in rows]

    def incoming(self, target_id: str, minimum: float = 0.0) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM edges WHERE target_id=? AND score>=? AND status='active' ORDER BY score DESC,id", (target_id, minimum)
        )
        return [self._edge_dict(row) for row in rows]

    def outgoing(self, source_id: str, minimum: float = 0.0) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM edges WHERE source_id=? AND score>=? AND status='active' ORDER BY score DESC,id", (source_id, minimum)
        )
        return [self._edge_dict(row) for row in rows]

    @staticmethod
    def _edge_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        result["evidence_ids"] = json.loads(result.pop("evidence_ids_json", "[]") or "[]")
        return result

    def add_run(self, run: dict[str, Any]) -> None:
        previous = self.connection.execute("SELECT status FROM runs WHERE id=?", (run["id"],)).fetchone()
        self.connection.execute(
            """INSERT OR REPLACE INTO runs(id,task,started_at,finished_at,cwd,command_json,exit_code,status,changes_json,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                run["id"], run.get("task"), run.get("started_at"), run.get("finished_at"), run.get("cwd"),
                json.dumps(run.get("command"), sort_keys=True), run.get("exit_code"), run.get("status", "complete"),
                json.dumps(run.get("changes", {}), sort_keys=True), json.dumps(run.get("metadata", {}), sort_keys=True),
            ),
        )
        self.connection.execute(
            """INSERT OR REPLACE INTO activities(id,activity_type,state,started_at,finished_at,metadata_json)
               VALUES(?,?,?,?,?,?)""",
            (
                run["id"], "run", run.get("status", "completed"), run.get("started_at"), run.get("finished_at"),
                json.dumps(run.get("metadata", {}), sort_keys=True),
            ),
        )
        if previous is None or previous[0] != run.get("status"):
            self.add_run_transition(run["id"], run.get("status", "completed"), run.get("finished_at") or run.get("started_at"))

    def add_run_transition(self, run_id: str, state: str, observed_at: str | None) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO run_transitions(run_id,state,observed_at) VALUES(?,?,?)",
            (run_id, state, observed_at),
        )

    def runs(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute("SELECT * FROM runs ORDER BY started_at,id"):
            item = dict(row)
            item["command"] = json.loads(item.pop("command_json") or "null")
            item["changes"] = json.loads(item.pop("changes_json") or "{}")
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def run(self, run_id: str) -> dict[str, Any] | None:
        return next((item for item in self.runs() if item["id"] == run_id), None)

    def add_cluster(self, cluster: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO clusters(id,run_id,label,reason,members_json,representatives_json) VALUES(?,?,?,?,?,?)",
            (
                cluster["id"], cluster.get("run_id"), cluster["label"], cluster["reason"],
                json.dumps(cluster["members"], sort_keys=True), json.dumps(cluster["representatives"], sort_keys=True),
            ),
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO output_families(id,label,rule_json,created_at) VALUES(?,?,?,?)",
            (
                cluster["id"], cluster["label"],
                json.dumps({"reason": cluster["reason"], "members": cluster["members"], "representatives": cluster["representatives"]}, sort_keys=True),
                None,
            ),
        )

    def clusters(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query, params = ("SELECT * FROM clusters", ()) if run_id is None else ("SELECT * FROM clusters WHERE run_id=?", (run_id,))
        result = []
        for row in self.connection.execute(query, params):
            item = dict(row)
            item["members"] = json.loads(item.pop("members_json"))
            item["representatives"] = json.loads(item.pop("representatives_json"))
            result.append(item)
        return result

    def add_warning(self, collected_at: str, path: str, adapter: str, message: str) -> None:
        self.connection.execute(
            "INSERT INTO warnings(collected_at,path,adapter,message) VALUES(?,?,?,?)",
            (collected_at, path, adapter, message),
        )

    def delete_adapter_records(self, adapters: set[str]) -> None:
        if not adapters:
            return
        placeholders = ",".join("?" for _ in adapters)
        values = tuple(sorted(adapters))
        self.connection.execute(f"UPDATE claims SET status='superseded' WHERE adapter IN ({placeholders}) AND status='active'", values)
        self.connection.execute(f"DELETE FROM edges WHERE adapter IN ({placeholders})", values)
        removable = []
        for item in self.files(include_deleted=True):
            if item["path"].startswith("@") and item.get("metadata", {}).get("external_adapter") in adapters:
                removable.append(item["id"])
        for node_id in removable:
            self.connection.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id))
            self.connection.execute("DELETE FROM files WHERE id=?", (node_id,))

    def warnings(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM warnings ORDER BY id")]

    def claims(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else " WHERE status='active'"
        result = []
        for row in self.connection.execute(f"SELECT * FROM claims{where} ORDER BY target_id,relation,id"):
            item = dict(row)
            item["evidence_ids"] = json.loads(item.pop("evidence_ids_json") or "[]")
            result.append(item)
        return result

    def raw_evidence(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute("SELECT * FROM raw_evidence ORDER BY id"):
            item = dict(row)
            item["facts"] = json.loads(item.pop("facts_json") or "{}")
            item["location"] = json.loads(item.pop("location_json")) if item.get("location_json") else None
            item.pop("location_json", None)
            result.append(item)
        return result

    def locations(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute("SELECT * FROM file_locations ORDER BY path,id"):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def versions(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute("SELECT * FROM artifact_versions ORDER BY artifact_id,observed_at,id"):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def current_version(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM artifact_versions WHERE artifact_id=? ORDER BY observed_at DESC,id DESC LIMIT 1",
            (artifact_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def decisions(self, include_undone: bool = True) -> list[dict[str, Any]]:
        where = "" if include_undone else " WHERE status='active'"
        return [dict(row) for row in self.connection.execute(f"SELECT * FROM user_decisions{where} ORDER BY created_at,id")]

    def add_decision(
        self,
        action: str,
        created_at: str,
        *,
        claim_id: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
        reason: str | None = None,
        decision_id: str | None = None,
    ) -> str:
        if action not in {"confirm", "reject"}:
            raise ValueError("decision action must be confirm or reject")
        decision_id = decision_id or f"decision:{uuid.uuid4()}"
        self.connection.execute(
            """INSERT INTO user_decisions(id,action,claim_id,source_id,target_id,relation,reason,created_at,status)
               VALUES(?,?,?,?,?,?,?,?, 'active')""",
            (decision_id, action, claim_id, source_id, target_id, relation, reason, created_at),
        )
        if action == "reject" and claim_id:
            self.connection.execute("UPDATE claims SET status='rejected' WHERE id=?", (claim_id,))
            self.connection.execute("UPDATE edges SET status='rejected' WHERE id=?", (claim_id,))
        return decision_id

    def undo_decision(self, decision_id: str, undone_at: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM user_decisions WHERE id=?", (decision_id,)).fetchone()
        if not row:
            raise ValueError(f"decision not found: {decision_id}")
        item = dict(row)
        if item["status"] == "undone":
            return item
        self.connection.execute("UPDATE user_decisions SET status='undone',undone_at=? WHERE id=?", (undone_at, decision_id))
        claim_id = item.get("claim_id")
        if claim_id and item.get("action") == "reject":
            other = self.connection.execute(
                "SELECT 1 FROM user_decisions WHERE claim_id=? AND action='reject' AND status='active' AND id<>?",
                (claim_id, decision_id),
            ).fetchone()
            if not other:
                self.connection.execute("UPDATE claims SET status='active' WHERE id=?", (claim_id,))
                self.connection.execute("UPDATE edges SET status='active' WHERE id=?", (claim_id,))
        elif claim_id and item.get("action") == "confirm":
            self.connection.execute("UPDATE claims SET status='withdrawn' WHERE id=?", (claim_id,))
            self.connection.execute("UPDATE edges SET status='withdrawn' WHERE id=?", (claim_id,))
        return dict(self.connection.execute("SELECT * FROM user_decisions WHERE id=?", (decision_id,)).fetchone())

    def rescore_claims(self) -> dict[str, int]:
        updated = 0
        for claim in self.claims(include_inactive=True):
            evidence: list[Any] = []
            for evidence_id in claim["evidence_ids"]:
                row = self.connection.execute("SELECT * FROM raw_evidence WHERE id=?", (evidence_id,)).fetchone()
                if not row:
                    continue
                item = dict(row)
                from ..model import Evidence
                evidence.append(
                    Evidence(
                        kind=item["kind"], adapter=item["adapter"], mode=item["mode"],
                        facts=json.loads(item["facts_json"] or "{}"), collected_at=item.get("collected_at") or "",
                        location=json.loads(item["location_json"]) if item.get("location_json") else None,
                        weight=float(item["weight"]), signal_group=item["signal_group"], id=item["id"],
                        basis=item["basis"], assurance=item["assurance"], scope=item["scope"],
                        adapter_version=item["adapter_version"], status=item["status"],
                        observed_at=item.get("observed_at"), exact_allowed=item["assurance"] == "verified",
                    )
                )
            score, confidence = aggregate(evidence)
            assurance = "verified" if confidence == "exact" else {
                "strong": "strong-candidate", "probable": "candidate", "weak": "weak-signal", "unknown": "insufficient",
            }.get(confidence, "candidate")
            self.connection.execute("UPDATE claims SET score=?,confidence=?,assurance=? WHERE id=?", (score, confidence, assurance, claim["id"]))
            self.connection.execute("UPDATE edges SET score=?,confidence=?,assurance=? WHERE id=?", (score, confidence, assurance, claim["id"]))
            updated += 1
        return {"claims_rescored": updated}

    def prepare_rebuild(self) -> dict[str, int]:
        """Invalidate derived projections while preserving identity and decisions."""
        preserved = {
            "artifacts": self.connection.execute("SELECT count(*) FROM logical_artifacts").fetchone()[0],
            "versions": self.connection.execute("SELECT count(*) FROM artifact_versions").fetchone()[0],
            "runs": self.connection.execute("SELECT count(*) FROM runs").fetchone()[0],
            "decisions": self.connection.execute("SELECT count(*) FROM user_decisions").fetchone()[0],
            "raw_evidence": self.connection.execute("SELECT count(*) FROM raw_evidence").fetchone()[0],
        }
        with self.transaction():
            for row in self.connection.execute("SELECT id,metadata_json FROM files"):
                metadata = json.loads(row["metadata_json"] or "{}")
                metadata["recognition_version"] = 0
                self.connection.execute("UPDATE files SET metadata_json=? WHERE id=?", (json.dumps(metadata, sort_keys=True), row["id"]))
            self.connection.execute("UPDATE claims SET status='superseded' WHERE status='active' AND adapter<>'user-decision'")
            self.connection.execute("DELETE FROM edges WHERE adapter<>'user-decision'")
            self.connection.execute("DELETE FROM file_text")
            if self.fts_available:
                self.connection.execute("DELETE FROM file_text_fts")
            self.connection.execute("DELETE FROM warnings")
            self.connection.execute("DELETE FROM clusters")
            self.connection.execute("DELETE FROM output_families")
            self.connection.execute("DELETE FROM extractor_cache")
        return preserved

    def find_files(
        self,
        query: str,
        *,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM files WHERE 1=1"
        params: list[Any] = []
        if status == "deleted":
            sql += " AND deleted=1"
        elif status in {None, "current"}:
            sql += " AND deleted=0"
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " AND (lower(path) LIKE ? OR lower(label) LIKE ?) ORDER BY deleted,path LIMIT ?"
        needle = f"%{query.casefold()}%"
        params.extend([needle, needle, max(limit * 3, limit)])
        rows = [self._file_dict(row) for row in self.connection.execute(sql, tuple(params))]
        if len(rows) < limit and query:
            candidates = self.files(include_deleted=status == "deleted")
            present = {item["id"] for item in rows}
            needle_name = query.casefold()
            scored = [
                (
                    difflib.SequenceMatcher(None, needle_name, Path(item["path"]).name.casefold()).ratio(),
                    item,
                )
                for item in candidates
                if item["id"] not in present and (not kind or item["kind"] == kind)
            ]
            # Sort on the ratio alone; tied ratios must never fall through to
            # comparing the file dictionaries, and path keeps ordering stable.
            scored.sort(key=lambda pair: (-pair[0], pair[1]["path"]))
            rows.extend(item for ratio, item in scored if ratio >= FUZZY_MATCH_MINIMUM_RATIO)
        return rows[:limit]

    def graph(self, minimum: float = 0.0) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_revision": "artifact-v2",
            "nodes": self.files(include_deleted=True),
            "edges": self.edges(minimum),
            "runs": self.runs(),
            "run_transitions": [dict(row) for row in self.connection.execute("SELECT * FROM run_transitions ORDER BY id")],
            "clusters": self.clusters(),
            "warnings": self.warnings(),
            "logical_artifacts": [dict(row) for row in self.connection.execute("SELECT * FROM logical_artifacts ORDER BY id")],
            "artifact_versions": self.versions(),
            "file_locations": self.locations(),
            "claims": self.claims(include_inactive=True),
            "evidence": self.raw_evidence(),
            "output_families": [dict(row) for row in self.connection.execute("SELECT * FROM output_families ORDER BY id")],
            "user_decisions": self.decisions(),
            "external_entities": [dict(row) for row in self.connection.execute("SELECT * FROM external_entities ORDER BY id")],
        }
