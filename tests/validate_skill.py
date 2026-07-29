from __future__ import annotations

import re
from pathlib import Path


def main() -> int:
    skill = Path(__file__).resolve().parents[1] / "skills" / "trace-file-lineage"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"^name:\s*trace-file-lineage\s*$", text, re.MULTILINE)
    assert re.search(r"^description:\s*\S", text, re.MULTILINE)
    assert "[TODO:" not in text
    assert (skill / "agents" / "openai.yaml").exists()
    assert (skill / "scripts" / "lineage.py").exists()
    print("repository skill structure: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
