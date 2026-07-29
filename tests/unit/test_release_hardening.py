from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "skills/trace-file-lineage/scripts"
CLI = CORE / "lineage.py"
sys.path.insert(0, str(CORE))

from lineage_core.capture import pending_captures, record, run_command, write_snapshot  # noqa: E402
from lineage_core.config import Config  # noqa: E402
from lineage_core.query import receipt, reproduce, why  # noqa: E402
from lineage_core.renderers.obsidian import export_obsidian  # noqa: E402
from lineage_core.scanner import scan  # noqa: E402
from lineage_core.storage import Store  # noqa: E402


class SchemaAndSemanticsTests(unittest.TestCase):
    def test_legacy_database_migrates_without_data_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "lineage.db"
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO meta VALUES('schema_version','1');
                CREATE TABLE files(
                  id TEXT PRIMARY KEY,path TEXT UNIQUE,kind TEXT,label TEXT,size INTEGER,mtime_ns INTEGER,
                  sha256 TEXT,metadata_json TEXT,first_seen TEXT,last_seen TEXT,deleted INTEGER
                );
                CREATE TABLE edges(
                  id TEXT PRIMARY KEY,source_id TEXT,target_id TEXT,relation TEXT,score REAL,confidence TEXT,
                  mode TEXT,adapter TEXT,source_path TEXT,evidence_json TEXT
                );
                CREATE TABLE runs(
                  id TEXT PRIMARY KEY,task TEXT,started_at TEXT,finished_at TEXT,cwd TEXT,command_json TEXT,
                  exit_code INTEGER,status TEXT,changes_json TEXT,metadata_json TEXT
                );
                INSERT INTO files VALUES(
                  'file:legacy','旧 文件.txt','document','旧 文件.txt',3,1,'abc','{}','2026-01-01Z','2026-01-01Z',0
                );
                """
            )
            connection.commit()
            connection.close()
            with Store(db) as store:
                self.assertEqual(store.file_by_path("旧 文件.txt")["id"], "file:legacy")
                self.assertTrue(store.current_version("file:legacy"))
                self.assertEqual(store.get_meta("model_revision"), "artifact-v2")
                tables = {row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"logical_artifacts", "artifact_versions", "file_locations", "claims", "raw_evidence", "user_decisions"} <= tables)

    def test_static_writer_is_a_candidate_not_verified_causality(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "make.py").write_text("from pathlib import Path\nPath('result.txt').write_text('x')\n", encoding="utf-8")
            (root / "result.txt").write_text("x", encoding="utf-8")
            with Store(root / ".file-lineage/lineage.db") as store:
                scan(Config(root), store)
                result = why(store, "result.txt", 0.0)
                self.assertEqual(result["best"]["relation"], "can_generate")
                self.assertEqual(result["best"]["basis"], "inference")
                self.assertNotEqual(result["best"]["assurance"], "verified")
                self.assertFalse(result["unique_producer_supported"])

    def test_direct_runtime_receipt_and_safe_reproduction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = Config(root)
            with Store(config.db_path) as store:
                exit_code = run_command(
                    config,
                    store,
                    "produce Unicode output",
                    [sys.executable, "-c", "from pathlib import Path; Path('产物 (final).txt').write_text('ok', encoding='utf-8')"],
                )
                self.assertEqual(exit_code, 0)
                scan(config, store)
                origin = why(store, "产物 (final).txt", 0.0)
                self.assertTrue(origin["unique_producer_supported"])
                self.assertEqual(origin["best"]["relation"], "was_generated_by")
                self.assertEqual(origin["best"]["assurance"], "verified")
                run_id = origin["best"]["source_id"]
                task_receipt = receipt(store, run_id)
                self.assertEqual(task_receipt["manifest_count"], 1)
                plan = reproduce(store, "产物 (final).txt")
                self.assertTrue(plan["dry_run"])
                self.assertFalse(plan["will_execute"])
                self.assertIsInstance(plan["command"], list)

    def test_manual_boundary_is_observation_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = Config(root)
            before = root / "before.json"
            write_snapshot(config, before)
            (root / "boundary.txt").write_text("created", encoding="utf-8")
            with Store(config.db_path) as store:
                run = record(config, store, before, "manual boundary")
                edges = store.outgoing(run["id"])
                self.assertEqual({edge["relation"] for edge in edges}, {"observed_created_during"})
                self.assertTrue(all(edge["assurance"] != "verified" for edge in edges))

    def test_copy_is_distinct_and_captured_rename_preserves_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("same", encoding="utf-8")
            (root / "b.txt").write_text("same", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                a_id = store.file_by_path("a.txt")["id"]
                b_id = store.file_by_path("b.txt")["id"]
                self.assertNotEqual(a_id, b_id)
                before = root / "rename-before.json"
                write_snapshot(config, before)
                (root / "a.txt").rename(root / "c (重命名).txt")
                record(config, store, before, "captured rename")
                scan(config, store)
                self.assertEqual(store.file_by_path("c (重命名).txt")["id"], a_id)
                self.assertEqual(store.file_by_path("b.txt")["id"], b_id)

    def test_decisions_survive_rescore_and_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "make.py").write_text("open('out.txt', 'w').write('x')\n", encoding="utf-8")
            (root / "out.txt").write_text("x", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                claim = why(store, "out.txt", 0.0)["best"]
                with store.transaction():
                    decision = store.add_decision("reject", "2026-01-01Z", claim_id=claim["id"], reason="wrong producer")
                    store.rescore_claims()
                self.assertFalse(any(item["id"] == claim["id"] for item in store.edges(include_inactive=False)))
                store.prepare_rebuild()
                scan(config, store)
                regenerated = next(item for item in store.claims(include_inactive=True) if item["id"] == claim["id"])
                self.assertEqual(regenerated["status"], "rejected")
                with store.transaction():
                    store.undo_decision(decision, "2026-01-02Z")
                self.assertTrue(any(item["id"] == claim["id"] for item in store.edges()))

    def test_captured_create_modify_delete_recall_is_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "modify.txt").write_text("before", encoding="utf-8")
            (root / "delete.txt").write_text("before", encoding="utf-8")
            config = Config(root)
            before = root / "change-before.json"
            write_snapshot(config, before)
            (root / "created.txt").write_text("new", encoding="utf-8")
            (root / "modify.txt").write_text("after", encoding="utf-8")
            (root / "delete.txt").unlink()
            with Store(config.db_path) as store:
                run = record(config, store, before, "all change types")
                self.assertEqual(run["changes"]["created"], ["created.txt"])
                self.assertEqual(run["changes"]["modified"], ["modify.txt"])
                self.assertEqual(run["changes"]["deleted"], ["delete.txt"])

    def test_overlapping_boundaries_remain_temporal_not_causal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = Config(root)
            first, second = root / "first.json", root / "second.json"
            write_snapshot(config, first)
            write_snapshot(config, second)
            (root / "shared-window.txt").write_text("x", encoding="utf-8")
            with Store(config.db_path) as store:
                run_a = record(config, store, first, "overlap A")
                run_b = record(config, store, second, "overlap B")
                edges = store.outgoing(run_a["id"]) + store.outgoing(run_b["id"])
                self.assertTrue(edges)
                self.assertEqual({edge["relation"] for edge in edges}, {"observed_created_during"})
                self.assertFalse(any(edge["assurance"] == "verified" for edge in edges))

    def test_timestamp_alone_never_creates_an_export_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "same-name.md", root / "same-name.pdf"
            source.write_text("unrelated source", encoding="utf-8")
            target.write_bytes(b"%PDF-1.4\n%%EOF")
            stamp = 1_700_000_000
            os.utime(source, (stamp, stamp))
            os.utime(target, (stamp, stamp))
            with Store(root / ".file-lineage/lineage.db") as store:
                scan(Config(root), store)
                document_edges = [edge for edge in store.edges() if edge["adapter"] == "document"]
                self.assertEqual(document_edges, [])

    def test_full_scan_rehashes_when_size_and_mtime_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "same-metadata.txt"
            target.write_text("first", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                original = store.file_by_path(target.name)
                original_stat = target.stat()
                target.write_text("other", encoding="utf-8")
                os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                ordinary = scan(config, store)
                self.assertEqual(ordinary.reused, 1)
                self.assertEqual(store.file_by_path(target.name)["sha256"], original["sha256"])
                forced = scan(config, store, full=True)
                self.assertTrue(forced.full_rehash)
                self.assertEqual(forced.changed, 1)
                self.assertNotEqual(store.file_by_path(target.name)["sha256"], original["sha256"])

    def test_sqlite_uses_wal_and_bounded_lock_wait(self):
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp) / "lineage.db") as store:
                self.assertEqual(store.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(store.connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_confirm_reject_and_undo_are_persistent_and_authoritative(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "maker.py").write_text("open('out.txt','w').write('x')", encoding="utf-8")
            (root / "out.txt").write_text("x", encoding="utf-8")
            subprocess.run([sys.executable, str(CLI), "scan", "--root", str(root)], check=True, capture_output=True, text=True)
            confirmed = subprocess.run(
                [sys.executable, str(CLI), "confirm", "--root", str(root), "--source", "maker.py", "--target", "out.txt", "--reason", "operator witnessed export"],
                check=True, capture_output=True, text=True,
            )
            confirmation = json.loads(confirmed.stdout)
            with Store(root / ".file-lineage/lineage.db") as store:
                self.assertTrue(why(store, "out.txt", 0.0)["unique_producer_supported"])
            rejected = subprocess.run(
                [sys.executable, str(CLI), "reject", confirmation["claim_id"], "--root", str(root), "--reason", "review pending"],
                check=True, capture_output=True, text=True,
            )
            rejection = json.loads(rejected.stdout)
            with Store(root / ".file-lineage/lineage.db") as store:
                self.assertFalse(why(store, "out.txt", 0.0)["unique_producer_supported"])
            subprocess.run(
                [sys.executable, str(CLI), "undo", rejection["decision_id"], "--root", str(root)],
                check=True, capture_output=True, text=True,
            )
            with Store(root / ".file-lineage/lineage.db") as store:
                self.assertTrue(why(store, "out.txt", 0.0)["unique_producer_supported"])
            subprocess.run(
                [sys.executable, str(CLI), "undo", confirmation["decision_id"], "--root", str(root)],
                check=True, capture_output=True, text=True,
            )
            with Store(root / ".file-lineage/lineage.db") as store:
                self.assertFalse(why(store, "out.txt", 0.0)["unique_producer_supported"])


class RecoveryAndExporterTests(unittest.TestCase):
    def test_forced_termination_at_four_boundaries_is_recoverable(self):
        points = (
            "after_created_before_snapshot",
            "after_snapshot_before_in_progress",
            "after_in_progress_before_child",
            "after_child_before_finalize",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                env = dict(os.environ)
                env["TRACE_FILE_LINEAGE_TEST_TERMINATE_AT"] = point
                process = subprocess.run(
                    [
                        sys.executable,
                        str(CLI),
                        "run",
                        "--root",
                        str(root),
                        "--task",
                        point,
                        "--",
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('crash-output.txt').write_text('x')",
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(process.returncode, 99)
                config = Config(root)
                pending = pending_captures(config)
                self.assertEqual(len(pending), 1)
                recovered = subprocess.run(
                    [sys.executable, str(CLI), "recover", "--root", str(root), "--run-id", pending[0]["run_id"], "--status", "recovered"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                payload = json.loads(recovered.stdout)
                self.assertIn(payload["status"], {"recovered", "incomplete"})
                with Store(config.db_path) as store:
                    self.assertFalse(any(edge["assurance"] == "verified" for edge in store.outgoing(payload["id"])))

    def test_obsidian_preserves_user_edits_and_remains_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root, destination = base / "workspace", base / "vault/Trace File Lineage Test"
            root.mkdir(parents=True)
            (root / "note.md").write_text("hello", encoding="utf-8")
            with Store(root / ".file-lineage/lineage.db") as store:
                scan(Config(root), store)
                first = export_obsidian(store.graph(), destination)
                manifest = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
                node_id = store.file_by_path("note.md")["id"]
                owned_note = destination / manifest["owned"][node_id]
                owned_note.write_text(owned_note.read_text(encoding="utf-8") + "\nUser edit.\n", encoding="utf-8")
                second = export_obsidian(store.graph(), destination)
                self.assertTrue(second["preserved_user_edit_conflicts"])
                self.assertIn("User edit.", owned_note.read_text(encoding="utf-8"))
                before = {path.name: path.read_bytes() for path in destination.iterdir() if path.is_file()}
                third = export_obsidian(store.graph(), destination)
                after = {path.name: path.read_bytes() for path in destination.iterdir() if path.is_file()}
                self.assertEqual(before, after)
                self.assertFalse(third["preserved_user_edit_conflicts"])

    def test_archive_bomb_degrades_to_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "suspicious.docx"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", b"A" * (1024 * 1024))
            with Store(root / ".file-lineage/lineage.db") as store:
                result = scan(Config(root), store)
                item = store.file_by_path("suspicious.docx")
                self.assertEqual(item["metadata"]["document_status"], "metadata-only")
                self.assertTrue(any("compression ratio" in warning.message for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
