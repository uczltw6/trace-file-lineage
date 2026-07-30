from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.config import Config
from lineage_core.query import why
from lineage_core.scanner import scan
from lineage_core.storage import Store

from tests.fixtures.generate_pdf_fixture import APPENDIX_TEXT, OCR_TEXT, generate

FIXTURE_DEPENDENCIES = ("pypdf", "PIL", "reportlab", "docx")


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in FIXTURE_DEPENDENCIES), "PDF runtime fixture dependencies are not installed")
class PDFRuntimeIntegrationTests(unittest.TestCase):
    def test_real_pypdf_extraction_media_similarity_and_origin_ranking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate(root)
            config = Config(root)
            with Store(config.db_path) as store:
                result = scan(config, store)
                self.assertFalse(result.warnings)
                pdf = store.file_by_path("submission_final.pdf")
                source = store.file_by_path("proposal_master.docx")
                self.assertEqual(pdf["metadata"]["document_structure"]["parser"], "pypdf")
                self.assertEqual(pdf["metadata"]["document_status"], "extracted")
                self.assertGreater(pdf["metadata"]["text_length"], 200)
                self.assertIn("deterministic PDF integration fixture", store.text_for_file(pdf["id"], "native"))
                self.assertTrue(pdf["metadata"]["embedded_media_sha256"])
                self.assertTrue(pdf["metadata"]["embedded_media_fingerprints"])
                shared_media = set(pdf["metadata"]["embedded_media_fingerprints"]) & set(
                    source["metadata"]["embedded_media_fingerprints"]
                )
                self.assertTrue(shared_media)
                self.assertGreaterEqual(source["metadata"]["document_structure"]["tables"], 1)
                self.assertEqual(source["metadata"]["document_properties"]["creator"], "Trace File Lineage")
                ranked = why(store, "submission_final.pdf")
                self.assertEqual(ranked["best"]["source"]["path"], "proposal_master.docx")
                kinds = {item["kind"] for item in ranked["best"]["evidence"]}
                self.assertIn("normalized-text-similarity", kinds)
                self.assertIn("embedded-media-fingerprint-match", kinds)
                self.assertNotEqual(ranked["best"]["confidence"], "exact")
                self.assertFalse(ranked["unique_producer_supported"])
                post_edited = why(store, "submission_post_edited.pdf")
                self.assertEqual(post_edited["best"]["source"]["path"], "proposal_master.docx")
                self.assertNotEqual(post_edited["best"]["assurance"], "verified")
                multi = why(store, "submission_multi_source.pdf", 0.0)
                source_paths = {
                    edge["source"]["path"]
                    for edge in ([multi["best"]] if multi.get("best") else []) + multi.get("alternatives", [])
                    if edge.get("source")
                }
                self.assertIn("proposal_master.docx", source_paths)
                self.assertIn("appendix_source.docx", source_paths)
                self.assertIn(APPENDIX_TEXT.split()[0].casefold(), store.text_for_file(store.file_by_path("submission_multi_source.pdf")["id"], "native").casefold())
                self.assertFalse(multi["unique_producer_supported"])

    def test_same_real_pdf_degrades_without_site_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            generated = generate(base / "generated")
            root = base / "degraded"
            root.mkdir()
            shutil.copy2(generated["text_pdf"], root / "submission_final.pdf")
            command = [
                sys.executable,
                "-S",
                str(SKILL_SCRIPTS / "lineage.py"),
                "scan",
                "--root",
                str(root),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True, env=dict(os.environ))
            with Store(root / ".file-lineage/lineage.db") as store:
                pdf = store.file_by_path("submission_final.pdf")
                self.assertEqual(pdf["metadata"]["document_structure"]["parser"], "literal-fallback")
                self.assertIn(pdf["metadata"]["document_status"], {"degraded-literal-text", "no-native-text"})
                self.assertEqual(pdf["metadata"]["embedded_media_sha256"], [])


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in FIXTURE_DEPENDENCIES), "OCR fixture dependencies are not installed")
class OCRRuntimeIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("tesseract") and shutil.which("pdftoppm"), "contract-tested, not runtime-validated on this platform")
    def test_scanned_pdf_and_png_store_separate_noncausal_ocr_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate(root)
            config = Config(root, ocr_enabled=True)
            with Store(config.db_path) as store:
                scan(config, store)
                for relative in ("scanned-text.png", "scanned-text.pdf"):
                    item = store.file_by_path(relative)
                    records = store.text_records(item["id"])
                    ocr = [record for record in records if record["source"] == "ocr"]
                    self.assertEqual(len(ocr), 1)
                    self.assertIn("LINEAGE", ocr[0]["text"].upper())
                    self.assertIsNotNone(ocr[0]["engine"])
                    self.assertIsNotNone(ocr[0]["confidence"])
                    native = [record for record in records if record["source"] == "native"]
                    if relative.endswith(".pdf"):
                        self.assertEqual(native, [])
                ocr_edges = [
                    edge
                    for edge in store.edges()
                    if any(fact.get("adapter") == "ocr" for fact in edge["evidence"])
                ]
                self.assertEqual(ocr_edges, [])
                self.assertTrue(all(edge["confidence"] != "exact" for edge in ocr_edges))
                self.assertTrue(store.search_text(OCR_TEXT.split()[0], source="ocr"))


if __name__ == "__main__":
    unittest.main()
