from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.capabilities import capability_matrix
from lineage_core.config import Config
from lineage_core.evidence import fact
from lineage_core.scanner import scan
from lineage_core.scoring import aggregate
from lineage_core.storage import Store
from lineage_core.adapters.text import TEXT_SUFFIXES
from lineage_core.adapters.documents import inspect_pdf
from lineage_core.privacy import private_reference


def scan_root(root: Path, *, ocr: bool = False) -> tuple[dict, list[dict], list[dict]]:
    config = Config(root, ocr_enabled=ocr)
    with Store(config.db_path) as store:
        result = scan(config, store)
        return result.to_dict(), store.files(), store.edges()


class TextRecognitionTests(unittest.TestCase):
    def test_p0_native_text_suffixes_are_registered(self):
        expected = {
            ".txt", ".log", ".md", ".rst", ".adoc", ".org", ".tex", ".json", ".jsonl", ".yaml", ".yml",
            ".toml", ".ini", ".cfg", ".xml", ".csv", ".tsv", ".html", ".css", ".scss", ".svg", ".sh",
            ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".py", ".js", ".ts", ".sql", ".r", ".m", ".java",
            ".c", ".cpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".jl",
        }
        self.assertTrue(expected <= TEXT_SUFFIXES)

    def test_utf8_utf16_chinese_spaces_and_parentheses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            utf8 = root / "中文 资料" / "(final) UTF-8.txt"
            utf16 = root / "中文 资料" / "(final) UTF-16.txt"
            utf8.parent.mkdir(parents=True)
            utf8.write_text("原生文本 data/source.csv", encoding="utf-8")
            utf16.write_bytes("第二份文本 figures/final.png".encode("utf-16"))
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                first = store.file_by_path("中文 资料/(final) UTF-8.txt")
                second = store.file_by_path("中文 资料/(final) UTF-16.txt")
                self.assertEqual(first["metadata"]["recognition"]["native_encoding"], "utf-8")
                self.assertEqual(second["metadata"]["recognition"]["native_encoding"], "utf-16")
                self.assertEqual(store.text_records(second["id"], "native")[0]["source"], "native")
                self.assertEqual(store.search_text("第二份文本")[0]["path"], "中文 资料/(final) UTF-16.txt")

    def test_undecodable_file_is_metadata_only_with_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "broken.txt").write_bytes(b"\x80\x81\x82")
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                item = store.file_by_path("broken.txt")
                self.assertEqual(item["metadata"]["recognition"]["native_text"], "metadata-only")
                self.assertEqual(store.text_records(item["id"]), [])
                self.assertTrue(any("metadata-only fallback" in warning.message for warning in result.warnings))

    def test_generic_source_is_not_mislabeled_syntax_aware(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main.go").write_text('package main\nvar source = "data/input.csv"\n', encoding="utf-8")
            (root / "data").mkdir()
            (root / "data/input.csv").write_text("x\n1\n", encoding="utf-8")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                item = store.file_by_path("main.go")
                recognition = item["metadata"]["recognition"]
                self.assertFalse(recognition["syntax_aware_lineage"])
                self.assertEqual(recognition["static_lineage_level"], "explicit-reference-only")
                references = [edge for edge in store.edges() if edge["source_path"] == "main.go"]
                self.assertTrue(references)
                self.assertTrue(all(edge["adapter"] == "text-reference" for edge in references))
                self.assertTrue(all(edge["relation"] == "references" for edge in references))

    def test_javascript_token_parser_ignores_comments_and_tracks_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main.ts").write_text(
                "// fs.writeFileSync('fake.png', data)\n"
                "const note = \"fs.writeFileSync('also-fake.png', data)\";\n"
                "fs.writeFileSync('real.png', data);\n",
                encoding="utf-8",
            )
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                edges = [edge for edge in store.edges() if edge["adapter"] == "javascript"]
                targets = {store.file_by_id(edge["target_id"])["metadata"].get("expected_path") for edge in edges}
                self.assertEqual(targets, {"real.png"})
                recognition = store.file_by_path("main.ts")["metadata"]["recognition"]
                self.assertFalse(recognition["syntax_aware_lineage"])
                self.assertEqual(recognition["capability_tier"], "conservative-static-token")


class StructuredDocumentTests(unittest.TestCase):
    def test_pdf_literal_fallback_without_optional_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fallback.pdf"
            path.write_bytes(b"%PDF-1.4\nBT (fallback searchable PDF text) Tj ET\n%%EOF")
            with mock.patch("lineage_core.adapters.documents.importlib.util.find_spec", return_value=None):
                text, structure, warnings = inspect_pdf(path)
            self.assertEqual(structure["parser"], "literal-fallback")
            self.assertEqual(structure["status"], "degraded-literal-text")
            self.assertIn("fallback searchable PDF text", text)
            self.assertEqual(warnings, [])

    def test_xlsx_structure_formula_chart_and_external_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "book.xlsx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "xl/workbook.xml",
                    '<workbook xmlns="urn:x"><sheets><sheet name="数据 Sheet" sheetId="1"/></sheets></workbook>',
                )
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    '<worksheet xmlns="urn:x"><sheetData><row><c><f>SUM(A1:A2)</f><v>3</v></c></row></sheetData></worksheet>',
                )
                archive.writestr("xl/charts/chart1.xml", '<chart xmlns="urn:x"/>')
                archive.writestr(
                    "xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="urn:r"><Relationship Target="data/source.csv" TargetMode="External"/></Relationships>',
                )
                archive.writestr("xl/media/image1.png", b"image")
            config = Config(root)
            with Store(config.db_path) as store:
                scan(config, store)
                item = store.file_by_path("book.xlsx")
                structure = item["metadata"]["document_structure"]
                self.assertEqual(structure["sheet_names"], ["数据 Sheet"])
                self.assertEqual(structure["formula_count"], 1)
                self.assertEqual(structure["charts"], 1)
                self.assertEqual(len(item["metadata"]["embedded_media_sha256"]), 1)
                self.assertEqual(item["metadata"]["external_links"], ["data/source.csv"])
                formula_edges = [edge for edge in store.edges() if "SUM(A1:A2)" in json.dumps(edge["evidence"])]
                self.assertEqual(formula_edges, [])

    def test_odf_epub_malformed_encrypted_and_unsupported_degrade_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "notes.odt", "w") as archive:
                archive.writestr("content.xml", '<document xmlns="urn:o"><p>ODF searchable text</p></document>')
                archive.writestr("meta.xml", '<meta xmlns="urn:o"><title>Notes</title></meta>')
            with zipfile.ZipFile(root / "book.epub", "w") as archive:
                archive.writestr("chapter.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body>EPUB searchable text</body></html>')
                archive.writestr("content.opf", '<package xmlns="urn:o"><title>Book</title></package>')
            (root / "bad.docx").write_bytes(b"not-a-zip")
            (root / "locked.pdf").write_bytes(b"%PDF-1.4\n/Encrypt 4 0 R\n%%EOF")
            (root / "legacy.pages").write_bytes(b"proprietary")
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                self.assertEqual(store.search_text("ODF searchable")[0]["path"], "notes.odt")
                self.assertEqual(store.search_text("EPUB searchable")[0]["path"], "book.epub")
                self.assertEqual(store.file_by_path("locked.pdf")["metadata"]["document_status"], "encrypted-metadata-only")
                self.assertEqual(store.file_by_path("legacy.pages")["metadata"]["recognition"]["metadata_fingerprint"], "indexed")
                messages = [warning.message for warning in result.warnings]
                self.assertTrue(any("document parse failed" in message for message in messages))
                self.assertTrue(any("encrypted or password-protected" in message for message in messages))


class OCRAndCapabilityTests(unittest.TestCase):
    def test_ocr_evidence_alone_never_becomes_exact(self):
        score, label = aggregate([fact("ocr-text-match", "ocr", "content", {}, weight=1.0, signal_group="ocr")])
        self.assertLess(score, 1.0)
        self.assertNotEqual(label, "exact")

    def test_ocr_text_is_stored_separately_from_native_text(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Config(Path(temp))
            with Store(config.db_path) as store:
                file_id = store.upsert_file("screen.png", "image", "screen.png", 1, 1, "hash", {}, "now")
                store.replace_text(
                    file_id,
                    [
                        {"source": "native", "text": "native", "encoding": "utf-8"},
                        {"source": "ocr", "text": "识别文本", "engine": "fixture-ocr", "confidence": 0.81},
                    ],
                )
                records = store.text_records(file_id)
                self.assertEqual([record["source"] for record in records], ["native", "ocr"])
                self.assertEqual(records[1]["engine"], "fixture-ocr")
                self.assertEqual(records[1]["confidence"], 0.81)

    def test_doctor_matrix_separates_syntax_aware_and_text_only(self):
        matrix = capability_matrix()
        python = next(row for row in matrix if row["formats"] == [".py"])
        javascript = next(row for row in matrix if ".ts" in row["formats"])
        generic = next(row for row in matrix if ".go" in row["formats"])
        self.assertIn("syntax-aware", python["static_lineage_extraction"])
        self.assertEqual(javascript["capability_tier"], "conservative-static-token")
        self.assertIn("not syntax-aware", javascript["static_lineage_extraction"])
        self.assertIn("not syntax-aware", generic["static_lineage_extraction"])


class PackagingTests(unittest.TestCase):
    def test_one_canonical_skill_and_documented_manifests(self):
        skills = list((REPO / "skills").glob("**/SKILL.md"))
        self.assertEqual(skills, [REPO / "skills/trace-file-lineage/SKILL.md"])
        self.assertEqual(json.loads((REPO / ".codex-plugin/plugin.json").read_text())["name"], "trace-file-lineage")
        self.assertEqual(json.loads((REPO / ".claude-plugin/plugin.json").read_text())["name"], "trace-file-lineage")

    def test_platform_hook_dispatch_records_equivalent_task_boundaries(self):
        for platform in ("codex", "claude-code"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                env = dict(os.environ)
                env.pop("PLUGIN_ROOT", None)
                env.pop("PLUGIN_DATA", None)
                env.pop("CLAUDE_PLUGIN_ROOT", None)
                env.pop("CLAUDE_PLUGIN_DATA", None)
                if platform == "codex":
                    env["PLUGIN_ROOT"] = str(REPO)
                    env["PLUGIN_DATA"] = str(root / "plugin-data")
                else:
                    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
                    env["CLAUDE_PLUGIN_DATA"] = str(root / "plugin-data")
                common = {"cwd": str(root), "session_id": "session", "turn_id": "turn"}
                start = json.dumps(common | {"hook_event_name": "UserPromptSubmit", "prompt": "Create output"})
                subprocess.run(
                    [sys.executable, str(REPO / "platforms/hook_dispatch.py")],
                    input=start,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                with Store(root / ".file-lineage/lineage.db") as store:
                    pending = store.runs()
                    self.assertEqual(len(pending), 1)
                    self.assertEqual(pending[0]["status"], "in_progress")
                (root / "output.txt").write_text("done", encoding="utf-8")
                stop = json.dumps(common | {"hook_event_name": "Stop"})
                subprocess.run(
                    [sys.executable, str(REPO / "platforms/hook_dispatch.py")],
                    input=stop,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                with Store(root / ".file-lineage/lineage.db") as store:
                    runs = store.runs()
                    self.assertEqual(len(runs), 1)
                    self.assertEqual(runs[0]["status"], "completed")
                    self.assertEqual(runs[0]["metadata"]["platform"], platform)
                    self.assertEqual(runs[0]["changes"]["created"], ["output.txt"])

    def test_missed_stop_is_offered_and_explicitly_recovered_without_exact_edges(self):
        for platform in ("codex", "claude-code"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                env = dict(os.environ)
                env.pop("PLUGIN_ROOT", None)
                env.pop("PLUGIN_DATA", None)
                env.pop("CLAUDE_PLUGIN_ROOT", None)
                env.pop("CLAUDE_PLUGIN_DATA", None)
                if platform == "codex":
                    env["PLUGIN_ROOT"] = str(REPO)
                    env["PLUGIN_DATA"] = str(root / "plugin-data")
                else:
                    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
                    env["CLAUDE_PLUGIN_DATA"] = str(root / "plugin-data")

                first_payload = {
                    "cwd": str(root),
                    "session_id": "session",
                    "turn_id": "interrupted-turn",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Create interrupted output",
                }
                subprocess.run(
                    [sys.executable, str(REPO / "platforms/hook_dispatch.py")],
                    input=json.dumps(first_payload),
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                (root / "interrupted-output.txt").write_text("partial", encoding="utf-8")

                second_payload = first_payload | {
                    "turn_id": "next-turn",
                    "prompt": "Continue after interruption",
                }
                offered = subprocess.run(
                    [sys.executable, str(REPO / "platforms/hook_dispatch.py")],
                    input=json.dumps(second_payload),
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                offer = json.loads(offered.stdout)
                context = offer["hookSpecificOutput"]["additionalContext"]
                self.assertIn("lineage recover", context)
                self.assertIn("never exact command traces", context)

                with Store(root / ".file-lineage/lineage.db") as store:
                    runs = store.runs()
                    first_run = next(
                        item for item in runs
                        if item["metadata"].get("turn_ref") == private_reference("interrupted-turn", "turn")
                    )
                    self.assertEqual(first_run["status"], "in_progress")

                recovered = subprocess.run(
                    [
                        sys.executable,
                        str(SKILL_SCRIPTS / "lineage.py"),
                        "recover",
                        "--root",
                        str(root),
                        "--run-id",
                        first_run["id"],
                        "--status",
                        "recovered",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                recovered_run = json.loads(recovered.stdout)
                self.assertEqual(recovered_run["status"], "recovered")
                self.assertEqual(recovered_run["changes"]["created"], ["interrupted-output.txt"])
                with Store(root / ".file-lineage/lineage.db") as store:
                    edges = store.outgoing(first_run["id"])
                    self.assertTrue(edges)
                    self.assertTrue(all(edge["confidence"] != "exact" for edge in edges))
                    self.assertTrue(all(edge["score"] < 1.0 for edge in edges))
                    kinds = {fact["kind"] for edge in edges for fact in edge["evidence"]}
                    self.assertEqual(kinds, {"recovered-task-boundary-diff"})

    def test_codex_and_claude_wrappers_emit_equivalent_normalized_graphs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            outputs = []
            wrappers = [REPO / "platforms/codex/lineage.py", REPO / "platforms/claude-code/lineage.py"]
            for index, wrapper in enumerate(wrappers):
                root = base / f"fixture-{index}"
                (root / "data").mkdir(parents=True)
                (root / "data/input.csv").write_text("x\n1\n", encoding="utf-8")
                (root / "render.py").write_text("import pandas as pd\npd.read_csv('data/input.csv').to_csv('result.csv')\n", encoding="utf-8")
                (root / "result.csv").write_text("x\n1\n", encoding="utf-8")
                subprocess.run([sys.executable, str(wrapper), "scan", "--root", str(root)], check=True, capture_output=True, text=True)
                output = base / f"graph-{index}.json"
                subprocess.run(
                    [sys.executable, str(wrapper), "export", "--root", str(root), "--format", "json", "--normalized", "--destination", str(output)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append(json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(outputs[0], outputs[1])

    def test_core_cli_requires_no_vendor_api(self):
        forbidden = {"openai", "anthropic"}
        imports: set[str] = set()
        core = SKILL_SCRIPTS / "lineage_core"
        for path in core.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", 1)[0])
        self.assertFalse(imports & forbidden)
        env = {key: value for key, value in os.environ.items() if key not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}}
        result = subprocess.run(
            [sys.executable, str(SKILL_SCRIPTS / "lineage.py"), "doctor", "--root", str(REPO)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertFalse(json.loads(result.stdout)["vendor_api_required"])


if __name__ == "__main__":
    unittest.main()
