"""Stable checkpoint identity and provider terminal semantics for CHANDAN."""
import hashlib,json,re

def continuation_key(agent,task):
 if agent!='chandan':return None
 try:p=json.loads(task)
 except (ValueError,TypeError):return None
 if p.get('brand')!='origin_to_ovation' or not p.get('continuation_of') or not p.get('checkpoint'):return None
 checkpoint=re.sub(r'[-_]v\d+$','',p['checkpoint'])
 return 'chandan-checkpoint:'+hashlib.sha256(json.dumps([p['brand'],p['mission_id'],p['continuation_of'],checkpoint]).encode()).hexdigest()

class ProviderTerminalError(RuntimeError):
 def __init__(self,job_id,status,reason):
  self.job_id,self.status,self.reason=job_id,status,reason
  super().__init__(f'LAO {job_id} {status}: {reason}; checkpoint preserved; no automatic duplicate')

def terminal_result(error):
 if error.status in {'Stopped','Cancelled'}:
  return {'_blocked':True,'status':'review_required','provider_job':error.job_id,'provider_status':error.status,'blocked_reason':error.reason or 'Provider stopped safely; editorial review required before explicit resume','upload_authorized':False}
 raise error
