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
