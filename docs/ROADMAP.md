# ONE — Roadmap

Last updated: 2026-07-09

This tracks what's actually built, what's actually running, and what's next —
written from direct inspection of the code, config, and runtime data, not
from memory. Where something looked done but wasn't, that's called out
explicitly.

## Current state

### Core platform
Built on OpenJarvis (Apache 2.0) with a proprietary layer on top: the
`one_agents` persona registry, the IA content pipeline, NVIDIA
Nemotron/FLUX model wiring, the credential vault UI, and two skills
(`one-local-transcription`, `one-memory-curator`).

### Model routing (fast/heavy tier) — done
- Fast tier is the default for every job: local Ollama, `llama3.1:8b`.
- Heavy tier is opt-in only, via `tier=heavy` (the `agent_network` tool
  parameter, or saying "heavy"/"escalate"/"use nemotron" in chat) — routes to
  NVIDIA Nemotron. It is never used unless a job asks for it by name.
- Fixed a latent bug: an unset `ONE_ROUTER_MODEL` used to fall through to
  `NEMOTRON_MODEL`, meaning even a "fast" job could have silently landed on
  the paid cloud model. `_resolve_planner_model()` in
  `one_agents/runtime.py` no longer does that.
- `llama3.1:8b` is now actually pulled in Ollama — it was configured and
  documented as "Active" but was not present locally until this pass.

### Image generation — done
- OpenAI is now the formally documented default (`ONE_IMAGE_PROVIDER=openai`),
  matching what was already running live. Local FLUX stays wired as a free,
  opt-in alternative — set `ONE_IMAGE_PROVIDER=flux` and
  `ONE_FLUX_AUTOSTART=true` to switch.

### Named-persona operator layer — corrected this pass
12 personas are registered in `one_agents/runtime.py`. On inspection, **6**
have real execute/publish logic, not just generic planning: **TITAN, IA,
ALFA, JOBHUNT, BETA, HEPHAISTOS**. The other 6 — HERMES, ARES, APOLLO,
ATHENA, POSEIDON, ZEUS — fall through to the generic planner only (no
persona-specific action yet).

TITAN was believed unimplemented going into this pass. It is fully coded
(`_run_titan`: PostForge refresh → generate → carousel-images → Instagram
publish) but was non-functional because `POSTFORGE_API_SECRET` was blank
locally. A secret has been generated and set in `one.env`.
**Outstanding: set the same value as `POSTFORGE_API_SECRET` in the
postforge-ai Vercel project**, then run one real TITAN job to confirm it
actually posts.

### Skill optimization loop — diagnosed, not yet actionable
`jarvis optimize skills` and `jarvis bench skills` are fully wired and run
cleanly (confirmed via `--dry-run` and `--help`). Telemetry is active — 106
traces / 346 trace_steps recorded from real usage. But zero of those traces
invoke either skill (`one-local-transcription`, `one-memory-curator`) — they
have never actually been used, so there's nothing to optimize against the
default minimum of 20 traces per skill. This is a usage gap, not a wiring
problem: it becomes actionable once the skills see real use.

### IA restoration-reel pipeline — diagnosed, do not expand yet
The location rotation already anticipates international expansion: 5
international cities (Jakarta, Manila, Lagos, Cairo, Rio de Janeiro) are
pre-staged in `configs/restoration_locations/india_rotation.json` with
`"active": false` — flipping them on is a one-line config change, no code.

However: IA has **no automated recurring schedule** —
`_enqueue_due_recurring_jobs()` only auto-schedules ALFA and JOBHUNT, not
IA. All 10 historical IA runs in `restoration_runs.db` are manual one-offs
from 2026-06-20/21; every single one has `posted_channels` empty and
`views` at 0; nothing has run since. Flipping international on now would be
premature — there is no India-phase traction to measure yet, because
nothing has actually been published. The config file's own note ties
international activation to "the India phase [having] enough traction (per
the 5-6 month plan)" — that clock hasn't started.

### Dead code — cleaned up this pass
Removed `one_agents/restoration.py` and `agents/restoration_reel.py`, both
explicit, unreferenced, self-documented-as-safe-to-delete stubs superseded
by the IA agent family. Verified nothing imported either before deleting.

## Next up, in order

1. **Activate TITAN.** Set `POSTFORGE_API_SECRET` in the postforge-ai Vercel
   project to the value now in `one.env`; run one real TITAN job end-to-end.
2. **Give IA a pulse.** Wire it into an actual recurring schedule (extend
   `_enqueue_due_recurring_jobs`, or a Cowork/cron scheduled task) and
   confirm at least one post reaches a real channel — right now it has
   never posted anything.
3. **Earn the skill-optimization data.** Use ONE for real tasks that touch
   `one-local-transcription` and `one-memory-curator` until each has 20+
   traced invocations, then run `jarvis optimize skills --policy dspy`.
4. **Pick one planner-only persona, not six.** Of HERMES, ARES, APOLLO,
   ATHENA, POSEIDON, ZEUS, implement whichever has the clearest near-term
   revenue/utility case next — don't add more registry placeholders.
5. **Only then, go international.** Once IA has a measurable India-phase
   track record (real posting cadence, tracked views/engagement), flip the
   pre-staged entries in `india_rotation.json`.

## Known caveat on this file

`sync-one-github.ps1` wipes `ONE/docs/` on every run except for
`ONE_LOCAL_MODEL_INVENTORY.md`, which it copies back explicitly. This file
lives durably here (the sync script only ever *reads* from
`one-local/src/docs/`, never deletes it) and has been copied once into
`ONE/docs/ROADMAP.md` for immediate visibility, but that copy will not
survive the next automated sync unless `sync-one-github.ps1`'s file list is
updated to include it.
