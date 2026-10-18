"""Offline integration tests: no Instagram account, network, or token needed."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from instagram_publisher import (
    PublisherError, Settings, Store, Worker, allowed_url, validate_job,
)


HOSTS = frozenset({"raw.githubusercontent.com"})
MEDIA = {"url": "https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/"
                + "a" * 40 + "/social-publisher/media/sample.jpg",
         "sha256": "a" * 64, "size": 12345}


def job(kind="image", media=None):
    now = datetime.now(timezone.utc)
    return {"dedup_key": "instagram:test001", "approved": True, "caption": "Sample caption",
            "not_before": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "media_type": kind, "media": media if media is not None else [copy.deepcopy(MEDIA)]}


class FakeGraph:
    def __init__(self):
        self.created = []
        self.published = []
        self.should_fail_publish = False

    def verify_account(self):
        return None

    def create_image(self, url, caption="", child=False):
        self.created.append(("image", url, caption, child))
        return "child" + str(len(self.created)) if child else "container01"

    def create_reel(self, url, caption):
        self.created.append(("reels", url, caption))
        return "container01"

    def create_carousel(self, children, caption):
        self.created.append(("carousel", children, caption))
        return "container01"

    def container_status(self, container):
        return "FINISHED"

    def publish(self, container):
        self.published.append(container)
        if self.should_fail_publish:
            raise PublisherError("simulate lost response")
        return "media01"

    def permalink(self, media):
        return "https://www.instagram.com/p/example/"


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.settings = Settings("123", "expected", "fake", "v24.0",
                                 "https://raw.githubusercontent.com/example/outbox.json",
                                 HOSTS, base / "jobs.sqlite3", base / "status.json", 180)
        self.graph = FakeGraph()
        self.db = Store(self.settings.db_path)
        self.worker = Worker(self.settings, self.graph, self.db)

    def _enqueue(self, candidate):
        envelope = {"protocol": 1, "network": "instagram", "source": "instagram",
                    "account": "expected", "jobs": [candidate]}
        with patch("instagram_publisher.fetch_json", return_value=envelope), \
             patch("instagram_publisher.verify_bytes"):
            self.worker.poll_once()

    def _tick(self):
        with patch("instagram_publisher.fetch_json", return_value={
            "protocol": 1, "network": "instagram", "source": "instagram",
            "account": "expected", "jobs": []}), patch("instagram_publisher.verify_bytes"):
            self.worker.poll_once()

    def _status(self):
        return self.db.conn.execute("SELECT status FROM jobs").fetchone()[0]

    def test_single_image_full_lifecycle(self):
        self._enqueue(job())
        self.assertEqual(self._status(), "awaiting_media")
        self._tick()
        self.assertEqual(self._status(), "published")
        self.assertEqual(self.graph.published, ["container01"])
        self.assertEqual(json.loads(self.settings.status_path.read_text())["jobs"][0]["permalink"],
                         "https://www.instagram.com/p/example/")

    def test_reels_lifecycle(self):
        item = copy.deepcopy(MEDIA)
        item["url"] = item["url"].replace(".jpg", ".mp4")
        self._enqueue(job("reels", [item]))
        self.assertEqual(self.graph.created[0][0], "reels")
        self._tick()
        self.assertEqual(self._status(), "published")

    def test_carousel_order_and_child_readiness(self):
        items = [copy.deepcopy(MEDIA), copy.deepcopy(MEDIA)]
        items[1]["url"] += "?index=2"
        self._enqueue(job("carousel", items))
        self.assertEqual(self._status(), "awaiting_children")
        self.assertEqual([item[3] for item in self.graph.created], [True, True])
        self._tick()
        self.assertEqual(self.graph.created[-1][0], "carousel")
        self.assertEqual(self.graph.created[-1][1], ["child1", "child2"])
        self._tick()
        self.assertEqual(self._status(), "published")

    def test_lost_publish_response_never_retries(self):
        self._enqueue(job())
        self.graph.should_fail_publish = True
        self._tick()
        self.assertEqual(self._status(), "publishing_unknown")
        self._tick()
        self.assertEqual(len(self.graph.published), 1)

    def test_immutable_job(self):
        original = job()
        self.assertEqual(self.db.accept(original), "accepted")
        self.assertEqual(self.db.accept(original), "existing")
        edited = copy.deepcopy(original)
        edited["caption"] = "changed"
        self.assertEqual(self.db.accept(edited), "conflict")

    def test_validation(self):
        candidate = job()
        validate_job(candidate, "instagram", HOSTS)
        candidate["approved"] = False
        with self.assertRaises(PublisherError):
            validate_job(candidate, "instagram", HOSTS)
        self.assertFalse(allowed_url("http://127.0.0.1/private", HOSTS))
        self.assertFalse(allowed_url("https://raw.githubusercontent.com.evil.test/x", HOSTS))

    def test_wrong_account_rejected(self):
        with patch("instagram_publisher.fetch_json", return_value={
            "protocol": 1, "network": "instagram", "source": "instagram",
            "account": "someone_else", "jobs": []}):
            with self.assertRaises(PublisherError):
                self.worker.poll_once()


if __name__ == "__main__":
    unittest.main()
