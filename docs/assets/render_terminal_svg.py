#!/usr/bin/env python3
"""Render captured terminal output as a self-contained SVG.

The README needs a header image. A screen recording would be better, but a still
that shows real output is far better than nothing and costs no maintenance.

This reads text on stdin and emits an SVG, so the image is regenerated from actual
command output rather than drawn by hand. Nothing is invented: if the tool's
output changes, re-run this and the picture changes with it.

    lineage demo | python docs/assets/render_terminal_svg.py --theme dark \\
        --title "lineage demo" > docs/assets/demo-dark.svg

Dependency-free, matching the rest of the project.
"""

from __future__ import annotations

import argparse
import html
import re
import sys

CHAR_WIDTH = 8.02
LINE_HEIGHT = 20
PADDING_X = 22
PADDING_Y = 18
TITLEBAR = 34
FONT = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
FONT_SIZE = 13.2

THEMES = {
    "dark": {
        "bg": "#14161a", "chrome": "#1b1e24", "border": "#2e333c",
        "text": "#d6d9de", "dim": "#7d8590", "accent": "#6aa2ff",
        "good": "#4ec98a", "warn": "#e0a94a", "title": "#9aa0ab",
    },
    "light": {
        "bg": "#ffffff", "chrome": "#f2f3f5", "border": "#d9dce3",
        "text": "#24292f", "dim": "#6a737d", "accent": "#2f6feb",
        "good": "#1f7a4d", "warn": "#b8791b", "title": "#57606a",
    },
}

# Highlighting driven by what the output actually means, not by guessing colours.
RULES = (
    (re.compile(r"^\s*\[\d/\d\]"), "accent"),
    (re.compile(r"\bverified\b"), "good"),
    (re.compile(r"This is proof"), "good"),
    (re.compile(r"\bcandidate\b"), "warn"),
    (re.compile(r"This is a good guess"), "warn"),
    (re.compile(r"^\s*\$ "), "accent"),
    (re.compile(r"^\s{4,}\S"), "dim"),
)


def colour_for(line: str, theme: dict[str, str]) -> str:
    for pattern, key in RULES:
        if pattern.search(line):
            return theme[key]
    return theme["text"]


def render(lines: list[str], theme_name: str, title: str) -> str:
    theme = THEMES[theme_name]
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    columns = max((len(line) for line in lines), default = 40)
    width = int(PADDING_X * 2 + columns * CHAR_WIDTH)
    height = int(TITLEBAR + PADDING_Y * 2 + len(lines) * LINE_HEIGHT)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Terminal output of {html.escape(title)}">',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="9" '
        f'fill="{theme["bg"]}" stroke="{theme["border"]}"/>',
        f'<path d="M0.5 9.5a9 9 0 0 1 9-9h{width - 20}a9 9 0 0 1 9 9v{TITLEBAR - 9}H0.5z" '
        f'fill="{theme["chrome"]}"/>',
        f'<line x1="0.5" y1="{TITLEBAR}.5" x2="{width - 0.5}" y2="{TITLEBAR}.5" stroke="{theme["border"]}"/>',
    ]
    for index, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'<circle cx="{20 + index * 17}" cy="{TITLEBAR / 2}" r="5.5" fill="{colour}"/>')
    out.append(
        f'<text x="{width / 2}" y="{TITLEBAR / 2 + 4.4}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="11.5" fill="{theme["title"]}">{html.escape(title)}</text>'
    )

    baseline = TITLEBAR + PADDING_Y + FONT_SIZE
    for offset, line in enumerate(lines):
        if not line:
            continue
        out.append(
            f'<text x="{PADDING_X}" y="{baseline + offset * LINE_HEIGHT:.0f}" '
            f'font-family="{FONT}" font-size="{FONT_SIZE}" '
            f'fill="{colour_for(line, theme)}" '
            f'xml:space="preserve">{html.escape(line)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=sorted(THEMES), default="dark")
    parser.add_argument("--title", default="lineage")
    parser.add_argument("--max-lines", type=int, default=40)
    arguments = parser.parse_args()

    lines = sys.stdin.read().splitlines()[: arguments.max_lines]
    if not lines:
        print("nothing on stdin", file=sys.stderr)
        return 2
    sys.stdout.write(render(lines, arguments.theme, arguments.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
