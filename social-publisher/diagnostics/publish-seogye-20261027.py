#!/usr/bin/env python3
"""Publish user-requested 5-part Seogye Threads chain through the existing Oracle bridge.
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
KEY = "realestate:seogye-blog-224455764746-20261027"
JOB_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "social-publisher/" + KEY))
BLOG = "https://blog.naver.com/comfunny_lj/224455764746"
RECEIPT = "https://161-33-141-193.sslip.io/social-publisher-status/status.json"
ACCOUNT, TOPIC, SOURCE = "genie_carrot", "부동산", "realestate"
OUTBOX = ROOT / "social-publisher/automation/realestate.json"
STATUS = ROOT / "social-publisher/diagnostics/seogye-20261027-threads-status.json"
MEDIA = ROOT / "social-publisher/media"
SOURCE_IMAGES = [
    "seogye_03_entry_price.png",
    "seogye_04_supply_valuation.png",
    "seogye_05_apt_comparables.png",
]
PARTS = [
  "🏙️ 서울역 바로 서쪽에서 대규모 재개발이 진행 중이야.\n\n서계통합구역 공개 매물은 매매 호가 7억, 플랫폼 표시 초기투자금 4.8억 원부터 확인돼(2026.10.27 기준).\n\n✅ 서울역 생활권\n✅ 2026년 7월 조합설립인가\n✅ 공동주택 2,691세대 계획\n✅ 최고 39층\n\n다만 4.8억은 광고 표시값이야. 보증금·대출 승계 가능 여부와 실제 필요한 현금은 따로 확인해야 해.\n\n(1/5)",
  "규모부터 살펴보면,\n\n🏗️ 구역면적 약 3만 4천 평\n🏢 공동주택 2,691세대\n🏢 오피스텔 246실 별도\n🏠 분양주택 2,103세대·임대 588세대\n\n2025년 4월 정비구역으로 지정됐고, 2026년 7월엔 조합설립인가까지 받았어.\n\n서울역 서쪽 노후 주택가가 최고 39층 주거단지로 바뀌는 계획이지. 현재 확정된 건 조합설립 단계까지고, 건축계획은 이후 변경될 수 있어.\n\n(2/5)",
  "사업성 숫자는 조금 복잡해.\n\n2025년 서울시 고시의 추정비례율은 101.02%, 당시 사업수지에 반영한 일반분양은 413세대야.\n\n그런데 민간 플랫폼은 소유자 1,948명을 기준으로 일반분양을 155세대로 단순 추정하고 있어.\n\n413은 당시 공식 사업수지의 가정이고, 155는 다른 기준의 민간 계산값이야. 둘 다 현재 확정된 최종 일반분양 물량은 아니지.\n\n향후 분양대상자 수와 정비계획 변경 결과가 관건이야.\n\n(3/5)",
  "입지는 확실히 눈길이 가.\n\n🚇 서울역에서 1·4호선, 공항철도, 경의중앙선과 KTX 이용 가능\n🚄 GTX-A 운정중앙~서울역 구간도 운행 중\n🏙️ 시청·광화문 등 CBD 접근성이 좋고, 여의도·강남으로도 철도 이동이 가능해.\n\n서울시는 최대 약 40m의 경사지에 입체 보행로와 녹지축을 조성하는 구상도 제시했어.\n\n물론 실제 서울역까지 걷는 시간은 구역 안에서도 위치별로 달라.\n\n(4/5)",
  "앞으로 볼 변화도 있어.\n\n2026년 10월 보도에 따르면 조합은 용적률 상향과 중대형 주택 비중 확대를 검토 중이야. 삼성물산·GS건설·대우건설 등도 수주에 관심을 보이고 있고.\n\n다만 시공사 선정과 용적률 상향은 아직 확정된 게 아니야.\n\n7억 매물도 분양자격, 토지거래허가, 실제 초투, 추가분담금을 따로 검증해야 해.\n\n서울역 입지가 강점인 만큼, 사업수지가 어떻게 개선될지 지켜볼 만한 곳이야.\n\n조감도와 자세한 사업성 분석은 블로그에 정리했어 👇\n\n#서계통합구역\n(5/5)\nhttps://blog.naver.com/comfunny_lj/224455764746"
]
FORMAL = re.compile(r"(?:입니다|습니다|합니다|됩니다|있습니다|없습니다|하세요|주세요|드립니다|해요|이에요|예요|네요|거예요|싶어요|바랍니다|십시오)")
state = {
    "dedup_key": KEY, "job_id": JOB_ID, "account": ACCOUNT, "topic": TOPIC,
    "blog_url": BLOG, "expected_parts": 5, "expected_images": 3,
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
        commit_push("Record Seogye Threads " + phase)
    print("STATE", phase, json.dumps(updates, ensure_ascii=False)[:2000], flush=True)

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Seogye-Threads/1.0)",
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
    assert len(PARTS) == 5 and all(30 <= n <= 450 for n in lengths), lengths
    assert not any(FORMAL.search(p) for p in PARTS), "Non-casual register detected"
    assert "4.8억" in PARTS[0][:80], "Upfront initial amount missing"
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
    """Create three exact-data Korean summary graphics, no borrowed renderings."""
    from PIL import Image, ImageDraw, ImageFont
    import glob
    font_candidates = (
        glob.glob("/usr/share/fonts/opentype/noto/*SansCJK*Regular*") +
        glob.glob("/usr/share/fonts/truetype/nanum/*") +
        glob.glob("/usr/share/fonts/truetype/noto/*SansCJK*Regular*")
    )
    assert font_candidates, "Korean font missing, do not publish broken image"
    font_path = next((p for p in font_candidates if p.lower().endswith((".ttf", ".ttc", ".otf"))), None)
    assert font_path, "No usable Korean font"
    def f(sz):
        return ImageFont.truetype(font_path, sz)
    cards = [
        {
            "tag": "REDEVELOPMENT  |  SEOUL STATION",
            "title": "서계통합구역",
            "subtitle": "서울역 바로 서쪽 · 조합설립인가 2026.07",
            "number": "4.8억 원",
            "unit": "플랫폼 표시 초기투자금",
            "rows": ["공개 매매 호가   7억 원", "공동주택 2,691세대 계획"],
            "foot": "2026.10.27 공개 광고 기준 · 실제 필요 현금 및 승계조건 별도 확인"
        },
        {
            "tag": "2025 SEOUL REDEVELOPMENT PLAN",
            "title": "공급계획",
            "subtitle": "2025년 서울시 정비계획",
            "number": "2,691세대",
            "unit": "공동주택 계획",
            "rows": ["분양주택 2,103세대", "임대주택 588세대", "오피스텔 246실은 별도"],
            "foot": "계획 수치로 후속 정비계획 변경 등에 따라 달라질 수 있음"
        },
        {
            "tag": "FINANCIAL ASSUMPTIONS",
            "title": "사업성 확인",
            "subtitle": "서울시 공식 자료와 민간 추정 구분",
            "number": "101.02%",
            "unit": "2025년 공식 추정비례율",
            "rows": ["2025년 고시 일반분양 413세대", "2026년 민간 단순 추정 155세대"],
            "foot": "서로 다른 기준의 추정값 · 현재 확정 일반분양 물량 아님"
        }
    ]
    originals=[]
    backgrounds=[("#102C3C","#134257"),("#132C37","#1D4D59"),("#2B303E","#393B53")]
    for i,card in enumerate(cards,1):
        dst = MEDIA / ("realestate-seogye-20261027-" + str(i).zfill(2) + ".jpg")
        assert not dst.exists(), "Refuse existing destination overwrite"
        im=Image.new("RGB",(1080,1350),backgrounds[i-1][0])
        d=ImageDraw.Draw(im)
        col_bg=backgrounds[i-1][0]
        d.rounded_rectangle((58,58,1022,1292),radius=36,fill=backgrounds[i-1][1])
        d.text((110,115),card["tag"],font=f(28),fill="#BBDDD8")
        d.text((108,235),card["title"],font=f(82),fill="#FFFFFF")
        d.text((110,350),card["subtitle"],font=f(35),fill="#D7E7E8")
        d.line((110,445,968,445),fill="#6CABB0",width=3)
        size=118 if len(card["number"])<=6 else 104
        d.text((108,515),card["number"],font=f(size),fill="#FFDB96")
        d.text((113,665),card["unit"],font=f(39),fill="#FFFFFF")
        y=800
        for line in card["rows"]:
            assert d.textbbox((0,0),line,font=f(36))[2] < 825, "Text exceeds card width"
            d.rounded_rectangle((104,y-20,977,y+76),radius=19,fill="#1B5366" if i!=3 else "#47465D")
            d.text((130,y),line,font=f(36),fill="#F0F6F6")
            y+=115
        d.line((110,1150,968,1150),fill="#6CABB0",width=2)
        foot=card["foot"]
        if len(foot)>37:
            pos=foot.rfind(" ",0,37)
            if pos<15:pos=34
            lines=[foot[:pos].strip(),foot[pos:].strip()]
        else:
            lines=[foot]
        for n,line in enumerate(lines):
            assert d.textbbox((0,0),line,font=f(26))[2] < 865, "Footnote overflow"
            d.text((110,1180+35*n),line,font=f(26),fill="#D7E7E8")
        original=MEDIA/("seogye-20261027-card-source-"+str(i)+".png")
        im.save(original,format="PNG")
        meta=preflight.normalize_image(original,dst,target_width=1080)
        originals.append((dst,meta))
    git("add",*[str(p.relative_to(ROOT)) for p,_ in originals])
    media_commit=commit_push("Add three sRGB 1080px Seogye Threads data cards")
    images=[]
    for path,meta in originals:
        url=f"https://raw.githubusercontent.com/{REPO}/{media_commit}/{path.relative_to(ROOT).as_posix()}"
        for attempt in range(6):
            try:
                remote=fetch(url)
                assert len(remote)==meta["size"], "Remote image size mismatch"
                assert hashlib.sha256(remote).hexdigest()==meta["sha256"], "Remote image SHA256 mismatch"
                preflight.inspect_image(remote)
                break
            except Exception:
                if attempt==5:raise
                time.sleep(5)
        images.append({"url":url,"sha256":meta["sha256"],"size":meta["size"]})
    return media_commit,images

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
    outbox_commit = commit_push("Queue approved Seogye 5-part Threads with verified charts and blog URL")
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
                result = preflight.classify_result(r, KEY, 5, 3)
                if result["decision"] == "confirmed":
                    save("published", root=result["links"][0], links=result["links"],
                         verified_parts=5, verified_images=3, verified_topic=TOPIC)
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
