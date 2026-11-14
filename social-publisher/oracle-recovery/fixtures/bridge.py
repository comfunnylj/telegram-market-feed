"""Read an owner-controlled GitHub outbox; export minimal public delivery receipts."""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import core
from registry import load_registry, DEFAULT_POLL_SECONDS

REPO = 'comfunnylj/telegram-market-feed'
PREFIX = 'social-publisher/automation'
BRIDGE_ID = 'sp-oracle-genie-carrot-v1'
POLL_SECONDS = DEFAULT_POLL_SECONDS


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.timestamp()


def job_id(key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'social-publisher/'+key))


def atomic_json(path, value, public=False):
    path = pathlib.Path(path)
    temp = path.parent/('.'+path.name+'.'+str(uuid.uuid4())+'.tmp')
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        if public:
            os.chmod(temp,0o644)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def fetch_json(url, maximum=4*1024*1024):
    req=urllib.request.Request(url,headers={'User-Agent':'SocialPublisher-Bridge/0.3','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        raw=response.read(maximum+1)
        if len(raw)>maximum:
            raise ValueError('response_too_large')
        return json.loads(raw)


class Bridge:
    def __init__(self,scheduler,status_dir=None):
        self.scheduler=scheduler
        self.status_dir=pathlib.Path(status_dir or os.environ.get('SP_STATUS','/status'))
        self.lock=threading.RLock()
        self.last_commit=None
        self.tasks={}
        self.poll_seconds=DEFAULT_POLL_SECONDS
        self.health={'bridge_id':BRIDGE_ID,'protocol':1,'enabled':False,'last_poll_at':None,
                     'last_success_at':None,'probe_id':None,'last_commit':None,'last_error':None,
                     'task_schema_version':1,'task_count':0,'tasks':[],'task_errors':{}}
        with scheduler.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bridge_events (event_key TEXT PRIMARY KEY, source TEXT, status TEXT, reason TEXT, updated REAL)')

    def set_health(self,**values):
        with self.lock:self.health.update(values)

    def health_copy(self):
        with self.lock:return self.health.copy()

    def event(self,key,source,status,reason=None):
        with self.scheduler.connect() as db:
            db.execute('INSERT OR REPLACE INTO bridge_events VALUES (?,?,?,?,?)',(key,source,status,reason,time.time()))

    def ingest(self,source,item,cutoff,now=None):
        task=self.tasks.get(source)
        if not task or not task['enabled']:
            raise ValueError('unregistered_or_disabled_task')
        now=time.time() if now is None else now
        key=item['dedup_key']
        if not isinstance(key,str) or not re.fullmatch(re.escape(source)+r':[A-Za-z0-9:_-]{1,150}',key):
            raise ValueError('invalid_dedup_key')
        identifier=job_id(key)
        envelope_digest=hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        with self.scheduler.connect() as db:
            previous=db.execute('SELECT payload FROM jobs WHERE id=?',(identifier,)).fetchone()
        if previous:
            previous_meta=json.loads(previous[0]).get('automation',{})
            if previous_meta.get('request_sha256')!=envelope_digest:
                raise ValueError('immutable_job_conflict')
            self.event(key,source,'already_received')
            return identifier
        created=timestamp(item['created_at']);due=timestamp(item['not_before']);expires=timestamp(item['expires_at'])
        if created<cutoff:
            self.event(key,source,'before_cutover');return
        if created>now+60 or due<created-60 or expires<=due or expires>due+task['late_grace_seconds']:
            raise ValueError('invalid_time_window')
        if item['topic']!=task['topic']:raise ValueError('topic_mismatch')
        text=item['text'];parts=item['parts']
        if (not isinstance(text,str) or len(text)>100000 or not isinstance(parts,list) or not 1<=len(parts)<=task['max_posts']
            or any(not isinstance(p,str) or not p.strip() or core.units(p)>task['max_utf16'] for p in parts)
            or ''.join(parts)!=text):
            raise ValueError('invalid_parts')
        media=core.image_list(item.get('image'),item.get('images'))
        if not media and task['image_required']:raise ValueError('image_required')
        stored_images=[]
        for image in media:
            url=image['url'];parsed=urllib.parse.urlparse(url)
            if (parsed.scheme!='https' or parsed.hostname!='raw.githubusercontent.com' or parsed.netloc!='raw.githubusercontent.com'
                or parsed.query or parsed.fragment
                or not re.fullmatch(r'/comfunnylj/telegram-market-feed/[a-f0-9]{40}/social-publisher/media/[A-Za-z0-9_.-]+\.(png|jpg|jpeg)',parsed.path)
                or not re.fullmatch(r'[a-f0-9]{64}',image['sha256'])
                or type(image['size']) is not int or not 0<image['size']<=8*1024*1024):
                raise ValueError('invalid_image')
            stored_images.append({'shared_url':url,'image_url':url,'sha256':image['sha256'],'size':image['size']})
        payload={'text':text,'topic':item['topic'],'parts':parts,
                 'automation':{'source':source,'dedup_key':key,'expires_at':expires,
                               'account':task['account'],'network':task['network'],'request_sha256':envelope_digest}}
        if item.get('images') is not None:payload['images']=stored_images
        else:payload['image']=stored_images[0] if stored_images else None
        with self.scheduler.connect() as db:
            existing=db.execute('SELECT due,payload FROM jobs WHERE id=?',(identifier,)).fetchone()
        if existing:
            if existing[0]!=due or json.loads(existing[1])!=payload:raise ValueError('immutable_job_conflict')
            self.event(key,source,'already_received');return identifier
        if now>expires:
            self.event(key,source,'expired');return
        for image in stored_images:
            content,_=core.image_bytes(image['image_url'])
            if len(content)!=image['size'] or hashlib.sha256(content).hexdigest()!=image['sha256']:
                raise ValueError('image_digest_mismatch')
        with self.scheduler.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT due,payload FROM jobs WHERE id=?',(identifier,)).fetchone()
            if existing:
                if existing[0]!=due or json.loads(existing[1])!=payload:raise ValueError('immutable_job_conflict')
            else:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',
                           (identifier,due,'pending',json.dumps(payload,ensure_ascii=False),None,now))
        self.event(key,source,'received')
        return identifier

    def poll_once(self):
        self.set_health(last_poll_at=time.time())
        try:
            # 20 unauthenticated API calls per hour in the steady state.
            commits=fetch_json('https://api.github.com/repos/'+REPO+'/commits?sha=main&path='+PREFIX+'&per_page=1')
            sha=commits[0]['sha']
            if not re.fullmatch(r'[a-f0-9]{40}',sha):raise ValueError('invalid_commit')
            if sha!=self.last_commit:
                base='https://raw.githubusercontent.com/'+REPO+'/'+sha+'/'+PREFIX+'/'
                control=fetch_json(base+'control.json')
                if (control.get('protocol')!=1 or control.get('bridge_id')!=BRIDGE_ID
                    or control.get('registry')!='tasks.json' or type(control.get('enabled')) is not bool):
                    raise ValueError('invalid_control')
                loaded=load_registry(fetch_json(base+'tasks.json'))
                probe=fetch_json(base+'probe.json')
                if probe.get('protocol')!=1 or probe.get('mode')!='read_only_no_publish' or not re.fullmatch(r'[a-z0-9-]{1,100}',probe.get('probe_id','')):
                    raise ValueError('invalid_probe')
                self.tasks=loaded['tasks']
                self.poll_seconds=loaded['poll_seconds']
                self.set_health(enabled=control['enabled'],probe_id=probe['probe_id'],
                                task_count=len(self.tasks),tasks=list(self.tasks.values()),task_errors={})
                task_errors={}
                if control['enabled']:
                    cutoff=timestamp(control['activated_at'])
                    if cutoff>time.time()+60:raise ValueError('future_cutover')
                    for source,task in self.tasks.items():
                        if not task['enabled']:continue
                        try:
                            outbox=fetch_json(base+task['outbox'])
                            if outbox.get('protocol')!=1 or outbox.get('source')!=source or not isinstance(outbox.get('jobs'),list) or len(outbox['jobs'])>100:
                                raise ValueError('invalid_outbox')
                            for item in outbox['jobs']:
                                try:self.ingest(source,item,cutoff)
                                except (urllib.error.URLError, TimeoutError, OSError):
                                    raise
                                except Exception as exc:
                                    digest=hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
                                    self.event('rejected:'+digest,source,'rejected',type(exc).__name__)
                        except Exception as exc:
                            task_errors[source]='http_'+str(exc.code) if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
                self.set_health(task_errors=task_errors)
                if task_errors:raise ValueError('task_outbox_errors')
                self.last_commit=sha
            self.set_health(last_success_at=time.time(),last_commit=sha,last_error=None)
        except Exception as exc:
            reason='http_'+str(exc.code) if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
            self.set_health(last_error=reason)
        self.export_status()

    def export_status(self):
        health=self.health_copy()
        atomic_json(core.DATA/'bridge-health.json',health)
        if not self.status_dir.is_dir():return
        jobs=[]
        for row in self.scheduler.list():
            meta=row['payload'].get('automation')
            if not meta:continue
            result=row.get('result') or {}
            parts=result.get('parts') or []
            public_parts=[]
            for index,part in enumerate(parts,1):
                post=part.get('result') or {}
                public_parts.append({'index':index,'status':part['status'],'id':part.get('post_id'),
                                     'permalink':post.get('permalink'),'topic_tag':post.get('topic_tag')})
            jobs.append({'id':row['id'],'source':meta['source'],'dedup_key':meta['dedup_key'],
                         'due':row['due'],'status':row['status'],'requested_topic':row['payload']['topic'],
                         'image_count':len(core.image_list(row['payload'].get('image'),row['payload'].get('images'))),
                         'parts':public_parts})
        with self.scheduler.connect() as db:
            rows=db.execute('SELECT event_key,source,status,reason,updated FROM bridge_events ORDER BY updated DESC LIMIT 100').fetchall()
        events=[dict(zip(('key','source','status','reason','updated_at'),row)) for row in rows]
        atomic_json(self.status_dir/'status.json',{'protocol':1,'account':'genie_carrot',
                    'publisher_version':core.VERSION,'capabilities':{'max_images':core.MAX_IMAGES,'carousel':True},'updated_at':time.time(),
                    'bridge':health,'jobs':jobs[:100],'events':events},public=True)

    def run(self,stopping):
        while not stopping.is_set():
            try:self.poll_once()
            except Exception as exc:
                print('bridge status export error:',type(exc).__name__,flush=True)
            stopping.wait(self.poll_seconds)
