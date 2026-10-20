"""Narration-bound motion copy; no new science claims or voice regeneration."""
import json
import math
import re


def motion_prompt(science, voice):
    scenes = [{"id": str(i), "title": scene["title"], "narration": scene["narration"],
               "required_phrases": max(1, math.ceil(round(segment["seconds"] * 30) / 105))}
              for i, (scene, segment) in enumerate(zip(science["scenes"], voice["segments"], strict=True), 1)]
    return ("Act as The Planexium's kinetic typography director. Return ONLY valid JSON between "
            "BEGIN_PLANEXIUM_MOTION_JSON and END_PLANEXIUM_MOTION_JSON. Schema: {\"motion_copy\": "
            "{\"1\":[\"phrase\", ...],...}}. Include every scene ID. Each scene needs exactly its "
            "required_phrases count. Follow narration in order. Each phrase 1-8 words, at most 70 characters. "
            "Do not repeat a phrase within a scene. Extract concise factual beats already in narration; "
            "introduce no claims, numbers, quotations or promises. No Sonia, travel branding or portraits. "
            "Vary phrasing across beats; do not simply alternate scene title and subtitle. "
            "Preserve uncertainty and avoid implying illustrative graphics are actual observations. "
            "Keep the original narration unchanged.\n" + json.dumps(scenes, ensure_ascii=False))


_SMALL='zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
_TENS={20:'twenty',30:'thirty',40:'forty',50:'fifty',60:'sixty',70:'seventy',80:'eighty',90:'ninety'}
_ORDINAL={'one':'first','two':'second','three':'third','five':'fifth','eight':'eighth','nine':'ninth','twelve':'twelfth'}


def _words(number):
    if number<20:return _SMALL[number]
    if number<100:return _TENS[number//10*10]+(' '+_SMALL[number%10] if number%10 else '')
    for value,label in [(10**12,'trillion'),(10**9,'billion'),(10**6,'million'),(1000,'thousand'),(100,'hundred')]:
        if number>=value:return _words(number//value)+' '+label+(' '+_words(number%value) if number%value else '')
    raise ValueError('Unsupported number')


def number_is_spoken(number,narration,*,preceding=None):
    def normalize(text):return ' '.join(re.sub(r'[^a-z0-9]+',' ',text.casefold()).split()).replace(' and ',' ')
    text=' '+normalize(narration)+' '
    if preceding is None and re.search(r'(?<!\d)'+re.escape(number)+r'(?!\d)',narration):return True
    if len(number)>16:return False
    whole,_,fraction=number.partition('.')
    value=int(whole)
    if value>10**15:return False
    standard=_words(value)
    forms=[standard]
    if fraction:forms=[standard+' point '+' '.join(_SMALL[int(d)] for d in fraction)]
    else:
        last=standard.split()[-1]
        ordinal=_ORDINAL.get(last,last[:-1]+'ieth' if last.endswith('y') else last+'th')
        forms.append(' '.join(standard.split()[:-1]+[ordinal]))
        if 1100<=value<=2099 and value%100:forms.append(_words(value//100)+' '+_words(value%100))
        if 100<=value<10000:
            forms.append(_words(value//100)+' hundred'+(' '+_words(value%100) if value%100 else ''))
    return any(' '+normalize((preceding+' ' if preceding else '')+form)+' ' in text for form in ([number]+forms))


def validate_motion(result, science, voice):
    copy = result.get("motion_copy")
    expected = {str(i) for i in range(1, len(science["scenes"]) + 1)}
    if not isinstance(copy, dict) or set(copy) != expected:
        raise ValueError("Motion director must cover every narration scene")
    for i, segment in enumerate(voice["segments"], 1):
        phrases = copy[str(i)]
        count = max(1, math.ceil(round(segment["seconds"] * 30) / 105))
        if not isinstance(phrases, list) or len(phrases) != count:
            raise ValueError(f"Motion director needs exactly {count} phrases for scene {i}")
        if any(not isinstance(p, str) or not 1 <= len(p.split()) <= 8 or len(p) > 70 for p in phrases):
            raise ValueError("Motion phrases must be concise authored text")
        if len({p.casefold().strip() for p in phrases}) != count:
            raise ValueError("Repeated motion copy would create repetitive title cards")
        spoken = science["scenes"][i-1]["narration"]
        for phrase in phrases:
            for written in re.findall(r"\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:st|nd|rd|th)?\b", phrase):
                number = written.replace(',', '')
                if not number_is_spoken(number, spoken):
                    # A repeated named entity can span scene boundaries: Falcon
                    # Nine may be abbreviated as Falcon 9 later. Require the
                    # same preceding entity word; another value elsewhere in
                    # the episode cannot authorize a new speed/distance claim.
                    entity=re.search(r"([A-Za-z]+)\s+"+re.escape(number)+r"(?:st|nd|rd|th)?\b",phrase)
                    episode=" ".join(scene["narration"] for scene in science["scenes"])
                    if not entity or not number_is_spoken(number,episode,preceding=entity[1]):
                        raise ValueError(f"Motion copy introduced an unspoken numeric claim in scene {i}")
    return copy
