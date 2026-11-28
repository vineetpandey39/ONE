"""Receipt-backed science commissioning before any paid production work."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

from . import space_research
from .sanjeevani_science import ResearchUnavailable

def evidence_text(receipt):
    result = receipt.get("result", {})
    return json.dumps(result["structuredContent"]) if result.get("structuredContent") else "\n".join(
        item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")


_GENERIC_SCIENCE_WORDS = {
    'a', 'an', 'and', 'apod', 'astronomy', 'at', 'for', 'from', 'how', 'image',
    'in', 'is', 'nasa', 'new', 'november', 'of', 'on', 'science', 'space',
    'star', 'the', 'to', 'universe', 'what', 'why', 'with', '2026',
    'launch', 'launches', 'mission', 'missions', 'research', 'studies',
}
_MIN_VOLUME_SCORE = 20.0
_MIN_MONTHLY_SEARCH = 1000
_BROAD_DEMAND_WORDS = {
    'earth', 'jupiter', 'mars', 'moon', 'planet', 'planets', 'saturn',
    'solar', 'system',
}
_SINGLE_TERM_ENTITY_ANCHORS = {'asteroid', 'asteroids'}
_OFFICIAL_EVERGREEN = (
    {'topic': 'Why NASA studies asteroids and what they reveal about the solar system',
     'sources': ['https://science.nasa.gov/solar-system/asteroids/facts/']},
    {'topic': 'How the James Webb Space Telescope sees the early universe',
     'sources': ['https://science.nasa.gov/mission/webb/']},
    {'topic': 'What Mars rover discoveries reveal about the planet',
     'sources': ['https://science.nasa.gov/mars/']},
    {'topic': 'Why Jupiter has such extreme storms',
     'sources': ['https://science.nasa.gov/jupiter/facts/']},
    {'topic': 'How Artemis changes human exploration of the Moon',
     'sources': ['https://www.nasa.gov/artemis/']},
)


def _terms(value):
    return {word for word in re.findall(r'[a-z0-9]+', str(value).casefold())
            if word not in _GENERIC_SCIENCE_WORDS and len(word) > 2}


def _keyword_rows(receipt):
    """Normalize both vidIQ's structured widget and its markdown table."""
    widget = receipt.get('result', {}).get('_meta', {}).get('widgetData', {})
    rows = []
    for row in [widget.get('seedKeyword'), *(widget.get('relatedKeywords') or [])]:
        if isinstance(row, dict) and row.get('keyword'):
            rows.append({
                'keyword': str(row['keyword']),
                'volume': float(row.get('volume') or 0),
                'monthly': int(row.get('estimatedMonthlySearch') or 0),
            })
    if rows:
        return rows
    for line in evidence_text(receipt).splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) < 5:
            continue
        try:
            volume = float(cells[1])
            monthly = int(re.sub(r'[^0-9]', '', cells[4]) or 0)
        except ValueError:
            continue
        rows.append({'keyword': cells[0], 'volume': volume, 'monthly': monthly})
    return rows


def _measured(row):
    return row['volume'] >= _MIN_VOLUME_SCORE and row['monthly'] >= _MIN_MONTHLY_SEARCH


def _videos(receipt):
    result = receipt.get('result', {})
    structured = result.get('structuredContent') or {}
    if isinstance(structured.get('videos'), list):
        return structured['videos']
    for item in result.get('content') or []:
        if item.get('type') != 'text':
            continue
        try:
            value = json.loads(item.get('text') or '')
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get('videos'), list):
            return value['videos']
    return []


def demand_support(receipt, candidate, keyword):
    """Return candidate-bound current demand; broad NASA VPH is not transferable."""
    target = _terms(candidate.get('topic', '')) | _terms(keyword)
    support = []
    for video in _videos(receipt):
        if float(video.get('vph') or 0) <= 0:
            continue
        haystack = _terms(' '.join([str(video.get('videoTitle') or ''),
                                    ' '.join(str(tag) for tag in video.get('videoTags') or [])]))
        overlap = sorted(target & haystack)
        distinctive = set(overlap) - _BROAD_DEMAND_WORDS
        # A single celestial body is not an angle.  This previously allowed a
        # planet-size simulation tagged ``mars`` to validate a Curiosity
        # sampling episode, and a generic Moon video to validate Artemis.
        if ((len(overlap) >= 2 and distinctive)
                or bool(set(overlap) & _SINGLE_TERM_ENTITY_ANCHORS)):
            support.append({'video_id': video.get('videoId'), 'title': video.get('videoTitle'),
                            'vph': float(video.get('vph') or 0), 'matched_terms': overlap})
    return sorted(support, key=lambda row: row['vph'], reverse=True)


def grounded_keyword(selection, receipt):
    """Bind the commission to a measured, topic-specific search phrase."""
    rows = _keyword_rows(receipt)
    seed = selection['search_keyword']
    seed_row = next((row for row in rows if row['keyword'].casefold() == seed.casefold()), None)
    if seed_row and _measured(seed_row):
        return {**selection, 'keyword_validation': {
            'validated': True, 'mode': 'exact', 'volume_score': seed_row['volume'],
            'estimated_monthly_search': seed_row['monthly'],
            'note': 'Measured exact phrase; demand is not a guaranteed view count'}}
    terms = _terms(seed)
    matched = []
    for row in rows:
        overlap = terms & _terms(row['keyword'])
        distinctive = overlap - _BROAD_DEMAND_WORDS
        if (_measured(row) and ((len(overlap) >= 2 and distinctive)
                or bool(overlap & _SINGLE_TERM_ENTITY_ANCHORS))):
            matched.append((row, overlap))
    if matched:
        # A broad phrase such as "solar system" may have more volume, but it
        # must not displace the recognizable subject that earned the trend
        # match (for example "asteroids").
        chosen, overlap = max(matched, key=lambda item: (
            bool(item[1] & _SINGLE_TERM_ENTITY_ANCHORS),
            len(item[1]), item[0]['volume'], item[0]['monthly']))
        return {**selection, 'original_search_keyword': seed, 'search_keyword': chosen['keyword'],
                'keyword_validation': {'validated': True, 'mode': 'topic-bound-related',
                'estimated_monthly_search': chosen['monthly'], 'volume_score': chosen['volume'],
                'note': 'Measured related phrase bound to the same entity and angle'}}
    return {**selection, 'keyword_validation': {'validated': False,
            'note': 'No measured candidate-bound phrase met the minimum demand floor'}}


def candidates(recent, read=space_research.read_public):
    feed = ET.fromstring(read('https://www.nasa.gov/feed/'))
    rows = []
    for item in feed.findall('./channel/item'):
        title = ' '.join((item.findtext('title') or '').split())
        if title in recent or re.search(r'\b(names|appoints?|director|administrator|leadership|contract|awards?|hiring)\b', title, re.I):
            continue
        if not re.search(r'planet|moon|mars|saturn|astronaut|galax|black hole|telescope|space|asteroid|cosmi|star', title, re.I):
            continue
        url = space_research.validate_url((item.findtext('link') or '').strip())
        rows.append({'id':str(len(rows)), 'topic':title, 'sources':[url], 'published_at':item.findtext('pubDate')})
        if len(rows) == 16:
            break
    for evergreen in _OFFICIAL_EVERGREEN:
        if evergreen['topic'] in recent:
            continue
        rows.append({'id': str(len(rows)), **evergreen, 'published_at': None,
                     'candidate_type': 'official_evergreen_demand_fallback'})
    if not rows:
        raise ResearchUnavailable('No unused official science candidate; no paid production started')
    return rows


def select_topic(root, recent, *, client=None, synthesize=None, read=space_research.read_public,
                 channel_performance=None, reusable=None):
    """Commission exclusively through Sanjeevani; historical parsers above are read-only."""
    from .sanjeevani_science import select_topic as select
    return select(root, recent, reusable=reusable, synthesize=synthesize,
                  read=read, channel_performance=channel_performance)
