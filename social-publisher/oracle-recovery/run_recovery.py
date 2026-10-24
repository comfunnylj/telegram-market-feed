"""Run only under the existing worker's exclusive lock after graceful shutdown."""
import argparse
import copy
import fcntl
import json
import pathlib
import sqlite3
import time
import uuid
import core
from recovery import Publisher, identity, own_matches, read

KEY = 'morning:2026-10-24'
JOB = str(uuid.uuid5(uuid.NAMESPACE_URL, 'social-publisher/' + KEY))


def run(candidate, apply=False):
    lock = (core.DATA / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    db = sqlite3.connect(str(core.DATA / 'schedule.sqlite3'), timeout=10)
    row = db.execute('SELECT status,payload,result FROM jobs WHERE id=?', (JOB,)).fetchone()
    if not row:
        raise RuntimeError('Original stable job missing; no new job will be inserted')
    old_status, raw_payload, raw_record = row
    payload = json.loads(raw_payload)
    if ((payload.get('automation') or {}).get('dedup_key') != KEY
            or payload.get('topic') != '미국주식' or len(payload.get('parts', [])) != 8):
        raise RuntimeError('Original job identity does not match authorized recovery')
    if payload['parts'] != candidate['parts'] or payload['text'] != candidate['text']:
        raise RuntimeError('Approved text changed')
    token = core.saved_token()
    identity(token)
    publisher = Publisher()
    publisher.root_image_count = len(core.image_list(payload.get('image'), payload.get('images')))
    if raw_record:
        record = json.loads(raw_record)
    else:
        raise RuntimeError('Original durable result missing; privileged investigation required')
    record['schedule_id'] = JOB
    if record.get('text') != payload['text'] or [p['text'] for p in record['parts']] != payload['parts']:
        raise RuntimeError('Original server history differs from approved source')
    report = {'key': KEY, 'job_id': JOB, 'account': 'genie_carrot',
              'old_status': old_status, 'checked_at': time.time(), 'posted_by_this_run': False}
    previous = None
    for index, active in enumerate(record['parts']):
        if active.get('post_id') or active.get('status') in ('publishing_unknown', 'published_unverified', 'published'):
            decision = publisher.reconcile(token, record, active, previous,
                                           '미국주식' if index == 0 else None)
            if decision == 'unknown':
                report.update(status='reconciliation_required', part=index + 1,
                              container_id=active.get('container_id'),
                              diagnosis=active.get('last_error') or record.get('error'),
                              reason='No authoritative no-publication evidence; no blind retry')
                return report
            if decision == 'retry_same_container':
                if not apply:
                    report.update(status='eligible_same_container_recovery', part=index+1)
                    return report
                active['status'] = 'container_created'
                publisher.audit(record, 'explicit_rejection_same_container_recovery', container_id=active['container_id'])
            if decision == 'unpublished_container':
                # Only an authoritative failed/expired container plus complete negative
                # Meta feed permits recreating this part under the SAME existing job.
                if not apply:
                    report.update(status='eligible_same_job_recovery', part=index + 1)
                    return report
                publisher.audit(record, 'authorized_failed_container_reset', part=index + 1,
                                old_container_id=active.get('container_id'), original_error=record.get('error'))
                for k in ('container_id', 'children', 'post_id', 'result', 'publish_attempt_at'):
                    active.pop(k, None)
                active['status'] = 'prepared'
            if active.get('post_id'):
                previous = active['post_id']
        elif active.get('status') not in ('prepared', 'creating', 'container_created'):
            raise RuntimeError('Unsupported partial state; manual inspection required')
    if not apply:
        report['status'] = 'read_only_audit_complete'
        return report
    if old_status in ('running', 'pending'):
        raise RuntimeError('Do not take over queued or active jobs')
    if not any(p.get('post_id') for p in record['parts']) and not record['parts'][0].get('container_id'):
        # Technical media normalization was explicitly authorized. Keep original
        # source metadata in private history and never mutate the public old outbox.
        publisher.audit(record, 'authorized_same_image_normalization',
                        original=payload.get('image'), replacement=candidate['image'])
        payload['image'] = {**candidate['image'], 'image_url': candidate['image']['url'], 'shared_url': candidate['image']['url']}
    with db:
        changed = db.execute("UPDATE jobs SET status='running' WHERE id=? AND status=?",
                             (JOB, old_status)).rowcount
        if changed != 1:
            raise RuntimeError('Job changed concurrently')
    # Same text, existing record, existing published IDs and parent chain.
    result = publisher.send(payload['text'], payload['topic'], payload['parts'],
                            payload.get('image'), scheduled=True, images=payload.get('images'),
                            job_id=JOB, record=record)
    result['automation'] = payload['automation']
    result['schedule_id'] = JOB
    publisher.save(result)
    with db:
        db.execute('UPDATE jobs SET status=?,result=? WHERE id=? AND status=?',
                   (result['status'], json.dumps(result, ensure_ascii=False), JOB, 'running'))
    report.update(status=result['status'], diagnosis=result.get('diagnosis'),
                  parts=[{'index': i + 1, 'status': p['status'], **{
                      k: (p.get('result') or {}).get(k) for k in ('id', 'permalink', 'topic_tag', 'media_type')}}
                      for i, p in enumerate(result['parts'])])
    report.pop('posted_by_this_run', None)
    report['same_job_recovery_executed'] = True
    if result['status'] == 'published':
        assert len(report['parts']) == 8 and all(p['status'] == 'published' and p['permalink'] for p in report['parts'])
        assert report['parts'][0]['topic_tag'] == '미국주식'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run(json.loads(pathlib.Path(args.candidate).read_text()), args.apply), ensure_ascii=False))
    except Exception as exc:
        # Do not dump environment, tokens, payloads or private DB contents to Actions.
        print(json.dumps({'key': KEY, 'status': 'blocked', 'error_type': type(exc).__name__,
                          'error': str(exc)[:400]}, ensure_ascii=False))
        raise SystemExit(1)
