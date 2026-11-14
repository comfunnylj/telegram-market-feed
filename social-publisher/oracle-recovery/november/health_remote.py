"""Verify live module hashes, worker lock, API events, receipts and all 24 URLs."""
import json
from pathlib import Path
import subprocess
import time

root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text())
name='social-publisher'
def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()
snapshot=json.loads(docker('inspect',name))[0]
assert snapshot['State']['Running']
code="import hashlib,json,pathlib,recovery,os;print(json.dumps({'version':recovery.VERSION,'uid':os.getuid(),'gid':os.getgid(),'hashes':{n:hashlib.sha256(pathlib.Path('/app/'+n).read_bytes()).hexdigest() for n in ['worker.py','recovery.py','durable.py']}}))"
runtime=json.loads(docker('exec',name,'python','-c',code))
assert runtime['version']==manifest['version'] and runtime['hashes']==manifest['deploy']
lock_code="""import fcntl,core
f=(core.DATA/'worker.lock').open('a');held=False
try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:held=True
assert held,'Live worker does not hold its exclusive lock'
print('exclusive worker lock held')
"""
docker('exec',name,'python','-c',lock_code)
# Observe at least one ordinary automatic recovery interval after startup.
time.sleep(35)
verified=docker('exec',name,'python','/app/maintenance/resume_incidents.py','--plan','/app/maintenance/plan.json','--verify-only')
print(verified,flush=True)
logs=subprocess.run(['docker','logs','--since','90s',name],capture_output=True,text=True)
all_logs=subprocess.run(['docker','logs',name],capture_output=True,text=True)
assert 'Social Publisher worker ready' in all_logs.stdout
assert not any(x in logs.stdout+logs.stderr for x in ['Traceback','PermissionError','recovery check error','status export error'])
data=Path(next(m['Source'] for m in snapshot['Mounts'] if m['Destination']=='/data'))
health=json.loads((data/'bridge-health.json').read_text())
assert health['enabled'] and health['last_error'] is None and not health['task_errors']
assert time.time()-health['last_success_at']<360
status_dir=Path(next(m['Source'] for m in snapshot['Mounts'] if m['Destination']=='/status'))
receipt=json.loads((status_dir/'status.json').read_text())
plan=json.loads((root/'plan.json').read_text());target_ids={x['job_id'] for x in plan['incidents']}
for jid in target_ids:
 job=next(x for x in receipt['jobs'] if x['id']==jid)
 assert job['status']=='published' and len(job['parts'])==6
 assert all(x['status']=='published' and x.get('permalink') for x in job['parts'])
 assert job['parts'][0]['topic_tag']=='미국주식'
audit=docker('exec',name,'python','-c',"""import sqlite3,json
c=sqlite3.connect('file:/data/schedule.sqlite3?mode=ro',uri=True)
print(json.dumps({'events':c.execute('SELECT COUNT(*) FROM publisher_api_events').fetchone()[0],
'publish_requests_by_part':c.execute(\"SELECT job_id,part,COUNT(*) FROM publisher_api_events WHERE phase='request_started' AND endpoint LIKE '%/threads_publish' GROUP BY job_id,part\").fetchall(),
'publish_responses':c.execute(\"SELECT http_status,COUNT(*) FROM publisher_api_events WHERE phase='response' AND endpoint LIKE '%/threads_publish' GROUP BY http_status\").fetchall()}))
""")
journal=json.loads(audit)
assert all(part>=3 for jid,part,count in journal['publish_requests_by_part'] if jid in target_ids),'Existing first/second part was re-published'
print('HEALTH_RESULT '+json.dumps({'status':'healthy','runtime':runtime,'exclusive_lock_held':True,
    'fresh_bridge':True,'bridge_id':health['bridge_id'],'control_enabled':health['enabled'],
    'all_24_parts_verified':True,'recent_errors':False,'journal':journal},ensure_ascii=False),flush=True)
