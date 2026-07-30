# Assets

## `social-preview.svg`

The image GitHub shows when the repository is linked on social media or in chat.
Designed at 1280×640, which is the size GitHub recommends.

**GitHub only accepts PNG, JPG, or GIF for a social preview**, so this needs
converting before upload. Any of these works:

```bash
# If you have librsvg (brew install librsvg)
rsvg-convert -w 1280 -h 640 social-preview.svg -o social-preview.png

# Or with Python
pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='social-preview.svg', write_to='social-preview.png', output_width=1280, output_height=640)"
```

Or open the SVG in a browser at a 1280×640 viewport and screenshot it.

Note: `qlmanage -t` on macOS renders SVGs at the wrong aspect ratio and letterboxes
the result into a square. Do not use it for this.

Then upload at **Settings → General → Social preview**.

The PNG itself is deliberately not committed: it is a derived artifact, and the SVG
is the thing worth reviewing in a diff.

### Why the background is a flat fill

It was a gradient at first. Rasterized, that produced a 430 KB PNG; a flat fill
produces around 90 KB for the identical layout. GitHub caps the upload at 1 MB, and
smaller is faster to load.
