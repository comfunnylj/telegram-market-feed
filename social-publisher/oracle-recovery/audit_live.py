"""Read-only incident audit; tokens and private payloads never leave Oracle."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parent
inspect=json.loads(subprocess.check_output(['docker','inspect','social-publisher']))[0]
print(json.dumps({'runtime_user':inspect['Config'].get('User'),'running':inspect['State']['Running'],'image':inspect['Image'],'mounts':[{'source':m['Source'],'destination':m['Destination']} for m in inspect['Mounts']]},ensure_ascii=False))
for name in ['core.py','worker.py','recovery.py']:
 live=subprocess.check_output(['docker','exec','social-publisher','cat','/app/'+name]).decode()
 expected=(root/name).read_text()
 print('CODE_DIFF '+name+' live_sha256='+hashlib.sha256(live.encode()).hexdigest())
 print(''.join(difflib.unified_diff(expected.splitlines(True),live.splitlines(True),fromfile='github/'+name,tofile='oracle/'+name)))
code=r'''
import os,json,pathlib,sqlite3,traceback
import core
from recovery import identity,read,own_matches,MetaError
print('RUNTIME_ID',os.getuid(),os.getgid())
for name in ['','recovery-enabled-at','worker.lock','schedule.sqlite3','history','threads-token']:
 p=core.DATA/name
 try:
  s=p.stat(); print('FILE',str(p),s.st_uid,s.st_gid,oct(s.st_mode&0o777))
  if name in ['recovery-enabled-at','worker.lock','schedule.sqlite3','threads-token']:
   with p.open('rb') as f: f.read(1)
   print('READABLE',name)
 except Exception: traceback.print_exc()
try:
 db=sqlite3.connect(str(core.DATA/'schedule.sqlite3'))
 rows=db.execute("SELECT id,status,payload,result FROM jobs WHERE id='cb9b3125-4bed-580c-9220-b5b9430de973'").fetchall()
 token=core.saved_token();print('IDENTITY',identity(token))
 for jid,status,payload,raw in rows:
  p=json.loads(payload); r=json.loads(raw)
  print('TARGET',json.dumps({'id':jid,'status':status,'result_job_id':r.get('job_id'),'created_at':r.get('created_at'),'error':r.get('error'),'parts':[{'status':x.get('status'),'container_id':x.get('container_id'),'post_id':x.get('post_id'),'last_error':x.get('last_error'),'publish_attempt_at':x.get('publish_attempt_at')} for x in r['parts']]},ensure_ascii=False))
  history=core.DATA/'history'/(r['job_id']+'.json');s=history.stat(); print('HISTORY_MODE',s.st_uid,s.st_gid,oct(s.st_mode&0o777));json.loads(history.read_text());print('HISTORY_READ_OK')
  print('CONTAINER',read(token,'/18124296265935413?fields=id,status,error_message'))
  hits,complete=own_matches(token,r['parts'][0]['text'],None,r['created_at']);print('ROOT_MATCHES',json.dumps({'hits':hits,'complete':complete},ensure_ascii=False))
except MetaError as e: print('META_ERROR',e.status,json.dumps(e.detail,ensure_ascii=False))
except Exception: traceback.print_exc()
'''
r=subprocess.run(['docker','exec','-i','social-publisher','python','-'],input=code,text=True,capture_output=True)
print(r.stdout);print(r.stderr)
