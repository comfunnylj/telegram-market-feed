#!/usr/bin/env python3
"""One-time user-authorized Threads replacement: deleted previous Seongbuk1 post.
Posts exactly four friendly informal Korean parts, preserves original immutable job,
reuses preflight-verified normalized images; fail-closed no duplicate retry.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"social-publisher/automation"))
import preflight
KST=dt.timezone(dt.timedelta(hours=9))
KEY="realestate:seongbuk1-20261025-friendly-republish1"
PREVIOUS_KEY="realestate:seongbuk1-20261025-blog-224453159178"
ACCOUNT="genie_carrot"
TOPIC="부동산"
SOURCE="realestate"
JOB_ID=str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY))
OUTBOX=ROOT/"social-publisher/automation/realestate.json"
STATUS=ROOT/"social-publisher/diagnostics/seongbuk1-20261025-friendly-republish1-status.json"
RECEIPT="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
PARTS=json.loads(r'''["🏘️ 서울 성북1구역, 초기투자금 약 3.03억부터!\n\n매매 호가는 4.4억! 이 정도 금액으로 2,086세대 공공재개발에 관심 가져볼 수 있다는 게 눈에 띄어. 👀\n\n✅ GS건설 시공사 선정\n✅ LH와 공동사업시행 협약\n✅ 4호선 한성대입구역 생활권\n\n도심 가까운 성북동이 신축 대단지로 바뀔 준비를 하고 있어!\n\n📌 2026.10.25 매물 기준. 초투 3.03억은 플랫폼 표시값이야. 실제 승계 조건과 취득비용은 따로 확인해야 해.\n\n(1/4)","🏗️ 성북1구역, 20년 넘게 지지부진했던 사업이 드디어 속도를 내고 있어.\n\n✔ 2024년 정비구역 지정\n✔ 2025년 GS건설 선정\n✔ 2026년 LH·GS건설 공동사업시행 협약\n\n전체 2,086세대 중 분양주택은 1,668세대야.\n\n서울시 공개 토지등소유자 1,192명에게 1세대씩 배정한다고 단순 계산하면 잠정 일반분양은 476세대!\n\n물론 실제 분양대상자 수에 따라 달라질 추정치야.\n\n(2/4)","🚇 성북1구역은 서울 도심 생활권이라는 게 매력이야.\n\n4호선 한성대입구역을 이용하면 혜화·동대문·서울역으로 이동하기 좋고, 주변에는 성북초·홍대부중·동구여중 등이 있어.\n\n서울대병원, 고려대 안암병원 같은 대형병원도 도심권에서 이용할 수 있지.\n\n🌳 게다가 2026년 10월엔 가까운 성북3구역의 약 1,070세대 신속통합기획까지 확정됐어!\n\n두 사업이 진행되면 성북동의 모습도 꽤 달라질 것 같아.\n\n(3/4)","💡 성북1구역을 눈여겨볼 이유를 정리하면?\n\n✅ 2,086세대 신축 대단지 계획\n✅ GS건설·LH 참여\n✅ 한성대입구역 생활권\n✅ 성북3구역 개발 추진\n✅ 4억 원대 공개 매물\n\n주변 삼선푸르지오 84㎡는 2026년 8월 약 11억에 거래된 사례도 있어.\n\n다만 매수 전엔 분양자격·추가분담금·총투입금을 꼭 확인해야 해.\n\n📖 조감도와 자세한 분석은 블로그에 정리했어 👇\nhttps://blog.naver.com/comfunny_lj/224453159178\n\n(4/4)"]''')
IMAGES=json.loads(r'''[{"url":"https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/b4858b53f145f48da4cda7217449a294e6c37f20/social-publisher/media/realestate-seongbuk1-20261025-01.jpg","sha256":"0fdff1027a04636941ad78bd92bd86f0518c14469c63356ae43b299e94fc3362","size":262647},{"url":"https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/b4858b53f145f48da4cda7217449a294e6c37f20/social-publisher/media/realestate-seongbuk1-20261025-02.jpg","sha256":"167ee4f0780f007d1b25086e6ff6c8a5fd3991cb83ab7d0c0f84b07e5dc50938","size":98829},{"url":"https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/b4858b53f145f48da4cda7217449a294e6c37f20/social-publisher/media/realestate-seongbuk1-20261025-03.jpg","sha256":"735ed7dbb2201891d2cbe99b52d1b0276dede52ce248818fdfab067baa9e00e6","size":132597}]''')
FORMAL=re.compile(r"(?:입니다|습니다|합니다|됩니다|있습니다|없습니다|하세요|주세요|드립니다|해요|이에요|예요|네요|거예요|싶어요|바랍니다)")
state={"dedup_key":KEY,"job_id":JOB_ID,"replaces_deleted":PREVIOUS_KEY,
       "account":ACCOUNT,"topic":TOPIC,"expected_parts":4,"expected_images":3,
       "phase":"starting"}

def git(*args):
    p=subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True)
    if p.returncode:
        raise RuntimeError("git "+str(args)+" "+p.stderr[-1000:])
    return p.stdout.strip()

def git_commit_push(message):
    git("commit","-m",message)
    for retry in range(3):
        try:
            git("push","origin","HEAD:main")
            return git("rev-parse","HEAD")
        except Exception:
            if retry==2:raise
            git("pull","--rebase","origin","main")

def save(phase,**extra):
    state.update(phase=phase,checked_at=dt.datetime.now(KST).isoformat(timespec="seconds"),**extra)
    STATUS.parent.mkdir(parents=True,exist_ok=True)
    STATUS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n")
    git("add",str(STATUS.relative_to(ROOT)))
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=ROOT).returncode:
        git_commit_push("record Seongbuk1 friendly Threads republish "+phase)
    print("STATUS",phase,json.dumps(extra,ensure_ascii=False)[:1500],flush=True)

def fetch_json():
    req=urllib.request.Request(RECEIPT+"?fresh="+str(time.time_ns()),
               headers={"User-Agent":"Seongbuk1-Republish-Verified/1.0","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=22) as r:
        return json.load(r)

def matched(receipt):
    return [x for x in receipt.get("jobs",[]) if x.get("dedup_key")==KEY or str(x.get("id",""))==JOB_ID]

def checks():
    assert len(PARTS)==4
    assert all(10<preflight.utf16_length(p)<=450 for p in PARTS)
    assert all(not FORMAL.search(p) for p in PARTS), "Honorific grammar detected, refuse publication"
    assert "3.03억" in PARTS[0] and PARTS[0].index("3.03억")<60
    assert "224453159178" in PARTS[-1]
    assert len(IMAGES)==3 and "seongbuk1" in IMAGES[0]["url"]
    ctl=json.loads((ROOT/"social-publisher/automation/control.json").read_text())
    reg=json.loads((ROOT/"social-publisher/automation/tasks.json").read_text())
    task=next((x for x in reg["tasks"] if x["id"]=="realestate"),None)
    assert ctl["enabled"] is True and ctl["bridge_id"]=="sp-oracle-genie-carrot-v1"
    assert task and task["enabled"] and task["account"]==ACCOUNT and task["topic"]==TOPIC
    assert task["outbox"]=="realestate.json" and task["max_utf16"]>=max(map(preflight.utf16_length,PARTS))
    assert task["image_required"] is True
    prev=json.loads(OUTBOX.read_text())
    assert prev["source"]=="realestate"
    assert any(x.get("dedup_key")==PREVIOUS_KEY for x in prev["jobs"]), "Previous job must be preserved for audit"
    assert not any(x.get("dedup_key")==KEY for x in prev["jobs"]), "Replacement already queued: stop"
    return prev

def main():
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("pull","--ff-only","origin","main")
    try:
        checks()
    except AssertionError as ex:
        save("stopped_local_preflight",message=str(ex))
        return
    live=fetch_json()
    preflight.validate_receipt(live,source=SOURCE,images=3)
    if matched(live):
        save("stopped_already_received",receipt_state=[x.get("status") for x in matched(live)])
        return
    # The original entry was published, then explicitly deleted by user.
    # The new, one-time replacement key is user-authorized; original audit trail preserved.
    save("text_and_bridge_verified",part_lengths=[preflight.utf16_length(x) for x in PARTS])
    now=dt.datetime.now(KST)
    due=now+dt.timedelta(minutes=5)
    job={
      "dedup_key":KEY,
      "created_at":now.isoformat(timespec="seconds"),
      "not_before":due.isoformat(timespec="seconds"),
      "expires_at":(due+dt.timedelta(minutes=5)).isoformat(timespec="seconds"),
      "topic":TOPIC,
      "text":"".join(PARTS),
      "parts":PARTS,
      "images":IMAGES,
    }
    # Must fetch each immutable source and verify real remote bytes before queueing.
    existing=checks()
    verified=preflight.validate_job(job,existing_jobs=existing["jobs"],remote=True)
    save("remote_images_verified",images=verified["image_metadata"])
    git("pull","--ff-only","origin","main")
    before=checks()
    live=fetch_json()
    preflight.validate_receipt(live,source=SOURCE,images=3)
    if matched(live):
        save("stopped_already_received")
        return
    before["jobs"].append(job)
    OUTBOX.write_text(json.dumps(before,ensure_ascii=False,indent=2)+"\n")
    git("add",str(OUTBOX.relative_to(ROOT)))
    commit=git_commit_push("queue user-authorized Seongbuk1 friendly Korean 4-post replacement")
    # Readback existing GitHub job before claiming it was accepted.
    committed=git("show",commit+":social-publisher/automation/realestate.json")
    confirm=json.loads(committed)
    exact=[x for x in confirm["jobs"] if x["dedup_key"]==KEY]
    assert len(exact)==1 and exact[0]==job
    save("queued",not_before=job["not_before"],outbox_commit=commit)
    end=time.monotonic()+630
    last="queued"
    while time.monotonic()<end:
        try:
            current=fetch_json()
            hits=matched(current)
            if hits:
                rec=hits[0]
                status=str(rec.get("status"))
                if status!=last:
                    save("receipt_"+status,receipt_image_count=rec.get("image_count"),
                         published_count=sum(x.get("status")=="published" for x in rec.get("parts",[])))
                    last=status
                verdict=preflight.classify_result(current,KEY,4,3)
                if verdict["decision"]=="confirmed":
                    save("published",root=verdict["links"][0],links=verdict["links"],
                         verified_parts=4,verified_images=3,verified_topic=TOPIC)
                    return
                if verdict["decision"] in ("hold","investigate"):
                    save("requires_reconciliation",receipt_status=status,
                         reason=verdict.get("reason"),parts=rec.get("parts",[]))
                    return
                print("PUBLISH_STATE",status,flush=True)
            else:
                print("AWAITING_RECEIPT",flush=True)
        except Exception as exc:
            print("RECEIPT_TRANSIENT",type(exc).__name__,str(exc)[:200],flush=True)
        time.sleep(18)
    save("verification_pending",note="Do not submit another request under another dedup key")

if __name__=="__main__":
    try:
        main()
    except Exception as err:
        print("PIPELINE_EXCEPTION",type(err).__name__,str(err),flush=True)
        try:save("error_review_required",error=type(err).__name__+": "+str(err)[:600])
        except Exception as e:print("STATUS_WRITE_FAILED",type(e).__name__,str(e)[:300],flush=True)
        raise
