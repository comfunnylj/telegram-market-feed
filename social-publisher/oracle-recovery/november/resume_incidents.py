"""Resume only four explicitly authorized, already-started original jobs."""
import argparse
import fcntl
import hashlib
import json
import time
import uuid
import sys
from pathlib import Path
if Path('/app/core.py').exists(): sys.path.insert(0, '/app')
import core
import durable
import recovery
from recovery import Publisher,identity,own_matches,read
from scheduler import Scheduler


def verified_parts(pub,token,payload,record):
    pub.root_image_count=len(core.image_list(payload.get('image'),payload.get('images')))
    previous=None;parts=[]
    for i,active in enumerate(record['parts']):
        post=pub.verify_post(token,active,payload['topic'] if i==0 else None)
        hits,complete=own_matches(token,active['text'],previous,record['created_at'])
        if not complete or len(hits)!=1 or str(hits[0]['id'])!=str(active['post_id']):
            raise RuntimeError('Duplicate or unverifiable chain at part '+str(i+1))
        parts.append({'index':i+1,'status':active['status'],'container_id':active.get('container_id'),
            'id':post['id'],'permalink':post['permalink'],'topic_tag':post.get('topic_tag'),
            'parent_id':previous,'verified_at':time.time()})
        previous=active['post_id']
    return parts


def main(plan,verify_only=False):
    assert recovery.VERSION=='2026-11-14.1'
    lock=None
    if not verify_only:
        lock=(core.DATA/'worker.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    scheduler=Scheduler(core.DATA/'schedule.sqlite3')
    token=core.saved_token();identity(token)
    reports=[]
    for entry in plan['incidents']:
        key=entry['key'];jid=entry['job_id']
        assert jid==str(uuid.uuid5(uuid.NAMESPACE_URL,'social-publisher/'+key))
        row=next(x for x in scheduler.list() if x['id']==jid)
        payload=row['payload'];record=durable.load_record(row)
        assert (payload.get('automation')or{}).get('dedup_key')==key
        assert payload['topic']==entry['topic']=='미국주식'
        assert len(payload['parts'])==entry['part_count']==6
        assert hashlib.sha256(json.dumps(payload['parts'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==entry['parts_sha256']
        assert ''.join(payload['parts'])==payload['text']
        assert record and [x['text'] for x in record['parts']]==payload['parts']
        record['schedule_id']=jid
        for index,pid in entry['retained_ids'].items():
            assert str(record['parts'][int(index)-1].get('post_id'))==pid,'Existing post identity changed'
        pub=Publisher();pub.root_image_count=len(core.image_list(payload.get('image'),payload.get('images')))
        if verify_only:
            assert row['status']==record['status']=='published'
        elif row['status']!='published':
            assert row['status'] in ('published_unverified','partial_failed','publishing_unknown','needs_review','failed_before_publish','running')
            assert entry['expired_partial_resume_authorized'] and record['parts'][0].get('post_id'), 'No expired unstarted backfill'
            # Read-only audit of all known public IDs and exact parents before any claim/POST.
            previous=None
            for i,active in enumerate(record['parts']):
                if active.get('post_id'):
                    pub.verify_post(token,active,payload['topic'] if i==0 else None)
                    hits,complete=own_matches(token,active['text'],previous,record['created_at'])
                    assert complete and len(hits)==1 and str(hits[0]['id'])==str(active['post_id'])
                    previous=active['post_id']
                else:
                    assert active['status'] in ('prepared','creating','container_created','publishing_unknown','published_unverified')
                    if active['status']=='prepared':
                        assert not active.get('container_id') and not active.get('publish_attempt_at')
            with scheduler.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                assert not db.execute("SELECT 1 FROM jobs WHERE status='running' AND id!=?",(jid,)).fetchone()
                assert db.execute('UPDATE jobs SET status=? WHERE id=? AND status=?',('running',jid,row['status'])).rowcount==1
            pub.audit(record,'operator_authorized_existing_partial_resume',dedup_key=key,
                original_expires_at=payload['automation']['expires_at'],
                previous_automatic_attempts=record.get('automatic_recovery_attempts',0))
            record['automatic_recovery_attempts']=0
            record.pop('automatic_recovery_after',None)
            record=pub.send(payload['text'],payload['topic'],payload['parts'],payload.get('image'),
                scheduled=True,images=payload.get('images'),job_id=jid,record=record,
                automation=payload.get('automation'))
            pub.save(record);scheduler.finish(jid,record)
            # Update public receipt without changing its existing bridge/control health.
            from bridge import Bridge
            bridge=Bridge(scheduler)
            health=core.DATA/'bridge-health.json'
            if health.exists():bridge.health=json.loads(health.read_text())
            bridge.export_status()
        report={'key':key,'job_id':jid,'status':record['status'],
                'root_preserved':record['parts'][0]['post_id']==entry['retained_ids']['1'],
                'second_post_preserved':record['parts'][1]['post_id']==entry['retained_ids']['2']}
        if record['status']=='published':
            report['parts']=verified_parts(pub,token,payload,record)
        else:
            report['diagnosis']=record.get('diagnosis')
        reports.append(report)
        print('JOB_RESULT '+json.dumps(report,ensure_ascii=False),flush=True)
    print('INCIDENT_RESULTS '+json.dumps({'version':recovery.VERSION,'jobs':reports,
          'all_verified':all(x['status']=='published' and len(x.get('parts',[]))==6 for x in reports)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    try:main(json.loads(open(args.plan).read()),args.verify_only)
    except Exception as e:
        print('BLOCKED '+json.dumps({'type':type(e).__name__,'message':str(e)[:500]}),flush=True)
        raise SystemExit(1)
