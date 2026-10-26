import json,time,sqlite3
import core,recovery
from recovery import Publisher
from scheduler import Scheduler
assert recovery.VERSION=='2026-10-26.1'
scheduler=Scheduler(core.DATA/'schedule.sqlite3')
canonical='1bf31796-ced2-50e1-8f5e-7f531f683bef'
duplicate='83a99347-6f9c-5c6f-be90-242a88897b9f'
with scheduler.connect() as db:
 db.execute('BEGIN IMMEDIATE')
 assert not db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone(),'Worker busy; no concurrent manual publish'
 rows={j['id']:j for j in scheduler.list() if j['id'] in (canonical,duplicate)}
 original=rows[canonical];dupe=rows[duplicate]
 assert original['payload']['parts']==dupe['payload']['parts']
 if original['status']!='published':
  assert original['status']=='published_unverified'
  assert db.execute("UPDATE jobs SET status='running' WHERE id=? AND status='published_unverified'",(canonical,)).rowcount==1
p=original['payload'];r=original['result']
pub=Publisher()
if original['status']!='published':
 r=pub.send(p['text'],p['topic'],p['parts'],p.get('image'),scheduled=True,images=p.get('images'),job_id=canonical,record=r)
 r['schedule_id']=canonical;r['automation']=p['automation'];pub.save(r);scheduler.finish(canonical,r)
assert r['status']=='published',json.dumps(r.get('diagnosis'))
previous=None
for n,active in enumerate(r['parts']):
 post=pub.verify_post(core.saved_token(),active,p['topic'] if n==0 else None)
 if n:assert active['reply_to_id']==previous
 previous=active['post_id']
# Retain already-public duplicate root, but never complete a second duplicate chain.
d=dupe['result'];dp=dupe['payload'];check=Publisher();check.root_image_count=1
check.verify_post(core.saved_token(),d['parts'][0],dp['topic'])
d['status']='duplicate_root_retained';d['canonical_job_id']=canonical;d.pop('error',None);d.pop('diagnosis',None);check.save(d)
with scheduler.connect() as db:
 db.execute("UPDATE jobs SET status=?,result=? WHERE id=? AND status='published_unverified'",(d['status'],json.dumps(d,ensure_ascii=False),duplicate))
from bridge import Bridge
Bridge(scheduler).export_status()
print(json.dumps({'status':'verified','version':recovery.VERSION,'job_id':canonical,'parts':[{'index':i+1,'id':x['post_id'],'permalink':x['result']['permalink'],'topic_tag':x['result'].get('topic_tag')} for i,x in enumerate(r['parts'])],'duplicate_root_retained':d['parts'][0]['result']['permalink']},ensure_ascii=False))
