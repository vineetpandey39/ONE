"""Offline provenance checks for manifest-owned regular reel briefs."""
import hashlib
import json
import re


def bind_regular_brief(brief, evidence, predicted_location):
    """Bind exact model context; citations establish attribution, not truth.

    A named incident must agree with the predicted manifest place. Other
    places may appear as context when both editorial lines name that subject.
    This never chooses or overrides the production location.
    """
    items = evidence.get("eligible") or []
    by_id = {str(x.get("evidence_id")): x for x in items if x.get("evidence_id")}
    def marker(name):
        match = re.search(r"^" + name + r":[^\S\n]*(.*)$", brief, re.M)
        return match.group(1).strip() if match else ""
    def core(value):
        return re.split(r"[,\(]", value, maxsplit=1)[0].strip().casefold()
    errors = []
    citations = {}
    for field in ("PRIORITY", "ANGLE"):
        line = marker(field)
        refs = re.findall(r"\[([^\[\]]+)\]", line)
        citations[field] = refs
        if not line or not refs or any(ref not in by_id for ref in refs):
            errors.append(field + ": missing or unknown evidence citation")
    place = core(marker("PLACE"))
    predicted = core(str((predicted_location or {}).get("name") or ""))
    # PLACE is an optional fresh-incident field, not a switch for checking
    # the editorial claims. Extract explicit landmark names independently.
    # This is a bounded lexical check, not general named-entity recognition.
    landmark = re.compile(
        r"\b(?:[A-Z][\w'-]*\s+){1,5}"
        r"(?:Market|Bazaar|Temple|Fort|Palace|Lake|River|Ghat|Mahal|Mosque|"
        r"Church|Monastery|Bridge|Park|Beach|Station|Dam|Memorial)\b")
    def named_core(value):
        value = re.sub(r"^(?:(?:Compare|Contrast|Explore|Visit|Historic|The)\s+)+", "", value)
        return core(value)
    names = {named_core(m.group()) for field in citations
             for m in landmark.finditer(marker(field))}
    # Also recognize the prediction and evidence-named landmarks regardless
    # of capitalization in the generated prose.
    names.update(named_core(m.group()) for item in items
                 for m in landmark.finditer(str(item.get("title") or "")))
    names.update(x for x in (place, predicted) if x)
    for field, refs in citations.items():
        line = marker(field).casefold()
        mentioned = {name for name in names if re.search(
            r"(?<!\w)" + re.escape(name) + r"(?!\w)", line)}
        headlines = " ".join(str(by_id.get(ref, {}).get("title") or "")
                             for ref in refs).casefold()
        for name in sorted(mentioned):
            if not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", headlines):
                errors.append(field + ": cited headlines do not support " + name)
        if mentioned and (not predicted or predicted not in mentioned):
            errors.append(field + ": named claims lack the predicted manifest subject")
    if place:
        if not predicted or place != predicted:
            errors.append("PLACE differs from predicted manifest subject or prediction unavailable")
        for field, refs in citations.items():
            if place not in marker(field).casefold():
                errors.append(field + ": named subject is inconsistent")
            if not any(place in str(by_id.get(ref, {}).get("title") or "").casefold() for ref in refs):
                errors.append(field + ": cited headline does not support named subject")
        if not marker("INCIDENT_SUMMARY") or not marker("SEARCH_TERMS"):
            errors.append("PLACE requires incident summary and search terms")
    payload = {"schema": 1, "brief": brief, "evidence": evidence,
               "predicted_location": predicted_location, "citations": citations,
               "errors": errors, "accepted": not errors}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return payload, hashlib.sha256(raw).hexdigest(), raw
