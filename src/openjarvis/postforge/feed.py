"""The verified source feed behind PostForge's five pillar tabs.

PostForge's real intelligence was never its copywriting -- it was ``refresh``:
five pillar query sets, a freshness window, and a verifier that re-fetched every
candidate and threw it away unless the source page itself proved the claim. That
part is ported here in full. Two things changed on the way in:

* **Discovery.** The Vercel app asked OpenAI's search model for candidates. Here
  candidates come from Sanjeevani's self-hosted SearXNG, so a refresh spends no
  cloud credits and stays inside ONE's local-first boundary.
* **The window.** PostForge worked in whole days (7 for news, 90 for income).
  Every tab here is the last 24 hours, so the arithmetic moved to timestamps:
  a day-granular check would accept a story 47 hours old.

The page date is the authority, not the search engine's guess. A candidate whose
own page carries no publish/update timestamp is rejected on every pillar -- at a
24-hour window an unprovable date is the same as a stale one.
"""

from __future__ import annotations

import html as _html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Pillars and the window
# ---------------------------------------------------------------------------

PILLARS: tuple[dict[str, str], ...] = (
    {"id": "news", "label": "News", "full": "AI News Breakdown", "color": "#3B82F6"},
    {"id": "tool", "label": "Tools", "full": "AI Tool Drop", "color": "#F59E0B"},
    {"id": "income", "label": "Income", "full": "AI Income Update", "color": "#10B981"},
    {
        "id": "transformation",
        "label": "Transform",
        "full": "AI Transformation",
        "color": "#8B5CF6",
    },
    {
        "id": "automation",
        "label": "Automation",
        "full": "AI Automation Win",
        "color": "#38BDF8",
    },
)

PILLAR_IDS: tuple[str, ...] = tuple(pillar["id"] for pillar in PILLARS)

#: Every tab is "the last 24 hours". Overridable for a wider sweep when a pillar
#: genuinely has nothing in a day, but the default is the product promise.
FRESH_HOURS = 24

#: Publishers stamp local time without an offset often enough that assuming UTC
#: can push a real story a few hours into the future. Tolerate that rather than
#: rejecting fresh items; anything further ahead is a broken date, not skew.
FUTURE_SKEW_HOURS = 6

_SOURCE_HINTS = (
    "official company blogs OR Reuters OR The Verge OR TechCrunch OR VentureBeat "
    "OR CNBC OR Bloomberg OR Google Blog OR OpenAI Blog OR Anthropic News OR "
    "Meta AI Blog OR Microsoft Blog"
)
_AI_MARKET = (
    "OpenAI OR Anthropic Claude OR Google Gemini DeepMind OR Meta AI Llama OR "
    "Microsoft Copilot OR xAI Grok OR Perplexity OR Mistral OR Cohere OR Runway "
    "OR ElevenLabs OR Stability AI"
)

QUERIES: dict[str, str] = {
    "news": f"latest AI announcements today ({_AI_MARKET}) {_SOURCE_HINTS}",
    "tool": f"AI tool launch or update announced today ({_AI_MARKET}) {_SOURCE_HINTS}",
    "income": "AI creator economy income case study with real numbers published today",
    "transformation": "AI workplace productivity or career transformation report today",
    "automation": "AI automation workflow case study time saved cost saved today",
}

#: Rotated per day so consecutive refreshes do not re-run the same search.
TARGETED_QUERIES: dict[str, tuple[str, ...]] = {
    "news": (
        "Anthropic Claude announcement today",
        "Google Gemini DeepMind announcement today",
        "Meta AI Llama announcement today",
        "Microsoft Copilot AI announcement today",
        "OpenAI announcement today",
        "Perplexity Mistral Cohere Runway ElevenLabs AI announcement today",
        "Reuters The Verge TechCrunch artificial intelligence news today",
    ),
    "tool": (
        "Anthropic Claude tool update launched today",
        "Google Gemini tool update launched today",
        "Microsoft Copilot tool update launched today",
        "OpenAI ChatGPT Codex tool update launched today",
        "Perplexity Mistral Runway ElevenLabs AI tool launched today",
    ),
    "income": (
        "creator AI income report published today",
        "AI side income case study numbers today",
    ),
    "transformation": (
        "AI jobs workforce study published today",
        "AI skills career shift report today",
    ),
    "automation": (
        "AI workflow automation case study today",
        "no-code AI automation time saved today",
    ),
}

COMPANY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anthropic", ("anthropic", "claude")),
    ("openai", ("openai", "chatgpt", "codex")),
    ("google", ("google", "gemini", "deepmind")),
    ("meta", ("meta ai", "llama", "meta")),
    ("microsoft", ("microsoft", "copilot")),
    ("xai", ("xai", "grok")),
    ("perplexity", ("perplexity",)),
    ("mistral", ("mistral",)),
    ("cohere", ("cohere",)),
    ("runway", ("runway",)),
    ("elevenlabs", ("elevenlabs", "eleven labs")),
    ("stability", ("stability ai", "stable diffusion")),
)

#: A launch headline pointing at an undated product page is a recycled launch.
#: These are URL path segments, matched whole.
EVERGREEN_SEGMENTS = frozenset(
    {
        "products",
        "product",
        "models",
        "model",
        "grok",
        "chatgpt",
        "claude",
        "gemini",
        "copilot",
    }
)

_DATE_META_PATTERNS = (
    re.compile(
        r"""property=["']article:published_time["'][^>]*content=["']([^"']+)["']""",
        re.I,
    ),
    re.compile(
        r"""content=["']([^"']+)["'][^>]*property=["']article:published_time["']""",
        re.I,
    ),
    re.compile(
        r"""property=["']article:modified_time["'][^>]*content=["']([^"']+)["']""", re.I
    ),
    re.compile(r"""name=["']date["'][^>]*content=["']([^"']+)["']""", re.I),
    re.compile(r"""name=["']pubdate["'][^>]*content=["']([^"']+)["']""", re.I),
    re.compile(
        r"""itemprop=["']datePublished["'][^>]*content=["']([^"']+)["']""", re.I
    ),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'"dateModified"\s*:\s*"([^"]+)"', re.I),
    re.compile(r"""<time[^>]*datetime=["']([^"']+)["']""", re.I),
    re.compile(
        r"(?:published|last updated)(?: on)?\s*[:\-]?\s*"
        r"([a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[a-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})",
        re.I,
    ),
)

_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "will",
        "soon",
        "new",
        "latest",
        "launches",
        "launch",
        "announces",
        "announced",
        "introduces",
        "unveils",
        "adds",
        "major",
        "could",
        "your",
        "about",
    }
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_ISO_DATE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?",
    re.I,
)
# The clock half is optional but load-bearing: Sanjeevani dates rows RFC-2822
# style ("Fri, 25 Sept 2026 11:14:00 GMT"), and flooring that to midnight ages a
# live story by most of a day -- fatal at a 24-hour window.
_CLOCK = (
    r"(?:[\s,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?(?:\s*(GMT|UTC|Z|[+-]\d{2}:?\d{2}))?"
)
_TEXT_DATE_MDY = re.compile(r"([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})" + _CLOCK, re.I)
_TEXT_DATE_DMY = re.compile(r"(\d{1,2})\s+([a-z]{3,9})\.?,?\s+(\d{4})" + _CLOCK, re.I)


class SanjeevaniUnavailable(RuntimeError):
    """Raised when the research library ONE refuses to work without is missing."""


_MISSING_LIBRARY = (
    "Sanjeevani's research library is unavailable; point "
    "SANJEEVANI_RESEARCH_LIBRARY at research_library.py. A PostForge refresh "
    "never falls back to a paid API."
)


@dataclass(frozen=True)
class Freshness:
    """Where a timestamp sits relative to the window."""

    fresh: bool
    age_hours: float | None
    published_at: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _int_env(name: str, fallback: int) -> int:
    try:
        parsed = int(str(os.environ.get(name, "")).strip())
    except ValueError:
        return fallback
    return parsed if parsed > 0 else fallback


def fresh_hours() -> int:
    """The live window. ``ONE_POSTFORGE_FRESH_HOURS`` widens it when a day is dry."""
    return _int_env("ONE_POSTFORGE_FRESH_HOURS", FRESH_HOURS)


def cache_minutes() -> int:
    return _int_env("ONE_POSTFORGE_CACHE_MINUTES", 45)


def search_budget(pillar: str) -> int:
    """Searches per refresh. News and Tools carry the most sources, so they get more."""
    fallback = 4 if pillar in ("news", "tool") else 2
    return _int_env("ONE_POSTFORGE_SEARCH_BUDGET", fallback)


def pillar_by_id(pillar_id: str) -> dict[str, str]:
    for pillar in PILLARS:
        if pillar["id"] == pillar_id:
            return dict(pillar)
    raise KeyError(f"Unknown pillar: {pillar_id!r}")


# ---------------------------------------------------------------------------
# Dates and freshness
# ---------------------------------------------------------------------------


def parse_item_date(value: Any) -> datetime | None:
    """Best-effort timestamp from anything a page or search row calls a date.

    Returns an aware UTC datetime. A value carrying no time of day lands at
    midnight UTC, which is the conservative reading: it can only make an item
    look older than it is, never fresher.
    """
    text = str(value or "").strip()
    if not text:
        return None

    match = _ISO_DATE.search(text)
    if match:
        year, month, day = (int(part) for part in match.group(1, 2, 3))
        hour = int(match.group(4) or 0)
        minute = int(match.group(5) or 0)
        second = int(match.group(6) or 0)
        offset = match.group(7) or ""
        tz = timezone.utc
        if offset and offset.upper() != "Z":
            sign = -1 if offset[0] == "-" else 1
            digits = offset[1:].replace(":", "")
            tz = timezone(
                sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
            )
        try:
            parsed = datetime(year, month, day, hour, minute, second, tzinfo=tz)
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc)

    for pattern, order in ((_TEXT_DATE_MDY, "mdy"), (_TEXT_DATE_DMY, "dmy")):
        found = pattern.search(text)
        if not found:
            continue
        month_name, day_text = (
            (found.group(1), found.group(2))
            if order == "mdy"
            else (found.group(2), found.group(1))
        )
        month = _MONTHS.get(month_name[:3].lower())
        if not month:
            continue
        zone = found.group(7) or ""
        tz = timezone.utc
        if zone and zone.upper() not in ("Z", "GMT", "UTC"):
            sign = -1 if zone[0] == "-" else 1
            digits = zone[1:].replace(":", "")
            tz = timezone(
                sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
            )
        try:
            return datetime(
                int(found.group(3)),
                month,
                int(day_text),
                int(found.group(4) or 0),
                int(found.group(5) or 0),
                int(found.group(6) or 0),
                tzinfo=tz,
            ).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def freshness(
    value: Any, now: datetime | None = None, hours: int | None = None
) -> Freshness:
    """How old ``value`` is, and whether that is inside the window."""
    window = fresh_hours() if hours is None else hours
    moment = now or datetime.now(timezone.utc)
    parsed = parse_item_date(value)
    if parsed is None:
        return Freshness(False, None, "")

    age = (moment - parsed).total_seconds() / 3600.0
    inside = -FUTURE_SKEW_HOURS <= age <= window
    return Freshness(inside, round(age, 2), parsed.isoformat().replace("+00:00", "Z"))


# ---------------------------------------------------------------------------
# Page reading
# ---------------------------------------------------------------------------


def strip_html(markup: str) -> str:
    text = re.sub(
        r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", str(markup or "")
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def extract_title(markup: str) -> str:
    found = re.search(r"(?is)<title[^>]*>(.*?)</title>", str(markup or ""))
    return strip_html(found.group(1))[:220] if found else ""


def extract_evidence_date(markup: str) -> str:
    """The page's own publish/update timestamp, ISO 8601 UTC, or ``""``.

    Only the head-ish portion is scanned: article bodies quote other dates, and
    the first match further down the page is usually a link to an older story.
    """
    source = str(markup or "")[:240_000]
    for pattern in _DATE_META_PATTERNS:
        found = pattern.search(source)
        if not found:
            continue
        parsed = parse_item_date(found.group(1))
        if parsed:
            return parsed.isoformat().replace("+00:00", "Z")
    return ""


def meaningful_tokens(value: Any) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return [
        token
        for token in cleaned.split()
        if len(token) > 2 and token not in _STOP_WORDS
    ]


def text_overlap_score(needle: Any, haystack: Any) -> float:
    """Share of a claim's distinctive words that actually appear on the page."""
    tokens = list(dict.fromkeys(meaningful_tokens(needle)))[:18]
    if not tokens:
        return 0.0
    page = str(haystack or "").lower()
    return sum(1 for token in tokens if token in page) / len(tokens)


def looks_evergreen(item: dict[str, Any]) -> bool:
    try:
        path = (urlparse(str(item.get("url") or "")).path or "").lower().rstrip("/")
    except ValueError:
        return False
    headline = str(item.get("headline") or "").lower()
    launchy = re.search(
        r"\b(launch|launches|unveil|unveils|announce|announces|introduced|introduces|dropped|released)\b",
        headline,
    )
    if not launchy:
        return False
    # Match whole path segments: substring matching would read /claudex as
    # /claude and reject a real launch article for sharing a prefix.
    segments = {segment for segment in path.split("/") if segment}
    return bool(segments & EVERGREEN_SEGMENTS)


# ---------------------------------------------------------------------------
# Item shaping
# ---------------------------------------------------------------------------


def is_valid_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _stable_id(value: str) -> str:
    digest = 0
    for char in value:
        digest = ((digest << 5) - digest + ord(char)) & 0xFFFFFFFF
    return format(digest, "x")


def company_key(item: dict[str, Any]) -> str:
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("company", "source", "headline", "summary")
    ).lower()
    for key, aliases in COMPANY_ALIASES:
        if any(alias in haystack for alias in aliases):
            return key
    slug = re.sub(r"[^a-z0-9]+", "-", str(item.get("source") or "unknown").lower())
    return slug[:40] or "unknown"


def normalize_item(
    raw: dict[str, Any], index: int, pillar: str, hours: int | None = None
) -> dict[str, Any]:
    """One search row in the shape the cockpit and the generator both expect."""
    window = fresh_hours() if hours is None else hours
    state = freshness(raw.get("date"), hours=window)
    url = str(raw.get("url") or "")
    host = (
        urlparse(url).netloc.lower().removeprefix("www.")
        if is_valid_http_url(url)
        else ""
    )
    headline = str(raw.get("headline") or "")
    seed = f"{pillar}|{index}|{url}|{headline}"
    item = {
        "id": f"{pillar}-{index}-{_stable_id(seed)}",
        "tag": str(raw.get("tag") or "AI")[:30],
        "date": str(raw.get("date") or "")[:80],
        "publishedAt": state.published_at,
        "ageHours": state.age_hours,
        "freshnessHours": window,
        "company": str(raw.get("company") or "")[:80],
        "source": str(raw.get("source") or host)[:80],
        "headline": headline[:180],
        "summary": str(raw.get("summary") or "")[:600],
        "url": url,
        "verified": False,
        "pillar": pillar,
    }
    return item


def unique_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").lower()
        headline = str(item.get("headline") or "").lower()
        key = f"{url}|{headline}"
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def diversify(
    items: Sequence[dict[str, Any]], limit: int = 6, per_company: int = 2
) -> list[dict[str, Any]]:
    """Cap one company's share so a single launch day cannot fill the feed."""
    counts: dict[str, int] = {}
    primary: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    for item in items:
        key = company_key(item)
        if counts.get(key, 0) < per_company:
            counts[key] = counts.get(key, 0) + 1
            primary.append(item)
        else:
            overflow.append(item)
    return [*primary, *overflow][:limit]


# ---------------------------------------------------------------------------
# Sanjeevani ports
# ---------------------------------------------------------------------------


def _sanjeevani() -> Any:
    """Sanjeevani's reusable library, through the runtime's single loader.

    ``runtime`` owns the path, the env override and the module cache for this;
    a second loader here would be a second place to keep in sync.
    """
    from openjarvis.one_agents.runtime import _sanjeevani_research

    return _sanjeevani_research()


# Sanjeevani's collector rows name these ``source_url`` and ``published_at`` and
# carry no snippet at all, which is exactly why every field is read from the
# first spelling present instead of one hardcoded name. Confirmed against a live
# row: source_type, source_url, title, published_at, captured_at, age_hours,
# freshness_bucket, freshness_eligible, evidence_id, market, role, raw_signal.
_ROW_URL_KEYS = ("source_url", "url", "link", "href")
_ROW_TITLE_KEYS = ("title", "headline", "name")
_ROW_SUMMARY_KEYS = ("content", "snippet", "summary", "description", "text")
_ROW_DATE_KEYS = (
    "published_at",
    "publishedDate",
    "published_date",
    "publishedAt",
    "date",
    "pubdate",
)
_ROW_SOURCE_KEYS = ("source", "site", "domain", "engine")


def _first(row: dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value)
    return ""


def row_to_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """A SearXNG result row in PostForge's item vocabulary.

    Key spellings vary by SearXNG version and engine, so each field is taken
    from the first spelling present rather than one hardcoded name.
    """
    url = _first(row, _ROW_URL_KEYS)
    host = (
        urlparse(url).netloc.lower().removeprefix("www.")
        if is_valid_http_url(url)
        else ""
    )
    return {
        "tag": "AI",
        "company": "",
        "date": _first(row, _ROW_DATE_KEYS),
        "source": _first(row, _ROW_SOURCE_KEYS) or host,
        "headline": _first(row, _ROW_TITLE_KEYS),
        "summary": _first(row, _ROW_SUMMARY_KEYS),
        "url": url,
    }


def select_queries(
    pillar: str, *, today: str = "", budget: int | None = None
) -> list[str]:
    """The primary query plus a day-rotated slice of the targeted ones."""
    primary = QUERIES.get(pillar, QUERIES["news"])
    targeted = list(TARGETED_QUERIES.get(pillar, ()))
    limit = search_budget(pillar) if budget is None else budget
    if not targeted:
        return [primary][:limit]
    stamp = parse_item_date(today) or datetime.now(timezone.utc)
    offset = int(stamp.timestamp() // 86400) % len(targeted)
    rotated = [
        targeted[(index + offset) % len(targeted)] for index in range(len(targeted))
    ]
    return [primary, *rotated][:limit]


def search_rows(queries: Sequence[str], *, library: Any = None) -> list[dict[str, Any]]:
    """Sanjeevani's SearXNG, pinned to its own day window."""
    reusable = library if library is not None else _sanjeevani()
    if reusable is None:
        raise SanjeevaniUnavailable(_MISSING_LIBRARY)
    rows, _mode = reusable.searxng(list(queries), time_range="day")
    return [row for row in rows if isinstance(row, dict)]


def read_page(url: str, *, library: Any = None) -> str:
    """One public page's markup through Sanjeevani's bounded, TLS-verified fetcher.

    It refuses private and loopback addresses, which is what makes a URL that a
    search engine handed us safe to open at all. The text is only ever matched
    against the candidate's own claim; it is never treated as an instruction.
    """
    reusable = library if library is not None else _sanjeevani()
    if reusable is None:
        raise SanjeevaniUnavailable("Sanjeevani's research library is unavailable")
    raw = reusable._get(
        reusable._safe_public_url(url), timeout=12, limit=1_500_000, attempts=1
    )
    return (
        raw.decode("utf-8", "replace")
        if isinstance(raw, (bytes, bytearray))
        else str(raw)
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_item(
    item: dict[str, Any],
    *,
    fetch: Callable[[str], str],
    now: datetime | None = None,
    hours: int | None = None,
) -> dict[str, Any]:
    """Re-open the source and keep the item only if the page proves the claim."""
    window = fresh_hours() if hours is None else hours
    checked = dict(item)

    if not is_valid_http_url(checked.get("url")):
        return {
            **checked,
            "verified": False,
            "verificationReason": "Missing or invalid source URL.",
        }
    if not checked.get("headline"):
        return {
            **checked,
            "verified": False,
            "verificationReason": "Candidate has no headline.",
        }

    try:
        markup = fetch(str(checked["url"]))
    except Exception as exc:  # noqa: BLE001 - a failed fetch is a rejection, not a crash
        return {
            **checked,
            "verified": False,
            "verificationReason": f"Source fetch failed: {type(exc).__name__}: {exc}",
        }

    page_text = strip_html(markup)[:120_000]
    title = extract_title(markup)
    evidence_date = extract_evidence_date(markup)

    if looks_evergreen(checked) and not evidence_date:
        return {
            **checked,
            "verified": False,
            "verificationReason": "Undated product page presented as a fresh launch.",
        }
    if not evidence_date:
        # At a 24-hour window an unprovable date is indistinguishable from a
        # stale one, so unlike PostForge this applies to every pillar.
        return {
            **checked,
            "verified": False,
            "verificationReason": "No publish or update date found on the source page.",
        }

    state = freshness(evidence_date, now=now, hours=window)
    if not state.fresh:
        age = (
            "unknown age" if state.age_hours is None else f"{state.age_hours:.1f}h old"
        )
        return {
            **checked,
            "verified": False,
            "verificationReason": (
                f"Source page date {evidence_date} is outside "
                f"the {window}h window ({age})."
            ),
        }

    headline_score = text_overlap_score(checked.get("headline"), f"{title} {page_text}")
    summary_score = (
        text_overlap_score(checked.get("summary"), page_text)
        if checked.get("summary")
        else 1.0
    )
    if headline_score < 0.28 or summary_score < 0.18:
        return {
            **checked,
            "verified": False,
            "verificationReason": (
                "Source page does not support the headline or summary."
            ),
        }

    return {
        **checked,
        "date": evidence_date,
        "publishedAt": state.published_at,
        "ageHours": state.age_hours,
        "verified": True,
        "verification": {
            "sourceChecked": True,
            "sourceTitle": title,
            "sourceDate": evidence_date,
            "headlineScore": round(headline_score, 2),
            "summaryScore": round(summary_score, 2),
        },
    }


def _worth_fetching(item: dict[str, Any], *, now: datetime | None, hours: int) -> bool:
    """Skip the fetch when the row's own date is already far outside the window.

    Only a clearly old row is dropped here: the page date decides everything
    inside the grey zone, and search engines often report no date at all.
    """
    state = freshness(item.get("date"), now=now, hours=hours)
    if state.age_hours is None:
        return True
    return state.age_hours <= hours + 48


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_key(pillar: str, hours: int) -> str:
    return f"{pillar}:{hours}"


def clear_cache() -> None:
    _CACHE.clear()


def refresh(
    pillar: str = "news",
    *,
    force: bool = False,
    library: Any = None,
    fetch: Callable[[str], str] | None = None,
    now: datetime | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Discover, verify and rank one pillar's last-24-hours sources.

    ``library`` and ``fetch`` exist so the whole pipeline can be exercised
    without a network; in production both default to Sanjeevani.
    """
    if pillar not in PILLAR_IDS:
        raise KeyError(f"Unknown pillar: {pillar!r}")

    window = fresh_hours()
    moment = now or datetime.now(timezone.utc)
    key = _cache_key(pillar, window)
    if not force:
        cached = _CACHE.get(key)
        if cached and (moment.timestamp() - cached[0]) < cache_minutes() * 60:
            return {**cached[1], "cached": True}

    reusable = library if library is not None else _sanjeevani()
    if reusable is None:
        raise SanjeevaniUnavailable(_MISSING_LIBRARY)
    reader = fetch or (lambda url: read_page(url, library=reusable))

    queries = select_queries(pillar, today=moment.isoformat())
    rows = search_rows(queries, library=reusable)
    candidates = unique_items(
        row_to_candidate(row)
        for row in rows
        if is_valid_http_url(_first(row, _ROW_URL_KEYS))
    )
    normalized = [
        normalize_item(raw, index, pillar, window)
        for index, raw in enumerate(candidates)
    ]

    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in normalized:
        if not _worth_fetching(item, now=moment, hours=window):
            rejected.append(
                {
                    **item,
                    "verificationReason": "Search row date is far outside the window.",
                }
            )
            continue
        result = verify_item(item, fetch=reader, now=moment, hours=window)
        (verified if result.get("verified") else rejected).append(result)

    items = diversify(
        verified, limit=limit, per_company=2 if pillar in ("news", "tool") else 3
    )
    payload = {
        "pillar": pillar,
        "pillarFull": pillar_by_id(pillar)["full"],
        "items": items,
        "refreshedAt": moment.isoformat().replace("+00:00", "Z"),
        "freshnessHours": window,
        "since": (moment - timedelta(hours=window)).isoformat().replace("+00:00", "Z"),
        "rejected": len(rejected),
        "rejectedReasons": [
            {"url": row.get("url", ""), "reason": row.get("verificationReason", "")}
            for row in rejected[:12]
        ],
        "candidates": len(normalized),
        "searchCalls": len(queries),
        "queries": queries,
        "sourceChecked": True,
        "cached": False,
        "researcher": "sanjeevani",
    }
    _CACHE[key] = (moment.timestamp(), payload)
    return payload


def require_verified(
    items: Sequence[dict[str, Any]], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Generation's gate: every selected item is still verified and still fresh."""
    if not items:
        raise ValueError("Select at least one verified source item.")
    window = fresh_hours()
    for item in items:
        state = freshness(
            item.get("publishedAt") or item.get("date"), now=now, hours=window
        )
        if (
            not item.get("verified")
            or not is_valid_http_url(item.get("url"))
            or not state.fresh
        ):
            raise ValueError(
                "Generation blocked: every selected item must be source-verified, "
                f"carry a valid URL, and sit inside the {window}h window. "
                "Refresh the feed first."
            )
    return list(items)
