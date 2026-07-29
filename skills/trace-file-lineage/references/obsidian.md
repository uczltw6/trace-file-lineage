# Obsidian export

Require an explicit vault or folder destination. Obsidian is a view; SQLite
remains canonical.

The exporter owns only files listed in `.trace-file-lineage-export.json` plus
`File Lineage Index.md`. Note filenames derive from persistent lineage IDs, so
supported path renames update one note rather than creating a duplicate.

Each note includes YAML properties for stable lineage ID, type, current path,
plain-language assurance, and evidence, plus upstream/downstream backlinks.
Repeated export is idempotent and writes atomically. The manifest stores hashes
for exporter-owned notes. If a user edits one, preserve it, write a reconciled
exporter-owned replacement, and report the conflict. If a would-be owned filename
already exists but is not listed in the manifest, skip it and report the
collision. Never overwrite unrelated notes or an unowned index.

Large run families should be summarized using cluster notes or representative
members while the complete membership remains in SQLite and JSON.

`lineage obsidian-detect` checks only documented/configured locations: the
platform-specific Obsidian configuration file, known application locations, the
official `obsidian` executable on `PATH`, and configured vaults that currently
contain `.obsidian`. It never recursively searches the whole computer.

`lineage obsidian-open --vault <vault> --file <relative-note>` validates that
the note exists within the selected vault and emits a request without opening it.
Add `--execute` only with user permission. Prefer the official CLI when detected;
otherwise use a percent-encoded `obsidian://open?path=...` URI when the operating
system has a registered handler. URI registration is normally available after
running Obsidian on Windows/macOS; Linux desktop integration varies and may be
reported as unavailable. Never hard-code a vault or write into a vault root.
