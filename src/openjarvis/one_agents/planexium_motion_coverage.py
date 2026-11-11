"""Bounded additional licensed footage when measured clips underfill narration."""
import copy


MAX_SUPPLEMENTS = 4


def coverage(plan, voice, stock):
    rows = []
    for number, segment in enumerate(voice['segments'], 1):
        duration = float(segment['seconds'])
        choices = plan['scene_assets'][str(number)]
        share = duration / max(1, len(choices))
        beats = [min(20.0, max(5.0, share),
            float(stock[i]['seconds']) - float(stock[i].get('usable_in', 0)) - .1)
            for i in choices if stock[i].get('subject_evidence') is not False]
        seconds = sum(beat for beat in beats if beat >= 2)
        rows.append({'scene': number, 'seconds': duration, 'motion': seconds})
    total = sum(row['seconds'] for row in rows)
    maximum = float((plan.get('visual_policy') or {}).get('archive_shot_ratio_max', 1))
    # Keep the original density ceiling. No still allowances or source loops.
    target = total * (1 - maximum)
    return rows, target, sum(row['motion'] for row in rows)


def supplement(plan, voice, stock, *, original_count):
    rows, target, motion = coverage(plan, voice, stock)
    if motion >= target + .5 or target <= 0:
        return None
    if len(stock) - original_count >= MAX_SUPPLEMENTS:
        raise ValueError(f'Motion coverage still short after {MAX_SUPPLEMENTS} additional licensed clips: '
                         f'{motion:.1f}s available; {target:.1f}s required')
    maximum = float(plan['visual_policy']['archive_shot_ratio_max'])
    selected = max(rows, key=lambda row: (row['seconds'] * (1 - maximum) - row['motion'], row['scene']))
    scene = str(selected['scene'])
    # Reuse an authored brief in this scene, never invent a generic filler.
    source_index = plan['scene_assets'][scene][-1]
    result = copy.deepcopy(plan)
    result['stock_requests'].append(copy.deepcopy(plan['stock_requests'][source_index]))
    result['scene_assets'][scene].append(len(stock))
    result.setdefault('coverage_supplements', []).append({
        'scene': selected['scene'], 'source_request': source_index,
        'new_request': len(stock), 'motion_before_seconds': round(motion, 3),
        'required_motion_seconds': round(target, 3)})
    return result
