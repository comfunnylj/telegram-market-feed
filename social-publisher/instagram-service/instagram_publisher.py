"""Separate, fail-closed Instagram sidecar for the existing GitHub outbox.

This service does not modify, import, or restart the existing Threads worker.
Python 3.10+; standard library only.  It deliberately does not automatically
retry a publication once the potentially non-idempotent API call has begun.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


LOG = logging.getLogger("instagram_publisher")
DEFAULT_OUTBOX = (
    "https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/"
    "main/social-publisher/instagram/outbox.json"
)
SAFE_STATUSES = {"pending", "awaiting_children", "awaiting_media", "publishing_unknown", "published_unverified",
                 "published", "expired", "needs_review"}
MAX_MEDIA_SIZE = 100 * 1024 * 1024  # GitHub's per-file limit; streamed, not buffered


class PublisherError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    account_id: str
    username: str
    token: str
    graph_version: str
    outbox_url: str
    media_hosts: frozenset[str]
    db_path: Path
    status_path: Path
    poll_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        missing = [k for k in ("IG_USER_ID", "IG_USERNAME", "IG_ACCESS_TOKEN") if not env.get(k)]
        if missing:
            raise PublisherError("Missing required secret/configuration: " + ", ".join(missing))
        version = env.get("IG_GRAPH_VERSION", "v26.0")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise PublisherError("IG_GRAPH_VERSION must look like v24.0")
        hosts = frozenset(x.strip().lower() for x in env.get(
            "IG_MEDIA_HOSTS", "raw.githubusercontent.com").split(",") if x.strip())
        return cls(
            account_id=env["IG_USER_ID"], username=env["IG_USERNAME"].lstrip("@").lower(),
            token=env["IG_ACCESS_TOKEN"], graph_version=version,
            outbox_url=env.get("IG_OUTBOX_URL", DEFAULT_OUTBOX), media_hosts=hosts,
            db_path=Path(env.get("IG_DB_PATH", "/data/instagram.sqlite3")),
            status_path=Path(env.get("IG_STATUS_PATH", "/data/status.json")),
            poll_seconds=max(180, int(env.get("IG_POLL_SECONDS", "180"))),
        )


def allowed_url(url: str, hosts: frozenset[str]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in hosts
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (ValueError, TypeError):
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: frozenset[str]):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.hosts):
            raise PublisherError("Disallowed media redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_json(url: str, allowed_hosts: frozenset[str]) -> dict:
    if not allowed_url(url, allowed_hosts):
        raise PublisherError("Outbox origin is not allowed")
    opener = urllib.request.build_opener(RestrictedRedirect(allowed_hosts))
    with opener.open(urllib.request.Request(url, headers={"Cache-Control": "no-cache"}), timeout=25) as res:
        if int(res.headers.get("Content-Length", "0")) > 4 * 1024 * 1024:
            raise PublisherError("Outbox is too large")
        body = res.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        raise PublisherError("Outbox is too large")
    obj = json.loads(body)
    if not isinstance(obj, dict):
        raise PublisherError("Invalid outbox")
    return obj


def validate_media(media: dict, allowed_hosts: frozenset[str]) -> None:
    if not isinstance(media, dict) or not allowed_url(media.get("url"), allowed_hosts):
        raise PublisherError("Media must have an allowed HTTPS URL")
    parsed = urllib.parse.urlsplit(media["url"])
    if parsed.hostname == "raw.githubusercontent.com" and not re.fullmatch(
        r"/comfunnylj/telegram-market-feed/[0-9a-f]{40}/social-publisher/media/[A-Za-z0-9_.-]+",
        parsed.path,
    ):
        raise PublisherError("GitHub media URL must use this repository's immutable commit SHA")
    if not isinstance(media.get("size"), int) or not 0 < media["size"] <= MAX_MEDIA_SIZE:
        raise PublisherError("Invalid media size")
    if not re.fullmatch(r"[a-f0-9]{64}", str(media.get("sha256", ""))):
        raise PublisherError("Missing SHA-256")


def verify_bytes(media: dict, allowed_hosts: frozenset[str]) -> None:
    """Do not ask Meta to fetch an unverified public URL; memory use is bounded."""
    validate_media(media, allowed_hosts)
    opener = urllib.request.build_opener(RestrictedRedirect(allowed_hosts))
    request = urllib.request.Request(media["url"], headers={"Accept": "*/*"})
    digest, size = hashlib.sha256(), 0
    with opener.open(request, timeout=60) as response:
        if not allowed_url(response.url, allowed_hosts):
            raise PublisherError("Redirected to disallowed host")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_MEDIA_SIZE:
                raise PublisherError("Media too large")
            digest.update(chunk)
    if size != media["size"] or digest.hexdigest() != media["sha256"]:
        raise PublisherError("Media size/hash mismatch")


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone offset required")
    return dt.astimezone(timezone.utc)


def validate_job(job: dict, source: str, hosts: frozenset[str]) -> None:
    if not isinstance(job, dict) or not isinstance(job.get("dedup_key"), str):
        raise PublisherError("Invalid job key")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", job["dedup_key"]):
        raise PublisherError("Unsafe job key")
    if not job["dedup_key"].startswith(source + ":"):
        raise PublisherError("Wrong source prefix")
    if job.get("approved") is not True:
        raise PublisherError("Only explicitly approved jobs may be accepted")
    if not isinstance(job.get("caption"), str) or len(job["caption"]) > 2200:
        raise PublisherError("Instagram caption exceeds 2,200 characters")
    kind, media = job.get("media_type"), job.get("media")
    if not isinstance(media, list) or any(not isinstance(item, dict) for item in media):
        raise PublisherError("Media list is required")
    if (kind in ("image", "reels") and len(media) != 1) or (kind == "carousel" and not 2 <= len(media) <= 10):
        raise PublisherError("Image/Reels need one item; image carousel needs 2-10 items")
    if kind not in ("image", "reels", "carousel"):
        raise PublisherError("Unsupported media_type")
    for item in media:
        validate_media(item, hosts)
        parsed_url = urllib.parse.urlsplit(item["url"])
        filename = urllib.parse.parse_qs(parsed_url.query).get("filename", [""])[0]
        extension = (filename or parsed_url.path).lower().rsplit(".", 1)[-1]
        if kind == "reels" and extension not in ("mp4", "mov"):
            raise PublisherError("Reels must use an MP4/MOV video URL")
        if kind != "reels" and extension not in ("jpg", "jpeg"):
            raise PublisherError("Image publishing needs a JPEG URL")
    start, end = parse_time(job["not_before"]), parse_time(job["expires_at"])
    if end <= start:
        raise PublisherError("expires_at must follow not_before")


class GraphClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = f"https://graph.instagram.com/{settings.graph_version}"

    def request(self, method: str, endpoint: str, fields: dict | None = None) -> dict:
        url = self.root + "/" + endpoint.lstrip("/")
        headers = {"Authorization": "Bearer " + self.settings.token, "Accept": "application/json"}
        data = None
        if method == "GET":
            if fields:
                url += "?" + urllib.parse.urlencode(fields)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(fields or {}).encode("utf-8")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=60) as r:
                payload = json.loads(r.read(1024 * 1024))
        except urllib.error.HTTPError as exc:
            # Do not print raw error bodies or access tokens.
            raise PublisherError(f"Meta API HTTP {exc.code} at {endpoint.split('?')[0]}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PublisherError("Meta API request outcome unknown (network/timeout)") from exc
        if not isinstance(payload, dict) or "error" in payload:
            raise PublisherError("Invalid Meta API response")
        return payload

    def verify_account(self) -> None:
        me = self.request("GET", "me", {"fields": "id,username,account_type"})
        if (str(me.get("id")) != self.settings.account_id
                or str(me.get("username", "")).lower() != self.settings.username):
            raise PublisherError("Authenticated Instagram account does not match configured account")

    def create_image(self, url: str, caption: str = "", child: bool = False) -> str:
        fields = {"image_url": url}
        if child:
            fields["is_carousel_item"] = "true"
        else:
            fields["caption"] = caption
        return self._create(fields)

    def create_reel(self, url: str, caption: str) -> str:
        return self._create({"media_type": "REELS", "video_url": url, "caption": caption})

    def create_carousel(self, child_ids: list[str], caption: str) -> str:
        return self._create({"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption})

    def _create(self, fields: dict) -> str:
        result = self.request("POST", f"{self.settings.account_id}/media", fields)
        if not result.get("id"):
            raise PublisherError("Meta returned no container id")
        return str(result["id"])

    def container_status(self, container_id: str) -> str:
        result = self.request("GET", container_id, {"fields": "status_code"})
        return str(result.get("status_code", "UNKNOWN"))

    def publish(self, container_id: str) -> str:
        result = self.request("POST", f"{self.settings.account_id}/media_publish", {"creation_id": container_id})
        if not result.get("id"):
            raise PublisherError("Meta returned no published media id")
        return str(result["id"])

    def permalink(self, media_id: str) -> str:
        result = self.request("GET", media_id, {"fields": "id,permalink"})
        url = result.get("permalink", "")
        if not isinstance(url, str) or not url.startswith("https://www.instagram.com/"):
            raise PublisherError("Media published but permalink not yet verifiable")
        return url


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL, child_ids TEXT NOT NULL DEFAULT '[]',
            container_id TEXT, media_id TEXT, permalink TEXT,
            error TEXT, updated_at TEXT NOT NULL)""")
        self.conn.commit()

    def accept(self, job: dict) -> str:
        key = job["dedup_key"]
        payload = json.dumps(job, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        existing = self.conn.execute("SELECT fingerprint FROM jobs WHERE key=?", (key,)).fetchone()
        if existing:
            return "existing" if existing[0] == fingerprint else "conflict"
        self.conn.execute("INSERT INTO jobs(key,fingerprint,payload,status,updated_at) VALUES(?,?,?,?,?)",
                          (key, fingerprint, payload, "pending", utc_now()))
        self.conn.commit()
        return "accepted"

    def update(self, key: str, **fields) -> None:
        assert fields and set(fields) <= {"status", "child_ids", "container_id", "media_id", "permalink", "error"}
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {assignments} WHERE key=?", (*fields.values(), key))
        self.conn.commit()

    def rows(self):
        return self.conn.execute("SELECT key,payload,status,child_ids,container_id,media_id,permalink,error FROM jobs ORDER BY updated_at ASC").fetchall()

    def public_status(self, account: str) -> dict:
        rows = self.conn.execute("SELECT key,status,media_id,permalink,updated_at FROM jobs ORDER BY updated_at DESC LIMIT 100").fetchall()
        return {"protocol": 1, "network": "instagram", "account": account,
                "updated_at": utc_now(),
                "jobs": [{"dedup_key": k, "status": status, "media_id": mid,
                          "permalink": link, "updated_at": updated}
                         for k, status, mid, link, updated in rows]}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Worker:
    def __init__(self, settings: Settings, api: GraphClient, store: Store):
        self.s, self.api, self.db = settings, api, store

    def poll_once(self) -> None:
        # Refuse to ingest or publish anything if the token belongs to a different account.
        self.api.verify_account()
        outbox = fetch_json(self.s.outbox_url, frozenset({"raw.githubusercontent.com"}))
        if outbox.get("protocol") != 1 or outbox.get("network") != "instagram" or outbox.get("source") != "instagram":
            raise PublisherError("Incorrect Instagram outbox envelope")
        if str(outbox.get("account", "")).lstrip("@").lower() != self.s.username:
            raise PublisherError("Outbox target account mismatch")
        jobs = outbox.get("jobs")
        if not isinstance(jobs, list) or len(jobs) > 100:
            raise PublisherError("Invalid job list")
        for job in jobs:
            try:
                validate_job(job, "instagram", self.s.media_hosts)
                outcome = self.db.accept(job)
                if outcome == "conflict":
                    LOG.error("Immutable job changed: %s (ignored)", job["dedup_key"])
            except (PublisherError, KeyError, ValueError, TypeError) as exc:
                LOG.error("Rejected job: %s", type(exc).__name__)
        for key, raw, status, children, container, media_id, _link, _err in self.db.rows():
            if status in ("published", "expired", "needs_review", "publishing_unknown"):
                continue
            try:
                self.process(key, json.loads(raw), status, json.loads(children), container, media_id)
            except Exception as exc:
                # No automatic re-publication after an uncertain API result.
                LOG.error("Job %s stopped in %s: %s", key, status, type(exc).__name__)
                current = self.db.conn.execute("SELECT status FROM jobs WHERE key=?", (key,)).fetchone()[0]
                if current not in ("publishing_unknown", "published_unverified", "published"):
                    self.db.update(key, status="needs_review", error=type(exc).__name__)
        self.write_receipt()

    def process(self, key: str, job: dict, status: str, children: list[str], container: str | None, media_id: str | None):
        now = datetime.now(timezone.utc)
        if status == "published_unverified":
            try:
                self.db.update(key, status="published", permalink=self.api.permalink(media_id))
            except PublisherError:
                pass
            return
        if status == "pending":
            if now < parse_time(job["not_before"]):
                return
            if now > parse_time(job["expires_at"]):
                self.db.update(key, status="expired")
                return
            # Validate all media prior to the first container creation.
            for item in job["media"]:
                verify_bytes(item, self.s.media_hosts)
            if job["media_type"] == "image":
                container = self.api.create_image(job["media"][0]["url"], job["caption"])
            elif job["media_type"] == "reels":
                container = self.api.create_reel(job["media"][0]["url"], job["caption"])
            else:
                for item in job["media"][len(children):]:
                    child_id = self.api.create_image(item["url"], child=True)
                    children.append(child_id)
                    self.db.update(key, child_ids=json.dumps(children))
                self.db.update(key, status="awaiting_children")
                return
            self.db.update(key, status="awaiting_media", container_id=container)
            return
        if status == "awaiting_children":
            states = [self.api.container_status(cid) for cid in children]
            if any(value in ("IN_PROGRESS", "PENDING") for value in states):
                return
            if any(value != "FINISHED" for value in states):
                raise PublisherError("Carousel child media not ready")
            container = self.api.create_carousel(children, job["caption"])
            self.db.update(key, status="awaiting_media", container_id=container)
            return
        if status == "awaiting_media":
            meta_status = self.api.container_status(container)
            if meta_status in ("IN_PROGRESS", "PENDING"):
                return
            if meta_status != "FINISHED":
                raise PublisherError("Media preparation failed or returned unknown status")
            # COMMIT BEFORE calling the non-idempotent publish endpoint. If the
            # HTTP response is lost, never blindly retry the publish call.
            self.db.update(key, status="publishing_unknown")
            published_id = self.api.publish(container)
            self.db.update(key, status="published_unverified", media_id=published_id)
            try:
                self.db.update(key, status="published", permalink=self.api.permalink(published_id))
            except PublisherError:
                pass

    def write_receipt(self) -> None:
        data = json.dumps(self.db.public_status(self.s.username), ensure_ascii=False, indent=2)
        path = self.s.status_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            tmp.write(data)
            name = tmp.name
        os.chmod(name, 0o600)
        os.replace(name, path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("IG_ENABLED") != "true":
        raise SystemExit("Instagram publisher is OFF; set IG_ENABLED=true after setup and account verification")
    settings = Settings.from_env()
    worker = Worker(settings, GraphClient(settings), Store(settings.db_path))
    while True:
        try:
            worker.poll_once()
        except Exception as exc:
            LOG.error("Poll failed safely: %s", type(exc).__name__)
        if os.environ.get("IG_ONCE") == "true":
            break
        time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    main()
