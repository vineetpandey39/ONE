"""Offline provenance checks for manifest-owned regular reel briefs."""
import hashlib
import json
import re


def _marker(brief, name):
    match = re.search(r"^" + name + r":[^\S\n]*(.*)$", brief, re.M)
    return match.group(1).strip() if match else ""


def _core(value):
    return re.split(r"[,\(]", value, maxsplit=1)[0].strip().casefold()


def repair_regular_brief(brief, evidence, predicted_location=None):
    """Fail-safe repair for a cited current incident omitted by local synthesis.

    A repair is possible only when the exact PLACE occurs in eligible evidence
    headlines. Factual prose is replaced with those headlines verbatim rather
    than preserving model-added numbers, causes, or consequences.
    """
    place_label = _marker(brief, "PLACE")
    place = _core(place_label)
    if not place:
        return brief
    # Repair only the observed local-model omission: both editorial lines
    # named a fresh general-news incident but omitted every evidence id.
    # Existing, invented, mixed, or predicted-location citations still fail
    # closed in the validator instead of being silently replaced.
    if re.search(r"\[[^\[\]]+\]", _marker(brief, "PRIORITY") + _marker(brief, "ANGLE")):
        return brief
    supporting = []
    for item in evidence.get("eligible") or []:
        evidence_id = str(item.get("evidence_id") or "")
        title = str(item.get("title") or "").strip()
        if (evidence_id and title and place in title.casefold()
                and item.get("category") != "predicted_location"):
            supporting.append((evidence_id, title))
    if not supporting:
        predicted_label = str((predicted_location or {}).get("name") or "").strip()
        predicted = _core(predicted_label)
        subject = (place if place and predicted and (place in predicted or predicted in place)
                   else predicted)
        predicted_support = [
            (str(item.get("evidence_id") or ""), str(item.get("title") or "").strip())
            for item in evidence.get("eligible") or []
            if item.get("category") == "predicted_location"
            and item.get("evidence_id") and item.get("title")
            and subject and subject in str(item.get("title") or "").casefold()
        ]
        if not predicted_support:
            return brief
        evidence_id, title = predicted_support[0]
        ref = f"[{evidence_id}]"
        grounding_label = place_label if subject == place else predicted_label
        # The model tried to force a general incident onto an unsupported
        # place. Fall back to the rotation subject's own exact headline and
        # explicitly remove every incident marker instead of inventing a link.
        replacements = {
            "PRIORITY": f"Ground the reel in verified context for {grounding_label} {ref}",
            "ANGLE": f"Use only the cited {grounding_label} context; make no current-incident claim {ref}",
            "BRIEF": (f"Eligible evidence headline: {title} {ref}. Produce the normal restoration "
                      "story for the rotation-owned location without transferring an unrelated "
                      "incident, casualty, cause or safety claim to it."),
            "PLACE": "",
            "INCIDENT_SUMMARY": "",
            "SEARCH_TERMS": "",
        }
        repaired = brief
        for name, value in replacements.items():
            pattern = r"^" + name + r":[^\n]*$"
            line = f"{name}: {value}"
            repaired, count = re.subn(pattern, line, repaired, count=1, flags=re.M)
            if not count:
                repaired = repaired.rstrip() + "\n" + line
        return repaired
    refs = " ".join(f"[{evidence_id}]" for evidence_id, _ in supporting[:3])
    titles = "; ".join(title for _, title in supporting[:3])
    replacements = {
        "PRIORITY": f"Cover the verified current report at {place_label} {refs}",
        "ANGLE": (f"Explain only the headline-backed update at {place_label}; "
                  f"do not add uncited causes, figures or consequences {refs}"),
        "BRIEF": (f"Current eligible evidence reports: {titles} {refs}. Keep every "
                  "production claim within these cited headlines. The rotation-owned "
                  "visual location remains independent and must not be presented as "
                  "the incident site unless it is the same place."),
        "INCIDENT_SUMMARY": f"{titles} {refs}",
        "SEARCH_TERMS": f"{place_label} news today, {place_label} latest report",
    }
    repaired = brief
    for name, value in replacements.items():
        pattern = r"^" + name + r":[^\n]*$"
        line = f"{name}: {value}"
        repaired, count = re.subn(pattern, line, repaired, count=1, flags=re.M)
        if not count:
            repaired = repaired.rstrip() + "\n" + line
    return repaired


def bind_regular_brief(brief, evidence, predicted_location):
    """Bind exact model context; citations establish attribution, not truth.

    A fresh named incident may differ from the rotation-owned visual location,
    but only exact eligible-headline support can establish that incident.
    This never chooses or overrides the production location.
    """
    brief = repair_regular_brief(brief, evidence, predicted_location)
    items = evidence.get("eligible") or []
    by_id = {str(x.get("evidence_id")): x for x in items if x.get("evidence_id")}
    def marker(name):
        return _marker(brief, name)
    def core(value):
        return _core(value)
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
        if not place and mentioned and (not predicted or predicted not in mentioned):
            errors.append(field + ": named claims lack the predicted manifest subject")
    if place:
        referenced = [by_id.get(ref, {}) for refs in citations.values() for ref in refs]
        if (any(item.get("category") == "predicted_location" for item in referenced)
                and (not predicted or place != predicted)):
            errors.append("PLACE differs from predicted manifest subject")
        for field, refs in citations.items():
            if place not in marker(field).casefold():
                errors.append(field + ": named subject is inconsistent")
            if not any(place in str(by_id.get(ref, {}).get("title") or "").casefold() for ref in refs):
                errors.append(field + ": cited headline does not support named subject")
        if not marker("INCIDENT_SUMMARY") or not marker("SEARCH_TERMS"):
            errors.append("PLACE requires incident summary and search terms")
    payload = {"schema": 2, "brief": brief, "evidence": evidence,
               "predicted_location": predicted_location, "citations": citations,
               "errors": errors, "accepted": not errors}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return payload, hashlib.sha256(raw).hexdigest(), raw
