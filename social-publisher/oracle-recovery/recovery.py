"""Durable same-job recovery. Never turn an ambiguous publish into a fresh post.

Loaded by the Oracle worker; credentials stay on Oracle. All retries are bounded.
"""
import copy
import contextvars
import durable
import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import core

VERSION = '2026-11-14.1'
_CURRENT = contextvars.ContextVar('publisher_api_context', default=None)


def text_matches(actual, expected):
    """Meta removes boundary ASCII whitespace; preserve internal and Unicode text."""
    return (isinstance(actual, str) and isinstance(expected, str)
            and actual.strip(' \t\r\n') == expected.strip(' \t\r\n'))


class MetaError(RuntimeError):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__('Meta HTTP ' + str(status))


def request(token, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(core.API + path, data=body,
                                 headers={'Authorization': 'Bearer ' + token})
    publisher = _CURRENT.get()
    event = {'event_id': str(uuid.uuid4()), 'phase': 'request_started',
             'started_at': time.time(), 'method': 'POST' if data is not None else 'GET',
             'endpoint': path.split('?', 1)[0],
             'publish_attempted': data is not None and path.split('?',1)[0].endswith('/threads_publish')}
    if publisher:
        publisher.log_api(event)  # durable write-ahead; failure prevents the request
    status = None
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.status
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Meta response too large')
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        text = exc.read(8192).decode('utf-8', 'replace').replace(token, '[REDACTED]')
        try:
            upstream = json.loads(text).get('error', {})
            detail = {k: upstream[k] for k in ('message', 'type', 'code',
                      'error_subcode', 'is_transient', 'fbtrace_id') if k in upstream}
        except ValueError:
            detail = {'message': text[:1000]}
        if publisher:
            publisher.log_api({**event, 'phase': 'response', 'ended_at': time.time(),
                'http_status': exc.code, 'error_code': detail.get('code'),
                'error_subcode': detail.get('error_subcode'), 'error': detail})
        raise MetaError(exc.code, detail) from None
    except (OSError, ValueError) as exc:
        if publisher:
            publisher.log_api({**event, 'phase': 'transport_error',
                'ended_at': time.time(), 'http_status':status, 'error': {'type': type(exc).__name__,
                'message': str(exc).replace(token, '[REDACTED]')[:500]}})
        raise
    if publisher:
        publisher.log_api({**event, 'phase': 'response', 'ended_at': time.time(),
            'http_status': status, 'response': {k: result[k] for k in
            ('id', 'status', 'error_message', 'permalink') if k in result}})
    return result


def read(token, path):
    for attempt in range(3):
        try:
            return request(token, path)
        except MetaError as exc:
            if exc.status not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (OSError, ValueError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def identity(token):
    me = read(token, '/me?fields=id,username')
    if str(me.get('id')) != core.ACCOUNT or me.get('username') != 'genie_carrot':
        raise RuntimeError('Meta account identity mismatch')
    return me


def rejected_missing_media(record, active):
    detail = active.get('last_error') or {}
    if detail.get('http_status') == 400 and detail.get('code') == 24 and detail.get('error_subcode') == 4279009:
        return True
    legacy = record.get('error') or ''
    if not legacy.startswith('HTTP 400: '):
        return False
    try:
        error = json.loads(legacy[len('HTTP 400: '):])['error']
        return (error.get('code') == 24 and error.get('error_subcode') == 4279009
                and str(active.get('container_id')) in error.get('error_user_msg', ''))
    except (ValueError, KeyError, TypeError):
        return False


def own_matches(token, text, previous, since):
    """Exhaust the relevant feed window; absence is never enough to retry POST."""
    edge = '/' + previous + '/replies' if previous else '/me/threads'
    path = edge + '?fields=id,text,permalink,topic_tag,username,timestamp,media_type&limit=100'
    hits = []
    for _ in range(20):
        page = read(token, path)
        items = page.get('data', [])
        for item in items:
            stamp = dt.datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).timestamp()
            if (item.get('username') == 'genie_carrot' and text_matches(item.get('text'), text)
                    and stamp >= since - 300):
                hits.append(item)
        next_url = (page.get('paging') or {}).get('next')
        if not next_url:
            return hits, True
        parsed = urllib.parse.urlsplit(next_url)
        allowed = {urllib.parse.urlsplit(core.API).hostname, 'graph.threads.net', 'graph.threads.com'}
        if parsed.scheme != 'https' or parsed.hostname not in allowed:
            raise RuntimeError('Unexpected Meta paging host')
        query = urllib.parse.parse_qs(parsed.query)
        query.pop('access_token', None)
        prefix = urllib.parse.urlsplit(core.API).path
        if not parsed.path.startswith(prefix + '/'):
            raise RuntimeError('Unexpected Meta paging API version')
        path = parsed.path[len(prefix):] + '?' + urllib.parse.urlencode(query, doseq=True)
    return hits, False


class Publisher(core.Publisher):
    def save(self, record):
        durable.save_record(self.store, record)

    def log_api(self, event):
        record = self._record
        active = getattr(self, '_active', None)
        event['stage'] = getattr(self, '_stage', 'account_check')
        if active is not None:
            event.update(part=record['parts'].index(active)+1,
                parent_post_id=active.get('reply_to_id'),
                container_id=active.get('container_id'), meta_post_id=active.get('post_id'))
            response_id = (event.get('response') or {}).get('id')
            if event['endpoint'].endswith('/threads') and response_id:
                event['container_id'] = str(response_id)
            if event['endpoint'].endswith('/threads_publish') and response_id:
                active.update(post_id=str(response_id), status='published_unverified')
                event['meta_post_id'] = str(response_id)
            active['last_api_event'] = {k:v for k,v in event.items() if k!='response'}
        durable.api_event(record, event)
        self.save(record)


    def wait_ready(self, token, container):
        self._stage = 'container_status'
        for _ in range(12):
            state = read(token, '/' + container + '?fields=id,status,error_message')
            if state.get('status') == 'FINISHED':
                return
            if state.get('status') in ('ERROR', 'EXPIRED', 'PUBLISHED'):
                raise RuntimeError('Container not eligible for a new publish: ' + json.dumps(state))
            time.sleep(5)
        raise RuntimeError('Container not ready; no publish attempted')

    def audit(self, record, event, **data):
        record.setdefault('recovery_events', []).append({'at': time.time(), 'event': event, **data})
        self.save(record)

    def verify_post(self, token, active, topic=None):
        self._stage = 'verify_post'
        fields = 'id,text,permalink,topic_tag,username,media_type,media_url'
        if topic and getattr(self, 'root_image_count', 0) > 1:
            fields += ',children{id}'
        for attempt in range(3):
            post = read(token, '/' + active['post_id'] + '?fields=' + fields)
            # Keep observed ID/URL even if verification fails; never mark as unposted.
            active['verification_observation'] = {k:post.get(k) for k in
                ('id','permalink','username','topic_tag','media_type')}
            if post.get('permalink'):
                break
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
        if not post.get('permalink'):
            self._stage = 'verify_permalink_feed'
            hits, complete = own_matches(token, active['text'], active.get('reply_to_id'),
                getattr(self, '_record', {}).get('created_at', 0))
            if complete and len(hits)==1 and str(hits[0]['id'])==str(active['post_id']) and hits[0].get('permalink'):
                post['permalink'] = hits[0]['permalink']
                active['permalink_restored_from'] = 'authenticated_parent_feed'
        reasons = []
        if str(post.get('id')) != str(active['post_id']): reasons.append('post_id_mismatch')
        if not text_matches(post.get('text'), active['text']): reasons.append('text_mismatch')
        if post.get('username') != 'genie_carrot': reasons.append('account_mismatch')
        if not post.get('permalink'): reasons.append('permalink_unavailable')
        if topic and post.get('topic_tag') != topic: reasons.append('official_topic_mismatch')
        count = getattr(self, 'root_image_count', 0) if topic else 0
        if count == 1 and (post.get('media_type') != 'IMAGE' or not post.get('media_url')):
            reasons.append('root_image_unconfirmed')
        if count > 1 and (post.get('media_type') != 'CAROUSEL_ALBUM' or
                len((post.get('children') or {}).get('data', [])) != count):
            reasons.append('carousel_image_count_mismatch')
        active['verification'] = {'at':time.time(), 'state':'failed' if reasons else 'verified',
            'reasons':reasons, 'text_normalization':'boundary_ascii_whitespace_only',
            'expected_text_sha256':hashlib.sha256(active['text'].encode()).hexdigest(),
            'actual_text_sha256':hashlib.sha256(post.get('text','').encode()).hexdigest()}
        if reasons:
            raise RuntimeError('Post verification: '+','.join(reasons))
        active.update(status='published', result=post)
        return post

    def verify_parent(self, token, record, active, previous):
        if not previous:
            return
        self._stage = 'verify_parent_reply'
        for attempt in range(3):
            hits, complete = own_matches(token, active['text'], previous, record['created_at'])
            if complete and len(hits)==1 and str(hits[0]['id'])==str(active['post_id']):
                active['parent_verified_at'] = time.time()
                active['reply_to_id'] = previous
                return
            if not complete or len(hits)>1:
                break
            if attempt<2:
                time.sleep(2 ** (attempt+1))
        active['status'] = 'published_unverified'
        raise RuntimeError('Published reply parent could not be uniquely verified')

    def reconcile(self, token, record, active, previous, topic=None):
        if active.get('post_id'):
            try:
                self.verify_post(token, active, topic)
            except MetaError:
                # A failed ID lookup is not evidence of no publication. Match the
                # saved ID against the complete account-owned parent/root feed.
                self._stage = 'reconcile_feed'
                hits, complete = own_matches(token, active['text'], previous, record['created_at'])
                if not complete or len(hits)!=1 or str(hits[0]['id'])!=str(active['post_id']):
                    raise RuntimeError('Saved post ID could not be reconciled')
                self.verify_post(token, active, topic)
            self.verify_parent(token, record, active, previous)
            self.audit(record, 'existing_post_verified', post_id=active['post_id'])
            return 'published'
        container = active.get('container_id')
        state = read(token, '/' + container + '?fields=id,status,error_message') if container else {}
        # A persisted Meta container and account-owned timeline are checked together.
        self._stage = 'reconcile_feed'
        hits, complete = own_matches(token, active['text'], previous, record['created_at'])
        self.audit(record, 'reconciled', container_id=container, container_state=state,
                   matching_ids=[p['id'] for p in hits], feed_window_complete=complete)
        if len(hits) == 1:
            active['post_id'] = hits[0]['id']
            self.verify_post(token, active, topic)
            self.verify_parent(token, record, active, previous)
            self.save(record)
            return 'published'
        if len(hits) > 1 or not complete:
            raise RuntimeError('Ambiguous or incomplete Meta timeline')
        if state.get('status') in ('ERROR', 'EXPIRED'):
            # Definitively unusable container plus complete negative account evidence.
            return 'unpublished_container'
        if state.get('status') == 'FINISHED' and rejected_missing_media(record, active):
            return 'retry_same_container'
        # FINISHED alone does not authorize retry; an explicit rejection is required.
        return 'unknown'

    def create(self, token, record, active, payload, child=None):
        target = child if child is not None else active
        for attempt in range(3):
            target.update(status='creating', create_attempt=attempt + 1)
            self.save(record)
            try:
                self._stage = 'create_container'
                container = request(token, '/' + core.ACCOUNT + '/threads', payload)['id']
                target.update(container_id=container, status='container_created')
                self.save(record)
                return container
            except MetaError as exc:
                target['last_error'] = {'http_status': exc.status, **exc.detail}
                self.save(record)
                if exc.status not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except OSError:
                # Creation never auto-publishes; orphan containers are not public posts.
                if attempt == 2:
                    raise
            time.sleep(2 ** attempt)

    def publish(self, token, record, active, previous, topic):
        for attempt in range(3):
            active.update(status='publishing_unknown', publish_attempt=attempt + 1,
                          publish_attempt_at=time.time())
            self.save(record)  # Write-ahead before any public side effect.
            try:
                self._stage = 'publish_container'
                active['post_id'] = request(token, '/' + core.ACCOUNT + '/threads_publish',
                                             {'creation_id': active['container_id']})['id']
                active['status'] = 'published_unverified'
                self.save(record)
                self.verify_post(token, active, topic)
                self.verify_parent(token, record, active, previous)
                self.save(record)
                return
            except MetaError as exc:
                active['last_error'] = {'http_status': exc.status, **exc.detail}
                self.audit(record, 'publish_error', **active['last_error'])
                decision = self.reconcile(token, record, active, previous, topic)
                if decision == 'published':
                    return
                # Only explicit rate-limit rejection can retry the SAME container.
                if (exc.status != 429 and decision != 'retry_same_container') or attempt == 2:
                    raise
            except (OSError, ValueError, KeyError):
                # Lost response: read-only reconciliation, never blind re-POST.
                for check in range(3):
                    if self.reconcile(token, record, active, previous, topic) == 'published':
                        return
                    if check < 2:
                        time.sleep(5 * (check + 1))
                raise RuntimeError('Publish outcome unresolved; same job retained')
            time.sleep(30 * (attempt + 1) if decision == 'retry_same_container' else 2 ** (attempt + 1))

    def send(self, text, topic, parts=None, image=None, scheduled=False, images=None,
             job_id=None, record=None, automation=None):
        parts = parts if parts is not None else core.split_posts(text)
        record = copy.deepcopy(record) if record is not None else {
            'job_id': job_id or str(uuid.uuid4()), 'created_at': time.time(),
            'text': text, 'requested_topic': topic, 'status': 'prepared',
            'parts': [{'text': p, 'status': 'prepared'} for p in parts]}
        if record.get('text') != text or [p['text'] for p in record['parts']] != parts:
            raise ValueError('Immutable record content mismatch')
        if ''.join(parts) != text or any(not p.strip() or core.units(p) > 450 for p in parts):
            raise ValueError('Invalid approved parts')
        media = core.image_list(image, images)
        self.root_image_count = len(media)
        record['schedule_id'] = job_id or record.get('schedule_id', record['job_id'])
        record['publisher_version'] = VERSION
        if automation is not None: record['automation'] = automation
        self._record = record
        self._active = None
        self._stage = 'account_check'
        context = _CURRENT.set(self)
        active = None
        try:
            self.save(record)
            token = core.saved_token()
            identity(token)
            for item in ([] if record['parts'][0].get('post_id') else media):
                content, _ = core.image_bytes(item['image_url'])
                if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                    raise ValueError('Image immutable readback mismatch')
            self.audit(record, 'start_or_resume', version=VERSION)
            previous = None
            for index, active in enumerate(record['parts']):
                self._active = active
                if index:
                    if active.get('reply_to_id') not in (None, previous):
                        raise RuntimeError('Persisted parent ID differs from verified chain')
                    active['reply_to_id'] = previous
                root_topic = topic if index == 0 else None
                if active.get('post_id') or active.get('status') in ('published', 'publishing_unknown', 'published_unverified'):
                    decision = self.reconcile(token, record, active, previous, root_topic)
                    if decision == 'published':
                        previous = active['post_id']
                        continue
                    if decision != 'retry_same_container':
                        raise RuntimeError('Existing publish unresolved; no new container')
                    active['status'] = 'container_created'
                    self.audit(record, 'retry_explicitly_rejected_same_container', container_id=active['container_id'])
                payload = {'media_type': 'TEXT', 'text': active['text'], 'auto_publish_text': 'false'}
                if index == 0 and len(media) == 1:
                    payload = {'media_type': 'IMAGE', 'text': active['text'], 'image_url': media[0]['image_url']}
                elif index == 0 and len(media) > 1:
                    children = active.setdefault('children', [])
                    for n, item in enumerate(media):
                        if len(children) <= n:
                            children.append({'index': n + 1, 'status': 'prepared'})
                        child = children[n]
                        if not child.get('container_id'):
                            self.create(token, record, active, {'media_type': 'IMAGE',
                                'image_url': item['image_url'], 'is_carousel_item': 'true'}, child)
                        self.wait_ready(token, child['container_id'])
                        child['status'] = 'ready'
                        self.save(record)
                    payload = {'media_type': 'CAROUSEL', 'text': active['text'],
                               'children': ','.join(c['container_id'] for c in children)}
                if root_topic:
                    payload['topic_tag'] = root_topic
                if previous:
                    payload['reply_to_id'] = previous
                    active['reply_to_id'] = previous
                if not active.get('container_id'):
                    self.create(token, record, active, payload)
                self.wait_ready(token, active['container_id'])
                self.publish(token, record, active, previous, root_topic)
                previous = active['post_id']
            record['status'] = 'published'
            record.pop('error', None)
            record.pop('diagnosis', None)
            record.pop('recovery_action', None)
        except Exception as exc:
            detail = {'type': type(exc).__name__, 'message': str(exc)[:1000]}
            if isinstance(exc, MetaError):
                detail.update(http_status=exc.status, upstream=exc.detail)
            record['diagnosis'] = detail
            record['error'] = str(exc)[:1000]
            permanent = (isinstance(exc, MetaError) and exc.status in (400,401,403) and not rejected_missing_media(record, active or {}))
            invalid_verification = isinstance(exc, RuntimeError) and any(x in str(exc) for x in ('text_mismatch','account_mismatch','official_topic_mismatch','parent ID differs'))
            record['recovery_action'] = 'operator_required' if permanent or invalid_verification else 'reconcile_same_job'
            record['status'] = (active['status'] if active and active['status'] in
                ('publishing_unknown', 'published_unverified') else
                ('partial_failed' if any(p.get('status') == 'published' for p in record['parts'])
                 else 'failed_before_publish'))
        finally:
            _CURRENT.reset(context)
        self.save(record)
        return record


def recover_one(scheduler):
    """Resume only this authorized incident or jobs created after rollout.

    Does not change due times, registry flags, cron, pending jobs or historical jobs.
    Every uncertain publish still goes through read-only reconciliation in send().
    """
    flag = core.DATA / 'recovery-enabled-at'
    if not flag.exists():
        return False
    enabled_at = float(flag.read_text())
    now = time.time()
    incident = str(uuid.uuid5(uuid.NAMESPACE_URL, 'social-publisher/morning:2026-10-24'))
    for row in scheduler.list():
        if row['status'] not in ('publishing_unknown', 'published_unverified', 'partial_failed', 'failed_before_publish', 'needs_review'):
            continue
        record = durable.load_record(row) or {}
        # Do not silently backfill other legacy jobs when deploying a new policy.
        if record.get('publisher_version') != VERSION or record.get('recovery_action') == 'operator_required':
            continue
        if row['id'] != incident and record.get('created_at', 0) < enabled_at:
            continue
        attempt = int(record.get('automatic_recovery_attempts', 0))
        if attempt >= 3 or now < record.get('automatic_recovery_after', 0):
            continue
        payload = row['payload']
        if record.get('text') != payload['text'] or [p.get('text') for p in record.get('parts', [])] != payload['parts']:
            continue
        with scheduler.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                return False
            if db.execute("UPDATE jobs SET status='running' WHERE id=? AND status=?",
                          (row['id'], row['status'])).rowcount != 1:
                continue
        record['automatic_recovery_attempts'] = attempt + 1
        record['automatic_recovery_after'] = now + 60 * 2 ** attempt
        publisher = Publisher()
        publisher.save(record)
        result = publisher.send(payload['text'], payload['topic'], payload['parts'],
                                payload.get('image'), scheduled=True, images=payload.get('images'),
                                job_id=row['id'], record=record, automation=payload.get('automation'))
        result['schedule_id'] = row['id']
        if payload.get('automation'):
            result['automation'] = payload['automation']
        publisher.save(result)
        scheduler.finish(row['id'], result)
        return True
    return False

