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

`sync-one-github.ps1` publishes source to this repo, and only when `origin` is
`vineetpandey39/ONE`. It mirrors a filtered subset of the working tree into this
clean repo rather than pushing from the working tree itself, so the live source
folder never carries a public remote. After staging it verifies what actually
got staged — `.env`, `one.env`, `credentials.toml`, key and certificate files,
runtime data, databases, logs, generated audio/video, virtual environments and
node modules — and if anything blocked slipped past the excludes it unstages it
and exits without committing or pushing.

`start-one.ps1` launches that sync, and the private one, detached at startup, so
a slow or failing backup never delays ONE coming online. A sync problem shows up
in `one-sync-github-error.log` rather than as an offline ONE.

Treat the runtime `data` folder, `one.env`, and the Obsidian vault as private
runtime state, not GitHub source.

Private runtime backups belong in a separate private repo such as
`vineetpandey39/ONE-private`. The local helper `sync-one-private.ps1` copies
runtime memory and vault files while blocking raw secret files and machine-local
caches such as model weights.

## Cloud note

The full ONE core depends on local services such as Ollama, native speech, local memory, and long-running workers. Vercel hosts the frontend/control surface from `frontend/`; the full autonomous core should run locally or on a persistent server/VPS.

`vercel.json` forces Vercel to build the Vite frontend instead of trying to deploy the Python backend from `pyproject.toml`.
