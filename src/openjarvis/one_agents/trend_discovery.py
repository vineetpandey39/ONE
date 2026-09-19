"""Broad, free, keyless "what is trending in India right now" discovery for IRIS.

Why this exists (2026-09-19): IRIS's research was five fixed topical queries
(heritage / roads / festival / AI-photo-trend / fire-collapse) run through
Google News `when:2d` -- it could only find stories someone had already
thought to ask about, and its local 9B model then had to pick an incident out
of a raw evidence dump (it kept blending Satya Niketan + Kondhwa + an MCD
crackdown into one story). The owner's own manual process -- look at what is
actually trending, on the day -- is what found the Jaipur fire (216k views).

This module does that in code, with no API key and no paid model:

  1. POOL   ~35 free feeds fetched in parallel through Sanjeevani's own
            `_get` (bundled Windows trust store): publisher RSS (TOI, NDTV,
            Indian Express, Hindustan Times), Google News top/nation plus one
            `when:1d` feed per major city, Google Trends India (search terms
            WITH the headlines behind them), Reddit r/india-family top of day,
            X/Twitter trending hashtags (getdaytrends), Bing News.
  2. CLUSTER  headlines about the same story collapse into one cluster;
            the number of DISTINCT sources covering it is the virality proxy.
  3. FIT    a lexicon scores whether a story is a visual, place-based
            civic/heritage/urban story ImagineIndia can shoot (market, fort,
            bridge, collapse, redevelopment...) and penalises politics,
            crime, sport, celebrity, war.
  4. AGE    every top candidate's FIRST report is measured over a 14-day
            window. Sanjeevani's freshness filter judges the ARTICLE date, so
            an aftermath piece published today about a two-week-old event looks
            new (Satya Niketan, 2026-09-06, was picked twice). A candidate
            whose first report is older than `max_event_age_hours` is stale.

The local model is then only asked to WRITE UP one already-verified candidate,
not to discover or date anything.
"""
from __future__ import annotations

import email.utils
import html
import math
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

ATOM = "{http://www.w3.org/2005/Atom}"
HT = "{https://trends.google.com/trending/rss}"

CITIES = ["Delhi", "Mumbai", "Bengaluru", "Chennai", "Kolkata", "Hyderabad",
          "Ahmedabad", "Jaipur", "Lucknow", "Pune", "Surat", "Patna", "Bhopal",
          "Chandigarh", "Kochi", "Varanasi"]

PUBLISHER_FEEDS = {
    "TOI": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "TOI India": "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
    "NDTV": "https://feeds.feedburner.com/ndtvnews-top-stories",
    "Indian Express": "https://indianexpress.com/feed/",
    "Hindustan Times": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
    "Google News Top": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "Google News Nation": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
}
REDDIT = ["india", "IndiaSpeaks", "mumbai", "delhi", "bangalore", "hyderabad", "chennai", "kolkata"]

STOP = set("""about above after again against among also amid been before being between both
but can could did does done down during each from further had has have having her here him his
how into its just like more most much must not now off once only other our out over own same she
should some such than that the their them then there these they this those through under until
very was were what when where which while who whom why will with would you your says said say
new news latest today live update updates watch video after amid over cm pm govt police india indian
""".split())

POS_FIT = set("""market bazaar fort palace haveli monument heritage restoration restore temple
bridge flyover underpass road highway expressway station railway airport terminal metro tunnel
lake river ghat riverfront dam port stadium tower skydeck skyscraper building collapse collapsed
fire blaze flood flooding waterlogging encroachment demolition demolished redevelopment
redevelop revamp makeover smart-city smart city colony slum traffic jam pothole potholes garbage
landfill pollution smog crowd stampede crumbling cracks sinking landslide cyclone drainage sewer
walled lane chowk crossing skywalk waterfront beach promenade museum library""".split())
NEG_FIT = set("""election elections poll polls minister chief bjp congress trinamool aap sena
verdict supreme court sanctions tariff tariffs trump putin ukraine gaza israel iran pakistan
china ipl cricket match innings wicket football tennis olympic film actor actress box office
trailer bigg boss serial singer song concert murder murdered rape gangrape arrested arrest
suicide molest scam fraud stock stocks sensex nifty ipo shares rupee gold silver price
birthday wishes divorce wedding engaged dating netflix ott""".split())

_TOK = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}|\d{2,}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _clean_title(title: str) -> str:
    title = html.unescape(re.sub(r"<[^>]+>", "", title or "")).strip()
    return re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", title).strip() if " - " in title else title


def _tokens(title: str) -> set[str]:
    return {t.lower() for t in _TOK.findall(title) if t.lower() not in STOP and len(t) > 2}


def _headline(title: str, published: datetime | None, source: str, url: str, feed: str,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"title": _clean_title(title), "published": published, "source": source or feed,
            "url": url, "feed": feed, **(extra or {})}


def _parse_feed(raw: bytes, feed: str) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    out: list[dict[str, Any]] = []
    if feed.startswith("Google Trends"):
        for item in root.findall(".//item"):
            term = (item.findtext("title") or "").strip()
            traffic = (item.findtext(f"{HT}approx_traffic") or "").strip()
            stamp = _dt(item.findtext("pubDate") or "")
            for news in item.findall(f"{HT}news_item"):
                out.append(_headline(
                    news.findtext(f"{HT}news_item_title") or "", stamp,
                    news.findtext(f"{HT}news_item_source") or "",
                    news.findtext(f"{HT}news_item_url") or "", feed,
                    {"trend_term": term, "traffic": traffic}))
        return out
    for item in root.findall(".//item"):
        source = item.findtext("source") or ""
        out.append(_headline(item.findtext("title") or "", _dt(item.findtext("pubDate") or ""),
                             source, (item.findtext("link") or "").strip(), feed))
    for entry in root.findall(f".//{ATOM}entry"):
        link = entry.find(f"{ATOM}link")
        out.append(_headline(entry.findtext(f"{ATOM}title") or "",
                             _dt(entry.findtext(f"{ATOM}updated") or ""), "Reddit",
                             (link.get("href") if link is not None else "") or "", feed))
    return out


def _source_urls() -> dict[str, str]:
    urls = dict(PUBLISHER_FEEDS)
    urls["Google Trends"] = "https://trends.google.com/trending/rss?geo=IN"
    urls["Bing News"] = "https://www.bing.com/news/search?q=India+viral+today&format=rss&setlang=en-IN"
    for sub in REDDIT:
        urls[f"Reddit r/{sub}"] = f"https://www.reddit.com/r/{sub}/top/.rss?t=day"
    for city in CITIES:
        urls[f"GNews {city}"] = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{city} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    return urls


def _x_trends(lib: Any) -> list[str]:
    raw = lib._get("https://getdaytrends.com/india/", timeout=15, attempts=2).decode("utf-8", "ignore")
    tags = [html.unescape(m.group(1)) for m in re.finditer(r'<a href="/india/trend/[^"]+">([^<]+)</a>', raw)]
    return list(dict.fromkeys(tags))[:60]


def collect_pool(lib: Any, *, max_age_hours: float = 48.0) -> dict[str, Any]:
    urls = _source_urls()
    ok: list[str] = []
    failed: dict[str, str] = {}
    items: list[dict[str, Any]] = []

    def fetch(name_url: tuple[str, str]) -> tuple[str, list[dict[str, Any]] | None, str]:
        name, url = name_url
        try:
            return name, _parse_feed(lib._get(url, timeout=15, attempts=2), name), ""
        except Exception as exc:  # noqa: BLE001 - one dead feed must not sink the pool
            return name, None, f"{type(exc).__name__}: {exc}"[:120]

    with ThreadPoolExecutor(max_workers=10) as pool:
        for name, parsed, error in pool.map(fetch, urls.items()):
            if parsed is None:
                failed[name] = error
            else:
                ok.append(name)
                items.extend(parsed)
    try:
        x_tags = _x_trends(lib)
        ok.append("X trends (getdaytrends)")
    except Exception as exc:  # noqa: BLE001
        x_tags = []
        failed["X trends (getdaytrends)"] = f"{type(exc).__name__}: {exc}"[:120]

    cutoff = _now().timestamp() - max_age_hours * 3600
    fresh, seen = [], set()
    for it in items:
        if not it["title"] or len(it["title"]) < 15:
            continue
        if it["published"] is not None and it["published"].timestamp() < cutoff:
            continue
        key = re.sub(r"\W+", " ", it["title"].lower())[:90]
        if key in seen:
            continue
        seen.add(key)
        fresh.append(it)
    return {"items": fresh, "raw_count": len(items), "sources_ok": ok,
            "sources_failed": failed, "x_trends": x_tags}


def _cluster(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for it in sorted(items, key=lambda i: i["published"] or _now(), reverse=True):
        toks = _tokens(it["title"])
        if len(toks) < 3:
            continue
        placed = False
        for c in clusters:
            shared = toks & c["tokens"]
            if len(shared) >= 3 and len(shared) / max(1, min(len(toks), len(c["core"]))) >= 0.5:
                c["items"].append(it)
                c["tokens"] |= toks
                placed = True
                break
        if not placed:
            clusters.append({"items": [it], "tokens": set(toks), "core": set(toks)})
    return clusters


def _fit(text: str) -> tuple[int, int]:
    words = {w.lower().strip("'-") for w in _TOK.findall(text)}
    pos = len(words & POS_FIT) + sum(1 for p in POS_FIT if " " in p and p in text.lower())
    neg = len(words & NEG_FIT)
    return pos, neg


def _proper_nouns(title: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", title)
    out: list[str] = []
    for i, w in enumerate(words):
        if w[0].isupper() and w.lower() not in STOP and len(w) > 3 and (i > 0 or w.isupper() or len(words) < 4):
            out.append(w)
        elif w[0].isupper() and i == 0 and w.lower() not in STOP and len(w) > 4:
            out.append(w)
    return list(dict.fromkeys(out))[:3]


def first_report_age(lib: Any, headline: str, *, window_days: int = 14) -> dict[str, Any]:
    """Earliest headline over `window_days` matching the story's distinctive
    words -- the real first-report age, not today's aftermath article's age."""
    nouns = _proper_nouns(headline) or sorted(_tokens(headline), key=len, reverse=True)[:3]
    if not nouns:
        return {"verified": False, "age_hours": None, "earliest": None, "query": ""}
    query = " ".join(nouns)
    try:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{query} when:{window_days}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        root = ET.fromstring(lib._get(url, timeout=20, attempts=3))
        need = {n.lower() for n in nouns}
        dates = []
        for node in root.findall("./channel/item"):
            title = (node.findtext("title") or "").lower()
            if not all(n in title for n in need):
                continue
            d = _dt(node.findtext("pubDate") or "")
            if d:
                dates.append(d)
        if not dates:
            return {"verified": False, "age_hours": None, "earliest": None, "query": query}
        earliest = min(dates)
        return {"verified": True, "earliest": earliest.isoformat(), "query": query,
                "age_hours": round((_now() - earliest).total_seconds() / 3600, 1),
                "matches": len(dates)}
    except Exception as exc:  # noqa: BLE001
        return {"verified": False, "age_hours": None, "earliest": None, "query": query,
                "error": f"{type(exc).__name__}: {exc}"[:120]}


def discover(lib: Any, *, top_n: int = 10, max_event_age_hours: float = 72.0) -> dict[str, Any]:
    pool = collect_pool(lib)
    x_words = {w.lower() for tag in pool["x_trends"] for w in _TOK.findall(tag)}
    scored: list[dict[str, Any]] = []
    for c in _cluster(pool["items"]):
        items = c["items"]
        sources = sorted({(i["source"] or i["feed"]).strip() for i in items})
        text = " ".join(i["title"] for i in items)
        pos, neg = _fit(text)
        dated = [i["published"] for i in items if i["published"]]
        latest = max(dated) if dated else None
        age_latest = round((_now() - latest).total_seconds() / 3600, 1) if latest else None
        x_hit = len(c["core"] & x_words) >= 2 or any(i.get("trend_term") for i in items)
        fit = pos * 2 - neg * 3
        score = (3.0 * math.log(1 + len(sources)) + fit + (1.5 if x_hit else 0.0)
                 + (max(0.0, 48 - (age_latest if age_latest is not None else 48)) / 48 * 2))
        rep = max(items, key=lambda i: len(i["title"]))
        scored.append({"title": rep["title"], "headlines": [i["title"] for i in items[:5]],
                       "sources": sources[:8], "n_sources": len(sources), "n_items": len(items),
                       "latest_age_hours": age_latest, "fit": fit, "positive_hits": pos,
                       "negative_hits": neg, "trend_signal": x_hit, "score": round(score, 2),
                       "urls": [i["url"] for i in items[:3] if i["url"]]})
    shortlist = [s for s in sorted(scored, key=lambda s: s["score"], reverse=True)
                 if s["positive_hits"] >= 1 and s["negative_hits"] == 0][:top_n * 2]

    def verify(s: dict[str, Any]) -> dict[str, Any]:
        age = first_report_age(lib, s["title"])
        s["first_report"] = age
        s["verified"] = bool(age.get("verified"))
        s["stale"] = bool(s["verified"] and age["age_hours"] > max_event_age_hours)
        return s

    with ThreadPoolExecutor(max_workers=6) as pool_ex:
        verified = list(pool_ex.map(verify, shortlist))
    return {"generated_at": _now().isoformat(), "pool_raw": pool["raw_count"],
            "pool_fresh": len(pool["items"]), "clusters": len(scored),
            "sources_ok": pool["sources_ok"], "sources_failed": pool["sources_failed"],
            "x_trends_sample": pool["x_trends"][:15], "max_event_age_hours": max_event_age_hours,
            "candidates": verified[:top_n]}
