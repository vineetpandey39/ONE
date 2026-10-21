import json,re
from pathlib import Path
root=Path('E:/ONE-SUITE/data/youtube/origin_to_ovation/missions/virat-kohli-2026-10-21');p=root/'production/master-v1/shot-plan.json';plan=json.loads(p.read_text())
updates={'P16':(19,'August2008 Sri Lanka'),'P17':(19,'August2008 Sri Lanka'),'P18':(21,'December2009 India'),'P19':(21,'December2009 India'),'P20':(22,'February2011 India'),'P33':(33,'January2022 neutral Test career illustration'),'P34':(30,'January2019 Australia'),'P35':(29,'August2018 England'),'P41':(31,'November2019 India'),'P42':(31,'June2020 neutral practice illustration'),'P43':(32,'August2021 neutral cricket illustration'),'P44':(33,'September2022 Dubai'),'P45':(33,'September2022 Dubai'),'P66':(36,'March2025 Dubai'),'P67':(36,'May2025 neutral Test career illustration'),'P68':(36,'May2025 neutral Test career illustration'),'P69':(36,'June2025 Ahmedabad'),'P70':(37,'May2026 neutral IPL illustration')}
for s in plan:
 if s['shot_id'] in updates:
  old=s['age'];age,era=updates[s['shot_id']];s['age']=age;s['era']=era;s['visual']=re.sub(r'age\s*'+str(old)+r'\b','age '+str(age),s['visual'])
  s['prompt']=re.sub(r'age\s*'+str(old)+r'\b','age '+str(age),s['prompt'])+' Exact scene time and age override any chapter-level wording: '+era+', age '+str(age)+'.'
 s['reference_conditioning_required']=True
 s['review_required']=['identity','anatomy','historical_accuracy','shot_intent']
p.write_text(json.dumps(plan,indent=2))
(root/'runtime/scene-age-corrections.json').write_text(json.dumps(updates,indent=2))
