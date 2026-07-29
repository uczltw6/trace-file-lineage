# Mode A baseline

- No local or workspace `SKILL.md` with `name: trace-file-lineage` existed.
- The authorized development workspace contained only the earlier project-level
  lineage bootstrap files; no unrelated repository changes were present.
- Python 3.14.0, Git 2.50.1, and Codex CLI 0.146.0-alpha.3.1 were available.
- The official Codex documentation confirmed `.agents/skills` user discovery,
  plugin `.codex-plugin/plugin.json`, default `hooks/hooks.json`, and the
  `UserPromptSubmit` / `Stop` hook events.
- Mode A was selected and the plugin and skill were scaffolded with the provided
  creator workflows.

Compatibility risks: historical inference remains probabilistic; optional PDF
and image dependencies are absent in the core test environment; Linux and
Windows claims require successful remote CI execution.
