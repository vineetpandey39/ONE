---
name: one-memory-curator
description: Turn verified conversations, decisions, and transcripts into durable, linked Obsidian memory using ONE's vault-scoped tools.
license: MIT
allowed-tools: obsidian_memory
---

# ONE Memory Curator

Use `obsidian_memory` for every vault operation. It is restricted to the connected
vault and supports `search`, `read`, `create`, and `append` actions.

## Rules

1. Search before creating to avoid duplicate notes.
2. Use `obsidian-markdown` for valid properties, wikilinks, callouts, and embeds.
3. Store confirmed facts, decisions, preferences, task outcomes, and source links.
4. Clearly label estimates, assumptions, and unverified claims.
5. Never store credentials, tokens, passwords, or private keys.
6. Prefer atomic notes with descriptive filenames and `[[wikilinks]]` to related notes.
7. Use `create` for a new note and `append` for an existing journal; never overwrite silently.
8. Use `obsidian-bases` or `json-canvas` only for a requested database view or visual knowledge map.
