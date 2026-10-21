"""Bounded reference-conditioned correction; fails closed for visual review."""
def run(path,job):
 from pathlib import Path
 from openjarvis.one_agents.origin_to_ovation import read,write,image_provider,digest
 from openjarvis.one_agents import stages
 m=read(path/'mission.json');plan=read(path/'production/master-v1/shot-plan.json')
 outputs=[]
 for shotid in ['P12','P14','P15']:
  shot=next(s for s in plan if s['shot_id']==shotid)
  output=path/'production/identity-corrections-v5'/f'{shotid}-age19-v5.png'
  output.parent.mkdir(parents=True,exist_ok=True)
  stages.set_stage('chandan',stages.EXECUTING,f'Virat identity repair: {shotid}, age19; reference conditioned')
  write(path/'runtime/active.json',{'agent':'chandan','job_id':job['id'],'status':'identity_correction','shot_id':shotid,'upload_authorized':False})
  prompt=('IDENTITY CORRECTION: The last generated age19 scenes were rejected as a generic different person. '
   'Use the attached canonical v2 sheet AGE18 face panel as actual visual identity conditioning for this age19 2008 scene. '
   'Same facial proportions, eye shape/spacing, nose bridge and tip, jaw, hairline, skin tone, fuller youthful cheeks. '
   'Clean shaven or very faint period stubble only. No adult shaped beard, no generic model substitution. '
   'Do not copy any rejected scene face. Show ONLY one 16:9 finished cinematic photoreal CGI frame, not a reference sheet. '
   'Age19 in Malaysia during the2008 junior cricket tournament. Generic era-correct cricket whites. '
   'No invented logos/dialogue. Anatomically sound arms/hands, proper thumbs, five fingers; avoid complex grip. '
   +shot['visual'])
  receipt=image_provider(path,{**shot,'shot_id':shotid+'-identity-v5','image':str(output),'reference':m['character_reference'],'prompt':prompt})
  outputs.append({'shot_id':shotid,'path':str(output),'sha256':digest(output),'reference_sha256':digest(Path(m['character_reference'])),'editorial_status':'pending'})
 write(path/'runtime/identity-corrections-v5.json',{'outputs':outputs,'status':'awaiting_visual_gate','auto_accept':False})
 return {'_blocked':True,'status':'awaiting_identity_review','blocked_reason':'First three reference-conditioned corrections require visual identity, anatomy and period QA before remaining images can run.','outputs':outputs,'upload_authorized':False}

