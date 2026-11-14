"""Read-only Oracle audit for four explicitly named partial jobs. Never publishes."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

NAME='social-publisher'
root=Path(__file__).resolve().parent
snapshot=json.loads(subprocess.check_output(['docker','inspect',NAME]))[0]
data=Path(next(m['Source'] for m in snapshot['Mounts'] if m['Destination']=='/data'))
secret=(data/'threads-token').read_text().strip()
def redacted(text):
 return text.replace(secret,'[REDACTED]') if secret else text
print('RUNTIME '+json.dumps({'user':snapshot['Config'].get('User'),'image':snapshot['Image'],'running':snapshot['State']['Running'],'started_at':snapshot['State']['StartedAt'],'restart_count':snapshot.get('RestartCount'),'mounts':[{'source':m['Source'],'destination':m['Destination'],'rw':m['RW']} for m in snapshot['Mounts']],'cmd':snapshot['Config'].get('Cmd'),'entrypoint':snapshot['Config'].get('Entrypoint')},ensure_ascii=False))
for name in ['core.py','worker.py','recovery.py','scheduler.py','bridge.py','registry.py']:
 raw=subprocess.check_output(['docker','exec',NAME,'cat','/app/'+name])
 if secret.encode() in raw:raise RuntimeError('Refuse source extraction containing credential')
 print('SOURCE '+name+' '+base64.b64encode(raw).decode())
for p in [data,data/'history',data/'worker.lock',data/'recovery-enabled-at',data/'schedule.sqlite3',data/'threads-token']:
 try:
  s=p.stat();print('MODE '+json.dumps({'path':str(p),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode&0o777)}))
 except Exception as e:print('MODE_ERROR '+str(type(e).__name__))
logs=subprocess.run(['docker','logs','--tail','400',NAME],capture_output=True,text=True)
print('LOGS '+json.dumps(redacted(logs.stdout+logs.stderr)[-32000:]))
code=r'''
import difflib,hashlib,json,os,sqlite3,uuid,traceback
import core,recovery
from recovery import read,identity,own_matches,MetaError
wanted=['2026-11-07','2026-11-12','2026-11-13','2026-11-14']
def output(label,obj):print(label+' '+json.dumps(obj,ensure_ascii=False))
token=core.saved_token();output('ACCOUNT',identity(token))
db=sqlite3.connect('file:/data/schedule.sqlite3?mode=ro',uri=True)
for day in wanted:
 key='morning:'+day;jid=str(uuid.uuid5(uuid.NAMESPACE_URL,'social-publisher/'+key))
 row=db.execute('SELECT id,due,status,payload,result,created FROM jobs WHERE id=?',(jid,)).fetchone()
 if not row:output('INCIDENT',{'key':key,'job_id':jid,'missing':True});continue
 _,due,status,raw,rr,created=row;p=json.loads(raw);r=json.loads(rr) if rr else {}
 history=core.DATA/'history'/(r.get('job_id',jid)+'.json')
 hr=json.loads(history.read_text()) if history.exists() else {}
 output('INCIDENT',{'key':key,'job_id':jid,'row_status':status,'due':due,'created':created,'requested_topic':p.get('topic'),'parts_count':len(p.get('parts',[])),'parts_sha256':hashlib.sha256(json.dumps(p.get('parts'),ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),'history_job_id':r.get('job_id'),'error':r.get('error'),'diagnosis':r.get('diagnosis'),'automatic_recovery_attempts':r.get('automatic_recovery_attempts'),'history_status':hr.get('status'),'recent_events':r.get('recovery_events',[])[-8:]})
 previous=None
 for i,a in enumerate(r.get('parts',[])[:6]):
  rec={'key':key,'job_id':jid,'index':i+1,'status':a.get('status'),'container_id':a.get('container_id'),'post_id':a.get('post_id'),'parent_recorded':a.get('reply_to_id'),'expected_parent':previous,'last_error':a.get('last_error'),'publish_attempt':a.get('publish_attempt'),'publish_attempt_at':a.get('publish_attempt_at'),'result':{k:(a.get('result')or{}).get(k) for k in ['id','permalink','topic_tag']}}
  if a.get('post_id'):
   try:
    post=read(token,'/'+a['post_id']+'?fields=id,text,permalink,username,topic_tag,timestamp,media_type,media_url')
    expected=a['text'];actual=post.get('text','')
    rec['meta']={k:post.get(k) for k in ['id','permalink','username','topic_tag','timestamp','media_type']};rec['meta_http_status']=200
    rec['text_compare']={'exact':actual==expected,'old_verifier':recovery.text_matches(actual,expected),'strip_ascii':actual.strip(' \t\r\n')==expected.strip(' \t\r\n'),'expected_len':len(expected),'actual_len':len(actual),'expected_prefix':repr(expected[:12]),'actual_prefix':repr(actual[:12]),'expected_suffix':repr(expected[-12:]),'actual_suffix':repr(actual[-12:]),'diff':[{'op':tag,'expected':repr(expected[i1:i2]),'actual':repr(actual[j1:j2])} for tag,i1,i2,j1,j2 in difflib.SequenceMatcher(None,expected,actual).get_opcodes() if tag!='equal'][:8]}
   except MetaError as e:rec['meta_error']={'http_status':e.status,**e.detail}
   except Exception as e:rec['meta_error']={'type':type(e).__name__,'message':str(e)[:500]}
  if a.get('container_id'):
   try:rec['container_state']=read(token,'/'+a['container_id']+'?fields=id,status,error_message')
   except MetaError as e:rec['container_error']={'http_status':e.status,**e.detail}
  if i<2:
   try:
    hits,complete=own_matches(token,a['text'],previous,r.get('created_at',created))
    rec['old_matcher_feed']={'complete':complete,'matching_ids':[h['id'] for h in hits]}
   except Exception as e:rec['feed_error']={'type':type(e).__name__,'message':str(e)[:500]}
  output('PART',rec)
  if a.get('post_id'):previous=a['post_id']
output('READ_ONLY_COMPLETE',{'uid':os.getuid(),'gid':os.getgid(),'version':recovery.VERSION})
'''
r=subprocess.run(['docker','exec','-i',NAME,'python','-'],input=code,capture_output=True,text=True)
print(redacted(r.stdout));print(redacted(r.stderr))
if r.returncode:raise SystemExit(r.returncode)
