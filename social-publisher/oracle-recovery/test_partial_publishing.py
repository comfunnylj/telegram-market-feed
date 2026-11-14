"""Regression tests derived from the four live November incidents. No real API."""
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch
import core
import durable
import recovery as r
from scheduler import Scheduler
import test_recovery as base


class PartialTests(unittest.TestCase):
    setUp = base.RecoveryTests.setUp
    api = base.RecoveryTests.api
    send = base.RecoveryTests.send
    patched = base.RecoveryTests.patched

    def setup_queue(self, status='running'):
        scheduler=Scheduler(core.DATA/'schedule.sqlite3')
        payload={'text':''.join(self.parts),'parts':self.parts,'topic':'미국주식',
                 'image':None,'automation':{'dedup_key':'morning:test','expires_at':time.time()+300}}
        with scheduler.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',
                       ('stable-job',time.time(),status,json.dumps(payload),None,time.time()))
        return scheduler,payload

    def test_six_parts_with_leading_newlines_complete_and_keep_input(self):
        self.parts=['approved root']+['\n\nreply '+str(i) for i in range(2,7)]
        original=copy.deepcopy(self.parts)
        def api(t,p,d=None):
            result=self.api(t,p,d)
            if isinstance(result,dict) and 'text' in result:
                result['text']=result['text'].strip(' \t\r\n')
            return result
        with self.patched(api): result=self.send()
        self.assertEqual(result['status'],'published')
        self.assertEqual(len(result['parts']),6)
        self.assertEqual([p['text'] for p in result['parts']],original)
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),6)

    def test_second_publish_response_lost_adopts_without_reposting(self):
        self.parts=['root']+['\n\nreply '+str(i) for i in range(2,7)]
        lost=[False]
        def api(t,p,d=None):
            out=self.api(t,p,d)
            if p.endswith('/threads_publish') and d['creation_id']=='c2' and not lost[0]:
                lost[0]=True
                raise TimeoutError('response lost after acceptance')
            return out
        with self.patched(api): result=self.send()
        self.assertEqual(result['status'],'published')
        self.assertEqual([d['creation_id'] for p,d in self.calls if p.endswith('/threads_publish')].count('c2'),1)

    def test_missing_permalink_restored_from_same_parent_feed(self):
        self.parts=['root','\n\nreply']
        def api(t,p,d=None):
            out=self.api(t,p,d)
            if p.startswith('/pc2?'):out.pop('permalink',None)
            return out
        with self.patched(api): result=self.send()
        self.assertEqual(result['status'],'published')
        self.assertEqual(result['parts'][1]['permalink_restored_from'],'authenticated_parent_feed')
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),2)

    def test_unavailable_permalink_retains_id_then_resumes(self):
        self.parts=['root','reply 2','reply 3']
        def api(t,p,d=None):
            out=self.api(t,p,d)
            if p.startswith('/pc2?'):out.pop('permalink',None)
            if p.startswith('/pc1/replies?'):
                for item in out['data']:item.pop('permalink',None)
            return out
        with self.patched(api): first=self.send()
        self.assertEqual(first['status'],'published_unverified')
        self.assertEqual(first['parts'][1]['post_id'],'pc2')
        with self.patched(): final=self.send(record=first)
        self.assertEqual(final['status'],'published')
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),3)

    def test_worker_crash_before_third_restores_latest_checkpoint(self):
        self.parts=['root','reply 2','reply 3','reply 4','reply 5','reply 6']
        scheduler,payload=self.setup_queue()
        def api(t,p,d=None):
            if p.endswith('/threads') and d and d['text']=='reply 3':
                raise SystemExit('simulated worker process death')
            return self.api(t,p,d)
        with self.patched(api),self.assertRaises(SystemExit):self.send(automation=payload['automation'])
        # Same startup path as the production worker marks running as needs_review.
        scheduler=Scheduler(core.DATA/'schedule.sqlite3',recover=True)
        self.assertEqual(scheduler.list()[0]['status'],'needs_review')
        record=durable.load_record(scheduler.list()[0])
        self.assertEqual([x['status'] for x in record['parts'][:2]],['published','published'])
        (core.DATA/'recovery-enabled-at').write_text('0')
        with self.patched():self.assertTrue(r.recover_one(scheduler))
        self.assertEqual(scheduler.list()[0]['status'],'published')
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),6)

    def test_bridge_duplicate_dedup_key_creates_only_one_job(self):
        sys.path.insert(0,str(Path(__file__).parent/'fixtures'))
        from bridge import Bridge
        scheduler=Scheduler(core.DATA/'schedule.sqlite3')
        bridge=Bridge(scheduler,status_dir=core.DATA/'not-public')
        bridge.tasks={'morning':{'enabled':True,'late_grace_seconds':300,'topic':'미국주식',
            'max_posts':500,'max_utf16':450,'image_required':False,'account':'genie_carrot','network':'threads'}}
        now=time.time()
        stamp=lambda n:dt.datetime.fromtimestamp(n,dt.timezone.utc).isoformat()
        envelope={'dedup_key':'morning:2026-11-14','created_at':stamp(now),
            'not_before':stamp(now+60),'expires_at':stamp(now+300),
            'topic':'미국주식','text':'root','parts':['root'],'image':None}
        first=bridge.ingest('morning',envelope,now-600,now=now)
        second=bridge.ingest('morning',envelope,now-600,now=now)
        self.assertEqual(first,second);self.assertEqual(len(scheduler.list()),1)
        changed={**envelope,'text':'changed','parts':['changed']}
        with self.assertRaisesRegex(ValueError,'immutable_job_conflict'):
            bridge.ingest('morning',changed,now-600,now=now)

    def test_transient_5xx_read_retries_without_new_publish(self):
        self.parts=['root','reply']
        failed=[False]
        def api(t,p,d=None):
            if p.startswith('/pc2?') and not failed[0]:
                failed[0]=True;raise r.MetaError(503,{'code':2,'is_transient':True})
            return self.api(t,p,d)
        with self.patched(api):result=self.send()
        self.assertEqual(result['status'],'published')
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),2)

    def test_5xx_publish_response_is_reconciled_not_blindly_reposted(self):
        seen=[False]
        def api(t,p,d=None):
            result=self.api(t,p,d)
            if p.endswith('/threads_publish') and not seen[0]:
                seen[0]=True;raise r.MetaError(503,{'code':2,'is_transient':True})
            return result
        with self.patched(api):result=self.send()
        self.assertEqual(result['status'],'published')
        self.assertEqual(len([1 for p,d in self.calls if p.endswith('/threads_publish')]),2)

    def test_image_hash_error_prevents_container_and_publish(self):
        raw=b'valid image bytes'
        media={'image_url':'https://example.invalid/image.jpg','size':len(raw),'sha256':'0'*64}
        with self.patched(),patch.object(core,'image_bytes',return_value=(raw,'.jpg')):
            result=self.send(image=media)
        self.assertEqual(result['status'],'failed_before_publish')
        self.assertFalse(any(d for p,d in self.calls))

    def test_valid_image_and_actual_topic_are_verified(self):
        raw=b'valid image bytes'
        media={'image_url':'https://example.invalid/image.jpg','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        def api(t,p,d=None):
            out=self.api(t,p,d)
            if p.startswith('/pc1?'):out.update(media_type='IMAGE',media_url='https://example.invalid/rendered.jpg')
            return out
        with self.patched(api),patch.object(core,'image_bytes',return_value=(raw,'.jpg')):
            result=self.send(image=media)
        self.assertEqual(result['status'],'published')
        self.assertEqual(result['parts'][0]['result']['topic_tag'],'미국주식')

    def test_checkpoint_file_newer_than_db_is_adopted(self):
        scheduler,payload=self.setup_queue()
        record={'job_id':'stable-job','schedule_id':'stable-job','created_at':time.time(),
            'text':payload['text'],'status':'prepared','parts':[{'text':x,'status':'prepared'} for x in self.parts]}
        pub=r.Publisher();pub.save(record)
        newer=copy.deepcopy(record);newer['checkpoint_seq']+=1
        newer['parts'][0].update(post_id='accepted',status='published_unverified')
        (core.DATA/'history/stable-job.json').write_text(json.dumps(newer))
        self.assertEqual(durable.load_record(scheduler.list()[0])['parts'][0]['post_id'],'accepted')
        self.assertEqual((core.DATA/'history/stable-job.json').stat().st_mode&0o777,0o600)

    def test_real_request_wrapper_journals_http_and_ids_without_token(self):
        scheduler,payload=self.setup_queue()
        secret='not-a-real-production-token'
        class Response(io.BytesIO):
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def open_mock(req,timeout):
            path=req.full_url[len(core.API):]
            data={k:v[0] for k,v in urllib.parse.parse_qs(req.data.decode()).items()} if req.data is not None else None
            return Response(json.dumps(self.api(secret,path,data)).encode())
        with patch.object(core,'saved_token',return_value=secret),patch.object(r.urllib.request,'urlopen',side_effect=open_mock),patch.object(r.time,'sleep'):
            result=self.send(automation=payload['automation'])
        self.assertEqual(result['status'],'published')
        with scheduler.connect() as db:
            rows=db.execute('SELECT detail FROM publisher_api_events').fetchall()
            publishes=db.execute("SELECT http_status,meta_post_id,parent_post_id FROM publisher_api_events WHERE phase='response' AND endpoint LIKE '%/threads_publish'").fetchall()
        self.assertEqual(len(publishes),2)
        self.assertEqual(publishes[1],(200,'pc2','pc1'))
        self.assertFalse(any(secret in raw for raw, in rows))
        self.assertEqual(scheduler.list()[0]['result']['parts'][-1]['status'],'published')

    def test_http_error_is_journaled_and_access_token_redacted(self):
        scheduler,payload=self.setup_queue()
        secret='fake-secret-for-redaction-regression'
        class Response(io.BytesIO):
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def open_mock(req,timeout):
            path=req.full_url[len(core.API):]
            if req.data is not None:
                body=json.dumps({'error':{'code':190,'message':'invalid '+secret}}).encode()
                raise urllib.error.HTTPError(req.full_url,400,'Bad Request',{},io.BytesIO(body))
            return Response(json.dumps(self.api(secret,path)).encode())
        with patch.object(core,'saved_token',return_value=secret),patch.object(r.urllib.request,'urlopen',side_effect=open_mock),patch.object(r.time,'sleep'):
            result=self.send(automation=payload['automation'])
        self.assertEqual(result['recovery_action'],'operator_required')
        with scheduler.connect() as db:
            rows=db.execute('SELECT http_status,error_code,detail FROM publisher_api_events WHERE http_status=400').fetchall()
        self.assertEqual(rows[0][:2],(400,190))
        self.assertNotIn(secret,rows[0][2]);self.assertIn('[REDACTED]',rows[0][2])
