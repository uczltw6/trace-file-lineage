from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.capture import compare, redact_command, run_command
from lineage_core.config import Config
from lineage_core.evidence import fact
from lineage_core.identity import comparable_path, normalize_relative
from lineage_core.index import plan
from lineage_core.scoring import aggregate, confidence_label
from lineage_core.storage import Store


class IdentityTests(unittest.TestCase):
    def test_windows_and_unicode_normalization(self):
        self.assertEqual(normalize_relative(r"C:\研究\a b\x.txt"), "研究/a b/x.txt")
        self.assertEqual(normalize_relative("e\u0301.txt"), "é.txt")

    def test_comparable_case(self):
        self.assertEqual(comparable_path("A/B.TXT", False), comparable_path("a/b.txt", False))


class ScoringTests(unittest.TestCase):
    def test_correlated_signals_do_not_inflate(self):
        evidence = [fact("stem", "test", "heuristic", {}, weight=0.4, signal_group="name") for _ in range(4)]
        score, label = aggregate(evidence)
        self.assertEqual(score, 0.4)
        self.assertEqual(label, "weak")

    def test_independent_evidence_combines(self):
        evidence = [
            fact("text", "test", "content", {}, weight=0.65, signal_group="text"),
            fact("media", "test", "content", {}, weight=0.70, signal_group="media"),
        ]
        score, label = aggregate(evidence)
        self.assertGreaterEqual(score, 0.8)
        self.assertEqual(label, "strong")

    def test_exact_requires_explicit_causal_authorization(self):
        inferred = aggregate([fact("task", "test", "captured", {}, weight=1.0)])
        self.assertEqual(inferred, (0.99, "strong"))
        score, label = aggregate([
            fact(
                "task", "test", "captured", {}, weight=1.0, basis="confirmation",
                assurance="verified", exact_allowed=True,
            )
        ])
        self.assertEqual((score, label), (1.0, "exact"))
        self.assertEqual(confidence_label(0.29), "unknown")


class CaptureTests(unittest.TestCase):
    def test_compare_rename_by_unique_hash(self):
        before = {"files": {"old.txt": {"sha256": "a", "bytes": 1}}}
        after = {"files": {"new.txt": {"sha256": "a", "bytes": 1}}}
        changes = compare(before, after)
        self.assertEqual(changes["renamed"][0]["from"], "old.txt")
        self.assertEqual(changes["created"], [])

    def test_redacts_sensitive_arguments(self):
        self.assertEqual(redact_command(["tool", "--token=abc"]), ["tool", "--token=[REDACTED]"])
        self.assertEqual(
            redact_command(["tool", "--password", "abc", "https://user:secret@example.invalid/path"]),
            ["tool", "--password", "[REDACTED]", "https://user:[REDACTED]@example.invalid/path"],
        )

    def test_child_exit_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            with Store(config.db_path) as store:
                code = run_command(config, store, "exit test", [sys.executable, "-c", "raise SystemExit(7)"])
                self.assertEqual(code, 7)
                self.assertEqual(store.runs()[0]["exit_code"], 7)


class ConfigTests(unittest.TestCase):
    def test_secret_and_cache_exclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            self.assertTrue(config.excluded(".env"))
            self.assertTrue(config.excluded("node_modules/x.js"))
            self.assertFalse(config.excluded("src/x.py"))

    def test_incremental_plan(self):
        value = plan({"a": (1, 1), "b": (2, 2)}, {"a": (1, 1), "b": (3, 3), "c": (1, 1)})
        self.assertEqual(value.reused, ("a",))
        self.assertEqual(value.changed, ("b",))
        self.assertEqual(value.added, ("c",))


if __name__ == "__main__":
    unittest.main()
