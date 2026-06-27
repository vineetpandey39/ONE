# ONE JARVIS

ONE is Vineet Pandey's local-first JARVIS command core.

This repository is a clean source snapshot for the ONE local/cloud command platform. Runtime secrets, local memory, databases, generated media, virtual environments, and node modules are intentionally excluded from Git.

## Local source

Primary local app path:

```text
C:\Users\pc\Documents\Codex\2026-06-12\files-mentioned-by-the-user-postforge\work\one-local
```

Primary source repo path:

```text
C:\Users\pc\Documents\Codex\2026-06-12\files-mentioned-by-the-user-postforge\work\ONE
```

## Safe sync

`scripts/one_git_autosync.ps1` only runs when `origin` is `vineetpandey39/ONE`. It blocks `.env`, runtime data, databases, logs, generated audio/video, virtual environments, and node modules.

`work\one-local\start-one.ps1` also runs a guarded clean-repo sync on startup, so source changes in `work\ONE` are pushed before ONE comes online.

Treat `work\one-local\data`, `work\one-local\one.env`, and the Obsidian vault as private runtime state, not GitHub source.

Private runtime backups belong in a separate private repo such as `vineetpandey39/ONE-private`. The local helper `work\one-local\sync-one-private.ps1` copies runtime memory and vault files while blocking raw secret files.

## Cloud note

The full ONE core depends on local services such as Ollama, native speech, local memory, and long-running workers. Vercel hosts the frontend/control surface from `frontend/`; the full autonomous core should run locally or on a persistent server/VPS.

`vercel.json` forces Vercel to build the Vite frontend instead of trying to deploy the Python backend from `pyproject.toml`.
