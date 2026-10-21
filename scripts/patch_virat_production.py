from pathlib import Path
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py')
s=p.read_text()
s=s.replace('"url": "https://chatgpt.com/c/6ad78e84-5904-83ee-8711-fbc640db6c1b"','"url": browser["chat_url"]')
s=s.replace('f"Origin to Ovation - Sachin First Video - {shot[\'shot_id\']}"','f"Origin to Ovation - {manifest[\'subject\']} - {shot[\'shot_id\']}"')
s=s.replace('''        {"action": "navigate", "args": {"url": "https://chatgpt.com/"}},
        {"action": "click_first", "args": {
            "selectors": ["[data-testid='create-new-chat-button']", "a[href='/']"],
            "timeout_ms": 30000}},''','''        {"action": "navigate", "args": {"url": browser["chat_url"]}},''')
s=s.replace('f"Origin to Ovation - Sachin - {missing[0][\'shot_id\']}-{missing[-1][\'shot_id\']} single chat"','f"Origin to Ovation - {manifest[\'subject\']} - {missing[0][\'shot_id\']}-{missing[-1][\'shot_id\']} single chat"')
s=s.replace('timeout=7200)', 'timeout=21600)')
s=s.replace('    missing = [shot for shot in shots', '''    if not browser.get("chat_url", "").startswith("https://chatgpt.com/c/"):
        raise ValueError("Episode must have a recorded persistent conversation")
    for shot in shots:
        if not Path(shot["image"]).resolve().is_relative_to(path.resolve()):
            raise ValueError("Image escapes mission")
    missing = [shot for shot in shots''')
p.write_text(s)
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21')
source=root.parent/'sachin-first-video/production/master-v1/generate_narration.py'
s=source.read_text()
s=s.replace('episode=ContentCalendar(CHANNEL).reserve("sachin-first-video","sachin-tendulkar","Sachin Tendulkar")\n    assert episode["voice_name"]=="George"','manifest=json.loads((ROOT.parents[1]/"mission.json").read_text())\n    episode=ContentCalendar(CHANNEL).reserve(manifest["mission_id"],manifest["subject_id"],manifest["subject"])\n    assert episode["voice_name"]=="Bill"')
a=s.index('        elif chapter==1:'); b=s.index('        else:',a);s=s[:a]+s[b:]
s=s.replace('"speed":0.94','"speed":1.0').replace('george-narration-master.wav','bill-narration-master.wav')
(root/'production/master-v1/generate_narration.py').write_text(s)
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/chandan_render.py');s=p.read_text();s=s.replace("voice=root/'george-narration-master.wav'", "voices=list(root.glob('*-narration-master.wav'))\n    if len(voices)!=1: raise ValueError('Exactly one episode narration master required')\n    voice=voices[0]");p.write_text(s)
