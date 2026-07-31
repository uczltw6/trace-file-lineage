# How this compares, and when not to use it

Short version: most provenance tools need you to have set something up *before* the
file was created. This one is for when you didn't.

| | Needs prior setup | Works on files you never committed | Answers "which script made this?" | Needs a server |
|---|---|---|---|---|
| **Trace File Lineage** | no | yes | yes, with a confidence label | no |
| Git | commits only | no | no | no |
| DVC | yes, pipelines declared up front | only what you track | yes, for declared stages | no |
| OpenLineage / Marquez | yes, jobs must emit events | no | yes, for instrumented jobs | usually |
| MLflow / W&B | yes, runs must be logged | logged artifacts only | yes, for logged runs | usually |
| `find` / `grep` | no | yes | no | no |

## Why not just use Git?

Git tracks *commits*, not *derivation*. It records that `figure.png` changed in commit
`abc123`, which tells you nothing about which of your four notebooks produced it. It
also cannot help with the many files you never committed — build outputs, intermediate
data, and everything an agent scattered through your working directory.

The two are complementary. This tool reads Git history as one evidence source, mainly
to follow files across renames.

## Why not DVC?

DVC is excellent, and if you already have a declared pipeline you should keep using it.
It answers questions *within* what you declared: stages, dependencies, and outputs
written in `dvc.yaml` before the work ran.

The difference is direction. DVC is prospective — declare, then run, then query. This
tool is mainly retrospective — the artifact already exists, nothing was declared, and
you need a best-supported guess with the evidence attached.

They compose: `lineage import --format dvc --source dvc.yaml` folds your declared
stages in as strong evidence alongside everything inferred.

## Why not OpenLineage?

OpenLineage is a standard for jobs that *emit* lineage events, typically into a backend
like Marquez. That is the right architecture for orchestrated data platforms, and it
scales far beyond a single workspace.

It requires instrumentation and, usually, a service. This tool requires neither, and
targets a single local workspace. It can read OpenLineage events you already have —
`lineage import --format openlineage` — but it will never ask you to stand up a server.

## Why not MLflow or Weights & Biases?

Both are experiment trackers: you log runs, parameters, and artifacts, and get an
excellent history of what you logged. If a file was produced outside a tracked run,
they have nothing to say about it. That gap is this tool's entire subject.

## When you should NOT use this

Being direct, because a tool that claims to fit everything fits nothing:

- **You need a guarantee, not a best guess.** Retrospective inference gives you ranked
  candidates with evidence. If you need proof, you need capture — either wrap the
  command with `lineage run` from now on, or use a system that enforces declaration.
- **You already have a declared, instrumented pipeline.** If DVC or OpenLineage already
  answers your questions, adding this only helps for the files outside that pipeline.
- **You need team-wide or cross-machine lineage.** The index is local and per-workspace.
  There is no server, no sync, and no shared history.
- **Your work is mostly in a database or warehouse.** This tool reasons about files.
  Table-level lineage is a different problem with better-suited tools.
- **You need deep JavaScript, Java, Go, or Rust analysis.** Python and notebooks are
  parsed properly. Everything else is text-indexed with conservative literal references.
- **You want automatic cleanup or enforced placement.** It can recommend where an
  agent should put an output, write that rule into agent memory, and report the
  resulting file tree. It never moves, renames, or deletes anything itself.

## What it is actually good at

- An artifact exists, nothing was recorded, and you need the most likely origin *with
  its evidence* rather than a confident-sounding guess.
- An agent or script produced a large batch of files and you need them grouped and
  explained rather than listed.
- An agent is about to create a file and should follow the workspace's established
  directory conventions instead of inventing a new output folder.
- You want to know what a change to an input would affect, before making it.
- You want zero setup: no server, no account, no API key, no declaration file, and no
  dependency beyond Python.
