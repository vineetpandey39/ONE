"""The house content policy, enforced before a book can be published.

Why this exists
---------------
Publishing on Floor 5 became unattended on 2026-09-24, and an audit on
2026-09-26 found no content check anywhere on the floor. A book could be
written, packaged and put on sale without anything having read it for the one
risk the owner named first: that a reader is provoked rather than
entertained, and the brand is boycotted over a sentence nobody reviewed.

What this is not
----------------
It is not a bad-words list. A list like that flags "murder" in a mystery,
"blood" in a thriller and "affair" in a romance, and a gate that cries wolf
gets switched off - which is worse than not having one. The brief was
explicit that fiction must not be made bland: villains, crime, betrayal,
romance, fear, grief, suspense and moral conflict all belong in it. What does
not belong is material that attacks a real group or person, sexualizes a
child, or is built to enrage rather than to entertain.

So the detectors below look for structure, not for topics. A religion's name
is not a finding; a religion's name with an incitement predicate is. Violence
is not a finding; violence written as dehumanization is. That distinction is
the whole design.

Two layers
----------
Deterministic rules run first and are the ones that block. They are written
to be high-precision: each needs two things to co-occur, not one word to
appear. A judgement pass over the passages they surface can then be run by a
caller that has a model available - see `passages_for_review` - because the
last call on tone is not something a regular expression should make alone.

Nothing here edits a manuscript. It reports, and the publishing gate refuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

BLOCK = "block"
REVIEW = "review"
PASS = "pass"

# Ordered worst-first; a book's verdict is the worst thing found in it.
_SEVERITY_ORDER = {BLOCK: 2, REVIEW: 1, PASS: 0}


@dataclass(frozen=True)
class Finding:
    category: str
    severity: str
    why: str
    excerpt: str
    position: int

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "severity": self.severity, "why": self.why,
                "excerpt": self.excerpt, "position": self.position}


@dataclass
class Report:
    verdict: str
    findings: list[Finding] = field(default_factory=list)
    scanned_chars: int = 0
    kind: str = "fiction"

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "kind": self.kind,
                "scanned_chars": self.scanned_chars,
                "blocking": [f.to_dict() for f in self.findings if f.severity == BLOCK],
                "review": [f.to_dict() for f in self.findings if f.severity == REVIEW],
                "findings": len(self.findings),
                "summary": self.summary()}

    def summary(self) -> str:
        if self.verdict == PASS:
            return "nothing in the house policy was triggered"
        blocking = [f for f in self.findings if f.severity == BLOCK]
        if blocking:
            names = sorted({f.category for f in blocking})
            return f"blocked on {', '.join(names)}"
        names = sorted({f.category for f in self.findings})
        return f"needs a person's judgement on {', '.join(names)}"


# --------------------------------------------------------------- vocabulary
#
# Neutral nouns only. These are the words a piece of writing uses when it is
# talking ABOUT a group; none of them is a finding on its own, and each is
# only ever consulted next to a predicate below.
_IDENTITY = (
    r"muslims?|hindus?|sikhs?|christians?|jews?|buddhists?|jains?|parsis?"
    r"|dalits?|brahmins?|adivasis?"
    r"|immigrants?|refugees?|migrants?"
    r"|blacks?|whites?|asians?|arabs?|africans?"
    r"|women|men|girls?|boys?"
    r"|gays?|lesbians?|queers?|trans(?:gender)?(?:\s+people)?"
    r"|disabled(?:\s+people)?|autistic(?:\s+people)?"
)

# What turns a group's name into an attack. These are predicates of being, or
# calls to action, not descriptions of a character's opinion in a scene.
_DEHUMANIZING = (
    r"are\s+(?:all\s+)?(?:vermin|parasites?|animals?|subhuman|filth|scum|a\s+disease|a\s+cancer)"
    r"|should\s+be\s+(?:eliminated|exterminated|wiped\s+out|removed|cleansed|driven\s+out)"
    r"|do\s+not\s+deserve\s+to\s+(?:live|exist)"
    r"|must\s+be\s+(?:destroyed|purged|erased)"
)

_INCITEMENT = (
    r"(?:kill|burn|attack|lynch|stone|drive\s+out|throw\s+out|boycott)\s+(?:all\s+|every\s+|the\s+)?"
)

# Explicit sexual vocabulary. The house default for romance is fade-to-black,
# so the presence of these is a block rather than a flag - a romance can carry
# desire, tension and a closed door without them.
_EXPLICIT_SEXUAL = (
    r"penetrat\w*|thrust\w*\s+into|genitals?|erection|orgasm\w*|climax\w+\s+inside"
    r"|nipples?|aroused\s+flesh|between\s+her\s+thighs|between\s+his\s+thighs"
)

# Age markers. Used only next to sexual vocabulary, where the finding is
# absolute and has no fictional exception of any kind.
_MINOR = (
    r"child|children|kid|kids|minor|minors|schoolgirl|schoolboy|teenager|teen"
    r"|(?:thirteen|fourteen|fifteen|sixteen|seventeen|eleven|twelve|ten|nine|eight)[- ]year[- ]old"
    r"|1[0-7][- ]year[- ]old"
)

_SEXUAL_CONTEXT = (
    r"sex\w*|seduc\w*|nude|naked|undress\w*|fondl\w*|caress\w*|kiss\w+\s+deeply"
    r"|aroused|lust\w*|erotic\w*" + "|" + _EXPLICIT_SEXUAL
)

# Graphic-injury vocabulary. One of these is a thriller; a paragraph full of
# them, lingering, is what the policy calls gratuitous.
_GORE = (
    r"disembowel\w*|entrails|viscera|intestines\s+spill\w*|eviscerat\w*"
    r"|skull\s+(?:crack\w*|split\w*)|flesh\s+(?:peel\w*|tore|torn)"
    r"|blood\s+(?:pooled|sprayed|gushed)|mutilat\w*|dismember\w*"
)

# Allegation verbs. Only a finding when attached to what looks like a real,
# named person - a character in a novel is not defamed.
_ALLEGATION = (
    r"(?:is|was|has\s+been)\s+(?:a\s+)?(?:fraud|criminal|rapist|murderer|paedophile|pedophile|terrorist|thief)"
    r"|(?:raped|murdered|embezzled|stole\s+from|bribed|molested)"
)

# Rage-bait. Marketing that sells anger rather than the book. Every one of
# these addresses the reader directly and promises a feeling rather than a
# story, which is what separates it from a thriller's blurb. An earlier draft
# also matched "expose the conspiracy" and flagged a real novel whose plot is
# a journalist exposing a conspiracy - a summary of a book is not a provocation
# of the person reading the summary.
_PROVOCATIVE_MARKETING = (
    r"they\s+don'?t\s+want\s+you\s+to\s+know"
    r"|will\s+make\s+you\s+(?:furious|angry|sick|rage)"
    r"|the\s+truth\s+(?:they|the\s+\w+)\s+(?:are\s+)?hid\w+"
    r"|wake\s+up,?\s+(?:sheeple|india|america)"
    r"|banned\s+(?:book|truth)"
)

# Where humour turns into punching down. Deliberately not the whole identity
# list: "men", "women", "boys" and "girls" appear in ordinary prose constantly,
# and pairing them with "laughter" flagged a scene of an audience applauding in
# the rain. What is protected here is what a joke cannot be aimed at.
_PROTECTED_SUBJECT = (
    r"muslims?|hindus?|sikhs?|christians?|jews?|buddhists?|jains?|parsis?"
    r"|dalits?|brahmins?|adivasis?"
    r"|immigrants?|refugees?|migrants?"
    r"|gays?|lesbians?|queers?|trans(?:gender)?(?:\s+people)?"
    r"|disabled(?:\s+people)?|autistic(?:\s+people)?"
    r"|suicide|rape|abuse|trauma|holocaust|genocide|disability"
)
_JOKE_MARKER = r"joke|punchline|hilarious|comic\w*|funny"


def _words(pattern: str) -> str:
    """The same alternation, but only where a word actually begins.

    Every vocabulary list here started without this and it was not a
    theoretical problem. Run against the live catalogue on 2026-09-26, two
    published books came back BLOCKED for sexualising a minor. Both were
    false: "lust" had matched inside "c-luster", in the phrase "a cluster of
    schoolchildren crossing near the promenade". A gate that says that about
    a real book gets switched off within a week, and a switched-off gate is
    worse than none because everybody believes it is running.

    Both ends matter. With only a leading boundary the same run still flagged
    gratuitous gore in a retirement guide, because "viscera" is the start of
    "visceral fear". A trailing \\b costs nothing: every alternation here
    either ends in a literal or in \\w*, which is greedy and reaches the word
    end by itself.
    """
    return rf"\b(?:{pattern})\b"


def _near(pattern_a: str, pattern_b: str, *, window: int = 120) -> re.Pattern[str]:
    """Two things within a window of each other, in either order.

    Co-occurrence rather than either word alone is what keeps this from
    flagging every thriller: "child" is common, "sex" is common, and the two
    inside the same sentence is not.
    """
    first, second = _words(pattern_a), _words(pattern_b)
    return re.compile(
        rf"(?:{first}.{{0,{window}}}?{second}|{second}.{{0,{window}}}?{first})",
        re.IGNORECASE | re.DOTALL,
    )


_REAL_PERSON = re.compile(
    # Two or three capitalised words, the shape of a real name in prose. A
    # character's name looks the same, which is why this is REVIEW and never
    # a block - a person decides whether the name is a real one.
    r"\b[A-Z][a-z]{2,}\s+(?:[A-Z][a-z]{1,}\s+)?[A-Z][a-z]{2,}\b"
)


@dataclass(frozen=True)
class Rule:
    category: str
    severity: str
    why: str
    pattern: re.Pattern[str]


RULES: tuple[Rule, ...] = (
    Rule("sexualisation of a minor", BLOCK,
         "sexual language appears near an age marker below eighteen. This has "
         "no fictional exception and no context that permits it.",
         _near(_MINOR, _SEXUAL_CONTEXT, window=140)),
    Rule("explicit sexual content", BLOCK,
         "the house default for romance is fade-to-black; desire and tension "
         "belong in the book, the act itself does not.",
         re.compile(_words(_EXPLICIT_SEXUAL), re.IGNORECASE)),
    Rule("dehumanisation of a group", BLOCK,
         "a named group is written as less than human. A villain may hold "
         "this view in dialogue; the book may not assert it.",
         _near(_IDENTITY, _DEHUMANIZING, window=90)),
    Rule("incitement against a group", BLOCK,
         "the text calls for action against a named group.",
         re.compile(_words(rf"(?:{_INCITEMENT})(?:{_IDENTITY})"), re.IGNORECASE)),
    Rule("gratuitous gore", REVIEW,
         "graphic injury is described at length. Violence is allowed and "
         "lingering on it is what the policy asks a person to weigh.",
         re.compile(_words(_GORE), re.IGNORECASE)),
    Rule("possible defamation", REVIEW,
         "an allegation appears next to what reads like a real person's name. "
         "A character cannot be defamed; a living person can.",
         _near(_REAL_PERSON.pattern, _ALLEGATION, window=80)),
    Rule("humour at a protected subject", REVIEW,
         "a joke marker sits next to identity, disability or trauma. Comedy "
         "is welcome; these are not the punchline.",
         _near(_JOKE_MARKER, _PROTECTED_SUBJECT, window=60)),
)

MARKETING_RULES: tuple[Rule, ...] = (
    Rule("rage-bait marketing", REVIEW,
         "the copy sells anger rather than the book. It is the fastest way to "
         "be boycotted by readers who never opened it.",
         re.compile(_words(_PROVOCATIVE_MARKETING), re.IGNORECASE)),
)


def _excerpt(text: str, start: int, end: int, *, pad: int = 60) -> str:
    return " ".join(text[max(0, start - pad):min(len(text), end + pad)].split())


def _apply(rules: Iterable[Rule], text: str, *, limit_per_rule: int = 5) -> list[Finding]:
    found: list[Finding] = []
    for rule in rules:
        for count, match in enumerate(rule.pattern.finditer(text)):
            if count >= limit_per_rule:
                break
            found.append(Finding(rule.category, rule.severity, rule.why,
                                 _excerpt(text, match.start(), match.end()),
                                 match.start()))
    return found


def scan(text: str, *, kind: str = "fiction", marketing: str = "") -> Report:
    """Read a manuscript against the house policy.

    ``marketing`` is the description and subtitle, scanned under its own rule:
    a book can be blameless and still be sold in a way that provokes.
    """
    body = str(text or "")
    findings = _apply(RULES, body)
    if marketing:
        findings += _apply(MARKETING_RULES, str(marketing))

    worst = PASS
    for finding in findings:
        if _SEVERITY_ORDER[finding.severity] > _SEVERITY_ORDER[worst]:
            worst = finding.severity
    return Report(verdict=worst, findings=findings, scanned_chars=len(body), kind=kind)


def passages_for_review(report: Report) -> list[dict[str, Any]]:
    """What a judgement pass should look at, if a model is available.

    The deterministic rules are deliberately narrow, so this is the hand-off
    point rather than the end of the check: a caller with a model can weigh
    tone on these passages, which is not a job for a regular expression.
    """
    return [f.to_dict() for f in report.findings if f.severity == REVIEW]


def may_publish(report: Report) -> tuple[bool, str]:
    """The gate's answer, and the sentence to record with it."""
    if report.verdict == BLOCK:
        return False, f"House content policy refuses this manuscript: {report.summary()}"
    if report.verdict == REVIEW:
        return True, (f"Published with findings a person should read: "
                      f"{report.summary()}")
    return True, "House content policy found nothing to raise."
