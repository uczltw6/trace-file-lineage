"""Entity-expansion hardening for XML inside untrusted documents.

Python's ElementTree expands internal entities, so a small nested-entity payload
inside an otherwise valid archive expands to gigabytes in memory. The archive
limits enforced during extraction bound the compressed bytes read, not what
those bytes expand to, which makes this a separate layer of defence.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO / "skills" / "trace-file-lineage" / "scripts"
sys.path.insert(0, str(SOURCE_ROOT))

from lineage_core.adapters.documents import xml_root
from lineage_core.config import Config
from lineage_core.scanner import scan
from lineage_core.storage import Store

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
]>
<w:document xmlns:w="x"><w:t>&lol6;</w:t></w:document>"""

EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b"<r>&x;</r>"
)

BENIGN = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>hello lineage</w:t></w:r></w:p></w:body></w:document>"
)


class EntityExpansionTests(unittest.TestCase):
    def test_entity_expansion_payload_is_rejected(self):
        warnings: list[str] = []
        self.assertIsNone(xml_root(BILLION_LAUGHS, "word/document.xml", warnings))
        self.assertTrue(warnings)
        self.assertIn("document type declarations are not permitted", warnings[0])

    def test_external_entity_payload_is_rejected(self):
        warnings: list[str] = []
        self.assertIsNone(xml_root(EXTERNAL_ENTITY, "word/document.xml", warnings))
        self.assertTrue(warnings)

    def test_benign_document_part_still_parses(self):
        warnings: list[str] = []
        root = xml_root(BENIGN, "word/document.xml", warnings)
        self.assertIsNotNone(root)
        self.assertEqual(warnings, [])
        self.assertIn("hello lineage", "".join(root.itertext()))

    def test_doctype_inside_a_comment_is_not_treated_as_a_declaration(self):
        warnings: list[str] = []
        commented = b'<?xml version="1.0"?><!-- <!DOCTYPE x> --><r><t>fine</t></r>'
        root = xml_root(commented, "word/document.xml", warnings)
        self.assertIsNotNone(root, f"benign comment rejected: {warnings}")
        self.assertEqual(warnings, [])

    def test_a_doctype_after_a_closed_comment_is_still_rejected(self):
        warnings: list[str] = []
        payload = b'<?xml version="1.0"?><!-- note --><!DOCTYPE r [<!ENTITY a "b">]><r>&a;</r>'
        self.assertIsNone(xml_root(payload, "word/document.xml", warnings))
        self.assertTrue(warnings)

    def test_uppercase_declaration_is_rejected(self):
        warnings: list[str] = []
        self.assertIsNone(
            xml_root(b'<?xml version="1.0"?><!DoCtYpE r []><r/>', "part", warnings)
        )
        self.assertTrue(warnings)


class ScanIntegrationTests(unittest.TestCase):
    def test_a_docx_carrying_the_payload_scans_without_exhausting_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            document = root / "hostile.docx"
            with zipfile.ZipFile(document, "w") as archive:
                archive.writestr(
                    "[Content_Types].xml",
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
                archive.writestr("word/document.xml", BILLION_LAUGHS.decode("utf-8"))

            with Store(root / ".file-lineage" / "lineage.db") as store:
                result = scan(Config(root), store)
                indexed = store.file_by_path("hostile.docx")

            # The scan must complete, index the file, and say why the part was dropped.
            self.assertIsNotNone(indexed)
            self.assertTrue(
                any("document type declarations" in warning.message for warning in result.warnings),
                f"expected a rejection warning, got {[w.message for w in result.warnings]}",
            )


if __name__ == "__main__":
    unittest.main()
