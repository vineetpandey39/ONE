"""The verifier is the whole product, so it is tested without a network.

Every case here is one PostForge rejected in production: an undated page, a
recycled product page dressed as a launch, a search row whose headline the page
does not actually support, or a story that is real but older than the window.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openjarvis.postforge import feed

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)


def _page(
    *, date_meta: str = "", title: str = "Anthropic ships Claude memory", body: str = ""
) -> str:
    meta = (
        f'<meta property="article:published_time" content="{date_meta}">'
        if date_meta
        else ""
    )
    text = (
        body or "Anthropic shipped a memory feature for Claude today, the company said."
    )
    return (
        f"<html><head><title>{title}</title>{meta}</head>"
        f"<body><p>{text}</p></body></html>"
    )


def _candidate(**overrides):
    item = {
        "tag": "AI",
        "company": "Anthropic",
        "date": "2026-09-24T12:00:00Z",
        "source": "anthropic.com",
        "headline": "Anthropic ships Claude memory",
        "summary": "Anthropic shipped a memory feature for Claude today.",
        "url": "https://www.anthropic.com/news/claude-memory",
    }
    item.update(overrides)
    return feed.normalize_item(item, 0, "news", 24)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-24T10:00:00Z", datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)),
        (
            "2026-09-24T10:00:00+05:30",
            datetime(2026, 9, 24, 4, 30, tzinfo=timezone.utc),
        ),
        ("2026-09-24 10:00", datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)),
        ("2026-09-24", datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)),
        ("September 24, 2026", datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)),
        ("24 September 2026", datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)),
    ],
)
def test_parse_item_date_handles_the_shapes_pages_actually_use(value, expected):
    assert feed.parse_item_date(value) == expected


@pytest.mark.parametrize("value", ["", None, "yesterday", "2026-13-45"])
def test_parse_item_date_refuses_what_it_cannot_prove(value):
    assert feed.parse_item_date(value) is None


def test_freshness_counts_hours_not_days():
    # A 23-hour-old story is in; 25 hours is out. A day-granular check would
    # have kept both, which is the bug this window exists to avoid.
    assert feed.freshness("2026-09-23T19:00:00Z", now=NOW, hours=24).fresh
    assert not feed.freshness("2026-09-23T17:00:00Z", now=NOW, hours=24).fresh


def test_freshness_tolerates_publisher_clock_skew_but_not_fiction():
    assert feed.freshness("2026-09-24T22:00:00Z", now=NOW, hours=24).fresh
    assert not feed.freshness("2026-09-26T10:00:00Z", now=NOW, hours=24).fresh


def test_freshness_of_an_unparseable_date_is_never_fresh():
    state = feed.freshness("sometime last week", now=NOW)
    assert (state.fresh, state.age_hours, state.published_at) == (False, None, "")


# ---------------------------------------------------------------------------
# Page reading
# ---------------------------------------------------------------------------


def test_extract_evidence_date_reads_the_common_metadata_slots():
    for markup in (
        '<meta property="article:published_time" content="2026-09-24T10:00:00Z">',
        '<meta name="pubdate" content="2026-09-24">',
        '<script type="application/ld+json">'
        '{"datePublished":"2026-09-24T10:00:00Z"}</script>',
        '<time datetime="2026-09-24T10:00:00Z">today</time>',
        "<p>Published on September 24, 2026</p>",
    ):
        assert feed.extract_evidence_date(markup).startswith("2026-09-24")


def test_extract_evidence_date_returns_empty_when_the_page_proves_nothing():
    assert feed.extract_evidence_date("<html><body>No dates here.</body></html>") == ""


def test_strip_html_drops_scripts_and_styles():
    text = feed.strip_html(
        "<style>p{color:red}</style><script>var x=1</script><p>Real &amp; visible</p>"
    )
    assert text == "Real & visible"


def test_text_overlap_score_measures_distinctive_words_only():
    assert (
        feed.text_overlap_score(
            "Claude memory shipped", "anthropic shipped claude memory"
        )
        == 1.0
    )
    assert (
        feed.text_overlap_score(
            "Gemini robotics preview", "anthropic shipped claude memory"
        )
        == 0.0
    )
    # Stop words alone carry no evidence, so they score nothing rather than 1.0.
    assert feed.text_overlap_score("the and for", "anything at all") == 0.0


def test_looks_evergreen_only_flags_launch_language_on_a_product_path():
    assert feed.looks_evergreen(
        {"headline": "OpenAI launches ChatGPT", "url": "https://openai.com/chatgpt"}
    )
    assert not feed.looks_evergreen(
        {"headline": "OpenAI ChatGPT usage grows", "url": "https://openai.com/chatgpt"}
    )
    assert not feed.looks_evergreen(
        {"headline": "OpenAI launches Codex", "url": "https://openai.com/index/codex"}
    )


# ---------------------------------------------------------------------------
# Item shaping
# ---------------------------------------------------------------------------


def test_row_to_candidate_reads_sanjeevanis_own_row_shape():
    """The live shape, captured from a real refresh on 2026-09-25.

    Sanjeevani names the link ``source_url`` and the date ``published_at``, and
    sends no snippet. Reading only ``url`` silently dropped every row, which
    looked identical to "no AI news today" -- nothing was rejected, because
    nothing was ever a candidate.
    """
    row = {
        "source_type": "bing_web_rss",
        "source_url": "https://www.ndtv.com/latest",
        "title": "Latest News",
        "published_at": "Fri, 25 Sept 2026 11:14:00 GMT",
        "captured_at": "2026-09-25T15:44:12.998663+00:00",
        "age_hours": 4.5,
        "role": "web_discovery",
    }
    candidate = feed.row_to_candidate(row)

    assert candidate["url"] == "https://www.ndtv.com/latest"
    assert candidate["headline"] == "Latest News"
    assert candidate["date"] == "Fri, 25 Sept 2026 11:14:00 GMT"
    # The hostname beats source_type: "ndtv.com" is a source, "bing_web_rss"
    # is the pipe the row arrived through.
    assert candidate["source"] == "ndtv.com"


def test_rfc_2822_dates_keep_their_time_of_day():
    # Flooring this to midnight would add up to 24h of apparent age, which at a
    # 24-hour window silently ages live stories out of the feed.
    assert feed.parse_item_date("Fri, 25 Sept 2026 11:14:00 GMT") == datetime(
        2026, 9, 25, 11, 14, tzinfo=timezone.utc
    )
    assert feed.parse_item_date("25 Sept 2026 11:14:00 +05:30") == datetime(
        2026, 9, 25, 5, 44, tzinfo=timezone.utc
    )
    assert feed.parse_item_date("Sept 25, 2026 11:14 UTC") == datetime(
        2026, 9, 25, 11, 14, tzinfo=timezone.utc
    )


def test_a_date_without_a_clock_still_lands_at_midnight():
    assert feed.parse_item_date("September 24, 2026") == datetime(
        2026, 9, 24, tzinfo=timezone.utc
    )


def test_normalize_item_fills_source_from_the_host_when_the_row_omits_it():
    item = feed.normalize_item(
        {"url": "https://www.theverge.com/a", "headline": "x"}, 0, "news", 24
    )
    assert item["source"] == "theverge.com"
    assert item["verified"] is False


def test_normalize_item_ids_are_stable_for_the_same_source():
    row = {"url": "https://example.com/a", "headline": "x"}
    assert (
        feed.normalize_item(row, 0, "news", 24)["id"]
        == feed.normalize_item(row, 0, "news", 24)["id"]
    )


def test_unique_items_drops_the_same_story_found_by_two_engines():
    rows = [
        {"url": "https://example.com/a", "headline": "One"},
        {"url": "https://example.com/a", "headline": "One"},
        {"url": "https://example.com/b", "headline": "Two"},
    ]
    assert len(feed.unique_items(rows)) == 2


def test_diversify_caps_one_company_so_a_launch_day_cannot_fill_the_feed():
    items = [
        {"source": "openai.com", "headline": "OpenAI ships one"},
        {"source": "openai.com", "headline": "OpenAI ships two"},
        {"source": "openai.com", "headline": "OpenAI ships three"},
        {"source": "anthropic.com", "headline": "Anthropic ships one"},
    ]
    top = feed.diversify(items, limit=3, per_company=2)
    assert [item["source"] for item in top] == [
        "openai.com",
        "openai.com",
        "anthropic.com",
    ]


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verify_item_accepts_a_page_that_proves_the_claim():
    result = feed.verify_item(
        _candidate(),
        fetch=lambda url: _page(date_meta="2026-09-24T12:00:00Z"),
        now=NOW,
        hours=24,
    )
    assert result["verified"] is True
    assert result["date"] == "2026-09-24T12:00:00Z"
    assert result["verification"]["headlineScore"] >= 0.28


def test_verify_item_rejects_an_undated_page_on_every_pillar():
    result = feed.verify_item(
        _candidate(), fetch=lambda url: _page(), now=NOW, hours=24
    )
    assert result["verified"] is False
    assert "date" in result["verificationReason"]


def test_verify_item_rejects_a_real_story_that_is_simply_too_old():
    result = feed.verify_item(
        _candidate(),
        fetch=lambda url: _page(date_meta="2026-09-21T12:00:00Z"),
        now=NOW,
        hours=24,
    )
    assert result["verified"] is False
    assert "outside the 24h window" in result["verificationReason"]


def test_verify_item_rejects_a_page_that_does_not_support_the_headline():
    result = feed.verify_item(
        _candidate(headline="Meta releases Llama 5 weights"),
        fetch=lambda url: _page(date_meta="2026-09-24T12:00:00Z"),
        now=NOW,
        hours=24,
    )
    assert result["verified"] is False
    assert "does not support" in result["verificationReason"]


def test_verify_item_rejects_an_evergreen_product_page_sold_as_a_launch():
    item = _candidate(
        headline="OpenAI launches ChatGPT",
        summary="",
        url="https://openai.com/chatgpt",
    )
    result = feed.verify_item(
        item, fetch=lambda url: _page(title="ChatGPT"), now=NOW, hours=24
    )
    assert result["verified"] is False
    assert "product page" in result["verificationReason"]


def test_verify_item_turns_a_failed_fetch_into_a_rejection_not_a_crash():
    def explode(url):
        raise TimeoutError("read timed out")

    result = feed.verify_item(_candidate(), fetch=explode, now=NOW, hours=24)
    assert result["verified"] is False
    assert "TimeoutError" in result["verificationReason"]


def test_verify_item_rejects_a_row_without_a_usable_url():
    result = feed.verify_item(
        _candidate(url="not-a-url"), fetch=lambda url: "", now=NOW, hours=24
    )
    assert result["verified"] is False


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class _Library:
    """Stands in for Sanjeevani: the two calls feed.py actually makes."""

    def __init__(self, rows, mode="searxng"):
        self.rows = rows
        self.mode = mode
        self.queries: list[str] = []

    def searxng(self, queries, time_range=""):
        self.queries.extend(queries)
        assert time_range == "day"
        return list(self.rows), self.mode


def test_refresh_keeps_only_what_its_own_page_proves(monkeypatch):
    feed.clear_cache()
    library = _Library(
        [
            {
                "url": "https://www.anthropic.com/news/claude-memory",
                "title": "Anthropic ships Claude memory",
                "content": "Anthropic shipped a memory feature for Claude today.",
                "publishedDate": "2026-09-24T12:00:00Z",
            },
            {
                "url": "https://example.com/old-story",
                "title": "Anthropic ships Claude memory",
                "content": "Anthropic shipped a memory feature for Claude today.",
                "publishedDate": "2026-09-24T12:00:00Z",
            },
        ]
    )

    def fetch(url):
        if "anthropic.com" in url:
            return _page(date_meta="2026-09-24T12:00:00Z")
        return _page()  # undated: the source cannot prove its own claim

    payload = feed.refresh("news", library=library, fetch=fetch, now=NOW, force=True)

    assert [item["url"] for item in payload["items"]] == [
        "https://www.anthropic.com/news/claude-memory"
    ]
    assert payload["rejected"] == 1
    assert payload["freshnessHours"] == 24
    assert payload["researcher"] == "sanjeevani"
    assert library.queries, "refresh must actually search"


def test_refresh_records_which_discovery_path_answered():
    """A live run with SearXNG uninstalled still returned rows, tagged
    bing_web_rss. Without this the operator cannot tell a healthy fallback from
    a healthy SearXNG -- both just look like a working feed."""
    feed.clear_cache()
    library = _Library([], mode="bing_web_rss")
    payload = feed.refresh(
        "news", library=library, fetch=lambda url: "", now=NOW, force=True
    )
    assert payload["discovery"] == "bing_web_rss"


def test_search_rows_reports_an_unnamed_mode_rather_than_none():
    library = _Library([], mode=None)
    rows, mode = feed.search_rows(["q"], library=library)
    assert (rows, mode) == ([], "unknown")


def test_refresh_skips_the_fetch_for_a_row_already_far_outside_the_window():
    feed.clear_cache()
    library = _Library(
        [
            {
                "url": "https://example.com/ancient",
                "title": "Anthropic ships Claude memory",
                "content": "Old news.",
                "publishedDate": "2026-08-01T12:00:00Z",
            }
        ]
    )
    fetched: list[str] = []

    def fetch(url):
        fetched.append(url)
        return _page(date_meta="2026-09-24T12:00:00Z")

    payload = feed.refresh("news", library=library, fetch=fetch, now=NOW, force=True)
    assert payload["items"] == []
    assert fetched == []


def test_refresh_serves_the_cache_until_it_expires():
    feed.clear_cache()
    library = _Library([])
    first = feed.refresh(
        "tool", library=library, fetch=lambda url: "", now=NOW, force=True
    )
    second = feed.refresh("tool", library=library, fetch=lambda url: "", now=NOW)
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(library.queries) == len(first["queries"])


def test_refresh_without_sanjeevani_refuses_instead_of_buying_a_fallback():
    feed.clear_cache()
    with pytest.raises(feed.SanjeevaniUnavailable):
        feed.refresh("news", library=None, fetch=lambda url: "", now=NOW, force=True)


def test_refresh_rejects_an_unknown_pillar():
    with pytest.raises(KeyError):
        feed.refresh("crypto", force=True)


def test_every_pillar_has_queries_and_a_label():
    for pillar in feed.PILLAR_IDS:
        assert feed.select_queries(pillar, today=NOW.isoformat())
        assert feed.pillar_by_id(pillar)["full"]


def test_select_queries_rotates_with_the_day():
    monday = feed.select_queries("news", today="2026-09-24T00:00:00Z")
    tuesday = feed.select_queries("news", today="2026-09-25T00:00:00Z")
    assert monday != tuesday


# ---------------------------------------------------------------------------
# The generation gate
# ---------------------------------------------------------------------------


def test_require_verified_blocks_an_empty_selection():
    with pytest.raises(ValueError):
        feed.require_verified([])


def test_require_verified_blocks_an_item_that_went_stale_after_the_refresh():
    item = {
        "verified": True,
        "url": "https://example.com/a",
        "publishedAt": "2026-09-20T10:00:00Z",
    }
    with pytest.raises(ValueError):
        feed.require_verified([item], now=NOW)


def test_require_verified_passes_a_still_fresh_verified_item():
    item = {
        "verified": True,
        "url": "https://example.com/a",
        "publishedAt": "2026-09-24T10:00:00Z",
    }
    assert feed.require_verified([item], now=NOW) == [item]
