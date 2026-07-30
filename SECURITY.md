# Security policy

## Supported versions

This project is in public alpha. Security fixes land on the latest minor release.

| Version | Supported |
|---|---|
| 0.7.x | yes |
| < 0.7 | no |

## Reporting a vulnerability

Report privately first. Use GitHub's
[private vulnerability reporting](https://github.com/uczltw6/trace-file-lineage/security/advisories/new)
for this repository, or contact the maintainer directly. Please do not open a public
issue for a suspected vulnerability.

Expect an acknowledgement within a few days and a status update as the fix progresses.

### What to include

- Affected version and platform, plus the `lineage doctor` output.
- The exact command and a description of the impact.
- A **minimal redacted fixture** that reproduces the problem.

### What never to include

Do not attach workspace contents, credentials, API keys, raw session identifiers,
browser history databases, or a real `.file-lineage/lineage.db`. The index can contain
extracted text from your files.

## Security model

What the tool guarantees:

- Analysis is local; no file contents are transmitted.
- The core imports no vendor SDK and requires no API key.
- **Scanning never executes project code.** Python and notebook analysis is AST-based,
  not evaluated.
- Secret-like files, credential stores, dependencies, caches, and the tool's own index
  are excluded by default.
- External symlinks are not followed.
- Hashing and extraction respect size limits.
- ZIP-based documents enforce member-count, member-size, total expanded-size, and
  compression-ratio limits before content is read (zip-bomb defence).
- Malformed documents produce warnings rather than scan failures.
- Child commands use argument arrays with no shell interpolation, and credential-looking
  arguments are redacted from run records.
- Run records store safe summaries only — never prompts, conversations, transcripts,
  arbitrary environment variables, or raw session identifiers.
- `reproduce` is dry-run only and never launches a process.
- The HTML explorer is fully self-contained: no network request, CDN, or remote font.

What is explicitly out of scope:

- **The local index is not encrypted.** `.file-lineage/lineage.db` contains extracted
  text from your workspace. Treat it with the same care as the workspace itself and keep
  it out of version control (the shipped `.gitignore` already excludes it).
- **Plugin hooks require host trust.** They run on host lifecycle events under whatever
  permissions the host grants.
- **Opt-in platform adapters** (browser history, Spotlight, GVFS) read OS-provided
  metadata when you enable them. They are off by default.
- **Imported provenance marked `--trusted`** is accepted as attested by design. Only
  trust sources you control.
