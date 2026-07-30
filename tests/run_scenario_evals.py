from __future__ import annotations

import io
import json
import sys
import time
import unittest
from pathlib import Path

SCENARIOS = {
    "lost-research-figure": "scenarios.test_scenarios.ScenarioTests.test_01_lost_research_figure",
    "renamed-docx-pdf": "scenarios.test_scenarios.ScenarioTests.test_02_renamed_docx_pdf",
    "agent-run-150-images": "scenarios.test_scenarios.ScenarioTests.test_03_agent_run_150_images_clusters",
    "ambiguous-producer": "scenarios.test_scenarios.ScenarioTests.test_04_ambiguous_producer",
    "downstream-impact": "scenarios.test_scenarios.ScenarioTests.test_05_downstream_impact",
    "obsidian-idempotency": "scenarios.test_scenarios.ScenarioTests.test_06_obsidian_idempotency_and_rename",
    "windows-unicode": "scenarios.test_scenarios.ScenarioTests.test_07_windows_unicode_paths",
    "privacy-boundary": "scenarios.test_scenarios.ScenarioTests.test_08_privacy_and_boundary_safety",
}


def main() -> int:
    tests_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests_root))
    results = []
    all_passed = True
    for name, test_id in SCENARIOS.items():
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
        started = time.perf_counter()
        runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
        result = runner.run(suite)
        passed = result.wasSuccessful()
        all_passed &= passed
        results.append(
            {
                "scenario": name,
                "passed": passed,
                "tests_run": result.testsRun,
                "failures": [text for _, text in result.failures + result.errors],
                "duration_seconds": round(time.perf_counter() - started, 6),
            }
        )
    payload = {"schema_version": 2, "all_passed": all_passed, "scenarios": results}
    destination = tests_root.parent / "examples" / "scenario-evaluation.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
