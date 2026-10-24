"""Persistent local queue. All timestamps are epoch seconds; user input is Korea time."""
import datetime as dt
import json
import sqlite3
import time
import uuid

KST = dt.timezone(dt.timedelta(hours=9))
GRACE_SECONDS = 300
LABELS = {'pending': '대기', 'running': '처리 중', 'published': '게시 완료',
          'expired': '기한 경과', 'cancelled': '취소', 'missed': '시간 경과', 'needs_review': '중단 · 확인 필요',
          'failed_before_publish': '게시 전 실패', 'partial_failed': '일부 게시 · 확인 필요',
          'publishing_unknown': '발행 결과 확인 필요', 'published_unverified': '게시 조회 확인 필요'}


def parse_kst(value, now=None):
    try:
        result = dt.datetime.strptime(value.strip(), '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    except ValueError:
        raise ValueError('한국시간을 YYYY-MM-DD HH:MM 형식으로 입력해 주세요. 예: 2026-10-15 14:30') from None
    stamp = result.timestamp()
    if stamp <= (time.time() if now is None else now):
        raise ValueError('예약 시각은 현재보다 미래여야 합니다.')
    return stamp


def show_kst(stamp):
    return dt.datetime.fromtimestamp(stamp, KST).strftime('%Y-%m-%d %H:%M')


class Scheduler:
    def __init__(self, path, recover=False):
        self.path = str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, due REAL NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, created REAL NOT NULL)')
            # Single GUI instance is enforced by the entry point on Windows.
            if recover:
                db.execute("UPDATE jobs SET status='needs_review' WHERE status='running'")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, due, payload, now=None):
        now = time.time() if now is None else now
        if due <= now:
            raise ValueError('예약 시각이 지났습니다. 새 시각으로 다시 미리보기를 확인해 주세요.')
        identifier = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',
                       (identifier, due, 'pending', json.dumps(payload, ensure_ascii=False), None, now))
        return identifier

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,due,status,payload,result FROM jobs ORDER BY due DESC').fetchall()
        return [dict(id=r[0], due=r[1], status=r[2], payload=json.loads(r[3]),
                     result=json.loads(r[4]) if r[4] else None) for r in rows]

    def cancel(self, identifier):
        with self.connect() as db:
            result = db.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status='pending'", (identifier,))
            return result.rowcount == 1

    def claim(self, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET status='missed' WHERE status='pending' AND due<?", (now-GRACE_SECONDS,))
            row = db.execute("SELECT id,payload FROM jobs WHERE status='pending' AND due<=? ORDER BY due LIMIT 1", (now,)).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (row[0],))
                return row[0], json.loads(row[1])
        return None

    def finish(self, identifier, record):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?, result=? WHERE id=? AND status='running'",
                       (record['status'], json.dumps(record, ensure_ascii=False), identifier))
