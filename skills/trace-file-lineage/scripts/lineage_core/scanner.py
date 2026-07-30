from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .adapters import (
    DocumentAdapter,
    DVCAdapter,
    ImageAdapter,
    JavaScriptAdapter,
    OCRAdapter,
    PythonAdapter,
    TextAdapter,
    platform_origin_adapter,
)
from .adapters.base import Candidate
from .adapters.documents import text_fingerprint
from .config import Config
from .evidence import fact, now
from .external import apply_adapter_result
from .identity import content_hash, is_link_like, is_within_root, normalize_relative, stable_virtual_id
from .model import Edge, Evidence, Node, ScanResult, ScanWarning
from .pipeline import discover_declarations
from .storage import Store

CATEGORY_BY_SUFFIX = {
    **{suffix: "code" for suffix in (
        ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
        ".sql", ".r", ".m", ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".cs", ".go", ".rs",
        ".rb", ".php", ".swift", ".kt", ".kts", ".scala", ".sc", ".jl",
    )},
    ".ipynb": "notebook",
    **{suffix: "data" for suffix in (".csv", ".tsv", ".parquet", ".feather", ".json", ".jsonl", ".sqlite", ".db", ".npy", ".npz", ".pkl")},
    **{suffix: "document" for suffix in (".docx", ".pptx", ".xlsx", ".pdf", ".odt", ".odp", ".ods", ".epub", ".md", ".rst", ".adoc", ".org", ".tex", ".html", ".htm", ".rtf", ".txt", ".log")},
    **{suffix: "image" for suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".svg")},
    **{suffix: "configuration" for suffix in (".toml", ".yaml", ".yml", ".ini", ".cfg", ".xml")},
}
DOCUMENT_INFERENCE_SUFFIXES = {
    ".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".epub", ".md", ".html", ".htm", ".svg",
    ".pdf", ".png", ".jpg", ".jpeg",
}


def categorize(path: Path) -> str:
    return CATEGORY_BY_SUFFIX.get(path.suffix.lower(), "file")


def iter_files(config: Config) -> Iterable[tuple[Path, str]]:
    root = config.root
    for directory, dirnames, filenames in os.walk(root, followlinks=config.follow_symlinks):
        base = Path(directory)
        kept = []
        for name in sorted(dirnames):
            child = base / name
            relative = normalize_relative(child, root)
            if is_link_like(child):
                if not config.follow_symlinks or not is_within_root(child, root):
                    continue
                # Internal directory aliases and junctions are already reachable
                # by their canonical workspace path; do not duplicate or cycle.
                continue
            if (child / ".trace-file-lineage-export.json").exists():
                continue
            if not config.excluded(relative, is_dir=True):
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = base / name
            relative = normalize_relative(path, root)
            if config.excluded(relative) or is_link_like(path):
                continue
            try:
                if path.is_file():
                    yield path, relative
            except OSError:
                continue


def relevant_adapters(path: Path, config: Config) -> list:
    suffix = path.suffix.lower()
    adapters = [TextAdapter(), PythonAdapter(), JavaScriptAdapter(), DocumentAdapter(), ImageAdapter()]
    if config.ocr_enabled:
        adapters.append(OCRAdapter(config.ocr_languages))
    return [adapter for adapter in adapters if adapter.name in config.adapters and suffix in adapter.suffixes]


def merge_metadata(current: dict, extracted: dict) -> tuple[dict, list[dict]]:
    records = list(extracted.pop("_text_records", []))
    for key, value in extracted.items():
        if key == "recognition" and isinstance(value, dict):
            current.setdefault("recognition", {}).update(value)
        else:
            current[key] = value
    return current, records


def resolve_endpoint(store: Store, path: str, kind: str = "file") -> str:
    existing = store.file_by_path(path)
    if existing:
        return existing["id"]
    if path.startswith("@origin/"):
        kind = "external-origin"
    node_id = stable_virtual_id(kind, path)
    virtual_path = path if path.startswith("@") else f"@missing/{path}"
    label = path.rsplit("/", 1)[-1] if path.startswith("@") else Path(path).name
    node_kind = kind if kind != "file" else "missing-file"
    return store.ensure_virtual(Node(node_id, node_kind, label, virtual_path, {"expected_path": path}))


def add_candidate(store: Store, candidate: Candidate) -> None:
    source_id = resolve_endpoint(store, candidate.source_path)
    target_id = resolve_endpoint(store, candidate.target_path, candidate.target_kind)
    store.add_edge(
        Edge(
            source=source_id,
            target=target_id,
            relation=candidate.relation,
            evidence=candidate.evidence,
            adapter=candidate.adapter,
            mode=candidate.mode,
            source_path=(
                candidate.target_path
                if candidate.adapter in {"python-ast", "javascript"} and candidate.relation in {"declares_read", "imports"}
                else candidate.source_path
            ),
        )
    )


def git_renames(root: Path) -> list[tuple[str, str, str]]:
    if not (root / ".git").exists():
        return []
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "log", "--name-status", "--find-renames", "--format=%H", "--all", "-n", "200"],
            text=True, capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    commit = ""
    result = []
    for line in completed.stdout.splitlines():
        if re.fullmatch(r"[0-9a-f]{40,64}", line):
            commit = line
        elif line.startswith("R"):
            parts = line.split("\t")
            if len(parts) >= 3:
                result.append((normalize_relative(parts[1]), normalize_relative(parts[2]), commit))
    return result


def git_history_token(root: Path) -> str:
    if not (root / ".git").exists():
        return "not-a-git-worktree"
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            text=True, capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "git-unavailable"
    return completed.stdout.strip() or "git-no-head"


def infer_git_edges(store: Store, root: Path, renames: list[tuple[str, str, str]] | None = None) -> int:
    count = 0
    rename_records = renames if renames is not None else git_renames(root)
    for old, new, commit in rename_records:
        old_node = store.file_by_path(old) or store.file_by_alias(old)
        new_node = store.file_by_path(new)
        if not old_node or not new_node:
            continue
        evidence = fact("git-rename", "git", "git", {"old_path": old, "new_path": new, "commit": commit}, weight=0.90, signal_group="git")
        store.add_edge(Edge(old_node["id"], new_node["id"], "observed_rename", [evidence], "git", "git", old, scope="artifact-identity"))
        count += 1
    return count


def infer_document_edges(store: Store) -> int:
    files = [item for item in store.files() if item["kind"] in {"document", "image"}]
    sources = [item for item in files if Path(item["path"]).suffix.lower() in {".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".epub", ".md", ".html", ".htm", ".svg"}]
    targets = [item for item in files if Path(item["path"]).suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}]
    native_text = {item["id"]: store.text_for_file(item["id"], "native") for item in files}
    fingerprints = {node_id: text_fingerprint(value) for node_id, value in native_text.items()}
    count = 0
    for source in sources:
        for target in targets:
            evidence = []
            source_meta, target_meta = source["metadata"], target["metadata"]
            source_words, target_words = fingerprints[source["id"]], fingerprints[target["id"]]
            shared_words = source_words & target_words
            text_score = len(shared_words) / len(source_words | target_words) if source_words and target_words else 0.0
            containment = len(shared_words) / min(len(source_words), len(target_words)) if source_words and target_words else 0.0
            if text_score >= 0.15 or containment >= 0.50:
                evidence.append(
                    fact(
                        "normalized-text-similarity", "document", "content",
                        {"jaccard": round(text_score, 4), "containment": round(containment, 4)},
                        weight=min(0.72, 0.35 + max(text_score, containment * 0.65) * 0.5),
                        signal_group="document-text",
                    )
                )
            source_media = set(source_meta.get("embedded_media_sha256", []))
            if target.get("sha256") and target["sha256"] in source_media:
                evidence.append(fact("embedded-media-identity", "document", "content", {"sha256": target["sha256"]}, weight=0.85, signal_group="embedded-media"))
            shared_media = set(source_meta.get("embedded_media_fingerprints", [])) & set(
                target_meta.get("embedded_media_fingerprints", [])
            )
            if shared_media:
                evidence.append(
                    fact(
                        "embedded-media-fingerprint-match",
                        "document",
                        "content",
                        {"fingerprints": sorted(shared_media)},
                        weight=0.80,
                        signal_group="embedded-media",
                    )
                )
            # Naming and timestamps can rank an already content-supported
            # candidate, but are too common to create a provenance claim alone.
            if not evidence:
                continue
            stem_a, stem_b = Path(source["path"]).stem.casefold(), Path(target["path"]).stem.casefold()
            if stem_a == stem_b:
                evidence.append(fact("filename-stem", "document", "heuristic", {"stem": stem_a}, weight=0.30, signal_group="naming"))
            if source.get("mtime_ns") and target.get("mtime_ns"):
                delta = abs(source["mtime_ns"] - target["mtime_ns"]) / 1_000_000_000
                if delta <= 3600:
                    evidence.append(fact("timestamp-proximity", "document", "metadata", {"seconds": round(delta, 3)}, weight=0.25, signal_group="timing"))
            relation = "embedded_bytes_match" if any(item.kind == "embedded-media-identity" for item in evidence) else "content_matches"
            store.add_edge(Edge(source["id"], target["id"], relation, evidence, "document", "content", source["path"], competing_group=f"origin:{target['id']}"))
            count += 1
    return count


def reconcile_virtual_paths(store: Store) -> None:
    for item in store.files(include_deleted=True):
        expected = item.get("metadata", {}).get("expected_path")
        if not expected or not item["path"].startswith("@"):
            continue
        actual = store.file_by_path(expected)
        if not actual or actual["id"] == item["id"]:
            continue
        store.connection.execute("UPDATE edges SET source_id=? WHERE source_id=?", (actual["id"], item["id"]))
        store.connection.execute("UPDATE edges SET target_id=? WHERE target_id=?", (actual["id"], item["id"]))
        store.connection.execute("UPDATE claims SET source_id=? WHERE source_id=?", (actual["id"], item["id"]))
        store.connection.execute("UPDATE claims SET target_id=? WHERE target_id=?", (actual["id"], item["id"]))
        store.connection.execute("UPDATE files SET deleted=1 WHERE id=?", (item["id"],))


def scan(config: Config, store: Store, *, full: bool = False) -> ScanResult:
    started = time.perf_counter()
    result = ScanResult(root=".", full_rehash=full)
    seen_at = now()
    existing = {item["path"]: item for item in store.files() if not item["path"].startswith("@")}
    entries = list(iter_files(config))
    current_paths = {relative for _, relative in entries}
    missing = {path: item for path, item in existing.items() if path not in current_paths}
    git_token = git_history_token(config.root)
    git_dirty = store.get_meta("git_history_token") != git_token
    batched_git_renames = git_renames(config.root) if git_dirty else []
    git_old_by_new: dict[str, list[str]] = {}
    for old_path, new_path, _ in batched_git_renames:
        git_old_by_new.setdefault(new_path, []).append(old_path)
    pending_candidates: list[Candidate] = []
    document_dirty = any(Path(path).suffix.lower() in DOCUMENT_INFERENCE_SUFFIXES for path in missing)
    origin_adapter = platform_origin_adapter(
        browser_history=config.platform_browser_history,
        spotlight_fallback=config.platform_spotlight_fallback,
        gvfs_fallback=config.platform_gvfs_fallback,
    ) if config.platform_metadata_enabled else None

    with store.transaction():
        for path, relative in entries:
            result.scanned += 1
            try:
                stat = path.stat()
            except OSError as exc:
                warning = ScanWarning(relative, "scanner", f"file metadata unavailable; path skipped: {exc}")
                result.warnings.append(warning)
                store.add_warning(seen_at, warning.path, warning.adapter, warning.message)
                continue
            adapters = relevant_adapters(path, config)
            extractor_versions = {adapter.name: str(getattr(adapter, "version", "1")) for adapter in adapters}
            old = existing.get(relative)
            unchanged = bool(
                not full
                and old
                and old.get("size") == stat.st_size
                and old.get("mtime_ns") == stat.st_mtime_ns
                and old.get("metadata", {}).get("recognition_version") == 3
                and old.get("metadata", {}).get("extractor_versions", {}) == extractor_versions
            )
            if unchanged:
                result.reused += 1
                continue
            digest_warning = None
            try:
                digest = content_hash(path, config.hash_max_bytes)
            except OSError as exc:
                digest = None
                digest_warning = f"file content inaccessible; metadata-only fallback: {exc}"
            file_id = old["id"] if old else None
            if old:
                result.changed += 1
            else:
                declared_old_paths = [old_path for old_path in git_old_by_new.get(relative, []) if old_path in missing]
                rename_candidates = [missing[old_path] for old_path in declared_old_paths]
                if len(rename_candidates) == 1:
                    renamed = rename_candidates[0]
                    store.rename_file(renamed["id"], renamed["path"], relative, seen_at)
                    file_id = renamed["id"]
                    missing.pop(renamed["path"], None)
                    result.renamed += 1
                else:
                    result.added += 1
            if path.suffix.lower() in DOCUMENT_INFERENCE_SUFFIXES:
                document_dirty = True
            metadata = {
                "suffix": path.suffix.lower(),
                "hash_skipped": digest is None and stat.st_size > config.hash_max_bytes,
                "recognition_version": 3,
                "extractor_versions": extractor_versions,
                "recognition": {"metadata_fingerprint": "indexed"},
            }
            candidates: list[Candidate] = []
            text_records: list[dict] = []
            warning_records: list[tuple[str, str]] = []
            if digest_warning:
                warning_records.append(("scanner", digest_warning))
            if adapters and stat.st_size <= config.extract_max_bytes:
                for adapter in adapters:
                    try:
                        adapter_version = extractor_versions[adapter.name]
                        digest_id = f"digest:sha256:{digest}" if digest else ""
                        cached = store.extractor_cache(digest_id, adapter.name, adapter_version) if digest_id else None
                        if cached and cached.get("relative") == relative:
                            found = [
                                Candidate(
                                    item["source_path"], item["target_path"], item["relation"],
                                    [Evidence(**evidence) for evidence in item.get("evidence", [])],
                                    item["mode"], item["adapter"], item.get("target_kind", "file"), item.get("metadata", {}),
                                )
                                for item in cached.get("candidates", [])
                            ]
                            extracted = cached.get("metadata", {})
                            warnings = cached.get("warnings", [])
                        else:
                            found, extracted, warnings = adapter.inspect(path, relative, config.root)
                            if digest_id:
                                store.put_extractor_cache(
                                    digest_id,
                                    adapter.name,
                                    adapter_version,
                                    {
                                        "relative": relative,
                                        "candidates": [
                                            {
                                                "source_path": item.source_path,
                                                "target_path": item.target_path,
                                                "relation": item.relation,
                                                "evidence": [evidence.to_dict() for evidence in item.evidence],
                                                "mode": item.mode,
                                                "adapter": item.adapter,
                                                "target_kind": item.target_kind,
                                                "metadata": item.metadata,
                                            }
                                            for item in found
                                        ],
                                        "metadata": extracted,
                                        "warnings": warnings,
                                    },
                                    seen_at,
                                )
                        candidates.extend(found)
                        metadata, records = merge_metadata(metadata, extracted)
                        text_records.extend(records)
                        warning_records.extend((adapter.name, message) for message in warnings)
                    except Exception as exc:
                        warning_records.append((adapter.name, f"adapter failed; metadata-only fallback: {type(exc).__name__}: {exc}"))
            elif adapters:
                warning_records.extend((adapter.name, f"content extraction skipped above {config.extract_max_bytes} bytes") for adapter in adapters)
            if origin_adapter is not None:
                try:
                    found, extracted, warnings = origin_adapter.inspect(path, relative, config.root)
                    candidates.extend(found)
                    metadata, records = merge_metadata(metadata, extracted)
                    text_records.extend(records)
                    warning_records.extend((origin_adapter.name, message) for message in warnings)
                except Exception as exc:  # optional OS metadata must never stop the core scanner
                    warning_records.append((origin_adapter.name, f"platform metadata unavailable without stopping scan: {exc}"))
            file_id = store.upsert_file(relative, categorize(path), path.name, stat.st_size, stat.st_mtime_ns, digest, metadata, seen_at, file_id)
            store.replace_text(file_id, text_records)
            store.delete_evidence_for_source(relative)
            pending_candidates.extend(candidates)
            for adapter_name, message in warning_records:
                warning = ScanWarning(relative, adapter_name, message)
                result.warnings.append(warning)
                store.add_warning(seen_at, warning.path, warning.adapter, warning.message)
        for relative in missing:
            store.mark_deleted(relative, seen_at)
            result.deleted += 1
        for candidate in pending_candidates:
            add_candidate(store, candidate)
        reconcile_virtual_paths(store)
        # Rebuild cross-file inferences deterministically after metadata updates.
        if document_dirty:
            store.connection.execute("UPDATE claims SET status='superseded' WHERE adapter='document' AND status='active'")
            store.connection.execute("DELETE FROM edges WHERE adapter='document'")
            result.edges += infer_document_edges(store)
        if git_dirty:
            store.connection.execute("UPDATE claims SET status='superseded' WHERE adapter='git' AND status='active'")
            store.connection.execute("DELETE FROM edges WHERE adapter='git'")
            result.edges += infer_git_edges(store, config.root, batched_git_renames)
        store.connection.execute("DELETE FROM warnings WHERE id NOT IN (SELECT id FROM warnings ORDER BY id DESC LIMIT 1000)")

    generated_adapters = {"pipeline-declaration", "dvc"}
    with store.transaction():
        store.delete_adapter_records(generated_adapters)
    external_results = discover_declarations(config.root, store)
    if (config.root / "dvc.yaml").is_file():
        external_results.append(DVCAdapter().load(config.root / "dvc.yaml", config.root, trusted=True))
    for adapter_result in external_results:
        try:
            apply_adapter_result(store, adapter_result)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            adapter_result.warnings.append(f"adapter failed without stopping core scan: {exc}")
        for message in adapter_result.warnings:
            result.warnings.append(
                ScanWarning(str(adapter_result.metadata.get("source", "@adapter")), adapter_result.adapter, message)
            )

    result.edges = len(store.edges())

    store.set_meta("last_scan_at", seen_at)
    store.set_meta("git_history_token", git_token)
    result.duration_seconds = round(time.perf_counter() - started, 6)
    return result


def export_graph(config: Config, store: Store) -> Path:
    path = config.output_path / "graph.json"
    graph = store.graph()
    graph["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    graph["workspace_root"] = "."
    path.write_text(json.dumps(graph, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
