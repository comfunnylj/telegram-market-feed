"""Private durable checkpoints and credential-free API transaction events."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import core


def connect():
    db = sqlite3.connect(str(core.DATA / 'schedule.sqlite3'), timeout=15)
    db.execute('PRAGMA synchronous=FULL')
    return db


def save_record(store, record):
    # File checkpoint precedes DB checkpoint. A restart compares checkpoint_seq,
    # so it can adopt a newer file if the process died between the two commits.
    record['checkpoint_seq'] = int(record.get('checkpoint_seq', 0)) + 1
    record['checkpoint_at'] = time.time()
    raw = json.dumps(record, ensure_ascii=False, indent=2)
    path = Path(store) / (record['job_id'] + '.json')
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    if (core.DATA / 'schedule.sqlite3').exists():
        with connect() as db:
            db.execute("UPDATE jobs SET result=? WHERE id=? AND status='running'",
                       (raw, record.get('schedule_id', record['job_id'])))


def api_event(record, event):
    # Append-only table is private and is not exported in public receipts.
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS publisher_api_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            dedup_key TEXT, part INTEGER, event_id TEXT NOT NULL, phase TEXT NOT NULL,
            started_at REAL NOT NULL, ended_at REAL, method TEXT NOT NULL,
            endpoint TEXT NOT NULL, parent_post_id TEXT, container_id TEXT,
            meta_post_id TEXT, http_status INTEGER, error_code INTEGER,
            error_subcode INTEGER, detail TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS publisher_api_job ON publisher_api_events(job_id,seq)')
        db.execute('''INSERT INTO publisher_api_events
            (job_id,dedup_key,part,event_id,phase,started_at,ended_at,method,endpoint,
             parent_post_id,container_id,meta_post_id,http_status,error_code,error_subcode,detail)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            record.get('schedule_id', record['job_id']),
            (record.get('automation') or {}).get('dedup_key'), event.get('part'),
            event['event_id'], event['phase'], event['started_at'], event.get('ended_at'),
            event['method'], event['endpoint'], event.get('parent_post_id'),
            event.get('container_id'), event.get('meta_post_id'), event.get('http_status'),
            event.get('error_code'), event.get('error_subcode'),
            json.dumps(event, ensure_ascii=False)))


def load_record(row):
    saved = row.get('result') or {}
    names = {row['id'], saved.get('job_id')}
    candidates = [saved] if saved else []
    for name in names - {None}:
        path = core.DATA / 'history' / (name + '.json')
        if path.exists():
            candidate = json.loads(path.read_text())
            if candidate.get('schedule_id', candidate.get('job_id')) != row['id']:
                continue
            candidates.append(candidate)
    if not candidates:
        return None
    result = max(candidates, key=lambda r: int(r.get('checkpoint_seq', 0)))
    payload = row['payload']
    if (result.get('text') != payload['text'] or
            [p.get('text') for p in result.get('parts', [])] != payload['parts']):
        raise ValueError('Immutable checkpoint differs from original payload')
    return result
