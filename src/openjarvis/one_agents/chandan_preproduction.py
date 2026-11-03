"""Generate and validate a sourced 15-chapter/75-shot Origin production pack."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import origin_to_ovation as pipeline
from .planexium_adapters import LaoDraft, _marked_json
from openjarvis.tools.lao_orchestrator import LaoOrchestratorTool


BEGIN = "BEGIN_OTO_PACK_JSON"
END = "END_OTO_PACK_JSON"
SHOT_TYPES = ("three_quarter_closeup", "side_action", "dynamic_action", "establishing_wide",
              "low_angle", "overhead", "equipment_macro", "environmental_pov",
              "crowd_reaction", "quiet_aftermath")
MOTIONS = ("slow_push", "slow_pullback", "lateral_drift", "focus_detail", "wide_hold", "vertical_reveal", "prime_ramp")
TRANSITIONS = ("hard_cut", "match_cut", "measured_dissolve", "dip_to_black", "whip_cut", "sound_bridge")
ORIENTATION = {
    "three_quarter_closeup": "three_quarter", "side_action": "side_profile",
    "dynamic_action": "front", "establishing_wide": "environment", "low_angle": "three_quarter",
    "overhead": "overhead", "equipment_macro": "detail", "environmental_pov": "pov",
    "crowd_reaction": "environment", "quiet_aftermath": "side_profile",
}
ROADMAP = (
    "Record-pressure cold open and the question of reinvention",
    "Madeira childhood context without invented hardship or routines",
    "Sporting youth development and leaving home",
    "Manchester arrival in 2003 and the raw winger",
    "Technique, decision-making and the first major transformation",
    "2008 peak in Manchester and the move to Madrid",
    "Madrid expectations and immediate scoring pressure",
    "From touchline winger to penalty-box finisher",
    "Champions League accumulation and record scale",
    "Portugal responsibility, near misses and endurance",
    "Euro 2016 and a national-team breakthrough",
    "Leaving Madrid, Juventus and adapting again",
    "Later-career setbacks and another reinvention",
    "International longevity, six World Cups and 146 goals",
    "Verified records, meaning of longevity and natural CTA",
)

MESSI_ROADMAP = (
    "World Cup-pressure cold open and the unanswered international question",
    "Rosario childhood context without invented hardship or routines",
    "Newell's youth football and the move to Barcelona",
    "Barcelona academy development and the senior debut",
    "Early brilliance, physical resilience and the first transformation",
    "Club dominance, individual awards and rising expectations",
    "Argentina responsibility and the 2014 World Cup final",
    "Repeated international heartbreak and the burden of comparison",
    "Record scale at Barcelona and a changing role",
    "The 2021 Copa America breakthrough",
    "Leaving Barcelona and adapting in Paris",
    "Qatar 2022: pressure, leadership and the final campaign",
    "The World Cup final and the long-awaited resolution",
    "Later-career reinvention and sustained international longevity",
    "Verified records, legacy and a natural CTA",
)


def _roadmap(manifest: dict) -> tuple[str, ...]:
    return MESSI_ROADMAP if manifest.get("subject_id") == "lionel-messi" else ROADMAP


def _prompt(manifest: dict, brief: dict) -> str:
    sources = brief.get("sources") or {}
    return f"""Act as CHANDAN, a world-class factual sports-biography writer and director.
Create the complete English preproduction pack for {manifest['subject']} for Origin to Ovation.
Return JSON only between {BEGIN} and {END}.

Story contract: exactly 15 chronological chapters and exactly 5 shots per chapter. Each shot narration is 35-48 words, emotionally human, third-person, connected to the previous line, documentary-cinematic rather than a list of statistics. Begin with a high-stakes cold open, plant a clear question, use setbacks/reinvention/open loops, and end with verified records plus a natural CTA. Never invent dialogue, private thoughts, childhood routines, travel routes, poverty, injuries or match actions. Use only claims supported by the official sources below. If a detail is not supported, keep it atmospheric and non-specific.

Visual contract: photoreal cinematic CGI, recognisable age-appropriate editorial likeness without claiming archival authenticity. Front, three-quarter and true side angles dominate. Rear views are transitional only, maximum 15 percent and never consecutive. Every chapter includes an emotionally legible face angle. Use varied lenses and the supplied shot types. Plain era-correct kit; zero crests, logos, sponsors, maker marks or readable venue text. Correct football anatomy, hands, feet, running, ball contact and kicking mechanics.

Direction contract: every shot needs a concise visual brief and one shot_type chosen from {list(SHOT_TYPES)}. Reserve whooshes for motivated high-energy transitions; use silence drops before major turning points and kinetic text only for verified prime facts.

Required JSON schema:
{{"title":"...","central_dramatic_question":"...","description_lead":"...","tags":["..."],"thumbnail":{{"headline":"2-4 words","prompt":"..."}},"chapters":[{{"title":"...","age":18,"era":"...","claim_id":"C01","source_key":"uefa_records","shots":[{{"narration":"35-48 words","visual":"...","shot_type":"three_quarter_closeup","kinetic_text":""}}]}}]}}
Exactly 15 chapter objects, exactly 5 shots each. Allowed source_key values and official URLs: {json.dumps(sources, ensure_ascii=False)}.
Documented anchors available in the commissioned brief: {brief.get('opening_hook')}; {brief.get('central_dramatic_question')}; prime facts {json.dumps((brief.get('direction_requirements') or {}).get('prime_kinetic_facts', []))}.
Do not output markdown fences. End with {END}."""


def _chunk_prompt(manifest: dict, brief: dict, start: int, end: int) -> tuple[str, str, str]:
    begin = f"BEGIN_OTO_PACK_{start:02d}_{end:02d}"
    finish = f"END_OTO_PACK_{start:02d}_{end:02d}"
    roadmap = "\n".join(f"{i + 1}. {title}" for i, title in enumerate(_roadmap(manifest)))
    sources = brief.get("sources") or {}
    prompt = f"""Continue as CHANDAN, factual sports-biography writer and director for {manifest['subject']}.
Return ONLY valid JSON between {begin} and {finish}; no markdown fences or commentary.
Write chapters {start} through {end} from this locked 15-chapter roadmap:
{roadmap}

Schema: {{"chapters":[{{"chapter_number":{start},"title":"...","age":18,"era":"...","claim_id":"C{start:02d}","source_key":"one allowed key","shots":[{{"narration":"35-48 words","visual":"concise cinematic visual brief","shot_type":"one allowed type","kinetic_text":"verified fact or empty"}}]}}]}}
Return exactly {end-start+1} chapters and exactly five shots per chapter. Each narration must be 35-48 words, emotionally human, third-person English and connected end-to-end. No invented dialogue, thoughts, childhood routine, travel, hardship, injury or match action. Every factual sentence must remain within the official source represented by source_key.
Allowed source keys/URLs: {json.dumps(sources, ensure_ascii=False)}
Allowed shot types: {json.dumps(SHOT_TYPES)}. Use recognisable front, three-quarter and true side views; rear views only as rare transitions, never consecutive. Every chapter needs an emotionally legible face shot. Photoreal cinematic CGI, age/era accurate, plain kit, zero logos/crests/sponsors/maker marks/readable venue text, correct football anatomy and mechanics. Use selective whoosh only through visual energy; kinetic_text only for a verified prime fact.
Commissioned hook: {brief.get('opening_hook')}
Central question: {brief.get('central_dramatic_question')}
Prime facts: {json.dumps((brief.get('direction_requirements') or {}).get('prime_kinetic_facts', []))}
Close chapter {end} so the next numbered chapter follows naturally. End with {finish}."""
    return prompt, begin, finish


def generate(path: Path) -> dict:
    manifest = pipeline.read(path / "mission.json")
    brief = pipeline.read(path / "research/commission-brief.json")
    reference = Path(manifest["character_reference"])
    review = pipeline.read(path / "runtime/reference-review.json")
    if review.get("status") != "passed" or review.get("reference_sha256") != pipeline.digest(reference):
        raise ValueError("Approved hash-bound reference required before preproduction")
    steps = [
        {"action": "open_browser", "args": {"profile_dir": manifest["browser"]["profile_dir"], "cdp_url": manifest["browser"]["cdp_url"], "start_url": "https://chatgpt.com/"}},
        {"action": "open_tab", "args": {"url": "https://chatgpt.com/", "name": "episode_pack"}},
    ]
    chunks = []
    for start in range(1, 16, 3):
        end = start + 2
        prompt, begin, finish = _chunk_prompt(manifest, brief, start, end)
        key = f"pack_{start:02d}_{end:02d}"
        steps.append({"action": "ask_chatgpt", "args": {"prompt": prompt, "expected_markers": [begin, finish], "timeout_ms": 420000, "as": key}})
        chunks.append((key, begin, finish))
    config = pipeline.read(pipeline.ROOT / "runtime-config.json")
    provider = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id"), tuple(Path(p) for p in config["artifact_roots"]))
    receipt = path / "runtime/providers/preproduction-pack-v2.json"
    outputs, provider_job = provider.run(f"Origin to Ovation - {manifest['subject']} - preproduction", steps, {}, receipt, timeout=900)
    chapters = []
    for key, begin, finish in chunks:
        chunk = _marked_json(outputs.get(key, ""), begin, finish)
        chapters.extend(chunk.get("chapters") or [])
    pack = {"title": brief.get("working_title") or f"{manifest['subject']}: The Full Journey",
            "central_dramatic_question": brief["central_dramatic_question"],
            "description_lead": f"{manifest['subject']} biography — a source-linked journey of reinvention, pressure, records and longevity.",
            "tags": [manifest['subject'], f"{manifest['subject']} biography", "football documentary", "sports biography", "Origin to Ovation"],
            "thumbnail": {"headline": "BUILT TO ADAPT", "prompt": "Recognisable emotional three-quarter face, football foreground, Madeira-to-stadium contrast, no logos or crests."},
            "chapters": chapters}
    if len(chapters) != 15 or any(len(ch.get("shots") or []) != 5 for ch in chapters):
        raise ValueError("CHANDAN pack must contain exactly 15 chapters and 75 shots")
    sources = brief.get("sources") or {}
    master = path / "production/master-v1"
    images = master / "images"
    images.mkdir(parents=True, exist_ok=True)
    plan = []
    ledger = ["| Claim | Supported topic | Source | Notes |", "|---|---|---|---|"]
    register = []
    narration_lines = []
    for chapter_index, chapter in enumerate(chapters, 1):
        source_key = str(chapter.get("source_key") or "")
        if source_key not in sources:
            raise ValueError(f"Unknown source key in chapter {chapter_index}: {source_key}")
        claim_id = f"C{chapter_index:02d}"
        register.append({"claim_id": claim_id, "url": sources[source_key]})
        ledger.append(f"| {claim_id} | {chapter['title']} | [official source]({sources[source_key]}) | Narration paraphrased; no private routine or dialogue claimed |")
        for offset, shot in enumerate(chapter["shots"], 1):
            number = (chapter_index - 1) * 5 + offset
            shot_id = f"P{number:02d}"
            narration = re.sub(r"\s+", " ", str(shot.get("narration") or "")).strip()
            if not 25 <= len(narration.split()) <= 60:
                raise ValueError(f"{shot_id} narration length outside governed range")
            # Deterministic balanced grammar: every chapter gets a distinct
            # five-shot sequence, no adjacent duplicates, and no dominant family.
            chapter_zero = chapter_index - 1
            step = 1 if chapter_zero < 10 else 3
            shot_type = SHOT_TYPES[(chapter_zero + (offset - 1) * step) % len(SHOT_TYPES)]
            visual = re.sub(r"\s+", " ", str(shot.get("visual") or "")).strip()
            prompt_text = (f"Create ONE full-frame 16:9 photoreal cinematic CGI biography scene, original illustrative reconstruction, not archival footage. {shot_id}: {visual}. "
                           f"Subject {manifest['subject']}, age {chapter['age']}, era {chapter['era']}. Preserve the approved canonical identity from the attached reference. "
                           "Use a recognisable front, three-quarter or true side-profile angle appropriate to the requested shot; rear view only when explicitly requested and never as the default. "
                           "Plain period-correct kit with zero logos, crests, sponsors, maker marks, signatures, watermarks, flags, scoreboards or readable venue text. "
                           "Football anatomy, hands, feet, running posture, ball contact and kicking mechanics must be physically correct. Output one widescreen image.")
            plan.append({"shot_id": shot_id, "chapter": chapter_index, "chapter_title": chapter["title"],
                         "narration": narration, "claim_ids": [claim_id], "age": chapter["age"], "era": chapter["era"],
                         "visual": visual, "shot_type": shot_type, "prompt": prompt_text, "reference": str(reference),
                         "image": str(images / f"{shot_id}.png"), "motion": MOTIONS[(number - 1) % len(MOTIONS)],
                         "director": {"shot_type": shot_type, "faceless": False, "transition": TRANSITIONS[(number - 1) % len(TRANSITIONS)],
                                      "sound_cue": "whoosh" if shot_type in {"dynamic_action", "low_angle"} and number % 3 == 0 else ("silence_drop" if number in {1, 26, 46, 71} else "location_bed"),
                                      "kinetic_text": str(shot.get("kinetic_text") or "")},
                         "camera_orientation": ORIENTATION[shot_type], "status": "planned", "story": {"role": "cold_open" if number <= 5 else "chronological_payoff",
                         "open_loop": number in {1, 6, 26, 46}, "must_pay_off_with_documented_fact": True,
                         "pattern_interrupt": "camera_or_sound_shift", "retention_checkpoint": round((number - 1) / 75, 3)}})
            narration_lines.append(narration)
    pipeline.write(master / "shot-plan.json", plan)
    (master / "narration.txt").write_text("\n\n".join(narration_lines), encoding="utf-8")
    metadata = {"title": pack["title"], "central_dramatic_question": pack["central_dramatic_question"],
                "description_lead": pack["description_lead"], "voice_name": brief["voice"]["name"],
                "voice_id": brief["voice"]["voice_id"], "chapter_titles": [c["title"] for c in chapters],
                "tags": pack.get("tags") or [], "thumbnail_concepts": [pack.get("thumbnail") or {}]}
    pipeline.write(master / "editorial-metadata.json", metadata)
    (path / "research/claim-ledger.md").write_text("\n".join(ledger) + "\n", encoding="utf-8")
    pipeline.write(path / "research/source-register.json", register)
    template = pipeline.ROOT / "missions/pv-sindhu-2026-10-26/production/master-v1/generate_narration.py"
    if not template.is_file():
        raise FileNotFoundError("Governed ElevenLabs narration template missing")
    script = template.read_text(encoding="utf-8").replace("George Narration", f"{brief['voice']['name']} Narration")
    script = script.replace('VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"', f'VOICE_ID = "{brief["voice"]["voice_id"]}"')
    script = script.replace('TITLE = "P. V. Sindhu Biography: The Finals That Forged a Champion"', f'TITLE = {json.dumps(pack["title"])}')
    script = script.replace("narration-george", f"narration-{brief['voice']['name'].lower()}").replace("pv-sindhu-george", f"{manifest['subject_id']}-{brief['voice']['name'].lower()}")
    script = script.replace('"voice": "George"', f'"voice": "{brief["voice"]["name"]}"')
    script = script.replace('"voice": "George", "duration_seconds"', f'"voice": "{brief["voice"]["name"]}", "duration_seconds"')
    (master / "generate_narration.py").write_text(script, encoding="utf-8")
    manifest.update(production_phase="reference_then_produce", reference_review_required=True)
    pipeline.write(path / "mission.json", manifest)
    return {"status": "production_pack_ready", "shots": len(plan), "provider_job": provider_job,
            "shot_plan": str(master / "shot-plan.json")}


def tighten_narration(path: Path) -> dict:
    """Shorten a validated board to a real 10–12 minute voice contract."""
    manifest = pipeline.read(path / "mission.json")
    master = path / "production/master-v1"
    plan = pipeline.read(master / "shot-plan.json")
    if len(plan) != 75:
        raise ValueError("Narration tightening requires the complete 75-shot board")
    steps = [
        {"action": "open_browser", "args": {"profile_dir": manifest["browser"]["profile_dir"], "cdp_url": manifest["browser"]["cdp_url"], "start_url": "https://chatgpt.com/"}},
        {"action": "open_tab", "args": {"url": "https://chatgpt.com/", "name": "narration_tighten"}},
    ]
    chunks = []
    for start in range(0, 75, 15):
        subset = [{"shot_id": s["shot_id"], "narration": s["narration"]} for s in plan[start:start + 15]]
        begin, end = f"BEGIN_OTO_TIGHT_{start + 1:02d}", f"END_OTO_TIGHT_{start + 15:02d}"
        key = f"tight_{start + 1:02d}_{start + 15:02d}"
        prompt = (f"Rewrite these 15 connected sports-biography narration lines for a 10–12 minute film. Return JSON only between {begin} and {end}: "
                  '{"shots":[{"shot_id":"P01","narration":"16-20 words"}]}. '
                  "Keep every shot_id. Each narration must be 16–20 English words, third-person, human and cinematic. Preserve the supported meaning and chronology; add no facts, dialogue, thoughts, motives, statistics or claims. Avoid sentence fragments and repetitive openings. "
                  f"Input: {json.dumps(subset, ensure_ascii=False)} End with {end}.")
        steps.append({"action": "ask_chatgpt", "args": {"prompt": prompt, "expected_markers": [begin, end], "timeout_ms": 300000, "as": key}})
        chunks.append((key, begin, end))
    config = pipeline.read(pipeline.ROOT / "runtime-config.json")
    provider = LaoDraft(LaoOrchestratorTool(), config.get("lao_folder_id"), tuple(Path(p) for p in config["artifact_roots"]))
    outputs, provider_job = provider.run(f"Origin to Ovation - {manifest['subject']} - narration tighten", steps, {},
                                         path / "runtime/providers/narration-tighten-v1.json", timeout=900)
    revised = {}
    for key, begin, end in chunks:
        data = _marked_json(outputs.get(key, ""), begin, end)
        for row in data.get("shots") or []:
            words = str(row.get("narration") or "").split()
            if not 14 <= len(words) <= 22:
                raise ValueError(f"{row.get('shot_id')} tightened narration outside governed tolerance")
            revised[str(row.get("shot_id"))] = " ".join(words)
    if set(revised) != {s["shot_id"] for s in plan}:
        raise ValueError("Tightening response did not return all 75 unique shots")
    for shot in plan:
        shot["narration"] = revised[shot["shot_id"]]
    pipeline.write(master / "shot-plan.json", plan)
    (master / "narration.txt").write_text("\n\n".join(s["narration"] for s in plan), encoding="utf-8")
    return {"status": "narration_tightened", "words": sum(len(s["narration"].split()) for s in plan),
            "provider_job": provider_job}
