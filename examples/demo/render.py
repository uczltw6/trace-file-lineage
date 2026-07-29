from pathlib import Path

data = Path("examples/demo/data.csv").read_text(encoding="utf-8")
points = [line.split(",") for line in data.splitlines()[1:]]
circles = "".join(
    f'<circle cx="{20 + int(x) * 30}" cy="{120 - int(y) * 10}" r="4" />'
    for x, y in points
)
svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="140"><g fill="currentColor">{circles}</g></svg>\n'
Path("examples/demo/figure.svg").write_text(svg, encoding="utf-8")
