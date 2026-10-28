#!/usr/bin/env python3
"""Publish user-requested 5-part Jeonnong9 Threads chain through the existing Oracle bridge.
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
KEY = "realestate:jeonnong9-blog-224457184172-20261029"
JOB_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "social-publisher/" + KEY))
BLOG = "https://blog.naver.com/comfunny_lj/224457184172"
RECEIPT = "https://161-33-141-193.sslip.io/social-publisher-status/status.json"
ACCOUNT, TOPIC, SOURCE = "genie_carrot", "부동산", "realestate"
OUTBOX = ROOT / "social-publisher/automation/realestate.json"
STATUS = ROOT / "social-publisher/diagnostics/jeonnong9-20261029-threads-status.json"
MEDIA = ROOT / "social-publisher/media"
PARTS = [
  "🏙️ 청량리역 근처 재개발, 초기투자금 4.99억?\n\n서울 동대문구 전농9구역 이야기야.\n\n✅ 매매 호가 5.9억\n✅ 표시 초기투자금 4.99억\n✅ 대지지분 13.31평\n✅ 현대엔지니어링 시공사 선정\n✅ 청량리역 생활권\n\n2026년 10월 27일 공개 매물 기준이야.\n\n다만 4.99억은 광고 표시값이지 실제 필요한 현금이 확정된 건 아니야. 추가분담금도 별도고.\n\n그럼 사업은 얼마나 진행됐을까?\n\n(1/5)",
  "전농9구역은 일반 조합방식이 아니라 LH가 참여하는 공공재개발이야.\n\n📍 위치: 동대문구 전농동 일대\n📐 구역면적: 약 1만 4,841평\n\n✅ 2023년 정비구역 지정\n✅ 2023년 LH 사업시행자 지정\n✅ 2024년 현대엔지니어링 시공사 선정\n✅ 2026년 정비계획 변경안 심의 진행\n\n시공사까지 선정된 건 장점이지.\n\n다만 아직 사업시행계획인가가 완료된 단계는 아니야. 앞으로 인허가와 공사비 협의 과정을 지켜봐야 해.\n\n(2/5)",
  "전농9구역에서 가장 눈여겨볼 변화는 용적률이야.\n\n2026년 3월 정비계획 변경안 기준으로,\n\n🏢 최고 35층 → 39층\n📈 상한용적률 239.01% → 270.09%\n🏠 분양주택 920 → 943세대\n🏘️ 임대주택 239 → 218세대\n\n분양주택을 늘려 사업성을 개선하려는 방향이야.\n\n다만 이건 구의회에 제출된 변경안이야. 최종 인가 수치로 확정해서 보면 안 돼.\n\n용적률 상승이 실제 분담금 감소로 이어질지는 총사업비가 관건이지.\n\n(3/5)",
  "그럼 일반분양 물량은 얼마나 될까?\n\n2026년 3월 변경안 기준,\n\n🏠 총 1,161세대\n🏠 분양주택 943세대\n🏠 임대주택 218세대\n\n공개된 토지등소유자 717명을 분양주택에서 단순 차감하면 일반분양 약 226세대야.\n\n소유자 수 대비 약 31.5% 수준이지.\n\n다만 소유자 1명당 1세대 배정을 가정한 단순 계산이야. 실제 분양자격과 현금청산 결과에 따라 달라질 수 있어.\n\n입지는 좋지만 일반분양 여력이 풍부한 사업지는 아니라는 점을 기억해야 해.\n\n(4/5)",
  "전농9구역의 강점은 역시 입지야.\n\n🚇 청량리역 생활권\n🏙️ 종로·시청 등 도심 업무지구 접근성\n🎓 서울시립대 인접\n🏗️ 공공재개발에 시공사 선정까지 완료\n\n하지만 투자 전에는 꼭 확인해야 해.\n\n① 공공재개발 분양대상자격\n② 실제 승계 가능한 보증금·대출\n③ 최종 공사비와 추가분담금\n④ 정비계획 변경 확정 여부\n\n초투 4.99억만 보고 신축 한 채를 확보한다고 생각하면 위험해.\n\n입지는 매력적이지만, 결국 총투입금과 권리관계가 투자 결과를 결정할 거야.\n\n자세한 분석과 출처는 블로그에서 확인해 👇\n#전농9구역\n(5/5)\nhttps://blog.naver.com/comfunny_lj/224457184172"
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
        commit_push("Record Jeonnong9 Threads " + phase)
    print("STATE", phase, json.dumps(updates, ensure_ascii=False)[:2000], flush=True)

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Jeonnong9-Threads/1.0)",
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
    assert "4.99억" in PARTS[0][:80], "Upfront initial amount missing"
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
        "tag": "SEOUL REDEVELOPMENT  |  JEONNONG 9",
        "title": "전농9구역",
        "subtitle": "청량리역 생활권 · LH 공공재개발",
        "number": "4.99억",
        "unit": "플랫폼 표시 초기투자금",
        "rows": [
          "매매 호가 5.90억 원",
          "대지지분 13.31평",
          "2026.10.27 공개 매물 기록"
        ],
        "foot": "광고 표시액 · 보증금/대출 승계 및 실제 현금 별도 확인"
      },
      {
        "tag": "2026.03  |  PLAN REVISION",
        "title": "용적률 상향안",
        "subtitle": "2026년 3월 구의회 정비계획 변경안",
        "number": "270.09%",
        "unit": "상한용적률 변경안",
        "rows": [
          "기존 239.01% → 변경 270.09%",
          "최고 35층 → 39층",
          "차이 +31.08%p"
        ],
        "foot": "구의회 변경안이며 최종 인가·고시 확정치 아님"
      },
      {
        "tag": "2026.03  |  SUPPLY ESTIMATE",
        "title": "공급 및 사업성",
        "subtitle": "공식 변경안 · 일반분양은 단순 추정",
        "number": "1,161세대",
        "unit": "정비계획 변경안 공동주택",
        "rows": [
          "분양 943세대 · 임대 218세대",
          "토지등소유자 공개수 717명",
          "일반분양 단순추정 226세대"
        ],
        "foot": "226세대는 943-717 단순계산 · 최종 물량 아님"
      }
    ]
    originals=[]
    backgrounds=[("#102C3C","#134257"),("#132C37","#1D4D59"),("#2B303E","#393B53")]
    for i,card in enumerate(cards,1):
        dst = MEDIA / ("realestate-jeonnong9-20261029-" + str(i).zfill(2) + ".jpg")
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
        original=MEDIA/("jeonnong9-20261029-card-source-"+str(i)+".png")
        im.save(original,format="PNG")
        meta=preflight.normalize_image(original,dst,target_width=1080)
        originals.append((dst,meta))
    git("add",*[str(p.relative_to(ROOT)) for p,_ in originals])
    media_commit=commit_push("Add three sRGB 1080px Jeonnong9 Threads data cards")
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
    due = now + dt.timedelta(minutes=2)
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
    outbox_commit = commit_push("Queue approved Jeonnong9 5-part Threads with verified charts and blog URL")
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
