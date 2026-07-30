from __future__ import annotations

import contextlib
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from lineage_core.adapters.linux_downloads import LinuxDownloadOriginAdapter
from lineage_core.adapters.macos_downloads import MacOSDownloadOriginAdapter
from lineage_core.adapters.platform_downloads import platform_origin_adapter
from lineage_core.adapters.windows_downloads import WindowsDownloadOriginAdapter
from lineage_core.config import Config
from lineage_core.identity import comparable_path, filesystem_case_sensitive, is_link_like, normalize_relative
from lineage_core.normalization import normalize_graph
from lineage_core.platforms.obsidian import ObsidianDetection, detect_obsidian, open_obsidian
from lineage_core.scanner import export_graph, iter_files, scan
from lineage_core.storage import Store


def write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")


class PortablePathTests(unittest.TestCase):
    def test_drive_letter_and_separator_variants_are_portable(self):
        root = r"F:\research\project"
        self.assertEqual(normalize_relative(r"F:\research\project\资料 (final).csv", root), "资料 (final).csv")
        self.assertEqual(normalize_relative("F:/research/project/data/raw.csv", root), "data/raw.csv")
        self.assertEqual(normalize_relative(r"F:\research\project\data\raw.csv"), "research/project/data/raw.csv")

    def test_unc_paths_preserve_authority_when_not_relativized(self):
        unc = r"\\server\share\research\project\data.csv"
        self.assertEqual(normalize_relative(unc), "server/share/research/project/data.csv")
        self.assertEqual(normalize_relative(unc, r"\\server\share\research\project"), "data.csv")

    def test_spaces_parentheses_chinese_unicode_normalization_and_long_paths(self):
        decomposed = unicodedata.normalize("NFD", "资料-é (final).txt")
        long_parts = ["segment" + str(index).zfill(3) for index in range(48)]
        raw = "/".join(["folder with spaces", decomposed, *long_parts])
        normalized = normalize_relative(raw)
        self.assertTrue(normalized.startswith("folder with spaces/资料-é (final).txt/"))
        self.assertEqual(normalized, unicodedata.normalize("NFC", normalized))
        self.assertGreater(len(normalized), 260)

    def test_case_comparison_is_explicit(self):
        self.assertEqual(comparable_path("Data/Result.CSV", case_sensitive=False), "data/result.csv")
        self.assertNotEqual(
            comparable_path("Data/Result.CSV", case_sensitive=True),
            comparable_path("data/result.csv", case_sensitive=True),
        )

    def test_current_volume_case_behavior_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            probe = base / "CaseProbe"
            probe.mkdir()
            alternate = base / "cASEpROBE"
            insensitive = False
            with contextlib.suppress(OSError):
                insensitive = alternate.exists() and alternate.samefile(probe)
            self.assertEqual(filesystem_case_sensitive(probe), not insensitive)

    def test_real_long_path_when_host_policy_allows_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            long_directory = root.joinpath(*(f"segment-{index:02d}-abcdefgh" for index in range(18)))
            target = long_directory / "资料 (long path).txt"
            try:
                write(target, "long path fixture")
            except OSError as exc:
                self.skipTest(f"host long-path policy rejected the fixture: {exc}")
            self.assertGreater(len(str(target)), 260)
            paths = {relative for _, relative in iter_files(Config(root))}
            self.assertIn(target.relative_to(root).as_posix(), paths)

    def test_workspace_move_preserves_normalized_graph_and_portable_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            graphs = []
            for workspace in (base / "first location", base / "moved (location)"):
                write(workspace / "data" / "输入.csv", "x\n1\n")
                write(
                    workspace / "render.py",
                    "from pathlib import Path\n"
                    "source = Path('data') / '输入.csv'\n"
                    "target = Path('figures') / '结果.txt'\n"
                    "target.write_text(source.read_text())\n",
                )
                config = Config(workspace, platform_metadata_enabled=False)
                with Store(config.db_path) as store:
                    scan(config, store)
                    graphs.append(normalize_graph(store.graph()))
                    portable = json.loads(export_graph(config, store).read_text(encoding="utf-8"))
                    self.assertEqual(portable["workspace_root"], ".")
                    self.assertNotIn(str(workspace), json.dumps(portable, ensure_ascii=False))
            self.assertEqual(graphs[0], graphs[1])
            serialized = json.dumps(graphs[0], ensure_ascii=False)
            self.assertNotIn(str(base), serialized)
            self.assertIn("data/输入.csv", serialized)

    def test_symlink_targets_do_not_escape_or_duplicate_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "workspace"
            external = base / "external"
            write(root / "canonical" / "inside.txt", "inside")
            write(external / "outside.txt", "outside")
            try:
                (root / "internal-link").symlink_to(root / "canonical", target_is_directory=True)
                (root / "external-link").symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            self.assertTrue(is_link_like(root / "internal-link"))
            paths = {relative for _, relative in iter_files(Config(root, follow_symlinks=True))}
            self.assertEqual(paths, {"canonical/inside.txt"})

    @unittest.skipUnless(sys.platform == "win32", "real junction creation requires Windows")
    def test_windows_junction_is_detected_and_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            target = root / "canonical"
            junction = root / "junction"
            write(target / "inside.txt", "inside")
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                self.skipTest(f"junction creation unavailable: {completed.stderr or completed.stdout}")
            self.assertTrue(is_link_like(junction))
            paths = {relative for _, relative in iter_files(Config(root, follow_symlinks=True))}
            self.assertEqual(paths, {"canonical/inside.txt"})


class PlatformOriginContractTests(unittest.TestCase):
    def test_windows_zone_identifier_and_browser_history_are_conservative(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "下载 (1).pdf"
            write(target, b"pdf")
            write(
                target.parent / f"{target.name}:Zone.Identifier",
                "[ZoneTransfer]\nHostUrl=https://user:secret@example.test/files/doc.pdf?token=hidden#part\n"
                "ReferrerUrl=https://example.test/downloads?id=secret\n",
            )
            history = root / "History"
            connection = sqlite3.connect(history)
            connection.execute("CREATE TABLE downloads(target_path TEXT, tab_url TEXT)")
            connection.execute("INSERT INTO downloads VALUES(?, ?)", (str(target), "https://browser.test/source?q=private"))
            connection.commit()
            connection.close()
            candidates, metadata, warnings = WindowsDownloadOriginAdapter(
                browser_history=True,
                history_paths=[history],
            ).inspect(target, target.name, root)
            self.assertFalse(warnings)
            self.assertEqual(len(candidates), 3)
            self.assertTrue(all(candidate.relation == "downloaded_from" for candidate in candidates))
            self.assertTrue(all(item["confidence"] != "exact" for item in metadata["download_origins"]))
            serialized = json.dumps(metadata)
            self.assertNotIn("secret", serialized)
            self.assertNotIn("token=", serialized)

    def test_macos_where_from_plist_contract(self):
        payload = plistlib.dumps(["https://example.test/download?a=private", "https://referrer.test/page"])
        adapter = MacOSDownloadOriginAdapter()
        with mock.patch.object(adapter, "_where_from_xattr", return_value=payload):
            candidates, metadata, warnings = adapter.inspect(Path("fixture.pdf"), "fixture.pdf", Path.cwd())
        self.assertFalse(warnings)
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(candidate.mode == "metadata" for candidate in candidates))
        self.assertNotIn("private", json.dumps(metadata))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xattr"), "real kMDItemWhereFroms requires macOS xattr")
    def test_macos_where_from_xattr_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "下载 (runtime).pdf"
            write(target, b"pdf")
            payload = plistlib.dumps(["https://example.test/runtime.pdf?private=1"], fmt=plistlib.FMT_BINARY)
            completed = subprocess.run(
                [str(shutil.which("xattr")), "-wx", "com.apple.metadata:kMDItemWhereFroms", payload.hex(), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                self.skipTest(f"host filesystem rejected the test xattr: {completed.stderr}")
            candidates, metadata, warnings = MacOSDownloadOriginAdapter().inspect(target, target.name, root)
            self.assertFalse(warnings)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(metadata["download_origins"][0]["url"], "https://example.test/runtime.pdf")

    def test_linux_xattr_contract_and_missing_adapter_degradation(self):
        def fake_xattr(path: Path, name: str) -> bytes | None:
            values = {
                "user.xdg.origin.url": b"https://example.test/file.txt?private=1",
                "user.xdg.referrer.url": b"https://referrer.test/page",
            }
            return values.get(name)

        with mock.patch("lineage_core.adapters.linux_downloads.get_xattr", side_effect=fake_xattr):
            candidates, metadata, warnings = LinuxDownloadOriginAdapter().inspect(
                Path("file.txt"), "file.txt", Path.cwd()
            )
        self.assertFalse(warnings)
        self.assertEqual(len(candidates), 2)
        self.assertNotIn("private", json.dumps(metadata))
        null = platform_origin_adapter("unsupported-desktop")
        self.assertEqual(null.inspect(Path("file.txt"), "file.txt", Path.cwd()), ([], {}, []))

    @unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os, "setxattr"), "real XDG xattrs require Linux xattr support")
    def test_linux_origin_xattr_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "下载 (runtime).txt"
            write(target, "runtime")
            try:
                os.setxattr(target, "user.xdg.origin.url", b"https://example.test/runtime.txt?private=1")
            except OSError as exc:
                self.skipTest(f"host filesystem rejected the test xattr: {exc}")
            candidates, metadata, warnings = LinuxDownloadOriginAdapter().inspect(target, target.name, root)
            self.assertFalse(warnings)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(metadata["download_origins"][0]["url"], "https://example.test/runtime.txt")


class ObsidianPlatformContractTests(unittest.TestCase):
    def test_platform_configs_are_bounded_and_vaults_must_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            vault = Path(temp) / "Vault with spaces"
            (vault / ".obsidian").mkdir(parents=True)
            mac_config = home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
            write(mac_config, json.dumps({"vaults": {"stable": {"path": str(vault), "open": True}}}))
            with mock.patch("lineage_core.platforms.obsidian.shutil.which", return_value=None):
                detected = detect_obsidian("darwin", home=home, environment={})
            self.assertEqual([(item.id, item.path) for item in detected.vaults], [("stable", str(vault.resolve()))])
            self.assertEqual(detected.config_paths, [str(mac_config.resolve())])

    def test_safe_cli_and_uri_open_requests_do_not_execute_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "Vault"
            (vault / ".obsidian").mkdir(parents=True)
            note = Path("Trace File Lineage Test") / "File Lineage Index.md"
            write(vault / note, "# Index")
            detection = ObsidianDetection("win32", True, "1.12.7", "Obsidian.exe", "obsidian", True)
            cli = open_obsidian(vault, note.as_posix(), method="cli", detection=detection)
            self.assertEqual(cli.command, ["obsidian", "open", f"path={note.as_posix()}"])
            uri = open_obsidian(vault, note.as_posix(), method="uri", detection=detection)
            self.assertIn("obsidian://open?path=", uri.uri or "")
            self.assertIn("Trace+File+Lineage+Test", uri.uri or "")
            with self.assertRaises(ValueError):
                open_obsidian(vault, "../unrelated.md", method="uri", detection=detection)


class HostPackagingContractTests(unittest.TestCase):
    def test_codex_and_claude_hooks_use_documented_host_specific_forms(self):
        codex = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        claude = json.loads((REPO / "platforms" / "claude-code" / "hooks.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", codex_manifest)
        self.assertEqual(claude_manifest["hooks"], "./platforms/claude-code/hooks.json")
        for event in ("UserPromptSubmit", "Stop"):
            codex_hook = codex["hooks"][event][0]["hooks"][0]
            self.assertIn("commandWindows", codex_hook)
            self.assertIn("$PLUGIN_ROOT", codex_hook["command"])
            claude_hook = claude["hooks"][event][0]["hooks"][0]
            self.assertEqual(claude_hook["command"], "python")
            self.assertEqual(claude_hook["args"], ["${CLAUDE_PLUGIN_ROOT}/platforms/claude-code/hook.py"])


if __name__ == "__main__":
    unittest.main()
