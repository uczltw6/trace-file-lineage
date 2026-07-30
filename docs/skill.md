# Using this as an agent skill

Two ways to use it, and the difference matters.

## Manual mode

Nothing to enable. Ask your agent a question, or run the commands yourself:

```sh
lineage explain report.pdf          # where did this come from?
lineage views --list                # pick an angle
lineage layout                      # how is this project organised?
```

Use this for a historic project you did not track, or a one-off question.
Answers about files created before you installed anything are reconstructed from
evidence, so most of them are `candidate` rather than `verified`. That is the
honest ceiling of retrospective tracing, not a defect.

## Continuous mode

```sh
lineage enable
```

This writes a required instruction into the project's own agent memory —
`CLAUDE.md` and `AGENTS.md` — telling the agent to record a lineage boundary at
the end of **every** task, where to put new files, and to report assurance rather
than presenting a guess as proof.

From then on, files created in this project get `verified` provenance instead of
inferred guesses, because the run that produced them was observed.

`lineage status` shows whether it is on. `lineage disable` removes exactly the
block it added and nothing else.

### Why a written rule rather than trusting the agent to remember

An agent *may* recall that a skill exists. That produces intermittent coverage,
which is worse than none, because the gaps are invisible — you cannot tell
whether a missing record means "nothing changed" or "the agent forgot".

Agent memory files are re-read at the start of every session, so the requirement
is present in context every time rather than depending on recall.

**Honest limitation:** this is an instruction, not an enforcement mechanism. It is
far more reliable than hoping, and less reliable than a lifecycle hook. Hosts that
support hooks should install those as well — see [install.md](install.md) — which
capture the boundary without the agent having to cooperate at all.

## Choosing a view

`lineage views --list` prints all of them. There is deliberately no single
"the diagram", because the useful question differs each time:

| Question | View |
|---|---|
| What is even in this project? | `project-map` |
| Where did this one file come from, and what uses it? | `file-history` |
| What is behind this final report, all the way down? | `source-chain` |
| What are the multi-step pipelines here? | `pipeline` |
| What did that agent task produce? | `agent-run` |
| Which script made which figure? | `code-to-image` |
| Which document became this PDF? | `document-export` |
| What is duplicated? | `duplicates` |
| Is this a parameter sweep? | `sweeps` |
| What happened when? | `timeline` |
| What looks abandoned? | `orphans` |

Each renders as `--format markdown` (default), `json`, or `mermaid`.

## Keeping the workspace tidy

```sh
lineage layout
```

Reports the conventions the project already follows — where `.py` files usually
live, where outputs usually go — plus the shapes that normally mean drift:
single-file directories, names carrying `final`/`v2`/`copy`/a date, very long
filenames, deep nesting, crowded directories.

It is **read-only**. Nothing is moved, renamed, or deleted; acting on it stays
your decision. Continuous mode points the agent at this command so new files
follow the existing layout instead of adding another `output_final_v2/`.
