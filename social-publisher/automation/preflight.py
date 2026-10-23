#!/usr/bin/env python3
"""Reusable fail-closed Threads image/job preflight. Never publishes or stores tokens.

Examples:
 python preflight.py normalize input.png output.jpg
 python preflight.py verify-job pending-job.json --remote
 python preflight.py verify-job pending-job.json --outbox realestate.json --remote
 python preflight.py receipt-check public-receipt.json --source realestate --images 2
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 8 * 1024 * 1024
MIN_WIDTH, MAX_WIDTH = 320, 1440
MAX_UTF16 = 450
RAW_PATTERN = re.compile(
    r"^https://raw[.]githubusercontent[.]com/"
    r"comfunnylj/telegram-market-feed/[a-f0-9]{40}/"
    r"social-publisher/media/[a-zA-Z0-9_.-]+[.](?:jpg|jpeg|png)$")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
TOPIC = {"realestate": "부동산"}
ACCOUNT = "genie_carrot"
BRIDGE = "sp-oracle-genie-carrot-v1"

class PreflightError(ValueError):
    """Hard stop; never silently switch to text-only mode."""

def fail_if(condition: bool, message: str):
    if condition:
        raise PreflightError(message)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def bounded_fetch(url: str, *, timeout: int = 20) -> bytes:
    fail_if(not RAW_PATTERN.fullmatch(url), "Image URL must be immutable commit-pinned repository URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": "SocialPublisher-Preflight/1.0",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        fail_if(getattr(response, "status", 200) != 200, "Remote media returned non-200 status")
        content = response.read(MAX_BYTES + 1)
    fail_if(len(content) > MAX_BYTES, "Remote image exceeds 8 MiB")
    return content

def inspect_image(data: bytes) -> dict:
    try:
        from PIL import Image, ImageOps
        fail_if(len(data) == 0 or len(data) > MAX_BYTES, "Invalid image byte size")
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            fail_if(fmt not in ("JPEG", "PNG"), "Only JPEG/PNG files are supported")
            # EXIF orientation must be handled prior to checking exported geometry.
            upright = ImageOps.exif_transpose(image)
            width, height = upright.size
            fail_if(width < MIN_WIDTH or width > MAX_WIDTH, "Image width outside 320–1440 px")
            fail_if(height <= 0 or max(width/height, height/width) > 10, "Image aspect ratio exceeds 10:1")
            upright.load()
            return {"width": width, "height": height, "format": fmt, "size": len(data), "sha256": sha256(data)}
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError("Unreadable or malformed image: " + type(exc).__name__) from exc

def normalize_image(source: Path, destination: Path, target_width: int = 1080) -> dict:
    """Resample/canonicalize media encoding without cropping or inventing content.
    Original-source relevance and image reuse rights require separate review.
    """
    fail_if(destination.exists(), "Refuse overwrite existing image asset")
    fail_if(not 320 <= target_width <= 1440, "Target width out of bounds")
    try:
        from PIL import Image, ImageCms, ImageOps
        original = source.read_bytes()
        fail_if(len(original) == 0, "Empty source image")
        with Image.open(io.BytesIO(original)) as im:
            fail_if(im.format not in ("JPEG", "PNG"), "Input must be JPEG or PNG")
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            fail_if(w < 128 or h < 128 or max(w/h, h/w) > 10, "Source geometry invalid")
            icc = im.info.get("icc_profile")
            if icc:
                try:
                    src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    dst_profile = ImageCms.createProfile("sRGB")
                    im = ImageCms.profileToProfile(im.convert("RGB"), src_profile, dst_profile, outputMode="RGB")
                except Exception as exc:
                    raise PreflightError("Cannot safely convert embedded ICC color profile") from exc
            else:
                im = im.convert("RGB")
            out_h = round(h * target_width / w)
            fail_if(out_h < 1 or max(target_width / out_h, out_h / target_width) > 10,
                    "Output aspect ratio invalid")
            im = im.resize((target_width, out_h), Image.Resampling.LANCZOS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            for quality in (94, 88, 80):
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=quality, optimize=True,
                        subsampling=0, progressive=False, icc_profile=ImageCms.ImageCmsProfile(
                            ImageCms.createProfile("sRGB")).tobytes())
                data = buf.getvalue()
                if len(data) <= MAX_BYTES:
                    break
            else:
                raise PreflightError("Even compressed image exceeds 8 MiB")
            result = inspect_image(data)
            destination.write_bytes(data)
            return {**result, "path": str(destination), "source_width": w, "source_height": h}
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError("Normalization failed: " + type(exc).__name__) from exc

def check_media_ref(item: dict, *, remote: bool = False) -> dict:
    fail_if(not isinstance(item, dict), "Media reference is not an object")
    url, digest, size = item.get("url"), item.get("sha256"), item.get("size")
    fail_if(not isinstance(url, str) or not RAW_PATTERN.fullmatch(url),
            "Media URL must be validated immutable GitHub image URL")
    fail_if(not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest),
            "Invalid SHA256 digest")
    fail_if(type(size) is not int or size < 1 or size > MAX_BYTES, "Invalid image byte size")
    if remote:
        # This URL is public, commit pinned, and cannot contain auth headers.
        data = bounded_fetch(url)
        fail_if(sha256(data) != digest or len(data) != size, "Remote image hash or size mismatch")
        metadata = inspect_image(data)
        suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        fail_if((suffix in ("jpg", "jpeg") and metadata["format"] != "JPEG") or
                (suffix == "png" and metadata["format"] != "PNG"),
                "URL extension does not match decoded media")
        return metadata
    return {"sha256": digest, "size": size, "url_valid": True}

def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2

def validate_job(job: dict, *, existing_jobs: list | None = None, remote: bool = False,
                 allow_verified_replacement: bool = False) -> dict:
    fail_if(not isinstance(job, dict), "Job must be an object")
    key = job.get("dedup_key")
    fail_if(not isinstance(key, str) or not key.startswith("realestate:") or len(key) > 140,
            "Invalid realestate dedup key")
    fail_if(job.get("topic") != TOPIC["realestate"], "Real estate topic must be 부동산")
    parts = job.get("parts")
    fail_if(not isinstance(parts, list) or not parts, "Missing connected posts")
    fail_if(any(not isinstance(p, str) or not p or utf16_length(p) > MAX_UTF16
                for p in parts), "Connected post exceeds configured UTF-16 budget")
    fail_if("".join(parts) != job.get("text"), "Parts must concatenate to exact published text")
    pictures = job.get("images")
    fail_if(not isinstance(pictures, list) or not 2 <= len(pictures) <= 20,
            "Expected ordered 2–20 image carousel, no text-only fallback")
    fail_if(job.get("image") not in (None, ""), "Cannot mix legacy image and carousel images")
    measures = [check_media_ref(item, remote=remote) for item in pictures]
    fail_if(len(set(item["sha256"] for item in pictures)) != len(pictures),
            "Duplicated carousel image SHA256")
    fail_if(len(set(item["url"] for item in pictures)) != len(pictures),
            "Duplicated carousel image URL")
    timestamps = [job.get(x) for x in ("created_at", "not_before", "expires_at")]
    try:
        created, due, expires = [datetime.fromisoformat(t) for t in timestamps]
        fail_if(any(t.tzinfo is None for t in (created, due, expires)),
                "All timestamps must include timezone offset")
        fail_if(due < created or expires < due or (expires-due).total_seconds() > 300,
                "Invalid due / expiry / grace period")
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError("Invalid timestamp encoding") from exc
    if existing_jobs is not None:
        fail_if(any(x.get("dedup_key")==key for x in existing_jobs),
                "Existing key is immutable; do not resubmit")
        same_text = [x.get("dedup_key") for x in existing_jobs
                     if x.get("text") == job.get("text")]
        fail_if(bool(same_text) and not allow_verified_replacement,
                "Potential duplicate text exists under keys "+", ".join(same_text[:3])+
                "; require explicit reconciled replacement")
    return {"key": key, "part_count": len(parts), "image_count": len(measures),
            "image_metadata": measures, "max_utf16": max(map(utf16_length, parts))}

def validate_receipt(receipt: dict, *, source: str = "realestate", images: int = 2) -> dict:
    fail_if(receipt.get("protocol") != 1 or receipt.get("account") != ACCOUNT,
            "Unexpected Oracle protocol/account")
    bridge = receipt.get("bridge") or {}
    fail_if(bridge.get("bridge_id") != BRIDGE or bridge.get("enabled") is not True,
            "Bridge identity disabled or incorrect")
    fail_if(bridge.get("last_error") or (bridge.get("task_errors") or {}).get(source),
            "Oracle reports task/bridge errors")
    from time import time
    heartbeat = bridge.get("last_success_at")
    fail_if(type(heartbeat) not in (float, int) or abs(time() - heartbeat) > 600,
            "Oracle heartbeat missing or stale")
    # Do not rely on the public receipt alone for verifying Meta publishing.
    caps = receipt.get("capabilities") or {}
    version = str(receipt.get("publisher_version", ""))
    m = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", version)
    compatible = bool(m) and (int(m.group(1)) > 0 or int(m.group(2)) >= 4)
    fail_if(not compatible or caps.get("carousel") is not True or
            int(caps.get("max_images") or 0) < images, "Carousel receiver capability not verified")
    tasks = bridge.get("tasks") or []
    fail_if(not any(t.get("id")==source and t.get("enabled") is True and
                    t.get("account")==ACCOUNT and t.get("topic")==TOPIC.get(source) and
                    t.get("outbox")=="realestate.json" for t in tasks),
            "Real-estate task receiver not active")
    return {"bridge": BRIDGE, "account": ACCOUNT, "source": source, "carousel": True}

def classify_result(receipt: dict, key: str, expected_parts: int, expected_images: int) -> dict:
    hits = [x for x in receipt.get("jobs", []) if x.get("dedup_key") == key]
    fail_if(len(hits) != 1, "A unique accepted Oracle job is required")
    j = hits[0]
    status = j.get("status")
    posts = j.get("parts") or []
    if status == "published":
        if (len(posts)==expected_parts and j.get("image_count")==expected_images and
                all(p.get("status")=="published" and
                    isinstance(p.get("permalink"), str) and
                    p["permalink"].startswith("https://www.threads.com/") for p in posts) and
                posts[0].get("topic_tag")=="부동산"):
            return {"decision":"confirmed", "links":[p["permalink"] for p in posts]}
        return {"decision":"hold", "reason":"Server says published but required verification missing"}
    if status in ("publishing_unknown", "published_unverified", "partial_failed",
                  "needs_review", "unknown"):
        return {"decision":"hold", "reason":"Meta state uncertain; reconcile private IDs/account before new job"}
    if status in ("expired", "missed", "failed"):
        return {"decision":"investigate", "reason":"Review server history before considering new job"}
    return {"decision":"pending", "reason":str(status)}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    subs=p.add_subparsers(dest="command",required=True)
    n=subs.add_parser("normalize")
    n.add_argument("input",type=Path)
    n.add_argument("output",type=Path)
    n.add_argument("--width",type=int,default=1080)
    v=subs.add_parser("verify-job")
    v.add_argument("job_file",type=Path)
    v.add_argument("--outbox",type=Path)
    v.add_argument("--remote",action="store_true")
    v.add_argument("--allow-verified-replacement",action="store_true")
    c=subs.add_parser("receipt-check")
    c.add_argument("receipt_file",type=Path)
    c.add_argument("--source",default="realestate")
    c.add_argument("--images",type=int,default=2)
    args=p.parse_args(argv)
    try:
        if args.command=="normalize":
            result=normalize_image(args.input,args.output,args.width)
        elif args.command=="verify-job":
            job=json.loads(args.job_file.read_text())
            existing=json.loads(args.outbox.read_text()).get("jobs",[]) if args.outbox else None
            result=validate_job(job,existing_jobs=existing,remote=args.remote,
                                allow_verified_replacement=args.allow_verified_replacement)
        else:
            result=validate_receipt(json.loads(args.receipt_file.read_text()),
                                    source=args.source,images=args.images)
        print(json.dumps({"ok":True, **result},ensure_ascii=False))
    except (PreflightError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    sys.exit(main())
