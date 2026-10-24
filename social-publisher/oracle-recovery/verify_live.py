"""Read-only post-deployment verification of this exact original 8-part job."""
import json
import subprocess
code=r'''
import hashlib,json,os,sqlite3
import core,recovery
from recovery import Publisher,identity,own_matches
jid='cb9b3125-4bed-580c-9220-b5b9430de973'
db=sqlite3.connect(str(core.DATA/'schedule.sqlite3'))
row=db.execute('SELECT status,payload,result FROM jobs WHERE id=?',(jid,)).fetchone()
status,payload,raw=row;p=json.loads(payload);r=json.loads(raw)
token=core.saved_token();identity(token)
assert status=='published' and r['status']=='published'
assert len(r['parts'])==8 and [x['text'] for x in r['parts']]==p['parts']
assert (p.get('automation')or{}).get('dedup_key')=='morning:2026-10-24'
marker=core.DATA/'recovery-enabled-at';marker.read_text();s=marker.stat()
assert (s.st_uid,s.st_gid)==(os.getuid(),os.getgid())
previous=None;parts=[];pub=Publisher();pub.root_image_count=len(core.image_list(p.get('image'),p.get('images')))
for n,active in enumerate(r['parts']):
 post=pub.verify_post(token,active,'미국주식' if n==0 else None)
 hits,complete=own_matches(token,active['text'],previous,r['created_at'])
 assert complete and len(hits)==1 and hits[0]['id']==active['post_id'], 'Duplicate or parent chain mismatch'
 parts.append({'index':n+1,'id':post['id'],'permalink':post['permalink'],'topic_tag':post.get('topic_tag'),'parent_id':previous})
 previous=active['post_id']
print(json.dumps({'status':'verified','key':'morning:2026-10-24','job_id':jid,'version':recovery.VERSION,'uid':os.getuid(),'gid':os.getgid(),'marker_mode':oct(s.st_mode&0o777),'parts':parts,'code_sha256':{n:hashlib.sha256(open('/app/'+n,'rb').read()).hexdigest() for n in ['worker.py','recovery.py']}},ensure_ascii=False))
'''
r=subprocess.run(['docker','exec','-i','social-publisher','python','-'],input=code,text=True,capture_output=True)
if r.returncode:
 print(r.stdout);print(r.stderr)
if r.returncode: raise SystemExit(r.returncode)
logs=subprocess.run(['docker','logs','--since','90s','social-publisher'],capture_output=True,text=True)
combined=logs.stdout+logs.stderr
health={'recent_permission_error':'PermissionError' in combined,'recent_recovery_error':'recovery check error' in combined,'worker_ready':'worker ready' in combined}
report=json.loads(r.stdout.strip());report['health']=health
print(json.dumps(report,ensure_ascii=False))
if 'PermissionError' in combined or 'recovery check error' in combined: raise SystemExit(1)
