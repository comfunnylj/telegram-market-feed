"""Safety tests for reusable Threads publisher preflight. Offline; no post requests."""
import importlib.util
import json
import tempfile
import unittest
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("social_preflight", HERE / "preflight.py")
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

GOOD_URL = ("https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/"
            + "a"*40 + "/social-publisher/media/verified.jpg")
GOOD_URL2 = GOOD_URL.replace("verified.jpg","second.jpg")

def image(n=1000,m=900):
    from PIL import Image
    import io
    buf=io.BytesIO()
    Image.new("RGB",(n,m),"red").save(buf,format="JPEG",quality=90)
    return buf.getvalue()

def job():
    return {"dedup_key":"realestate:unitcase","topic":"부동산",
            "created_at":"2026-10-23T10:00:00+09:00",
            "not_before":"2026-10-23T10:05:00+09:00",
            "expires_at":"2026-10-23T10:10:00+09:00",
            "parts":["서울 면목9구역 🏡","사업 검토"],
            "text":"서울 면목9구역 🏡사업 검토",
            "images":[
                {"url":GOOD_URL,"sha256":"a"*64,"size":100000},
                {"url":GOOD_URL2,"sha256":"b"*64,"size":100001},
            ]}

def receipt(status="published"):
    return {
        "protocol":1,"account":"genie_carrot",
        "publisher_version":"0.4","capabilities":{"carousel":True,"max_images":20},
        "bridge":{"bridge_id":"sp-oracle-genie-carrot-v1","enabled":True,"last_error":None,
                  "last_success_at":time.time(),
                  "task_errors":{},"tasks":[{"id":"realestate","enabled":True,
                    "account":"genie_carrot","topic":"부동산",
                    "outbox":"realestate.json"}]},
        "jobs":[{"dedup_key":"realestate:unitcase","status":status,
                "image_count":2,"parts":[
                    {"status":"published","permalink":"https://www.threads.com/@genie_carrot/post/a",
                     "topic_tag":"부동산"},
                    {"status":"published","permalink":"https://www.threads.com/@genie_carrot/post/b",
                     "topic_tag":None},
                ]}],
    }

class Tests(unittest.TestCase):
    def test_normalize(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"i.png"; out=Path(d)/"o.jpg"
            Image.new("RGBA",(500,600),(5,15,25,190)).save(inp)
            m=pf.normalize_image(inp,out)
            self.assertEqual(m["width"],1080)
            self.assertEqual(m["height"],1296)
            self.assertEqual(m["format"],"JPEG")
            self.assertEqual(m["sha256"],pf.sha256(out.read_bytes()))
            self.assertTrue(m["size"]>0)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"a.png"; out=Path(d)/"b.jpg"
            from PIL import Image
            Image.new("RGB",(500,500),"black").save(inp)
            out.write_bytes(b"do-not-overwrite")
            with self.assertRaises(pf.PreflightError):
                pf.normalize_image(inp,out)
            self.assertEqual(out.read_bytes(),b"do-not-overwrite")

    def test_bad_aspect(self):
        with self.assertRaises(pf.PreflightError):
            pf.inspect_image(image(1000,30))

    def test_valid_original_small_photo(self):
        m=pf.inspect_image(image(498,330))
        self.assertEqual(m["width"],498)

    def test_basic_job(self):
        p=pf.validate_job(job())
        self.assertEqual(p["image_count"],2)
        self.assertEqual(p["part_count"],2)

    def test_missing_carousel(self):
        a=job();a.pop("images")
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_wrong_topic(self):
        a=job();a["topic"]="기타"
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_utf16_limit(self):
        a=job();a["parts"]=["😀"*230];a["text"]=a["parts"][0]
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_duplicate_photo(self):
        a=job();a["images"][1]=dict(a["images"][0])
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_invalid_url(self):
        a=job();a["images"][0]["url"]="https://example.com/asset.jpg"
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_existing_dedup_key(self):
        a=job()
        with self.assertRaises(pf.PreflightError):
            pf.validate_job(a,existing_jobs=[a])

    def test_same_body_other_key(self):
        a=job();b={**a,"dedup_key":"realestate:already-posted"}
        with self.assertRaises(pf.PreflightError):
            pf.validate_job(a,existing_jobs=[b])
        self.assertTrue(pf.validate_job(a,existing_jobs=[b],
                                       allow_verified_replacement=True))

    def test_timestamp_grace_guard(self):
        a=job();a["expires_at"]="2026-10-23T10:30:00+09:00"
        with self.assertRaises(pf.PreflightError):pf.validate_job(a)

    def test_receipt_gate(self):
        self.assertTrue(pf.validate_receipt(receipt())["carousel"])
        j=receipt();j["capabilities"]["carousel"]=False
        with self.assertRaises(pf.PreflightError):pf.validate_receipt(j)
        newer=receipt();newer["publisher_version"]="0.4.1"
        self.assertTrue(pf.validate_receipt(newer)["carousel"])
        stale=receipt();stale["bridge"]["last_success_at"]=time.time()-900
        with self.assertRaises(pf.PreflightError):pf.validate_receipt(stale)

    def test_published_confirmation(self):
        j=receipt()
        self.assertEqual(pf.classify_result(j,"realestate:unitcase",2,2)["decision"],"confirmed")
        j["jobs"][0]["parts"][0]["topic_tag"]=None
        self.assertEqual(pf.classify_result(j,"realestate:unitcase",2,2)["decision"],"hold")

    def test_unknown_never_requeue(self):
        j=receipt("publishing_unknown")
        self.assertEqual(pf.classify_result(j,"realestate:unitcase",2,2)["decision"],"hold")

    def test_pending_not_published(self):
        j=receipt("pending")
        self.assertEqual(pf.classify_result(j,"realestate:unitcase",2,2)["decision"],"pending")

if __name__=="__main__":
    unittest.main()
