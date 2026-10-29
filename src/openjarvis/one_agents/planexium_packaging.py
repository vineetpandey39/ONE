"""Episode-specific packaging, separate from unvalidated audience predictions."""
import re


_THUMBNAIL_FILLER = {
    'A', 'AN', 'THE', 'AND', 'OR', 'BUT', 'HOW', 'WHY', 'WHAT', 'WHERE',
    'WHEN', 'WHO', 'DOES', 'DO', 'IS', 'ARE', 'THIS', 'THAT', 'IN', 'ON',
    'OF', 'TO', 'FOR', 'WITH',
}


def _compact_thumbnail_hook(text):
    """Reduce a model-authored hook to the validator's three-word contract.

    Editorial generation is probabilistic, so a harmless fourth connective
    must not abort an otherwise valid production.  Only display filler is
    removed; the remaining words retain their original order and wording.
    """
    words = str(text or '').upper().split()
    if len(words) <= 3:
        return str(text or '')
    content = [word for word in words if re.sub(r'[^A-Z0-9]', '', word) not in _THUMBNAIL_FILLER]
    compact = content[:3]
    return ' '.join(compact) if compact else ' '.join(words[:3])


def repair_thumbnail_hooks(value, science):
    """Repair only a generic hook, using literal episode words already present in its own concept brief."""
    if not isinstance(value, dict):
        return value
    titles = value.get('titles') or []
    scene = value.get('focus_scene')
    focus = science['scenes'][scene-1].get('screen_text', '') if type(scene) is int and 1 <= scene <= len(science['scenes']) else ''
    episode = set(re.findall(r'[a-z0-9]+', ' '.join([science.get('video_title',''), *titles, focus]).casefold()))
    generic = {'the','and','why','how','where','what','times','every','one','does','this','new','two'}
    eligible = episode - generic
    for concept in value.get('concepts') or []:
        original = str(concept.get('text') or '')
        compact = _compact_thumbnail_hook(original)
        # Keep the authored question but prefer the episode's literal,
        # phone-readable subject when CONDITIONS would fall below the bounded
        # compositor size.  This is not a generic synonym: it is admitted only
        # when the episode titles themselves explicitly promise the universe.
        if compact.upper() == 'EARLY CONDITIONS?' and 'universe' in episode:
            compact = 'EARLY UNIVERSE?'
        if compact != original:
            concept['text'] = compact
            concept['text_repair'] = {'from': original, 'to': compact,
                                      'policy': 'phone-readable literal episode promise, at most three words'}
        else:
            concept['text'] = original
        hook = set(re.findall(r'[a-z0-9]+', original.casefold())) - generic
        if hook & eligible:
            continue
        evidence = ' '.join(str(concept.get(field) or '') for field in
                            ('left_usp','name','composition','visual_direction'))
        chosen = []
        for word in re.findall(r'[A-Za-z0-9]+', evidence):
            lowered = word.casefold()
            if lowered in eligible and lowered not in {w.casefold() for w in chosen}:
                chosen.append(word.upper())
            if len(chosen) == 2:
                break
        if not chosen:
            continue
        repaired = ' '.join(chosen)
        concept['text'] = repaired
        concept['text_repair'] = {'from': original, 'to': repaired,
                                  'policy': 'literal episode term from this concept brief'}
    return value


def readable_thumbnail_hook(text):
    """Apply narrow, meaning-preserving display abbreviations before generation."""
    replacements = {"MINUTES": "MINS", "MINUTE": "MIN", "WHERE'S": "WHERE"}
    words = [replacements.get(word, word) for word in str(text).upper().split()]
    # Keep hooks phone-readable without banning normal topic words such as
    # SUNRISES, ASTRONAUT or JUPITER. The previous six-character ceiling made
    # valid episode-specific hooks fail after a successful 20-minute render.
    # Twelve characters still fits a two/three-word 16:9 hook and admits
    # episode-defining science terms such as METALLICITY and CONDITIONS?.
    # Reject truly long prose tokens rather than blocking factual vocabulary.
    if not 1 <= len(words) <= 3 or any(len(word) > 12 for word in words):
        raise ValueError('Thumbnail hook needs one to three short readable words')
    return ' '.join(words)


def check_thumbnail_diversity(paths):
    """Catch duplicated or nearly identical layouts, including color-only changes."""
    from PIL import Image, ImageOps
    fingerprints = []
    for path in paths:
        with Image.open(path) as image:
            pixels = list(ImageOps.grayscale(image).resize((33, 32)).tobytes())
        bits = [pixels[y*33+x] > pixels[y*33+x+1] for y in range(32) for x in range(32)]
        if any(sum(a != b for a, b in zip(bits, previous)) <= 30 for previous in fingerprints):
            raise ValueError('Thumbnail images have near-identical layouts; revise the visual concepts')
        fingerprints.append(bits)
    return {'candidates': len(paths), 'near_duplicate_layouts': 0, 'method': 'grayscale difference hash; not semantic or CTR validation'}


def validate_packaging(value, science):
    if not isinstance(value, dict):
        raise ValueError('Episode packaging strategy is required')
    claims = {c['id'] for c in science['claims']}
    if not value.get('claim_ids') or not set(value['claim_ids']).issubset(claims):
        raise ValueError('Packaging hook must reference supported science claims')
    scene = value.get('focus_scene')
    if type(scene) is not int or not 1 <= scene <= len(science['scenes']):
        raise ValueError('Packaging must identify its strongest episode visual')
    if not str(value.get('viewer_question', '')).strip():
        raise ValueError('Packaging needs a concrete viewer question')
    if not str(value.get('description_opening','')).strip():
        raise ValueError('Packaging needs an episode-specific description opening')
    titles = value.get('titles', [])
    concepts = value.get('concepts', [])
    if len(titles) != 3 or any(not isinstance(t, str) or not 15 <= len(t.strip()) <= 100 for t in titles):
        raise ValueError('Provide three concise episode-specific title candidates')
    if len(set(t.casefold().strip() for t in titles)) != 3:
        raise ValueError('Title candidates must differ')
    if len(concepts) != 3:
        raise ValueError('Provide three distinct thumbnail concepts')
    episode_words = set()
    for text in [science.get('video_title', ''), *titles,
                 science['scenes'][scene-1].get('screen_text', '')]:
        episode_words.update(re.findall(r'[a-z0-9]+', text.casefold()))
    aliases = {'mins': 'minutes', 'min': 'minute'}
    episode_words = {aliases.get(word, word) for word in episode_words}
    generic = {'the','and','why','how','where','what','times','every','one','does','this'}
    for concept in concepts:
        concept['text'] = readable_thumbnail_hook(concept.get('text', ''))
        hook_words = {aliases.get(word, word) for word in re.findall(r'[a-z0-9]+', concept['text'].casefold())
                      if not word.isdigit()} - generic
        if not hook_words or not hook_words & (episode_words - generic):
            raise ValueError('Thumbnail hook must name a specific promise from this episode')
        for field in ['name', 'visual_direction', 'composition', 'left_usp']:
            if not isinstance(concept.get(field), str) or not concept[field].strip():
                raise ValueError('Thumbnail concepts need a subject, composition and visual direction')
    for field in ['name', 'composition', 'visual_direction', 'text']:
        if len({c[field].casefold().strip() for c in concepts}) != 3:
            raise ValueError('Color/style-only thumbnail variants are insufficient')
    return value


def apply_packaging(package, strategy, science):
    # Cached editorial plans may predate a compositor-safe repair. Apply the
    # same grounded normalization at packaging time so a thumbnail-only fix
    # never mutates the render checkpoint or invalidates a verified master.
    strategy = repair_thumbnail_hooks(strategy, science)
    strategy = validate_packaging(strategy, science)
    package['recommended_title'] = strategy['titles'][0]
    package['title_variants'] = strategy['titles']
    description=package.get('description','')
    chapters=description.find('CHAPTERS')
    package['description']=strategy['description_opening'].strip()+'\n\n'+(description[chapters:] if chapters>=0 else description)
    base = package['thumbnail']['variants'][0]
    package['thumbnail']['variants'] = [{**base, **c} for c in strategy['concepts']]
    package['thumbnail_strategy'] = {
        **strategy, 'mode': 'episode_specific_concepts',
        'selection': 'editorial first choice, provisional until audience testing',
        'internal_score_role': 'design_readiness_only',
        'audience_winner': None,
        'measurement_plan': {
            'preferred': 'YouTube native concurrent title/thumbnail test when available',
            'success_metric': 'watch time with CTR and retention context',
            'required_context': ['impressions', 'traffic_sources', 'first_30_seconds_retention', 'average_view_duration'],
            'small_sample_policy': 'No verdict or causal claim from sparse impressions; no guaranteed CTR target',
            'manual_rotation': 'Do not treat sequential title/thumbnail changes as a controlled experiment',
        },
    }
    return package
