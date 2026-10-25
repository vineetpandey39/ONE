"""Finite visual coverage for daily science explainers; never extend clips by replay."""
import hashlib
import json
import math
from pathlib import Path


def build_scene_shots(root, science, voice, assets, original, media, editorial, *, image_search=None):
    from openjarvis.one_agents.space_research import (article_images, nasa_image,
        nasa_subject_matches, nasa_image_is_visible)
    image_search = image_search or nasa_image
    root = Path(root)
    used = set()
    result = {}
    primary_cursor = 0.0
    archive_seconds = 0.0
    primary_is_video = Path(original['path']).suffix.lower() not in {'.jpg', '.jpeg', '.png'}
    for number, (scene, segment) in enumerate(zip(science['scenes'], voice['segments'], strict=True), 1):
        rows = []
        remaining = float(segment['seconds'])
        # Reserve the primary source for scenes explicitly describing it.
        if scene.get('visual_kind') == 'obs' and primary_is_video:
            seconds = min(8.0, remaining / 3, float(original['seconds']) - primary_cursor)
            if seconds >= 2:
                rows.append({'asset': original, 'kind': 'primary', 'offset': primary_cursor, 'seconds': seconds})
                primary_cursor += seconds
                remaining -= seconds
        elif not primary_is_video and original['sha256'] not in used:
            owned = next((a for a in media.get(str(number), {}).get('assets', [])
                          if a.get('sha256') == original['sha256']), None)
            if owned and nasa_subject_matches(scene.get('media_query', ''), owned.get('metadata', {})):
                rows.append({'asset': original, 'kind': 'primary'})
                used.add(original['sha256'])
        choices = editorial['scene_assets'][str(number)]
        # Budget motion from the scene's original remainder.  Recomputing the
        # share after every clip progressively under-filled later clips and
        # forced long narration scenes to demand three or more archive stills
        # even when two or three unique licensed clips were available.
        motion_share = remaining / max(1, len(choices))
        for index in choices:
            asset = assets['stock'][index]
            if asset['sha256'] in used:
                continue
            seconds = min(20.0, max(5.0, motion_share),
                          float(asset['seconds']) - asset.get('usable_in', 0) - .1)
            if seconds < 2:
                continue
            rows.append({'asset': asset, 'kind': 'envato', 'seconds': seconds})
            remaining -= seconds
            used.add(asset['sha256'])
        pictures = [r for r in rows if 'seconds' not in r]
        # A still receives a restrained pan/zoom in the cinematic assembler.
        # Fifteen seconds is the upper editorial beat; the previous nine-second
        # divisor could require more NASA images than the three authored
        # archive queries can supply when valid licensed clips are short.
        # The assembler adds a restrained pan/zoom, so this remains a moving
        # visual beat rather than a static card.
        needed = max(1, math.ceil(remaining / 15))
        # Prefer direct imagery from the commissioned official article before
        # searching an archive. These are original source figures, not captures.
        for asset in media.get(str(number),{}).get('assets',[]):
            if len(pictures)>=needed:break
            if (asset.get('caption') is None or asset['sha256'] in used
                    or not (asset.get('title','').strip() or asset.get('caption','').strip())):continue
            if not nasa_image_is_visible(asset['path']):continue
            if hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest()!=asset['sha256']:
                raise ValueError('Official article image changed')
            row={'asset':{**asset,'seconds':3600},'kind':'primary'}
            rows.append(row);pictures.append(row);used.add(asset['sha256'])
        queries = editorial.get('scene_visuals', {}).get(str(number), [])
        for index, query in enumerate(queries, 1):
            if len(pictures) >= needed:
                break
            directory = root / f'sources/editorial-{number}-{index}'
            receipt = directory / 'source-receipt.json'
            asset = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
            if (not asset or not Path(asset['path']).is_file() or (asset.get('provider')=='NASA' and
                    (not nasa_subject_matches(query,asset.get('metadata',{})) or not nasa_image_is_visible(asset['path'])))
                    or asset.get('editorial_query') != query or asset['sha256'] in used
                    or not Path(asset['path']).is_file()
                    or hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest() != asset['sha256']):
                try:
                    asset = image_search(query, directory, exclude_sha256=used)
                except ValueError:
                    continue
                asset['editorial_query'] = query
                receipt.write_text(json.dumps(asset, indent=2), encoding='utf-8')
            if asset['sha256'] in used:
                continue
            asset = {**asset, 'seconds': 3600,
                     'credit': asset.get('credit', 'NASA') + ' / archival context'}
            row = {'asset': asset, 'kind': 'archive'}
            rows.append(row)
            pictures.append(row)
            used.add(asset['sha256'])
        # Some newly published NASA articles have exact mission figures that
        # are not yet discoverable through the NASA Image Library search.
        # Use those verified article figures before failing coverage.  This is
        # not a generic web-image fallback: article_images enforces the source
        # allow-list and stores a source receipt beside every downloaded file.
        if len(pictures) < needed:
            commission = json.loads((root / 'commission.json').read_text(encoding='utf-8'))
            source_urls = list(commission.get('sources') or [])
            figures = []
            for source_url in source_urls[:2]:
                try:
                    figures.extend(article_images(source_url, root / 'sources/article-images'))
                except (OSError, ValueError):
                    continue
            for asset in figures:
                if len(pictures) >= needed:
                    break
                metadata = {'title': asset.get('title', ''),
                            'description': asset.get('caption', '')}
                matches = (nasa_subject_matches(scene.get('title', ''), metadata)
                           or nasa_subject_matches(scene.get('media_query', ''), metadata))
                if (asset['sha256'] in used or not matches
                        or not nasa_image_is_visible(asset['path'])):
                    continue
                row = {'asset': {**asset, 'seconds': 3600}, 'kind': 'primary'}
                rows.append(row)
                pictures.append(row)
                used.add(asset['sha256'])
        # A figure taken directly from the commissioned article may hold for
        # up to twenty seconds with the restrained pan/zoom. Archive-search
        # stills retain the tighter fifteen-second density rule.
        source_figure_hold_ok = (pictures and remaining / len(pictures) <= 20
                                 and any(row['kind'] == 'primary' for row in pictures))
        if len(pictures) < needed and not source_figure_hold_ok:
            raise ValueError(f'Scene {number} lacks distinct relevant imagery; shorten narration or revise its visual brief')
        if pictures:
            archive_seconds += (remaining / len(pictures)) * sum(
                row['kind'] == 'archive' for row in pictures)
        result[str(number)] = rows
    if not any(t['kind'] == 'envato' for rows in result.values() for t in rows):
        raise ValueError('Unique visual plan has no licensed footage')
    flat=[t for rows in result.values() for t in rows]
    motion=sum(t.get('seconds',0) for t in flat if t['kind']=='envato')
    archive=sum(1 for t in flat if t['kind']=='archive')
    if len([t for t in flat if t['kind']=='envato']) < min(16,len(assets['stock'])):
        raise ValueError('Visual-density gate: too few distinct licensed motion clips')
    policy=editorial.get('visual_policy')
    total_seconds = sum(float(segment['seconds']) for segment in voice['segments'])
    archive_time_ratio = archive_seconds / total_seconds if total_seconds else 1.0
    if policy and archive_time_ratio > float(policy.get('archive_shot_ratio_max',0.40)):
        raise ValueError('Visual-density gate: archival stills would dominate the cut')
    (root / 'edit/visual-mix.json').write_text(json.dumps({'licensed_motion_clips':sum(t['kind']=='envato' for t in flat),
        'licensed_motion_seconds':round(motion,2),'archive_stills':archive,
        'archive_screen_seconds':round(archive_seconds,2),'archive_screen_fraction':round(archive_time_ratio,4),
        'total_assets':len(flat)},indent=2),encoding='utf-8')
    (root / 'edit/resolved-editorial-plan.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def apply_director_copy(shots, motion_copy):
    """Two restrained narration-bound beats per scene; preserve evidence footage."""
    for scene_id, phrases in motion_copy.items():
        eligible = [s for s in shots if s['scene'] == int(scene_id) and s['kind'] != 'primary']
        if not eligible or not phrases:
            continue
        positions = sorted({0, len(eligible) // 2})
        for i, position in enumerate(positions):
            phrase = phrases[min(len(phrases) - 1, i * len(phrases) // len(positions))]
            eligible[position]['callout'] = phrase
            eligible[position]['director_authored'] = True
