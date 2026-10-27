#!/usr/bin/env python3
"""Publish user-requested 4-part Gocheok253 Threads chain through the existing Oracle bridge.
Fail-closed media/receipt gate; no automatic duplicate retry or publish without verification.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "social-publisher/automation"))
import preflight
KST = dt.timezone(dt.timedelta(hours=9))
REPO = "comfunnylj/telegram-market-feed"
KEY = "realestate:gocheok253-blog-224455463952-20261027"
JOB_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "social-publisher/" + KEY))
BLOG = "https://blog.naver.com/comfunny_lj/224455463952"
RECEIPT = "https://161-33-141-193.sslip.io/social-publisher-status/status.json"
ACCOUNT, TOPIC, SOURCE = "genie_carrot", "부동산", "realestate"
OUTBOX = ROOT / "social-publisher/automation/realestate.json"
STATUS = ROOT / "social-publisher/diagnostics/gocheok253-20261027-threads-status.json"
MEDIA = ROOT / "social-publisher/media"
SOURCE_IMAGES = [
    "gocheok253_03_entry_price.png",
    "gocheok253_04_supply_valuation.png",
    "gocheok253_05_apt_comparables.png",
]
PARTS = [
  "서울에서 매매가 3억, 초기투자금 1억 7,200만 원으로 표시된 재개발 매물이 있다면?\n\n구로구 고척동 253구역 이야기야.\n\n2026년 10월 25일 기준 공개 매물 호가가 3억 원이고, 플랫폼 표시 초투는 1.72억 원이야. 대지지분은 7.11평.\n\n게다가 2026년 8월 조합설립인가까지 받았어. 아직 사업 초기 구상에 머무는 곳은 아니라는 거지.\n\n다만 1.72억 원은 광고 표시값이지, 실제 필요한 현금이 확정됐다는 뜻은 아니야.\n\n(1/4)",
  "사업 규모도 꽤 커.\n\n✅ 정비구역 약 1만 9천 평\n✅ 최고 29층, 총 1,469세대 계획\n✅ 분양주택 1,243세대·임대 226세대\n✅ 세곡초 바로 옆, 고척근린공원 인접\n\n이 구역은 초역세권보다는 학교와 공원 가까운 주거환경이 강점이야. 오류동역·개봉역은 별도 이동 동선을 따져봐야 하고.\n\n위 세대수는 2025년 서울시 정비계획 기준이야. 나중에 바뀔 수 있어.\n\n(2/4)",
  "숫자로 보는 사업성도 살펴보자.\n\n2025년 서울시 고시에 나온 추정비례율은 111.79%야. 그때 공개된 전용 84.9㎡ 조합원분양가 추정액은 8.74억 원이고.\n\n민간 플랫폼의 소유자 560명을 분양주택 1,243세대에서 단순 차감하면 일반분양 683세대가 나와. 소유자 수 대비 약 122% 수준이지.\n\n다만 683세대는 확정 일반분양 물량이 아니고, 비례율과 분양가도 모두 당시 추정치야.\n\n(3/4)",
  "여기서 조심할 건 '초투 1.72억이면 신축 한 채를 갖는다'는 생각이야.\n\n매매가 3억과 표시 초투의 차이 1.28억이 실제로 승계 가능한 보증금이나 대출인지 확인해야 해. 해당 매물의 독립 분양자격, 조합원 지위 승계, 토지거래허가 여부도 중요하고.\n\n추가분담금은 별개야. 종전자산 감정평가와 최종 조합원분양가에 따라 총투입금이 크게 달라질 수 있어.\n\n자세한 분석과 근거 자료는 블로그 글 참고해 👇\n\n(4/4)\nhttps://blog.naver.com/comfunny_lj/224455463952"
]
FORMAL = re.compile(r"(?:입니다|습니다|합니다|됩니다|있습니다|없습니다|하세요|주세요|드립니다|해요|이에요|예요|네요|거예요|싶어요|바랍니다|십시오)")
state = {
    "dedup_key": KEY, "job_id": JOB_ID, "account": ACCOUNT, "topic": TOPIC,
    "blog_url": BLOG, "expected_parts": 4, "expected_images": 3,
    "phase": "initialized"
}

def run(*args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Command failed: " + str(args) + " " + r.stderr[-1200:])
    return r.stdout.strip()

def git(*args):
    return run("git", *args)

def commit_push(message):
    git("commit", "-m", message)
    for i in range(8):
        try:
            git("push", "origin", "HEAD:main")
            return git("rev-parse", "HEAD")
        except Exception:
            if i == 7:
                raise
            git("pull", "--rebase", "origin", "main")
            time.sleep(2)

def save(phase, **updates):
    state.update(phase=phase, checked_at=dt.datetime.now(KST).isoformat(timespec="seconds"), **updates)
    STATUS.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git("add", str(STATUS.relative_to(ROOT)))
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        commit_push("Record Gocheok253 Threads " + phase)
    print("STATE", phase, json.dumps(updates, ensure_ascii=False)[:2000], flush=True)

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Gocheok253-Threads/1.0)",
        "Cache-Control": "no-cache"
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(9 * 1024 * 1024)

def receipt():
    return json.loads(fetch(RECEIPT + "?fresh=" + str(time.time_ns()), timeout=22))

def matched(r):
    return [j for j in r.get("jobs", []) if j.get("dedup_key") == KEY or str(j.get("id", "")) == JOB_ID]

def check_config():
    lengths = [preflight.utf16_length(p) for p in PARTS]
    assert len(PARTS) == 4 and all(30 <= n <= 450 for n in lengths), lengths
    assert not any(FORMAL.search(p) for p in PARTS), "Non-casual register detected"
    assert "1억 7,200만 원" in PARTS[0][:80], "Upfront initial amount missing"
    assert BLOG in PARTS[-1] and PARTS[-1].endswith(BLOG), "Final blog link missing"
    assert all(BLOG not in p for p in PARTS[:-1])
    ctl = json.loads((ROOT / "social-publisher/automation/control.json").read_text())
    reg = json.loads((ROOT / "social-publisher/automation/tasks.json").read_text())
    task = next((t for t in reg["tasks"] if t["id"] == SOURCE), None)
    assert ctl.get("enabled") is True and ctl.get("bridge_id") == "sp-oracle-genie-carrot-v1"
    assert task is not None and task["enabled"] is True
    assert task["account"] == ACCOUNT and task["topic"] == TOPIC
    assert task["outbox"] == "realestate.json" and task["image_required"] is True
    assert task.get("max_utf16", 0) >= max(lengths)
    outbox = json.loads(OUTBOX.read_text())
    assert outbox["protocol"] == 1 and outbox["source"] == SOURCE
    assert not any(j.get("dedup_key") == KEY for j in outbox["jobs"]), "Already queued"
    assert not any(BLOG in j.get("text", "") for j in outbox["jobs"]), "Blog link already queued"
    return outbox, lengths

def build_media():
    paths = []
    for i, name in enumerate(SOURCE_IMAGES, 1):
        src = MEDIA / name
        assert src.exists() and src.stat().st_size >= 20000, "Source image missing: " + name
        dst = MEDIA / ("realestate-gocheok253-20261027-" + str(i).zfill(2) + ".jpg")
        assert not dst.exists(), "Destination already exists: stop before overwrite"
        meta = preflight.normalize_image(src, dst, target_width=1080)
        paths.append((dst, meta))
    git("add", *[str(path.relative_to(ROOT)) for path, _ in paths])
    media_commit = commit_push("Add three sRGB 1080px Gocheok253 Threads charts")
    images = []
    for path, meta in paths:
        url = f"https://raw.githubusercontent.com/{REPO}/{media_commit}/{path.relative_to(ROOT).as_posix()}"
        for attempt in range(6):
            try:
                remote = fetch(url)
                assert len(remote) == meta["size"], "Remote size mismatch"
                assert hashlib.sha256(remote).hexdigest() == meta["sha256"], "Remote hash mismatch"
                preflight.inspect_image(remote)
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(5)
        images.append({"url": url, "sha256": meta["sha256"], "size": meta["size"]})
    return media_commit, images

def main():
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("pull", "--ff-only", "origin", "main")
    out, lengths = check_config()
    first = receipt()
    preflight.validate_receipt(first, source=SOURCE, images=3)
    assert not matched(first), "Original key already known to Oracle"
    save("health_and_text_verified", lengths=lengths, publisher_version=first.get("publisher_version"))
    media_commit, images = build_media()
    save("remote_media_verified", media_commit=media_commit,
         media_hashes=[{"sha256": x["sha256"], "size": x["size"]} for x in images])
    now = dt.datetime.now(KST)
    due = now + dt.timedelta(minutes=5)
    job = {
        "dedup_key": KEY,
        "created_at": now.isoformat(timespec="seconds"),
        "not_before": due.isoformat(timespec="seconds"),
        "expires_at": (due + dt.timedelta(minutes=5)).isoformat(timespec="seconds"),
        "topic": TOPIC, "text": "".join(PARTS), "parts": PARTS, "images": images
    }
    git("pull", "--ff-only", "origin", "main")
    current_out, _ = check_config()
    preflight.validate_job(job, existing_jobs=current_out["jobs"], remote=True)
    current = receipt()
    preflight.validate_receipt(current, source=SOURCE, images=3)
    assert not matched(current), "Job already accepted; no duplicate"
    current_out["jobs"].append(job)
    OUTBOX.write_text(json.dumps(current_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git("add", str(OUTBOX.relative_to(ROOT)))
    outbox_commit = commit_push("Queue approved Gocheok253 4-part Threads with verified charts and blog URL")
    persisted = json.loads(git("show", outbox_commit + ":social-publisher/automation/realestate.json"))
    assert [j for j in persisted["jobs"] if j.get("dedup_key") == KEY] == [job], "Readback mismatch"
    save("queued", outbox_commit=outbox_commit,
         not_before=job["not_before"], expires_at=job["expires_at"])
    end = time.monotonic() + 650
    previous = "queued"
    while time.monotonic() < end:
        try:
            r = receipt()
            matches = matched(r)
            if matches:
                j = matches[0]
                status = str(j.get("status"))
                if status != previous:
                    save("receipt_" + status, receipt_status=status,
                         receipt_image_count=j.get("image_count"),
                         published_count=sum(p.get("status") == "published" for p in j.get("parts", [])))
                    previous = status
                result = preflight.classify_result(r, KEY, 4, 3)
                if result["decision"] == "confirmed":
                    save("published", root=result["links"][0], links=result["links"],
                         verified_parts=4, verified_images=3, verified_topic=TOPIC)
                    return
                if result["decision"] in ("hold", "investigate"):
                    save("requires_reconciliation", receipt_status=status,
                         reason=result.get("reason"), receipt_parts=j.get("parts", []))
                    return
        except Exception as exc:
            print("RECEIPT_TRANSIENT", type(exc).__name__, str(exc)[:220], flush=True)
        time.sleep(18)
    save("verification_pending", note="Do not blindly retry; reconcile original job first")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PUBLISH_ERROR", type(exc).__name__, str(exc)[:1000], flush=True)
        try:
            save("error_review_required", error=type(exc).__name__ + ": " + str(exc)[:650])
        except Exception as other:
            print("STATUS_SAVE_ERROR", type(other).__name__, str(other)[:230], flush=True)
        raise
