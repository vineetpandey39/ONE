"""No-spend daily Shloka mission creation.

Mission creation prepares reviewable text, music direction and visual briefs. It
never calls a provider, spends credits, renders, uploads or publishes.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .core import Journal, STAGES, fingerprint, read, write
from .floor12 import BRAND, CHANNEL
from .providers import music_payload
from .worker import lyrics_binding


FRIDAY_LAKSHMI_LYRICS = [
    "माँ लक्ष्मी आओ, दीप जलाओ।",
    "मन के आँगन ज्योति जगाओ।",
    "कमल चरण की शीतल छाया।",
    "हर मन में विश्वास जगाए।",
    "श्रम में धीरज, कर्म में निष्ठा।",
    "वाणी में मधुरता लाओ।",
    "लोभ मिटे, संतोष खिले।",
    "सच्ची समृद्धि घर में लाओ।",
    "अन्न का आदर, जल की रक्षा।",
    "सेवा का संकल्प जगाओ।",
    "दीन दुखी के संग खड़े हों।",
    "ऐसा निर्मल भाव सिखाओ।",
    "कमल खिले जब मन के भीतर।",
    "संशय का तम दूर हो जाए।",
    "सत्य, दया और श्रम की पूँजी।",
    "हर घर का उत्सव बन जाए।",
    "भोर सुनहरी, साँझ सुहानी।",
    "हर पल कृतज्ञता भर जाए।",
    "माँ लक्ष्मी की करुणा लेकर।",
    "जीवन शुभ पथ पर बढ़ जाए।",
    "सुख में विनय, दुख में साहस।",
    "मन में शुभ संकल्प जगाओ।",
    "माँ लक्ष्मी आओ, दीप जलाओ।",
    "मन के आँगन ज्योति जगाओ।",
]


LAKSHMI_SCENES = [
    "Serene canonical Lakshmi seated on a fully open pink lotus above a quiet lotus lake at blue hour.",
    "Close devotional portrait, calm compassionate expression, gold crown and red-gold sari, soft lamp bokeh.",
    "Wide lotus lake at dawn with Lakshmi centered, temple silhouette and warm sky reflected in water.",
    "Lakshmi beneath a carved temple arch, one hand in blessing, symmetrical oil lamps and marigolds.",
    "Medium portrait beside a luminous lotus pond, subtle gold particles and gentle rose petals.",
    "Wide palace courtyard at sunrise, rangoli and lamps leading toward the seated deity.",
    "Close view of blessing hand and lotus flower, face still visible and anatomically correct.",
    "Lakshmi seated in a quiet sanctum, warm diya light, deep crimson and antique gold palette.",
    "Moonlit lotus garden, silver-blue ambience with restrained warm gold rim light on Lakshmi.",
    "Temple steps with rows of lamps, Lakshmi framed at the top, respectful symmetrical composition.",
    "Canonical Lakshmi portrait with two white elephants in the distant background, no ritual action by deity.",
    "Lotus petals floating across a calm river, Lakshmi seated on the far bank in golden morning light.",
    "Close eyes-open portrait conveying compassion and serenity, clean negative space for captions.",
    "Wide rural harvest landscape at dawn, Lakshmi as a blessing presence, no coins or material excess.",
    "Family-free devotional still life of grain, water pot, lotus and lamps before a distant Lakshmi shrine.",
    "Lakshmi beside a temple pond at sunset, veena-like warm strings suggested through atmosphere only.",
    "Grand but uncluttered lotus mandala background with Lakshmi centered and subtle god rays.",
    "Side-profile devotional portrait, gold edge light, deep red drapery and soft floating petals.",
    "Wide festival courtyard with suspended lamps and Lakshmi seated beyond a clean central pathway.",
    "Lakshmi in a serene garden pavilion, lotus flowers and restrained morning mist.",
    "Close canonical portrait with warm smile, crisp eyes, natural skin texture and ornate but modest attire.",
    "Night temple exterior reflected in water, Lakshmi visible within the illuminated doorway.",
    "Final lifted tableau, Lakshmi on lotus with expanding warm light and rose-gold clouds.",
    "Closing prayer image, Lakshmi softly lit against a calm dark-blue background with one steady diya.",
]

LAKSHMI_AARTI = [
    "ॐ जय लक्ष्मी माता, मैया जय लक्ष्मी माता।",
    "तुमको निसिदिन सेवत, हर-विष्णु-धाता॥",
    "उमा, रमा, ब्रह्माणी, तुम ही जग-माता।",
    "सूर्य-चन्द्रमा ध्यावत, नारद ऋषि गाता॥",
    "दुर्गारूप निरंजनि, सुख-सम्पति दाता।",
    "जो कोई तुमको ध्यावत, ऋद्धि-सिद्धि-धन पाता॥",
    "तुम पाताल-निवासिनि, तुम ही शुभदाता।",
    "कर्म-प्रभाव-प्रकाशिनि, भवनिधि की त्राता॥",
    "जिस घर तुम रहती, तहँ सब सद्गुण आता।",
    "सब सम्भव हो जाता, मन नहिं घबराता॥",
    "तुम बिन यज्ञ न होते, वस्त्र न हो पाता।",
    "खान-पान का वैभव, सब तुमसे आता॥",
    "शुभ-गुण-मन्दिर सुन्दर, क्षीरोदधि-जाता।",
    "रत्न चतुर्दश तुम बिन, कोई नहिं पाता॥",
    "महालक्ष्मी जी की आरती, जो कोई नर गाता।",
    "उर आनन्द समाता, पाप उतर जाता॥",
]

LAKSHMI_AARTI_SOURCES = [
    "https://archive.org/ (Gita Press Shri Aarti Sangrah, code 0153, scanned edition)",
    "https://dailybhakti.app/aarti/om-jai-lakshmi-mata/",
    "https://jyotishjagat.com/library/om-jai-lakshmi-mata",
]


def create_daily_mission(root: Path, *, day: date, deity: str = "Lakshmi") -> dict:
    """Create today's review package without provider or publishing side effects."""
    root = Path(root).resolve()
    if (root / "mission.json").exists():
        return {"status": "existing", "root": str(root), "mission": str(root / "mission.json")}
    if deity.casefold() != "lakshmi":
        raise ValueError("This reviewed daily template currently supports Lakshmi only")

    title = "माँ लक्ष्मी आओ, दीप जलाओ | Lakshmi Bhajan | Shloka By Shloka"
    hook = FRIDAY_LAKSHMI_LYRICS[:4]
    verse1 = FRIDAY_LAKSHMI_LYRICS[4:8]
    verse2 = FRIDAY_LAKSHMI_LYRICS[8:12]
    verse3 = FRIDAY_LAKSHMI_LYRICS[12:16]
    verse4 = FRIDAY_LAKSHMI_LYRICS[16:20]
    bridge = FRIDAY_LAKSHMI_LYRICS[20:24]
    section_rows = [
        ("Immediate sung hook", hook, "Lead vocal begins in the first second; tanpura and soft harmonium"),
        ("Verse 1 honest prosperity", verse1, "Warm female solo; clear syllables, light tabla after line one"),
        ("Refrain intimate", hook, "Soft response chorus; no instrumental phrase over sung words"),
        ("Verse 2 service", verse2, "Veena answers only after complete lines; restrained manjira"),
        ("Verse 3 inner light", verse3, "Harmonium and tanpura, gently rising melodic contour"),
        ("Refrain lifted", hook, "Fuller chorus while the lead remains forward and intelligible"),
        ("Verse 4 gratitude", verse4, "Warm strings and bansuri between phrases, steady Keharwa"),
        ("Bridge humility", bridge, "Strip back to voice and tanpura, then tabla returns"),
        ("Final chorus", hook + verse1, "Strongest ensemble; exact lyrics, no improvised words"),
        ("Closing prayer", verse4 + hook, "Complete final word before reverb tail; no instrumental-only ending"),
    ]
    sections = [
        {"name": name, "duration": 48, "lines": lines * 2,
         "styles": [style, "76 BPM Keharwa 8-beat rhythm", "precise Hindi diction"]}
        for name, lines, style in section_rows
    ]
    bible = (
        "Original cinematic devotional artwork, respectful Hindu iconography, consistent canonical Lakshmi identity. "
        "Warm compassionate face, gold crown, red-gold sari, lotus motifs, two anatomically correct arms unless the "
        "scene explicitly needs a traditional four-arm depiction; never mix arm counts within a shot. Lakshmi never "
        "worships herself and never performs her own puja. No other deity impersonation. No text, logo, watermark, "
        "collage, malformed hands, extra fingers or cropped sacred objects. 16:9 landscape with safe central framing "
        "for a 9:16 crop; high-detail sapphire, crimson and antique-gold cinematic lighting. "
    )
    scenes = [
        {"id": f"lakshmi-{i:02d}", "image": f"images-quality-v2/quality-{i:02d}.png",
         "duration": 20, "reference_mode": "none" if i == 1 else "canonical",
         "prompt": bible + detail}
        for i, detail in enumerate(LAKSHMI_SCENES, 1)
    ]
    mission_id = root.name
    mission = {
        "schema": "one.divya-mission/v2", "brand": BRAND, "agent_id": "naad",
        "head_agent": "helios", "floor_id": "12", "mission_id": mission_id,
        "production_date": day.isoformat(), "deity": "Lakshmi", "preset": "LAKSHMI_GOLDEN",
        "vocal_style": "female_devotional", "composition_type": "original_bhajan",
        "music_model": "music_v2_5", "title": title, "display_title": "माँ लक्ष्मी आओ",
        "lyrics": FRIDAY_LAKSHMI_LYRICS,
        "text_origin": "Original Hindi devotional lyrics; not a scripture quotation",
        "scripture_sources": [], "text_review": "PENDING", "pronunciation_review": "PENDING",
        "requested_duration_seconds": 480, "sections": sections, "scenes": scenes,
        "music_direction": {
            "bpm": 76, "rhythm": "Keharwa, steady 8-beat cycle",
            "melodic_language": "Yaman-inspired devotional contour; accessible, not presented as a strict classical rendition",
            "vocal_delivery": "Warm female devotional lead, immediate vocal hook, minimal melisma, exact Hindi words",
            "instruments": ["tanpura", "harmonium", "tabla", "veena", "sparse bansuri", "soft manjira", "restrained temple bells"],
            "phrasing": "Four-line phrases, syllabic delivery and complete words before any instrumental answer",
            "sync": "Four-line phrases resolve on the sam; instrumental answers only between completed lyric lines",
            "avoid": "No long intro, no missing words, no ad-libs, no English lyrics, no cinematic trailer drums",
        },
        "shorts_policy": "vocals_first_v1", "shorts": [], "channel_id": CHANNEL,
        "public_publish_authorized": False, "upload_authorized": False, "schedule_enabled": False,
    }
    config = {
        "lao_folder_id": "446427d7-5722-4d59-a487-8de321325cbc",
        "artifact_roots": ["E:/ONE-Suite/lao-robot/worker"],
        "edit_tools": "C:/Users/pc/Documents/LAO/yatra-edit",
        "uploader_script": "C:/Users/pc/Documents/LAO/yatra-upload/youtube_api_upload.py",
        "voice_overrides": {}, "credential_asset": None, "channel_id": CHANNEL,
        "daily_schedule": {"enabled": False},
    }
    request = music_payload(mission)
    write(root / "mission.json", mission)
    write(root / "config.json", config)
    write(root / "channel-binding.json", {"brand": BRAND, "channel_id": CHANNEL, "mission_id": mission_id})
    write(root / "review-package/music-request.json", request)
    write(root / "review-package/metadata-brief.json", {
        "keyword": "Lakshmi Bhajan", "description": "Original Hindi Lakshmi Bhajan for Friday prayer, gratitude and inner prosperity.",
        "tags": ["lakshmi bhajan", "माँ लक्ष्मी भजन", "friday bhajan", "lakshmi mata song", "hindi devotional song"],
    })
    write(root / "review-package/commission.json", {
        "duration_seconds": 480, "variants": 1, "paid_attempts_authorized": 0,
        "credit_quote": None, "automatic_paid_retry": False,
        "lyrics_review": "PENDING", "pronunciation_review": "PENDING", "publish": False,
    })
    write(root / "review-package/review-templates.json", {
        purpose: {"approved": False, "reviewer": None, "authorization_reference": None,
                  "binding_sha256": fingerprint(binding)}
        for purpose, binding in (("lyrics", lyrics_binding(mission)), ("music-spend-and-rights", request))
    })
    journal = Journal(root)
    journal.stage("TOPIC_SELECTION", {"mission_id": mission_id},
                  lambda: {"files": [str(root / "mission.json")], "deity": "Lakshmi", "cost_usd": 0})
    for name in STAGES[1:]:
        journal.data["stages"].setdefault(name, {"status": "PENDING", "attempts": 0, "cost_usd": 0})
    journal.save()
    return {"status": "REVIEW_READY", "root": str(root), "mission": str(root / "mission.json"),
            "duration_seconds": 480, "paid_attempts_authorized": 0}


def switch_to_lakshmi_aarti(root: Path) -> dict:
    """Preserve the original draft and commission a verified traditional Aarti."""
    root = Path(root).resolve()
    mission = read(root / "mission.json")
    if mission.get("deity") != "Lakshmi":
        raise ValueError("Lakshmi mission required")
    if mission.get("composition_type") == "traditional_aarti":
        return {"status": "existing", "root": str(root)}

    write(root / "review-package/original-bhajan-reserve.json", {
        "title": mission["title"], "lyrics": mission["lyrics"],
        "music_direction": mission.get("music_direction"),
        "status": "PRESERVED_FOR_FUTURE_RELEASE",
    })
    refrain = LAKSHMI_AARTI[:2]
    verses = [LAKSHMI_AARTI[index:index + 2] for index in range(2, len(LAKSHMI_AARTI), 2)]
    rows = [("Opening Aarti refrain", refrain,
             "Lead begins within the first second; congregation answers the complete refrain")]
    rows.extend((f"Aarti verse {index}", verse + refrain,
                 "Warm female lead with a restrained response chorus; every printed word remains audible")
                for index, verse in enumerate(verses, 1))
    rows.extend([
        ("Devotional lift", verses[3] + refrain,
         "Full ensemble lift without tempo change or improvised lyric syllables"),
        ("Closing Aarti refrain", refrain * 2,
         "Complete final refrain before bells and reverb; no instrumental-only ending"),
    ])
    mission.update(
        title="ॐ जय लक्ष्मी माता | संपूर्ण लक्ष्मी आरती | Shloka By Shloka",
        display_title="ॐ जय लक्ष्मी माता", composition_type="traditional_aarti",
        lyrics=LAKSHMI_AARTI,
        text_origin=("Traditional Lakshmi Aarti; author unknown. Common Gita Press-aligned reading, "
                     "independently recorded with a fresh arrangement; no third-party recording copied."),
        scripture_sources=LAKSHMI_AARTI_SOURCES,
        text_review="PENDING", pronunciation_review="PENDING",
        sections=[{"name": name, "duration": 48, "lines": lines,
                   "styles": [style, "76 BPM Keharwa 8-beat Aarti rhythm", "precise Hindi diction"]}
                  for name, lines, style in rows],
        music_direction={
            "bpm": 76, "rhythm": "steady Keharwa 8-beat Aarti cycle",
            "melodic_language": "Traditional congregational Aarti contour in a fresh independent performance",
            "vocal_delivery": "Warm female lead, clear response chorus, minimal melisma and exact verified words",
            "instruments": ["tanpura", "harmonium", "tabla", "veena", "soft manjira", "restrained temple bells"],
            "phrasing": "Each two-line verse resolves before the full refrain; preserve every compound word",
            "sync": "Verse cadence and refrain resolve on sam; instrumental answers only between complete lines",
            "avoid": "No copied commercial recording, long intro, missing words, ad-libs or English lyrics",
        },
        pronunciation_notes={
            "निसिदिन": "ni-si-din", "हर-विष्णु-धाता": "har-vish-nu-dhaa-taa",
            "निरंजनि": "ni-ran-ja-ni", "भवनिधि": "bha-va-ni-dhi",
            "क्षीरोदधि-जाता": "kshee-ro-da-dhi jaa-taa", "उर": "ur",
        },
    )
    request = music_payload(mission)
    write(root / "mission.json", mission)
    write(root / "review-package/music-request.json", request)
    write(root / "review-package/metadata-brief.json", {
        "keyword": "Lakshmi Aarti",
        "description": "Om Jai Lakshmi Mata full Hindi Aarti with lyrics, fresh vocals and an original devotional arrangement.",
        "tags": ["om jai lakshmi mata", "lakshmi aarti", "लक्ष्मी माता की आरती", "friday aarti",
                 "mahalakshmi aarti", "hindi aarti", "laxmi ji ki aarti"],
    })
    write(root / "review-package/commission.json", {
        "duration_seconds": 480, "variants": 1, "paid_attempts_authorized": 0,
        "credit_quote": None, "automatic_paid_retry": False,
        "lyrics_review": "PENDING", "pronunciation_review": "PENDING", "publish": False,
        "rights_basis": "Traditional text; fresh recording and arrangement; source edition review required",
    })
    write(root / "review-package/review-templates.json", {
        purpose: {"approved": False, "reviewer": None, "authorization_reference": None,
                  "binding_sha256": fingerprint(binding)}
        for purpose, binding in (("lyrics", lyrics_binding(mission)), ("music-spend-and-rights", request))
    })
    return {"status": "REVIEW_READY", "root": str(root), "composition_type": "traditional_aarti",
            "verses": len(verses), "duration_seconds": 480, "paid_attempts_authorized": 0}
