#!/usr/bin/env python3
"""One-time user-approved Seongbuk1 Threads delivery via existing Oracle bridge.
Four approved posts; URL added to post 4. No token/API secrets in this file.
Fail closed on media, health, duplicate, receipt or provenance errors.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"social-publisher/automation"))
import preflight
KST=dt.timezone(dt.timedelta(hours=9))
REPO="comfunnylj/telegram-market-feed"
KEY="realestate:seongbuk1-20261025-blog-224453159178"
TOPIC="부동산"
OUTBOX=ROOT/"social-publisher/automation/realestate.json"
STATUS=ROOT/"social-publisher/diagnostics/seongbuk1-20261025-threads-result.json"
MEDIA=ROOT/"social-publisher/media"
RECEIPT="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
JOB_ID=str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY))
PARTS=[
"""🏘️ 서울 성북1구역, 초기투자금 약 3.03억 원부터!

✅ 매매 호가 4.4억 원
✅ 2,086세대 공공재개발
✅ GS건설 시공사 선정
✅ 4호선 한성대입구역 생활권

서울 도심 접근성이 좋은 성북동에 2,000세대급 신축단지가 추진되고 있습니다.

📌 2026.10.25 공개 매물 기준. 초기투자금은 플랫폼 표시값이며, 실제 승계조건과 취득비용은 별도 확인이 필요합니다.""",
"""🏗️ 20년 넘게 지연됐던 성북1구역, 이제 사업이 움직이고 있습니다.

✅ 2024년 정비구역 지정
✅ 2025년 GS건설 시공사 선정
✅ 2026년 LH·GS건설 공동사업시행 협약

전체 2,086세대 중 분양주택은 1,668세대입니다.

서울시 공개 토지등소유자 1,192명을 기준으로 계산하면 잠정 일반분양은 약 476세대!

최종 분양대상자 수에 따라 달라지는 추정치지만, 앞으로 사업성을 판단할 핵심 숫자입니다.""",
"""🚇 성북1구역의 강점은 입지입니다.

4호선 한성대입구역 생활권으로 혜화·동대문·서울역 접근이 편리합니다.

주변에는 서울성북초, 홍대부중, 동구여중 등 학교가 있고, 서울대병원과 고려대 안암병원도 이용할 수 있는 도심 생활권입니다.

🌳 2026년 10월에는 인근 성북3구역 약 1,070세대 신속통합기획도 확정됐습니다.

두 사업이 진행되면 성북동 일대의 주거환경 변화도 기대됩니다.""",
"""💡 성북1구역을 눈여겨볼 이유!

✔ 서울 도심 접근성
✔ GS건설 참여 2,086세대 계획
✔ 인근 성북3구역 개발 추진
✔ 4억 원대 공개 매물 존재

주변 삼선푸르지오 84㎡는 2026년 8월 약 11억 원에 거래된 사례도 있습니다.

다만 실제 투자 판단에서는 분양자격과 추가분담금, 총투입금 확인이 중요합니다.

📖 성북1구역 재개발 상세 분석
https://blog.naver.com/comfunny_lj/224453159178"""
]
assert len(PARTS)==4 and all(0<preflight.utf16_length(p)<=450 for p in PARTS)
assert len(PARTS[0])>10 and "3.03억" in PARTS[0] and "224453159178" in PARTS[3]
state={"dedup_key":KEY,"job_id":JOB_ID,"account":"genie_carrot","topic":TOPIC,
       "parts":len(PARTS),"stage":"initialized","image_count":3}

def run(*args):
    r=subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
    if r.returncode:
        raise RuntimeError(" ".join(args)+" :: "+r.stderr[-900:])
    return r.stdout.strip()

def git(*args):
    return run("git",*args)

def commit_push(msg):
    git("commit","-m",msg)
    for attempt in range(3):
        try:
            git("push","origin","HEAD:main")
            return git("rev-parse","HEAD")
        except RuntimeError:
            if attempt==2:
                raise
            git("pull","--rebase","origin","main")
    raise RuntimeError("git push unavailable")

def save(stage, **updates):
    state.update(stage=stage,checked_at=dt.datetime.now(KST).isoformat(timespec="seconds"),**updates)
    STATUS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n")
    git("add",str(STATUS.relative_to(ROOT)))
    diff=subprocess.run(["git","diff","--cached","--quiet"],cwd=ROOT)
    if diff.returncode:
        commit_push("record Seongbuk1 Threads delivery: "+stage)
    print("STAGE",stage,json.dumps(updates,ensure_ascii=False)[:3000],flush=True)

def get(url,timeout=30):
    r=urllib.request.Request(url,headers={
      "User-Agent":"Threads-Seongbuk1-20261025/1.0","Cache-Control":"no-cache"})
    with urllib.request.urlopen(r,timeout=timeout) as h:
        return h.read(10*1024*1024)

def receipt():
    return json.loads(get(RECEIPT+"?nocache="+str(time.time_ns()),timeout=25))

def existing(rec):
    return [j for j in rec.get("jobs",[]) if j.get("dedup_key")==KEY or str(j.get("id",""))==JOB_ID]

def local_checks():
    ctl=json.loads((ROOT/"social-publisher/automation/control.json").read_text())
    cfg=json.loads((ROOT/"social-publisher/automation/tasks.json").read_text())
    task=next((x for x in cfg["tasks"] if x["id"]=="realestate"),None)
    assert ctl.get("enabled") is True and ctl.get("bridge_id")=="sp-oracle-genie-carrot-v1", "control disabled"
    assert task and task["enabled"] and task["account"]=="genie_carrot"
    assert task["topic"]==TOPIC and task["outbox"]=="realestate.json"
    assert task.get("max_posts",0)>=4 and task.get("max_utf16",0)>=max(map(preflight.utf16_length,PARTS))
    assert task.get("image_required") is True
    out=json.loads(OUTBOX.read_text())
    assert out["source"]=="realestate" and out["protocol"]==1
    for job in out["jobs"]:
        if job["dedup_key"]==KEY:
            return "already_queued"
        if "224453159178" in job.get("text",""):
            return "possible_duplicate_link"
    return "ready"

def source_images():
    from PIL import Image
    import io
    # The first photo must be a verified Seongbuk1 rendering, not an infographic.
    # This 2025 LH/GS architectural rendering was identified in the prior approved blog.
    # Prefer it if its geometry is adequate; fall back to 2024 official Seoul plan art.
    sources=[
      ("2025 LH/GS image","https://img.hankyung.com/photo/202512/01.42747445.1.jpg"),
    ]
    src=None
    for description,url in sources:
        try:
            blob=get(url,timeout=40)
            with Image.open(io.BytesIO(blob)) as im:
                im.verify()
            with Image.open(io.BytesIO(blob)) as im:
                if im.width<650 or im.height<350:
                    raise ValueError("source too low-resolution")
                assert len(blob)>20000
            p=ROOT/"social-publisher/diagnostics/seongbuk1-photo-source.jpg"
            p.write_bytes(blob)
            src=p
            print("RENDER_SOURCE",description,len(blob),flush=True)
            break
        except Exception as exc:
            print("RENDER_CANDIDATE_FAILED",description,type(exc).__name__,str(exc)[:180],flush=True)
    if src is None:
        src=MEDIA/"seongbuk1_04_official_render.png"
        assert src.exists(), "Neither official rendering available"
        print("RENDER_SOURCE 2024 official Seoul plan",flush=True)
    return [src,
            MEDIA/"seongbuk1_01_entry_price.png",
            MEDIA/"seongbuk1_02_general_sale_scenarios.png"]

def main():
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("pull","--ff-only","origin","main")
    existing_local=local_checks()
    if existing_local!="ready":
        save("stopped_"+existing_local,note="No duplicate request or retry")
        return
    first=receipt()
    preflight.validate_receipt(first,source="realestate",images=3)
    if existing(first):
        save("stopped_existing_receipt",receipt_status=[j.get("status") for j in existing(first)])
        return
    save("health_checked",publisher_version=first.get("publisher_version"))
    source=source_images()
    outputs=[]
    for i,p in enumerate(source,1):
        if not p.exists():
            raise FileNotFoundError(str(p))
        dest=MEDIA/("realestate-seongbuk1-20261025-"+str(i).zfill(2)+".jpg")
        if dest.exists():
            raise ValueError("Asset already exists: do not change an earlier accepted submission")
        info=preflight.normalize_image(p,dest,target_width=1080)
        assert 20000<=info["size"]<=8*1024*1024, "Image too small/large"
        outputs.append((dest,info))
    git("add",*[str(p.relative_to(ROOT)) for p,info in outputs])
    sha=commit_push("add normalized Seongbuk1 3-image Threads carousel")
    refs=[]
    for p,info in outputs:
        url=f"https://raw.githubusercontent.com/{REPO}/{sha}/{p.relative_to(ROOT).as_posix()}"
        for attempt in range(5):
            try:
                body=get(url,timeout=25)
                assert len(body)==info["size"] and hashlib.sha256(body).hexdigest()==info["sha256"]
                preflight.inspect_image(body)
                break
            except Exception:
                if attempt==4:raise
                time.sleep(5)
        refs.append({"url":url,"sha256":info["sha256"],"size":info["size"]})
    save("images_verified",image_commit=sha,remote_image_hashes=[x["sha256"] for x in refs])
    now=dt.datetime.now(KST)
    due=now+dt.timedelta(minutes=5)
    job={"dedup_key":KEY,"created_at":now.isoformat(timespec="seconds"),
         "not_before":due.isoformat(timespec="seconds"),
         "expires_at":(due+dt.timedelta(minutes=5)).isoformat(timespec="seconds"),
         "topic":TOPIC,"text":"".join(PARTS),"parts":PARTS,"images":refs}
    git("pull","--ff-only","origin","main")
    if local_checks()!="ready":
        save("stopped_conflicting_outbox",note="New concurrent entry detected")
        return
    preflight.validate_job(job,existing_jobs=json.loads(OUTBOX.read_text())["jobs"],remote=True)
    second=receipt()
    preflight.validate_receipt(second,source="realestate",images=3)
    if existing(second):
        save("stopped_existing_receipt",receipt_status=[j.get("status") for j in existing(second)])
        return
    # Only after ALL preflight gates is the immutable approved envelope queued.
    current=json.loads(OUTBOX.read_text())
    current["jobs"].append(job)
    OUTBOX.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n")
    git("add",str(OUTBOX.relative_to(ROOT)))
    commit=commit_push("queue approved Seongbuk1 4-part Threads with 3 checked images")
    readback=json.loads(get(f"https://raw.githubusercontent.com/{REPO}/{commit}/social-publisher/automation/realestate.json"))
    matches=[j for j in readback["jobs"] if j["dedup_key"]==KEY]
    assert len(matches)==1 and matches[0]==job, "Cannot verify accepted immutable outbox write"
    save("queued",outbox_commit=commit,not_before=job["not_before"],expires_at=job["expires_at"])
    # After queueing do NOT requeue on any ambiguous receipt.
    end=time.monotonic()+660
    previous="queued"
    while time.monotonic()<end:
        try:
            r=receipt()
            found=existing(r)
            if found:
                j=found[0]
                status=j.get("status")
                if status != previous:
                    save("receipt_"+str(status),receipt_image_count=j.get("image_count"),
                         published_count=sum(p.get("status")=="published" for p in j.get("parts",[])))
                    previous=status
                result=preflight.classify_result(r,KEY,4,3)
                if result["decision"]=="confirmed":
                    save("published",root=result["links"][0],links=result["links"],
                         verified_parts=4,verified_images=3,verified_topic=TOPIC)
                    return
                if result["decision"] in ("hold","investigate"):
                    save("requires_reconciliation",reason=result.get("reason"),
                         receipt_status=status,parts=j.get("parts"))
                    return
                print("RECEIPT_STATUS",status,flush=True)
            else:
                print("AWAITING_INTAKE",flush=True)
        except Exception as exc:
            print("RECEIPT_TRANSIENT",type(exc).__name__,str(exc)[:180],flush=True)
        time.sleep(18)
    save("verification_pending",note="No new key or automatic retry. Check exact stable key.")

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("PIPELINE_ERROR",type(exc).__name__,str(exc),flush=True)
        try:save("execution_error_review_required",error=type(exc).__name__+": "+str(exc)[:500])
        except Exception as e: print("STATUS_WRITE_ERROR",str(e)[:200],flush=True)
        raise
