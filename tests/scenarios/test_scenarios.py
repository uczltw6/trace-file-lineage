from __future__ import annotations

import contextlib
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.capture import record, write_snapshot
from lineage_core.config import Config
from lineage_core.evidence import fact
from lineage_core.identity import normalize_relative
from lineage_core.model import Edge
from lineage_core.query import alternatives, impact, run_show, why
from lineage_core.renderers import export_obsidian, render_html, render_mermaid
from lineage_core.scanner import scan
from lineage_core.storage import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1, 1) + b"\x08\x06\x00\x00\x00" + b"fixture"


def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def make_docx(path: Path, text: str, media: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
        if media:
            archive.writestr("word/media/image1.png", media)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root)
        self.store = Store(self.config.db_path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def rescan(self):
        return scan(self.config, self.store)

    def test_01_lost_research_figure(self):
        write(self.root / "data/raw.csv", "x,y\n1,2\n")
        write(self.root / "config/figure.toml", "label='Truth'\n")
        write(self.root / "analysis/plot.py", "import pandas as pd\nimport matplotlib.pyplot as plt\ndf=pd.read_csv('data/raw.csv')\nplt.savefig('figures/panel_draft.png')\n")
        write(self.root / "analysis/alternative.py", "import matplotlib.pyplot as plt\nplt.savefig('figures/final_panel.png')\n")
        write(self.root / "figures/final_panel.png", PNG)
        self.rescan()
        draft = next(item for item in self.store.files(include_deleted=True) if item.get("metadata", {}).get("expected_path") == "figures/panel_draft.png")
        final = self.store.file_by_path("figures/final_panel.png")
        self.store.add_edge(Edge(draft["id"], final["id"], "derived_from", [fact("run-manifest-rename", "fixture-run", "git", {"from": "panel_draft.png", "to": "final_panel.png"}, weight=0.92, signal_group="git")], "git", "git", "figures/panel_draft.png"))
        self.store.connection.commit()
        result = why(self.store, "figures/final_panel.png", 0.3, 4)
        self.assertEqual(result["status"], "ok")
        self.assertIn("panel_draft", result["best"]["source"]["path"])
        self.assertTrue(any("alternative.py" in (edge["source"] or {}).get("path", "") for edge in result["alternatives"]))
        self.assertNotEqual(result["best"]["confidence"], "exact")

    def test_02_renamed_docx_pdf(self):
        true_text = "proposal evidence methods outcomes " * 12
        make_docx(self.root / "proposal_master.docx", true_text, PNG)
        make_docx(self.root / "notes.docx", "unrelated meeting notes " * 12)
        write(self.root / "submission_final.pdf", f"%PDF-1.4\n({true_text}) Tj\n%%EOF".encode())
        self.rescan()
        result = why(self.store, "submission_final.pdf", 0.3, 2)
        self.assertEqual(result["best"]["source"]["path"], "proposal_master.docx")
        kinds = {item["kind"] for item in result["best"]["evidence"]}
        self.assertIn("normalized-text-similarity", kinds)
        self.assertIn("timestamp-proximity", kinds)
        self.assertNotEqual(result["best"]["confidence"], "exact")

    def test_03_agent_run_150_images_clusters(self):
        before = self.root / ".file-lineage" / "before.json"
        write_snapshot(self.config, before)
        for index in range(155):
            write(self.root / f"images/family_{index:03}.png", PNG + str(index).encode())
        write(self.root / "notes.txt", "modified")
        run = record(self.config, self.store, before, "Generate image sweep")
        shown = run_show(self.store, run["id"])
        self.assertEqual(len(run["changes"]["created"]), 156)
        self.assertTrue(shown["clusters"])
        self.assertEqual(len(shown["clusters"][0]["members"]), 155)
        self.assertLessEqual(len(shown["clusters"][0]["representatives"]), 10)

    def test_04_ambiguous_producer(self):
        write(self.root / "a.py", "import matplotlib.pyplot as plt\nplt.savefig('result.png')\n")
        write(self.root / "b.py", "import matplotlib.pyplot as plt\nplt.savefig('result.png')\n")
        write(self.root / "result.png", PNG)
        self.rescan()
        result = alternatives(self.store, "result.png", 0.3)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertFalse(result["unique_producer_supported"])
        self.assertTrue(all(item["confidence"] != "exact" for item in result["candidates"]))

    def test_05_downstream_impact(self):
        write(self.root / "raw.csv", "x\n1\n")
        write(self.root / "preprocess.py", "import pandas as pd\ndf=pd.read_csv('raw.csv')\ndf.to_parquet('cleaned.parquet')\n")
        write(self.root / "cleaned.parquet", b"fixture")
        write(self.root / "train_or_plot.py", "import pandas as pd\nimport matplotlib.pyplot as plt\ndf=pd.read_parquet('cleaned.parquet')\nplt.savefig('figure.png')\nopen('model.bin','wb').write(b'x')\n")
        write(self.root / "figure.png", PNG)
        write(self.root / "model.bin", b"x")
        self.rescan()
        result = impact(self.store, "raw.csv", 0.3, 5)
        paths = {(edge["target"] or {}).get("path") for edge in result["direct"] + result["indirect"]}
        self.assertIn("preprocess.py", paths)
        self.assertIn("cleaned.parquet", paths)
        self.assertIn("figure.png", paths)

    def test_06_obsidian_idempotency_and_rename(self):
        write(self.root / "文档 source.txt", "same")
        write(self.root / "reader.py", "open('文档 source.txt').read()\n")
        self.rescan()
        graph = self.store.graph()
        vault = self.root / "vault"
        export_obsidian(graph, vault)
        second = export_obsidian(graph, vault)
        count = len(list(vault.glob("lineage-*.md")))
        self.assertEqual(count, len(graph["nodes"]))
        manifest_before = json.loads((vault / ".trace-file-lineage-export.json").read_text(encoding="utf-8"))
        source_id = self.store.file_by_path("文档 source.txt")["id"]
        source_note = vault / manifest_before["owned"][source_id]
        source_text = source_note.read_text(encoding="utf-8")
        self.assertIn("evidence_kinds:", source_text)
        self.assertIn("static-callsite via python-ast [static]", source_text)
        self.assertEqual(manifest_before["schema_version"], 2)
        rename_before = self.root / ".file-lineage/rename-before.json"
        write_snapshot(self.config, rename_before)
        (self.root / "文档 source.txt").rename(self.root / "renamed 文档.txt")
        record(self.config, self.store, rename_before, "captured note rename")
        self.rescan()
        export_obsidian(self.store.graph(), vault)
        manifest_after = json.loads((vault / ".trace-file-lineage-export.json").read_text(encoding="utf-8"))
        self.assertEqual(len(list(vault.glob("lineage-*.md"))), count + 1)
        self.assertEqual(manifest_before["owned"][source_id], manifest_after["owned"][source_id])
        self.assertIn('current_path: "renamed 文档.txt"', source_note.read_text(encoding="utf-8"))
        self.assertFalse(second["skipped_unowned_collisions"])

    def test_07_windows_unicode_paths(self):
        write(self.root / "中文 资料/(final)/é.txt", "ok")
        self.rescan()
        paths = {item["path"] for item in self.store.files()}
        self.assertIn("中文 资料/(final)/é.txt", paths)
        self.assertEqual(normalize_relative("C:\\中文 资料\\(final)\\e\u0301.txt"), "中文 资料/(final)/é.txt")

    def test_08_privacy_and_boundary_safety(self):
        write(self.root / ".env", "API_KEY=do-not-index")
        write(self.root / "bad.docx", b"not-a-zip")
        write(self.root / "large.bin", b"x" * 1024)
        outside = Path(self.temp.name).parent / "outside-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        with contextlib.suppress(OSError):
            (self.root / "outside-link").symlink_to(outside)
        self.config.hash_max_bytes = 100
        result = self.rescan()
        paths = {item["path"] for item in self.store.files()}
        self.assertNotIn(".env", paths)
        self.assertNotIn("outside-link", paths)
        self.assertIsNone(self.store.file_by_path("large.bin")["sha256"])
        self.assertTrue(any("document parse failed" in warning.message for warning in result.warnings))
        outside.unlink(missing_ok=True)

    def test_views_render_locally(self):
        write(self.root / "a.py", "open('out.txt','w').write('x')\n")
        write(self.root / "out.txt", "x")
        self.rescan()
        result = why(self.store, "out.txt")
        self.assertIn("flowchart", render_mermaid(result))
        graph_mermaid = render_mermaid(self.store.graph())
        self.assertIn("a.py", graph_mermaid)
        self.assertIn("out.txt", graph_mermaid)
        destination = render_html(self.store.graph(), self.root / "explorer.html")
        self.assertIn("File Lineage Explorer", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
