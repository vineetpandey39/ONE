"""Small narration-bound explanatory animations over illustrative footage."""
import re
from pathlib import Path


def overlay_kind(narration):
    words = re.sub(r'[^a-z ]', ' ', narration.casefold())
    if all(term in words for term in ['boost', 'entry', 'landing']):
        return 'return_burns'
    if all(term in words for term in ['first', 'second', 'stage', 'separat']):
        return 'stage_separation'
    return None


def explanatory_filter(directory, ordinal, narration, seconds):
    """Reveal factual labels in order; explicitly schematic, no invented trajectory."""
    kind = overlay_kind(narration)
    if not kind or seconds < 4:
        return '', None
    labels = ['BOOST-BACK', 'RE-ENTRY', 'LANDING'] if kind == 'return_burns' else ['STAGE SEPARATION', 'FIRST STAGE', 'SECOND STAGE']
    font = 'C\\:/Windows/Fonts/arialbd.ttf'
    result = ",drawbox=x=65:y=785:w=1790:h=240:color=black@0.7:t=fill"
    for i, label in enumerate(labels,1):
        path = Path(directory) / f'science-{ordinal}-{i}.txt'
        path.write_text(label, encoding='utf-8')
        escaped = path.as_posix().replace(':', '\\:')
        at = .3 + (i - 1) * (seconds - 1) / 3
        x = 105 + (i - 1) * 590
        result += f",drawbox=x={x}:y=875:w=535:h=95:color=cyan@0.65:t=3:enable='gte(t,{at:.3f})'"
        result += f",drawtext=fontfile='{font}':textfile='{escaped}':fontsize=31:fontcolor=white:x={x+22}:y=905:alpha='min(1,max(0,(t-{at:.3f})/0.3))'"
    return result, kind
