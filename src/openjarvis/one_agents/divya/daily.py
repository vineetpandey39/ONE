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


TULSI_VIVAH_LYRICS = [
    "तुलसी मैया का आँगन आज, मंगल दीप सजाए।",
    "शालिग्राम संग शुभ मिलन पर, हरि का नाम सुनाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "भक्ति की सुगंध बहे घर-घर, प्रेम की ज्योति जगाए।",
    "वृंदावन की पावन बेला, बंसी मधुर बजाए।",
    "फूलों का मंडप मुस्काए, मन भी फूल चढ़ाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "सच्चे भाव की एक अंजलि, जीवन सफल बनाए।",
    "अहंकार का तम मिट जाए, सेवा राह दिखाए।",
    "दया, क्षमा और सत्य का दीपक, अंतर में जल जाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "हर दुख में विश्वास रहे, हर सुख विनय सिखाए।",
    "माता तुलसी की छाया में, मन को शांति मिले।",
    "श्रीहरि की करुणा बरसे तो, सूने सपने खिलें।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "नाम तुम्हारा लेते-लेते, मन के बंधन खुलें।",
    "मंगल ध्वनि से गूँजे द्वारे, शंख और शहनाई।",
    "भक्ति बनी है आज दुल्हनिया, प्रेम बना वरदाई।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "सबके जीवन में शुभता हो, यही प्रार्थना गाई।",
    "आँगन-आँगन मंगल गूँजे, मन का मैल मिटाए।",
    "कंठ-कंठ से नाम हरि का, मीठी तान सुनाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "कर्म बने जब सच्ची पूजा, हर दिन पर्व बन जाए।",
    "धरती, जल और जीव सभी में, हरि का रूप निहारे।",
    "तुलसी दल की कोमल छाया, थके हृदय को सँवारे।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "संतोषी मन की समृद्धि, जग का मोह उतारे।",
    "विपदा में भी धीरज रखना, श्रद्धा हमें सिखाए।",
    "भटके पथ पर हरि का सुमिरन, सच्ची राह दिखाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "टूटी आशा फिर से जागे, प्रेम गले लग जाए।",
    "एक सुर में जब भजन उठे तो, दूरी सभी मिटाए।",
    "छोटा-बड़ा न कोई रहे, हर जन शीश झुकाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "तुलसी-हरि के मंगल मिलन से, जग परिवार बन जाए।",
    "मंगल मिलन की यह पावन धुन, हर हृदय में समाए।",
    "तुलसी-शालिग्राम की महिमा, हरि से प्रीत बढ़ाए।",
    "हरी-हरी तुलसी, जय श्रीहरि।",
    "प्रेम और विश्वास की ज्योति, युग-युग तक जगमगाए।",
]


TULSI_VIVAH_SCENES = [
    "Sacred Tulsi plant in an ornate Vrindavan courtyard at dawn, marigold mandap and rows of warm diyas.",
    "Close devotional view of fresh Tulsi leaves with dew, gold temple bokeh and soft morning rays.",
    "Respectful Shaligram shrine beside a decorated Tulsi planter, flowers and lamps, no human hands visible.",
    "Wide festive temple courtyard prepared for Tulsi Vivah, floral canopy, rangoli and luminous lamps.",
    "Serene Krishna portrait with flute in Vrindavan, compassionate expression, peacock feather and blue-gold light.",
    "Tulsi mandap beneath flowering vines, shehnai players suggested as distant silhouettes, devotional not theatrical.",
    "Close brass diya and marigold garland beside the Tulsi altar, shallow depth of field.",
    "Moonlit Vrindavan garden with Tulsi centered and Krishna temple glowing in the distance.",
    "Temple women carrying flower baskets toward the mandap, modest festive attire, faces natural and respectful.",
    "Conch, manjira and flower petals arranged near a clean sacred altar, cinematic gold and emerald palette.",
    "Wide river ghat at sunrise with Tulsi planter and lamps, soft mist and distant temple bells.",
    "Canonical Vishnu presence in a luminous temple arch, calm blessing gesture, anatomically correct iconography.",
    "Tulsi leaves moving gently in a warm breeze, floating petals and subtle god rays.",
    "Festive courtyard filled with lamps and flower strings, central aisle leading to the Tulsi mandap.",
    "Close Krishna flute and peacock feather beside Tulsi leaves, rich sapphire and emerald lighting.",
    "Devotees singing kirtan around the decorated courtyard, joyful but reverent, natural hand anatomy.",
    "Sacred Shaligram and Tulsi composition under a floral canopy, symmetrical lamps and no deity performing puja.",
    "Vrindavan temple exterior at blue hour, warm windows, drifting petals and subtle festival lights.",
    "Close devotional Tulsi portrait with a small red bridal cloth and restrained traditional ornaments.",
    "Grand overhead view of floral rangoli surrounding the Tulsi mandap, clean geometry and glowing diyas.",
    "Serene Krishna and Radha seen respectfully in the distant temple garden, Tulsi prominent in foreground.",
    "Golden dawn breaking behind the Tulsi altar, petals lifting in the light and soft volumetric rays.",
    "Final celebratory courtyard tableau, Tulsi and Shaligram shrine centered, lamps, flowers and joyful kirtan atmosphere.",
    "Closing prayer image of one steady diya beside green Tulsi leaves against a calm midnight-blue background.",
]


RAVI_PRADOSH_SHIVA_LYRICS = [
    "प्रदोष की बेला में, शिव-नाम सुना दो।",
    "मन के अँधेरों में, विश्वास जगा दो।",
    "काशी के विश्वेश्वर, करुणा बरसाओ।",
    "भटके हुए मन को, सच्ची राह दिखाओ।",
    "गंगा की लहरों में, पावन स्वर बहता।",
    "हर-हर महादेव कहे, काशी का कण-कण।",
    "डमरू की धुन सुनकर, संशय सब खोए।",
    "भोले की नगरी में, सोया मन जागे।",
    "नीलकंठ महादेव, धीरज हमें देना।",
    "विष पीकर भी जग को, अमृत-सा सुख देना।",
    "क्रोध की अग्नि बुझाकर, करुणा सिखा दो।",
    "मन के हर विकार को, चरणों में मिटा दो।",
    "त्रिनेत्र की ज्योति से, सत्य हमें दिखता।",
    "चन्द्रमा-सा शीतल हो, हर बोल हमारा।",
    "नंदी की निष्ठा-सा, विश्वास अटल हो।",
    "सेवा से जीवन का, हर मार्ग सरल हो।",
    "कैलाश की चोटी-सा, संकल्प दृढ़ कर दो।",
    "मौन की गहराई में, अपना स्वर भर दो।",
    "गौरी-शंकर जैसा, सम्मान सिखाओ।",
    "घर-घर में प्रेम और, सद्भाव बढ़ाओ।",
    "बेलपत्र की खुशबू, आँगन में छाए।",
    "दीपों की पंक्ति से, आशा जगमगाए।",
    "जल की हर बूँद हमें, संयम सिखलाए।",
    "सच्ची श्रद्धा मन को, निर्मल कर जाए।",
    "दुख की घड़ी आए तो, साहस न खोएँ।",
    "सुख के उजाले में भी, विनम्र हम रहें।",
    "शिव का स्मरण हर पल, विवेक जगाए।",
    "कर्मों की राहों में, ईमान बढ़ाए।",
    "समय के महाकाल, भय दूर भगाओ।",
    "टूटी हुई आशा को, फिर से सजाओ।",
    "दीनों के सहचर हो, असहाय के स्वामी।",
    "सबके ही अंतर में, बसते हो अन्तर्यामी।",
    "भस्म की रेखा कहे, अभिमान मिटाना।",
    "रुद्राक्ष की माला कहे, मन को सँभालना।",
    "हर श्वास में नाम रहे, हर कर्म में पूजा।",
    "सत्य और दया से हो, जीवन की आराधना।",
    "प्रदोष की बेला में, शिव-नाम सुना दो।",
    "मन के अँधेरों में, विश्वास जगा दो।",
    "काशी के विश्वेश्वर, करुणा बरसाओ।",
    "हर-हर महादेव कहे, यह जीवन सारा।",
]


RAVI_PRADOSH_SHIVA_SCENES = [
    "Medium waist-up portrait of canonical Lord Shiva in serene meditation above the Ganga at Kashi during luminous blue hour; frame ends above the hips so no knees, legs, feet or toes are visible; Vishwanath temple silhouettes and antique-gold lamps.",
    "Close devotional portrait of clean-shaven Shiva, compassionate eyes, smooth face with no beard or moustache, crescent moon, flowing matted hair and subtle blue-gold rim light.",
    "Wide aerial view of Kashi ghats at dawn, hundreds of diyas, soft mist and the sacred river reflecting indigo and gold.",
    "Shiva standing calmly beside the Ganga, trident planted nearby, temple spires rising through morning fog.",
    "Ancient Vishwanath-inspired temple corridor with brass lamps, marigolds and a distant respectful Shiva presence.",
    "Close view of Shiva's damaru and trident against a storm-cleared sapphire sky, sacred objects intact and sharply detailed.",
    "Moonlit Kailash landscape with Shiva seated in meditation, silver snow and restrained golden god rays.",
    "Devotees offering water to a Shiva lingam at a Kashi temple, Shiva represented only as distant iconography and never worshipping himself.",
    "Serene Ganga aarti viewed from the river, priests and lamps in the distance, cinematic blue-gold reflections.",
    "Shiva as Neelkanth in a dignified close portrait, gentle blue throat glow and calm compassionate expression.",
    "Nandi seated faithfully before a luminous Shiva temple doorway, symmetrical lamps and drifting incense fog.",
    "Wide Kashi alley at early morning with flower stalls, bells and a glowing temple entrance, no modern signage.",
    "Shiva and Parvati seated together respectfully on Kailash, balanced composition and warm family devotion.",
    "Close devotional portrait of clean-shaven Shiva with soft ash markings, rudraksha beads, smooth jaw and natural detailed skin texture, no beard or moustache.",
    "Bel leaves and a copper water vessel arranged before a Shiva lingam, hands of devotees natural and anatomically correct.",
    "Cosmic Shiva silhouette beneath a star-filled indigo sky, subtle nebula and a radiant crescent moon.",
    "Temple bells in foreground with Shiva visible through a carved stone arch, volumetric morning rays and floating dust.",
    "Riverside meditation scene at sunset, Shiva in profile, orange lamps and blue water creating strong color contrast.",
    "Dramatic monsoon clouds opening above Kashi, golden sunlight illuminating the Vishwanath temple spires.",
    "Shiva blessing a diverse group of devotees from a respectful distance, natural faces and hands, no self-worship.",
    "Close image of flowing Ganga emerging from Shiva's matted hair, symbolic, elegant and anatomically coherent.",
    "A quiet cremation-ghat horizon interpreted respectfully as impermanence, distant lamps and peaceful moonlight, no graphic imagery.",
    "Grand final Kashi tableau with Shiva, the Ganga, temple spires, trident and thousands of lamps in cinematic sapphire and gold.",
    "Closing prayer image with Shiva's calm face beside one steady diya and clean dark-blue negative space.",
]


def create_tulsi_vivah_mission(root: Path, *, day: date) -> dict:
    """Prepare an original, no-spend Tulsi Vivah production commission."""
    title = "तुलसी मैया संग शालिग्राम | Tulsi Vivah Bhajan 2026 | Shloka By Shloka"
    verses = [TULSI_VIVAH_LYRICS[index:index + 4] for index in range(0, 40, 4)]
    section_names = [
        "Immediate festive hook", "Vrindavan verse", "Inner devotion verse", "Grace verse",
        "Wedding celebration verse", "Community verse", "Sacred nature verse", "Faith verse",
        "Unity verse", "Closing blessing",
    ]
    section_styles = [
        "Female lead begins on beat one; soft shehnai answers only after the full line",
        "Bright female solo with bansuri and restrained dholak",
        "Lead remains forward; manjira marks the Keharwa pulse",
        "Gentle melodic lift with harmonium and flute between lines",
        "Dholak, manjira and restrained temple bells build festive energy",
        "Warm response chorus only on the explicitly written refrain",
        "Acoustic texture softens while the steady beat and vocal clarity remain",
        "Confident melodic rise without extra words or alaap",
        "Joyful ensemble supports the lead without covering consonants",
        "Complete the final written line, then use only a short instrumental resolution",
    ]
    section_rows = list(zip(section_names, verses, section_styles))
    sections = [
        {"name": name, "duration": 48, "lines": lines,
         "styles": [style, "92 BPM Keharwa 8-beat festive bhajan", "precise Hindi diction"]}
        for name, lines, style in section_rows
    ]
    bible = (
        "Original premium cinematic Tulsi Vivah devotional artwork, consistent Vrindavan temple world and respectful "
        "Hindu iconography. Emerald green, sapphire blue and antique gold palette, warm marigold accents, natural faces "
        "and anatomically correct hands. Tulsi remains a sacred plant or traditionally decorated altar; Krishna, Vishnu "
        "or Shaligram never worship themselves and no deity performs their own puja. No text, logo, watermark, collage, "
        "malformed fingers, duplicate people or cropped sacred objects. 16:9 landscape composed for safe 9:16 crops, "
        "cinematic depth, varied camera distance and distinct locations. "
    )
    scenes = [
        {"id": f"tulsi-{i:02d}", "image": f"images-quality-v2/quality-{i:02d}.png",
         "duration": 20, "reference_mode": "none" if i == 1 else "canonical",
         "prompt": bible + detail}
        for i, detail in enumerate(TULSI_VIVAH_SCENES, 1)
    ]
    mission_id = root.name
    mission = {
        "schema": "one.divya-mission/v2", "brand": BRAND, "agent_id": "naad",
        "head_agent": "helios", "floor_id": "12", "mission_id": mission_id,
        "production_date": day.isoformat(), "deity": "Tulsi-Vishnu", "preset": "KRISHNA_VRINDAVAN",
        "vocal_style": "female_devotional", "composition_type": "original_bhajan",
        "music_model": "music_v2_5", "title": title, "display_title": "तुलसी विवाह",
        "estimated_music_credits": 7198,
        "lyrics": TULSI_VIVAH_LYRICS,
        "strict_lyric_plan": True,
        "allowed_repeat_lines": ["हरी-हरी तुलसी, जय श्रीहरि।"],
        "text_origin": "Original Hindi devotional lyrics inspired by the Tulsi Vivah observance; not a scripture quotation",
        "scripture_sources": [], "text_review": "PENDING", "pronunciation_review": "PENDING",
        "requested_duration_seconds": 480, "sections": sections, "scenes": scenes,
        "music_direction": {
            "bpm": 92, "rhythm": "Keharwa, steady 8-beat festive wedding-bhajan groove",
            "melodic_language": "Bright Vrindavan folk-devotional contour with an immediately singable refrain",
            "vocal_delivery": "Clear female devotional lead from beat one, warm response chorus, exact Hindi words",
            "instruments": ["dholak", "manjira", "harmonium", "bansuri", "shehnai", "tanpura", "restrained temple bells"],
            "phrasing": "Complete one lyric line before instrumental answers; refrain may recur only at marked sections",
            "sync": "Resolve lyrical phrases on sam; Shorts begin with a complete vocal hook, never mid-instrumental",
            "avoid": "No long intro, no missing words, no endless refrain loop, no ad-libs, no EDM drop, no trailer drums",
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
        "autonomy_policy_path": "E:/ONE-Suite/one-company/floors/floor_12_youtube_studio/shloka_autonomy.json",
        "daily_schedule": {"enabled": False},
    }
    request = music_payload(mission)
    write(root / "mission.json", mission)
    write(root / "config.json", config)
    write(root / "channel-binding.json", {"brand": BRAND, "channel_id": CHANNEL, "mission_id": mission_id})
    write(root / "review-package/music-request.json", request)
    write(root / "review-package/metadata-brief.json", {
        "keyword": "Tulsi Vivah Bhajan 2026",
        "description": "Original Hindi Tulsi Vivah bhajan for Tulsi Mata and Shaligram's sacred festival.",
        "tags": ["tulsi vivah bhajan 2026", "तुलसी विवाह भजन", "tulsi mata bhajan", "shaligram bhajan", "dev uthani ekadashi 2026", "krishna bhajan"],
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
                  lambda: {"files": [str(root / "mission.json")], "deity": "Tulsi-Vishnu", "cost_usd": 0})
    for name in STAGES[1:]:
        journal.data["stages"].setdefault(name, {"status": "PENDING", "attempts": 0, "cost_usd": 0})
    journal.save()
    return {"status": "REVIEW_READY", "root": str(root), "mission": str(root / "mission.json"),
            "duration_seconds": 480, "paid_attempts_authorized": 0}


def create_ravi_pradosh_shiva_mission(root: Path, *, day: date) -> dict:
    """Prepare today's original Kashi Vishwanath / Ravi Pradosh Shiva package."""
    root = Path(root).resolve()
    if (root / "mission.json").exists():
        return {"status": "existing", "root": str(root), "mission": str(root / "mission.json")}
    section_names = [
        "Immediate Pradosh hook", "Kashi awakening", "Neelkanth courage", "Sacred virtues",
        "Kailash resolve", "Lamp and offering", "Courage and humility", "Mahakal hope",
        "Inner worship", "Final Vishweshwara blessing",
    ]
    section_styles = [
        "Powerful male lead starts on beat one; complete the first couplet before any flute answer",
        "Warm harmonium and bansuri support a clear vocal-forward Kashi atmosphere",
        "Low male register with restrained chorus only after complete written lines",
        "Steady dholak and manjira; every consonant remains clear and uncovered",
        "Open melodic lift with tanpura and strings, no invented alaap syllables",
        "Temple bells appear only between completed lyric lines",
        "Intimate lead vocal over harmonium before the full Keharwa groove returns",
        "Confident melodic rise without speeding up or repeating unwritten words",
        "Deeply devotional ensemble, exact written order and no refrain loop",
        "Complete every final word, then a short damaru-and-bell resolution only",
    ]
    sections = []
    for index, (name, style) in enumerate(zip(section_names, section_styles)):
        lines = RAVI_PRADOSH_SHIVA_LYRICS[index * 4:(index + 1) * 4]
        sections.append({
            "name": name, "duration": 48, "lines": lines,
            "styles": [style, "82 BPM Keharwa 8-beat Shiva bhajan", "precise Hindi diction"],
        })
    bible = (
        "Premium cinematic Kashi Vishwanath Shiva devotional artwork with one consistent canonical Shiva identity. "
        "Compassionate youthful-serene clean-shaven face with absolutely no beard, moustache, stubble or facial hair; "
        "crescent moon, flowing matted hair, rudraksha, subtle blue throat, trident and "
        "damaru only where compositionally appropriate. Sapphire blue, antique gold and warm diya palette, natural "
        "faces and anatomically correct hands. Exactly two arms and two legs; no duplicated limbs, feet or toes, no "
        "foot above a calf, and every visible lower limb must connect naturally from hip to knee to ankle to one foot. "
        "Lord Shiva never worships himself or performs his own puja. No text, "
        "logo, watermark, collage, duplicate deity, malformed fingers, cropped sacred objects or modern brand signs. "
        "Each shot must be a genuinely distinct location, camera distance, pose and lighting setup. 16:9 landscape "
        "with safe 9:16 crop, cinematic depth, photoreal devotional illustration and controlled volumetric light. "
    )
    scenes = [
        {"id": f"shiva-{i:02d}", "image": f"images-quality-v2/quality-{i:02d}.png",
         "duration": 20, "reference_mode": "none" if i == 1 else "canonical",
         "prompt": bible + detail}
        for i, detail in enumerate(RAVI_PRADOSH_SHIVA_SCENES, 1)
    ]
    mission_id = root.name
    title = "प्रदोष की बेला में शिव | काशी विश्वनाथ भजन 2026 | Shloka By Shloka"
    mission = {
        "schema": "one.divya-mission/v2", "brand": BRAND, "agent_id": "naad",
        "head_agent": "helios", "floor_id": "12", "mission_id": mission_id,
        "production_date": day.isoformat(), "deity": "Shiva", "preset": "SHIVA_COSMIC",
        "vocal_style": "powerful_male", "composition_type": "original_bhajan",
        "music_model": "music_v2_5", "title": title, "display_title": "प्रदोष की बेला में शिव",
        "estimated_music_credits": 7200, "lyrics": RAVI_PRADOSH_SHIVA_LYRICS,
        "strict_lyric_plan": True,
        "allowed_repeat_lines": [
            "प्रदोष की बेला में, शिव-नाम सुना दो।",
            "मन के अँधेरों में, विश्वास जगा दो।",
            "काशी के विश्वेश्वर, करुणा बरसाओ।",
        ],
        "text_origin": "Original Hindi devotional lyrics for Ravi Pradosh and Kashi Vishwanath; not a scripture quotation",
        "scripture_sources": [], "text_review": "PENDING", "pronunciation_review": "PENDING",
        "requested_duration_seconds": 480, "sections": sections, "scenes": scenes,
        "music_direction": {
            "bpm": 82, "rhythm": "Keharwa, steady 8-beat devotional groove",
            "melodic_language": "Accessible Shiva-bhajan contour with a memorable immediate hook and Kashi temple atmosphere",
            "vocal_delivery": "Powerful warm Indian male devotional lead from beat one, clear Hindi diction, restrained response chorus",
            "instruments": ["tanpura", "harmonium", "dholak", "tabla", "manjira", "bansuri", "damaru", "restrained temple bells"],
            "phrasing": "Sing each four-line block exactly once; complete every word before instrumental answers",
            "sync": "Resolve each couplet on sam; Shorts start on complete vocal hooks and end on complete phrases",
            "avoid": "No long intro, missing or substituted words, invented lyrics, endless hook loop, spoken narration, EDM or excessive alaap",
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
        "autonomy_policy_path": "E:/ONE-Suite/one-company/floors/floor_12_youtube_studio/shloka_autonomy.json",
        "daily_schedule": {"enabled": False},
    }
    request = music_payload(mission)
    write(root / "mission.json", mission)
    write(root / "config.json", config)
    write(root / "channel-binding.json", {"brand": BRAND, "channel_id": CHANNEL, "mission_id": mission_id})
    write(root / "review-package/music-request.json", request)
    write(root / "review-package/metadata-brief.json", {
        "keyword": "Pradosh Shiv Bhajan",
        "primary_keyword": "Pradosh Shiv Bhajan",
        "secondary_keywords": ["Kashi Vishwanath Bhajan", "Shiv Bhajan 2026", "Ravi Pradosh Vrat"],
        "description": "Original Hindi Shiva bhajan for Ravi Pradosh, Kashi Vishwanath devotion, prayer and meditation.",
        "tags": ["pradosh shiv bhajan", "प्रदोष शिव भजन", "kashi vishwanath bhajan", "shiv bhajan 2026", "ravi pradosh vrat", "mahadev bhajan", "har har mahadev"],
    })
    write(root / "review-package/thumbnail-brief.json", {
        "art": "images-quality-v2/quality-18.png",
        "title_lines": ["प्रदोष में", "शिव"],
        "subtitle": "8 मिनट का काशी विश्वनाथ भजन",
        "hooks": ["शिव-नाम सुना दो", "विश्वास जगा दो"],
        "style": "SHLOKA_GOLDEN_BLUE_V1",
        "composition": "Shiva on the left; clean sapphire-and-gold Kashi text-safe area on the right",
        "ctr_rules": [
            "large correct Hindi title", "no text over deity face or body",
            "no line or banner behind text", "mobile readability at 320x180",
            "single dominant subject", "no fake views or claims",
        ],
    })
    write(root / "review-package/commission.json", {
        "duration_seconds": 480, "variants": 1, "paid_attempts_authorized": 0,
        "credit_quote": 7200, "automatic_paid_retry": False,
        "lyrics_review": "PENDING", "pronunciation_review": "PENDING", "publish": False,
    })
    write(root / "review-package/review-templates.json", {
        purpose: {"approved": False, "reviewer": None, "authorization_reference": None,
                  "binding_sha256": fingerprint(binding)}
        for purpose, binding in (("lyrics", lyrics_binding(mission)), ("music-spend-and-rights", request))
    })
    journal = Journal(root)
    journal.stage("TOPIC_SELECTION", {"mission_id": mission_id},
                  lambda: {"files": [str(root / "mission.json")], "deity": "Shiva", "cost_usd": 0})
    for name in STAGES[1:]:
        journal.data["stages"].setdefault(name, {"status": "PENDING", "attempts": 0, "cost_usd": 0})
    journal.save()
    return {"status": "REVIEW_READY", "root": str(root), "mission": str(root / "mission.json"),
            "duration_seconds": 480, "estimated_music_credits": 7200, "paid_attempts_authorized": 0}


def create_daily_mission(root: Path, *, day: date, deity: str = "Lakshmi") -> dict:
    """Create today's review package without provider or publishing side effects."""
    root = Path(root).resolve()
    if (root / "mission.json").exists():
        return {"status": "existing", "root": str(root), "mission": str(root / "mission.json")}
    if deity.casefold() in {"tulsi", "tulsi-vishnu", "tulsi_vivah", "tulsi vivah"}:
        return create_tulsi_vivah_mission(root, day=day)
    if deity.casefold() in {"shiva", "ravi pradosh", "pradosh", "kashi vishwanath"}:
        return create_ravi_pradosh_shiva_mission(root, day=day)
    if deity.casefold() != "lakshmi":
        raise ValueError("This reviewed daily template currently supports Lakshmi and Tulsi Vivah")

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
        "estimated_music_credits": 7198,
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
        "autonomy_policy_path": "E:/ONE-Suite/one-company/floors/floor_12_youtube_studio/shloka_autonomy.json",
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
