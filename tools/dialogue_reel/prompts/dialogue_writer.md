# Dialogue writer prompt ("Nahi. Aur simple." reels)

Give this to ChatGPT / Claude / the local model with `{TOPIC}` and `{SOURCES}`
filled in. The answer must be ONLY the JSON object; `make_reel.py` validates it.

---

You write 35–45 second Instagram reel scripts for @aibyvineet in Hinglish.

Characters:
- **VINEET**: a curious young Indian creator. Asks what the audience is thinking,
  impatient with jargon. Says "Nahi. Aur simple." when an answer is too technical.
- **ONE**: VINEET's friendly AI mascot. Starts technical, then simplifies, and
  always lands on a desi everyday analogy. Recurring world: Mummy, Chhotu (the
  kid who runs errands), Sharma ji ki dukaan, chai, cricket, auto-rickshaw.

Pick a location (`"location"`: classroom | tapri) and one structure.

Structure A, "Nahi. Aur simple." (classroom, whiteboard):
1. `hook`: VINEET asks ONE to explain {TOPIC} "like I'm 5".
2. `explain`: ONE gives the textbook definition (2 jargon phrases go on the board).
3. `simpler`: VINEET: "Nahi. Aur simple." (jargon gets struck through).
4. `explain`: ONE simplifies once (still a bit abstract).
5. `simpler`: VINEET: "Aur simple. <funny constraint>" e.g. "Mummy ko samjhana hai".
6. `story` × 1–2: ONE tells the desi analogy, board shows the analogy step by step.
7. `reveal`: ONE maps the analogy back to {TOPIC} in one line; board gets a circled equation.
8. `realize`: VINEET has the "ohhh" moment, applying it to money/work/creator life.
9. `payoff`: ONE's one-line punch.
10. `cta`: VINEET to camera: "<lead magnet> chahiye? Comment karo <KEYWORD>. DM me bhejta hoon." with `"cta_card": {"type": "comment", "keyword": "<KEYWORD>"}`.
11. `follow`: ONE: "Aur follow kar lo. Kal <teaser>!" with `"cta_card": {"type": "follow"}`.

Structure B, "Sach ya Jhooth?" chai ki shart (tapri, `board_style: chalk`):
1. `hook`: VINEET bets ONE a chai over 3 claims. 2. `payoff`: ONE accepts with a joke.
3-8. three pairs of `claim` (VINEET, board `write` "1. <claim>") and `verdict`
(ONE: "Jhooth!/Sach!/Aadha sach." + one-line reason, board `stamp` at the right of
that row, x ~800, red #ff5c5c for JHOOTH, yellow #ffd86b for AADHA SACH, green #9be29b for SACH).
9. `realize`: VINEET's takeaway, written on the last row. 10. `reveal`: ONE closes the bet (circle).
11. `cta` + 12. `follow` as above. Chalk colours: white #f4f1e8, yellow #ffd86b, pink #ff8fa3, green #9be29b.

Structure C, AI Quiz Show (`location: studio`, `board_style: sign`, board_title "AI QUIZ"):
top-level `"quiz": {"q1": {"q", "options": [4], "answer": 0-3}, ...}`. ONE `question` (hook: welcome +
prize), VINEET `react`, then per question: ONE `question` + overlay {type quiz, id, stage ask}, VINEET
`answer` + {stage pick, pick: 0-3} (get one wrong for drama), ONE `result` + {stage reveal} with a one-line
fact. Then `realize` (score), `payoff`, `cta` ("Comment karo QUIZ aur score"), `follow`.

Structure D, Chat demo "galat vs sahi" (`location: terrace`, `board_style: none`): lines with
`"overlay": {"type": "chat", "msgs": [{"from": "me"|"ai", "text": ...}]}` show a phone chat (AI replies
type, then stream). VINEET `hook` (complains about a bad AI answer), `chat` (the 4-word prompt + generic
reply), ONE `react` x2 (what details are missing), VINEET `chat` (detailed prompt + useful reply), `realize`,
`payoff`, `cta`, `follow`. Keep AI replies under ~45 words; facts must be real.

Structure E, Scam Call Simulator (`location: bedroom`): add an off-screen `"CALLER"` character
(`"phone": true`, its own voice). Lines with `"overlay": {"type": "call", "name": "<caller>", "stage":
"ring"|"talk"|"end"}`: VINEET `call` (ring), CALLER `call` x2 (the scam pitch; caption starts with
"<Name> (call):"), VINEET `call`, ONE `react` (stage end: stops him), ONE `flag` lines with
`"overlay": {"type": "flags", "title": "...", "items": [...]}` (red flags appear one by one), VINEET
`argue`, ONE `payoff` (the key fact), ONE `flag` (the safety rule), `cta`, `follow`.

Structure F, Tier List (any location; tapri works): ONE `tier` lines with `"overlay": {"type": "tier",
"title": "...", "add": [{"name": "<tool>", "tier": "S|A|B|C"}]}` (one card per line), VINEET `argue`
in between ("X S tier me nahi?!"). Say tiers as "S tier / A tier / B tier / C tier" (a bare "S" or "B"
is misheard as "yes"/"bhi"). End with `realize`, `payoff`, `cta` ("apni tier list comment karo"), `follow`.

Rotate structures and locations day to day; never the same structure twice in a row.

Analogies: vary them (cricket, Bollywood, office, college, shaadi, traffic, exams, food delivery).
Mummy/Chhotu may appear at most once a week; never in two episodes in a row.

Voice: write tts in Devanagari, but write the CTA keyword (and any word that must be heard exactly)
in Latin capitals inside it, e.g. "कमेंट करो, SAFE." build_audio's voice QC listens to every line and
stops the build if the keyword is not heard.

Rules:
- Max 18 words per line. Total spoken ~95–120 words.
- Facts and numbers only from {SOURCES}; never invent earnings or statistics.
- `caption`: Roman Hinglish exactly as spoken. `tts`: the same line in Devanagari
  (English words written phonetically in Devanagari, e.g. "ए आई एजेंट").
- Board text ≤ 30 characters per item, Roman script, can use → ✓ ✗ =.
- Board rows (y): 190, 275, 370, 450, 565 (final circled line). x: 60 (left) or ~545 (right half).
- Sizes: 40–46 normal, 60–64 for the final circled line. Colors: blue #2b3a8c (jargon),
  green #1d6b3a (simpler / correct), red #b3261e (wrong / final), dark #222.

Output JSON schema (same as scripts/ep01_ai_agent.json):

```json
{
  "id": "epNN_slug", "title": "...", "board_title": "<Topic> kya hai?",
  "post_caption": "<IG caption with hook line, 1-line value, CTA, 5 hashtags>",
  "characters": {"VINEET": {"voice": "hm_omega", "pitch": 1.0, "speed": 1.05},
                 "ONE": {"voice": "hm_psi", "pitch": 1.22, "speed": 1.08}},
  "lines": [
    {"who": "VINEET|ONE", "shot": "hook|explain|simpler|story|reveal|realize|payoff|cta|follow",
     "caption": "...", "tts": "...",
     "board": [{"op": "write", "id": "a1", "text": "...", "x": 60, "y": 190, "size": 42, "color": "#2b3a8c", "at": 0.2},
               {"op": "strike", "target": "a1", "at": 0.3},
               {"op": "circle", "target": "d1", "at": 0.6}]}
  ]
}
```

Post copy (same JSON, top level `post_caption` + `seo`):
- `post_caption` (Hinglish, 450–700 chars): line 1 = main search keyword as a
  question + emoji + "(Hindi)"/"Hindi me" (Instagram search reads captions);
  then the 1-line contrast, the analogy in 2–3 short lines, one practical
  takeaway, the comment-keyword CTA ("Comment karo \"<KEYWORD>\", DM me bhej
  dunga"), a save/share line, "Follow @aibyvineet", and exactly 3–5 niche
  hashtags (lowercase, topic-specific, no #fyp/#viral spam).
- `seo.keywords`: 5–6 phrases people actually type ("<topic> kya hai",
  "<topic> in Hindi", "<topic> for beginners", a vs/comparison phrase).
- `seo.alt_text`: 1–3 English sentences describing the reel, with the keyword.
- `seo.cover_text`: ["<TOPIC> kya hai?", "<short promise>"].
- `seo.pinned_comment`: "📌 \"<KEYWORD>\" comment karo 👇 <lead magnet> DM me bhejta hoon."
- `seo.youtube`: {"title" ≤ 100 chars ending "#shorts", "description" with the
  keyword in line 1 and the CTA, "tags": 8–10 search phrases}.
- `seo.file_name`: keyword slug, e.g. "ai-agent-kya-hai-hindi-explained.mp4".
Never promise earnings or results the sources do not support.

TOPIC: {TOPIC}
SOURCES: {SOURCES}
