# Repository settings to apply

These need your GitHub account. They are not code, and they are the highest-leverage
items left: with an empty About section the repository does not surface in GitHub
search at all.

## 1. Description

Settings → General, or the ⚙️ beside "About" on the repository home page.

```text
Find out which script, notebook, data, command, or AI agent produced a file — locally, with evidence and honest uncertainty.
```

## 2. Topics

Same ⚙️ panel. GitHub allows 20; these are the ones people actually search:

```text
file-lineage
data-provenance
provenance
reproducibility
ai-agents
developer-tools
research-tools
artifact-tracking
local-first
python
jupyter
claude-code
codex
cli
```

## 3. Website

Set to the PyPI page once the first release is published:

```text
https://pypi.org/project/trace-file-lineage/
```

## 4. Enable Discussions

Settings → General → Features → tick **Discussions**.

`.github/ISSUE_TEMPLATE/config.yml` already links to it, so that link is dead until
this is on.

## 5. Social preview image

Settings → General → Social preview → upload.

`docs/assets/social-preview.svg` is the source. GitHub needs a raster image, so convert
it first — any of these work:

```bash
# macOS, no install needed
qlmanage -t -s 1280 -o . docs/assets/social-preview.svg

# or, if you have either tool
rsvg-convert -w 1280 -h 640 docs/assets/social-preview.svg -o social-preview.png
magick -background none -density 144 docs/assets/social-preview.svg -resize 1280x640 social-preview.png
```

## 6. Release and PyPI

Follow [v0.7.0-release-notes.md](v0.7.0-release-notes.md) — the order matters, since
tagging before the trusted publisher exists makes the publish job fail.

## 7. Issues

Eight drafts are ready in [draft-issues.md](draft-issues.md), two marked
`good first issue`.

---

## Why these matter more than more code

The engineering is in reasonable shape: 199 tests, 83% coverage enforced, linting, a
green 19-job matrix across three operating systems and four Python versions. What is
missing is discoverability and evidence that the project is alive. A visitor who cannot
find the repository, cannot install it with `pip`, and sees no issues or releases has no
way to judge it — regardless of how good the code is.
