"""Verify live module hashes, worker lock, API events, receipts and all 24 URLs."""
import json
from pathlib import Path
import subprocess
import sqlite3
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
# A transient GitHub error on startup must not be mistaken for a bad rollout.
# Preserve poll_seconds=180; wait for the actual background worker to retry.
for _ in range(420):
    health=json.loads((data/'bridge-health.json').read_text())
    if (health.get('enabled') and health.get('last_error') is None and not health.get('task_errors')
            and health.get('last_success_at') and time.time()-health['last_success_at']<360):
        break
    time.sleep(1)
else:raise RuntimeError('Actual worker bridge did not recover within two poll intervals')
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

# Recheck the original consistent backup after the initially transient health failure.
backups=sorted((data.parent/'backups').glob('partial-20261114-*'),key=lambda p:p.stat().st_mtime)
backup=backups[-1];before_snapshot=json.loads((backup/'container.json').read_text())
def rows(path):
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    result={r[0]:r for r in c.execute('SELECT id,due,status,payload,result,created FROM jobs ORDER BY id')};c.close();return result
before=rows(backup/'schedule.sqlite3');after=rows(data/'schedule.sqlite3')
env=lambda v:dict(s.split('=',1) for s in v['Config']['Env'])
preservation={'other_jobs_unchanged':{k:v for k,v in before.items() if k not in target_ids}=={k:v for k,v in after.items() if k not in target_ids},
    'environment_unchanged':env(snapshot)==env(before_snapshot),'user_unchanged':snapshot['Config']['User']==before_snapshot['Config']['User'],
    'restart_policy_unchanged':snapshot['HostConfig']['RestartPolicy']==before_snapshot['HostConfig']['RestartPolicy'],
    'command_unchanged':snapshot['Config']['Cmd']==before_snapshot['Config']['Cmd'] and snapshot['Config'].get('Entrypoint')==before_snapshot['Config'].get('Entrypoint')}
assert all(preservation.values())
print('DEPLOYMENT_RESULT '+json.dumps({'status':'deployed_verified','version':runtime['version'],'backup':str(backup),
    'installed_hashes':runtime['hashes'],'preservation':preservation,'other_job_count':len(before)-len(target_ids)},ensure_ascii=False),flush=True)
