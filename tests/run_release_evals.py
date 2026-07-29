from __future__ import annotations

import io
import json
import sys
import time
import unittest
from pathlib import Path


CASES = {
    "ambiguous producers": "scenarios.test_scenarios.ScenarioTests.test_04_ambiguous_producer",
    "near-match and current/old document versions": "optional.test_pdf_ocr_integration.PDFRuntimeIntegrationTests.test_real_pypdf_extraction_media_similarity_and_origin_ranking",
    "wrong timestamp/stem-only candidate": "unit.test_release_hardening.SchemaAndSemanticsTests.test_timestamp_alone_never_creates_an_export_claim",
    "stale output assurance boundary": "unit.test_interoperability.StaleAnalysisTests.test_stale_states_respect_confidence_boundaries",
    "duplicate hash copy versus captured rename": "unit.test_release_hardening.SchemaAndSemanticsTests.test_copy_is_distinct_and_captured_rename_preserves_identity",
    "edited-after-export and multiple sources": "optional.test_pdf_ocr_integration.PDFRuntimeIntegrationTests.test_real_pypdf_extraction_media_similarity_and_origin_ranking",
    "user confirm/reject/undo": "unit.test_release_hardening.SchemaAndSemanticsTests.test_confirm_reject_and_undo_are_persistent_and_authoritative",
    "150+ output receipt/clustering": "scenarios.test_scenarios.ScenarioTests.test_03_agent_run_150_images_clusters",
    "interrupted four-point recovery": "unit.test_release_hardening.RecoveryAndExporterTests.test_forced_termination_at_four_boundaries_is_recoverable",
    "overlapping runs": "unit.test_release_hardening.SchemaAndSemanticsTests.test_overlapping_boundaries_remain_temporal_not_causal",
    "Unicode/spaces/parentheses/normalization": "unit.test_cross_platform.PortablePathTests.test_spaces_parentheses_chinese_unicode_normalization_and_long_paths",
    "symlink boundary": "unit.test_cross_platform.PortablePathTests.test_symlink_targets_do_not_escape_or_duplicate_workspace",
    "malformed/encrypted documents": "unit.test_extended.StructuredDocumentTests.test_odf_epub_malformed_encrypted_and_unsupported_degrade_cleanly",
    "archive bomb": "unit.test_release_hardening.RecoveryAndExporterTests.test_archive_bomb_degrades_to_metadata_only",
    "create/modify/delete recall": "unit.test_release_hardening.SchemaAndSemanticsTests.test_captured_create_modify_delete_recall_is_complete",
    "secret redaction": "unit.test_interoperability.OptionalAdapterTests.test_private_agent_session_content_is_not_indexed_or_stored_by_default",
}


def main() -> int:
    tests_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests_root))
    results = []
    all_passed = True
    for name, test_id in CASES.items():
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
        started = time.perf_counter()
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        passed = result.wasSuccessful()
        skipped = bool(result.skipped)
        all_passed &= passed and not skipped
        results.append(
            {
                "case": name,
                "test": test_id,
                "passed": passed,
                "skipped": skipped,
                "failures": [text for _, text in result.failures + result.errors],
                "skip_reasons": [reason for _, reason in result.skipped],
                "duration_seconds": round(time.perf_counter() - started, 6),
            }
        )
    payload = {
        "schema_version": 2,
        "all_runtime_cases_passed": all_passed,
        "p0_metrics": {
            "false_verified_relationships": 0 if all_passed else None,
            "ambiguity_collapses": 0 if all_passed else None,
            "captured_create_modify_delete_recall": "100%" if all_passed else "not established",
            "captured_rename_identity_preservation": "100%" if all_passed else "not established",
            "copies_misclassified_as_renames": 0 if all_passed else None,
            "fixture_secrets_retained": 0 if all_passed else None,
        },
        "cases": results,
    }
    destination = tests_root.parent / "examples/release-evaluation.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
