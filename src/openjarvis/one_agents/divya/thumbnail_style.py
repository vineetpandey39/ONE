"""Shloka By Shloka golden/blue thumbnail typography over original artwork.

Artwork must be created with subject left and title space right. Hindi is
typeset locally using the existing Chromium card renderer, never painted by AI.
"""
import base64
from html import escape
from pathlib import Path
from .core import digest, write
from .render import cards_module

STYLE = {
    'id': 'SHLOKA_GOLDEN_BLUE_V1',
    'composition': 'large devotional portrait left; short gold Hindi title right',
    'palette': {'blue': '#043c79', 'cyan': '#23c9f5', 'gold': '#ffd65c'},
    'rules': ['Original deity artwork for each topic', 'Two to four Hindi title words',
              'Correct Nirmala UI shaping; no AI lettering',
              'No invented view counts, scripture claims or duration badges',
              'Inspect at 320x180 before upload; retain title safe space',
              'Shorts use portrait crop and explicit PART number'],
}

def render_thumbnails(config, art_path, out, title_lines, subtitle, hooks):
    if not 1 <= len(title_lines) <= 2 or any(len(s) > 16 for s in title_lines):
        raise ValueError('Keep title to one or two short lines for mobile readability')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    art_path = Path(art_path)
    art = 'data:image/png;base64,' + base64.b64encode(art_path.read_bytes()).decode()
    title = '<br>'.join(escape(s) for s in title_lines)
    common = """*{box-sizing:border-box}html,body{margin:0;overflow:hidden;background:#043465}
    .title{font-family:'Nirmala UI';font-weight:700;color:#ffdc62;
    -webkit-text-stroke:2px #8d5515;paint-order:stroke fill;
    text-shadow:0 3px 0 #6d4212,0 6px 0 #061d37,0 9px 16px #0009}
    .brand{font:600 19px 'Segoe UI';letter-spacing:2px;color:#fff0bf}
    """
    html = f'''<html lang="hi"><meta charset="utf-8"><style>{common}
    html,body{{width:1280px;height:720px}}
    .art{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
    .shade{{position:absolute;inset:0;background:linear-gradient(90deg,transparent 40%,#032d5833 58%,#021d3d55)}}
    .copy{{position:absolute;left:625px;right:35px;top:132px;text-align:center}}
    .title{{font-size:155px;line-height:1.28;margin:0}}
    .sub{{font:700 32px 'Segoe UI';color:white;margin-top:18px;text-shadow:0 3px 9px #000}}
    .brand{{position:absolute;right:60px;top:43px}}
    </style><img class="art" src="{art}"><div class="shade"></div>
    <div class="brand">SHLOKA BY SHLOKA</div><div class="copy"><div class="title">{title}</div>
    <div class="sub">{escape(subtitle)}</div></div></html>'''
    files=[]
    with cards_module(config).CardRenderer() as r:
        p=r.page
        def capture(name, markup, w, h):
            p.set_viewport_size({'width':w,'height':h});p.set_content(markup);p.evaluate('document.fonts.ready')
            (out/(name+'.html')).write_text(markup,encoding='utf-8')
            target=out/(name+'.jpg');p.screenshot(path=str(target),type='jpeg',quality=94)
            files.append({'path':str(target),'sha256':digest(target),'width':w,'height':h})
        capture('thumbnail-golden-blue-v2',html,1280,720)
        # Browser-scaled preview verifies real Hindi glyphs at feed size.
        p.evaluate("document.body.style.transform='scale(.25)';document.body.style.transformOrigin='top left'")
        p.set_viewport_size({'width':320,'height':180})
        p.screenshot(path=str(out/'thumbnail-golden-blue-mobile.jpg'),type='jpeg',quality=94)
        for n,hook in enumerate(hooks,1):
            portrait=f'''<html lang="hi"><meta charset="utf-8"><style>{common}
            html,body{{width:1080px;height:1920px}}
            .art{{position:absolute;inset:0;background:url('{art}') 8% top/auto 1480px no-repeat}}
            .shade{{position:absolute;inset:0;background:linear-gradient(0deg,#03284e 0%,#03284ef5 20%,transparent 55%)}}
            .part{{position:absolute;left:90px;top:320px;padding:16px 35px;border:3px solid #ffdc62;border-radius:20px;background:linear-gradient(120deg,#7822b7,#bb216c);font:900 72px 'Segoe UI';color:#ffe475}}
            .copy{{position:absolute;left:45px;right:45px;top:1250px;text-align:center}}
            .title{{font-size:166px;line-height:1.4}}.hook{{font:600 48px 'Nirmala UI';color:white;line-height:1.6;margin-top:24px}}
            .brand{{font-size:26px;margin-top:50px}}
            </style><div class="art"></div><div class="shade"></div><div class="part">PART {n}</div>
            <div class="copy"><div class="title">{escape(' '.join(title_lines))}</div><div class="hook">{escape(hook)}</div>
            <div class="brand">SHLOKA BY SHLOKA</div></div></html>'''
            capture(f'short-{n}-thumbnail-golden-blue-v2',portrait,1080,1920)
    manifest={'style':STYLE,'art_path':str(art_path),'art_sha256':digest(art_path),'outputs':files,
              'visual_review':'PENDING','published':False,'additional_music_credits':0}
    write(out/'golden-blue-thumbnail-manifest.json',manifest)
    return manifest
