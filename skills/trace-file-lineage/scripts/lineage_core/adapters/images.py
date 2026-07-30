from __future__ import annotations

import struct
from pathlib import Path
from typing import ClassVar


class ImageAdapter:
    name = "image"
    suffixes: ClassVar[set[str]] = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}

    def inspect(self, path: Path, relative: str, root: Path) -> tuple[list, dict, list[str]]:
        metadata: dict = {"format": path.suffix.lower().lstrip(".")}
        warnings: list[str] = []
        try:
            with path.open("rb") as handle:
                header = handle.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                metadata["width"], metadata["height"] = struct.unpack(">II", header[16:24])
            elif header[:2] == b"\xff\xd8":
                metadata.update(self._jpeg_size(path))
        except OSError as exc:
            warnings.append(f"image metadata failed: {exc}")
        return [], metadata, warnings

    @staticmethod
    def _jpeg_size(path: Path) -> dict:
        with path.open("rb") as handle:
            handle.read(2)
            while True:
                marker = handle.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xFF:
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) < 2:
                    break
                length = int.from_bytes(length_bytes, "big")
                if marker[1] in range(0xC0, 0xC4):
                    data = handle.read(5)
                    return {"height": int.from_bytes(data[1:3], "big"), "width": int.from_bytes(data[3:5], "big")}
                handle.seek(max(0, length - 2), 1)
        return {}
