from pathlib import Path
import json
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text()
s=s.replace('        chapters = []','        metadata_path = master_dir / "editorial-metadata.json"\n        metadata = read(metadata_path) if metadata_path.is_file() else {}\n        chapter_titles = metadata.get("chapter_titles", chapter_titles)\n        chapters = []')
s=s.replace('if claim == "C10":','if claim == "C10" and path.name == "sachin-first-video":')
s=s.replace('''            "From a boy in Bombay to a World Cup winner: the journey of Sachin Tendulkar. "
            "Explore his early training, international debut, defining innings and legacy.\\n\\n"
            "Original CGI illustrations reconstruct the story; these are not archival recordings. "
            "Third-person narration by George via ElevenLabs. No athlete voice clone or invented dialogue.\\n\\n"''','''            metadata.get("description_lead", "From a boy in Bombay to a World Cup winner: the journey of Sachin Tendulkar.") + "\\n\\n"
            "Original CGI illustrations reconstruct the story; these are not archival recordings. "
            "Third-person narration by " + metadata.get("voice_name", "George") + " via ElevenLabs. No athlete voice clone or invented dialogue.\\n\\n"''')
s=s.replace('"title": "Sachin Tendulkar: The Boy Behind 100 International Centuries",','"title": metadata.get("title", "Sachin Tendulkar: The Boy Behind 100 International Centuries"),')
s=s.replace('"tags": ["Sachin Tendulkar", "cricket biography", "Origin to Ovation",\n                     "Sachin journey", "cricket history"],','"tags": metadata.get("tags", ["Sachin Tendulkar", "cricket biography", "Origin to Ovation",\n                     "Sachin journey", "cricket history"]),')
a=s.index('        if manifest.get("upload_policy") == "package_only_until_later_explicit_user_instruction":',s.index('    if agent == "echo":'));b=s.index('        reference =',a);gate=s[a:b];s=s[:a]+s[b:]
s=s.replace('        image_provider(path, {\n            "shot_id": "thumbnail"','        metadata_path = master_dir / "editorial-metadata.json"\n        metadata = read(metadata_path) if metadata_path.is_file() else {}\n        image_provider(path, {\n            "shot_id": "thumbnail"')
s=s.replace('"prompt": "Create a premium 16:9 YouTube biography thumbnail in photoreal cinematic CGI. "','"prompt": metadata.get("thumbnail_prompt", "Create a premium 16:9 YouTube biography thumbnail in photoreal cinematic CGI. "')
s=s.replace('"Large readable headline only: THE BOY BEHIND THE LEGEND."})','"Large readable headline only: THE BOY BEHIND THE LEGEND.")})\n'+gate)
p.write_text(s)
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21')
p=root/'research/source-register.json';r=json.loads(p.read_text());r.append({'claim_id':'C16','claim':'RCB retained IPL title in 2026; Kohli 75 not out in the final.','url':'https://www.iplt20.com/news/article/tata-ipl-2026-final-rcb-v-gt-match-report','checked_on':'2026-10-21'});p.write_text(json.dumps(r,indent=2))
