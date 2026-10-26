"""Offline word alignment with explicit uncertainty and bounded timing.

ASR token grouping is not speech verification. Estimated or zero-duration timing
requires review; callers must not publish it as accepted forced alignment.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass


_ONES = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(20)))
_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))


def token_key(word: str) -> str:
    value = ''.join(c for c in unicodedata.normalize('NFKD', word.casefold()) if not unicodedata.combining(c))
    parts = re.findall(r'[a-z0-9]+', value)
    if len(parts) == 1 and parts[0] in _ONES:
        return str(_ONES[parts[0]])
    if parts and parts[0] in _TENS and (len(parts) == 1 or len(parts) == 2 and parts[1] in _ONES and _ONES[parts[1]] < 10):
        return str(_TENS[parts[0]] + (_ONES[parts[1]] if len(parts) == 2 else 0))
    return ''.join(parts)


@dataclass(frozen=True)
class AlignmentResult:
    times: tuple[tuple[float, float], ...]
    methods: tuple[str, ...]
    review_reasons: tuple[str, ...]


class AlignmentReviewRequired(ValueError):
    pass


def align_words(expected: list[str], measured: list[dict], chapter_seconds: float) -> AlignmentResult:
    """Match up to four split/merged tokens, then bound unmatched runs together.

    Numeric equivalence is lexical (e.g. twenty-one seven / 217), not proof of
    pronunciation. Partitioned groups are marked; unmatched runs require review.
    """
    if not math.isfinite(chapter_seconds) or chapter_seconds <= 0:
        raise ValueError('Chapter duration must be finite and positive')
    if not expected or not measured:
        raise ValueError('Expected and measured words are required')
    ek, mk = [token_key(x) for x in expected], [token_key(x['word']) for x in measured]
    if not all(ek + mk):
        raise ValueError('Empty normalized token')
    spans = [(float(x['start']), float(x['end'])) for x in measured]
    previous_end = 0.0
    for start, end in spans:
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start <= end <= chapter_seconds or start < previous_end:
            raise ValueError('Measured timing must be finite, bounded and nonoverlapping')
        previous_end = end

    # Maximize matched canonical characters; prefer fewer skips and smaller groups.
    n, m = len(expected), len(measured)
    scores = {(0, 0): (0, 0, 0)}
    parents = {}

    def offer(i, j, a, b, gain, method):
        old = scores[i, j]
        score = tuple(x + y for x, y in zip(old, gain))
        target = i + a, j + b
        if target not in scores or score > scores[target]:
            scores[target] = score
            parents[target] = (i, j, method)

    for i in range(n + 1):
        for j in range(m + 1):
            if (i, j) not in scores:
                continue
            if i < n:
                offer(i, j, 1, 0, (0, -1, 0), 'unmatched')
            if j < m:
                offer(i, j, 0, 1, (0, -1, 0), 'extra')
            for a in range(1, min(4, n - i) + 1):
                left = ''.join(ek[i:i+a])
                for b in range(1, min(4, m - j) + 1):
                    if left == ''.join(mk[j:j+b]):
                        offer(i, j, a, b, (len(left), 0, -(a+b-2)), 'matched')

    groups = []
    i, j = n, m
    while i or j:
        pi, pj, method = parents[i, j]
        groups.append((pi, i, pj, j, method))
        i, j = pi, pj
    times = [None] * n
    methods = ['unmatched'] * n
    reasons = []
    for i, end_i, j, end_j, method in reversed(groups):
        if method == 'extra':
            reasons.append(f'Unmatched recognized token {j}: {measured[j]["word"]}')
        if method != 'matched':
            continue
        if any(a == b for a, b in spans[j:end_j]):
            reasons.append(f'Zero-duration measured token in group {i}:{end_i}')
        # Map canonical character offsets into the actual measured token spans.
        # This preserves pauses between separately measured words.
        def boundary(offset, end=False):
            cursor = 0
            for k in range(j, end_j):
                width = len(mk[k])
                if offset < cursor + width or end and offset == cursor + width or k == end_j - 1:
                    a, b = spans[k]
                    return a + (b-a) * (offset-cursor) / width
                cursor += width
            raise AssertionError('Unreachable boundary')
        offset = 0
        for k in range(i, end_i):
            times[k] = boundary(offset), boundary(offset + len(ek[k]), end=True)
            methods[k] = 'measured' if end_i-i == end_j-j == 1 else 'group_partition'
            offset += len(ek[k])

    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        stop = i + 1
        while stop < n and times[stop] is None:
            stop += 1
        left = times[i-1][1] if i else 0.0
        right = times[stop][0] if stop < n else chapter_seconds
        if right < left:
            raise ValueError('Unmatched run has reversed anchors')
        reasons.append(f'Estimated unmatched run {i}:{stop}; review required')
        total = sum(len(x) for x in ek[i:stop])
        cursor = left
        for k in range(i, stop):
            end = right if k == stop - 1 else cursor + (right-left)*len(ek[k])/total
            times[k], methods[k] = (cursor, end), 'estimated'
            cursor = end
        i = stop
    return AlignmentResult(tuple(times), tuple(methods), tuple(reasons))


def character_alignment(text: str, result: AlignmentResult, pacing_scale: float = 1.0) -> dict:
    """Convert validated raw-second word timing, applying pacing exactly once."""
    if result.review_reasons:
        raise AlignmentReviewRequired('; '.join(result.review_reasons))
    if not math.isfinite(pacing_scale) or pacing_scale <= 0:
        raise ValueError('Pacing scale must be finite and positive')
    words = list(re.finditer(r'\S+', text))
    if len(words) != len(result.times):
        raise ValueError('Word count differs from alignment')
    starts, ends = [0.0] * len(text), [0.0] * len(text)
    previous_end = 0.0
    previous_pos = 0
    for word, (start, end) in zip(words, result.times):
        if not math.isfinite(start) or not math.isfinite(end) or start < previous_end or end <= start:
            raise AlignmentReviewRequired('Nonpositive or overlapping word interval')
        start, end = start*pacing_scale, end*pacing_scale
        for pos in range(previous_pos, word.start()):
            starts[pos] = previous_end*pacing_scale
            ends[pos] = start
        width = word.end()-word.start()
        for pos in range(word.start(), word.end()):
            starts[pos] = start+(end-start)*(pos-word.start())/width
            ends[pos] = start+(end-start)*(pos-word.start()+1)/width
        previous_end, previous_pos = end/pacing_scale, word.end()
    for pos in range(previous_pos, len(text)):
        starts[pos] = ends[pos] = previous_end*pacing_scale
    return {'characters': list(text), 'character_start_times_seconds': starts, 'character_end_times_seconds': ends}
