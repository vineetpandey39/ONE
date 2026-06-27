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
C:\Users\pc\Documents\Codex\2026-06-12\files-mentioned-by-the-user-postforge\work\one-local\src
```

## Safe sync

`scripts/one_git_autosync.ps1` only runs when `origin` is `vineetpandey39/ONE`. It blocks `.env`, runtime data, databases, logs, generated audio/video, virtual environments, and node modules.

## Cloud note

The full ONE core depends on local services such as Ollama, native speech, local memory, and long-running workers. Vercel can host a frontend or control surface, but the full autonomous core should run locally or on a persistent server/VPS.
