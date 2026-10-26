#!/usr/bin/env python3
"""Publish one user-requested Sangbong13 4-post friendly Threads chain.
Blog: https://blog.naver.com/comfunny_lj/224454397062
User authorized direct posting. Preserve original blog text facts; no new blog posts.
Fail closed on media integrity, text form, Oracle health and duplicate receipt.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import io
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
from PIL import Image
KST=dt.timezone(dt.timedelta(hours=9))
REPO="comfunnylj/telegram-market-feed"
KEY="realestate:sangbong13-blog-224454397062-20261026"
JOB_ID=str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY))
BLOG="https://blog.naver.com/comfunny_lj/224454397062"
ACCOUNT="genie_carrot"
TOPIC="부동산"
SOURCE="realestate"
OUTBOX=ROOT/"social-publisher/automation/realestate.json"
STATUS=ROOT/"social-publisher/diagnostics/sangbong13-20261026-threads-status.json"
MEDIA=ROOT/"social-publisher/media"
RECEIPT="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
OFFICIAL_RENDER="https://cleanup.seoul.go.kr/servlet/image?url=images%2Fassc%2F2025%2F09%2F202509251817021758791822028.jpg"
PARTS=json.loads(r'''["🏘️ 상봉13구역, 플랫폼 표시 초기투자금 3.11억부터! 👀\n\n서울 중랑구 망우동에 1,249세대 신축단지가 들어설 계획이야.\n\n✅ 공개 매매 호가 4.3억\n✅ 2026년 9월 조합설립인가 완료\n✅ 망우역·상봉역 생활권\n✅ 최고 37층 계획\n\n4억대 매물로 재개발에 접근할 수 있다는 게 눈에 띄지?\n\n📌 2026.10.26 공개 매물 기준. 초투는 광고 표시액이라 보증금·대출 승계와 실제 필요 현금은 따로 확인해야 해.\n\n(1/4)","🏗️ 상봉13구역의 진짜 관전 포인트는 일반분양이야.\n\n2025년 서울시 정비계획은 분양주택 979세대 중 일반분양 566세대, 소유자분양 409세대, 보류지 4세대로 잡았어.\n\n그런데 2026년 공개 조합원 수는 451명으로 달라졌지. 예전 공급계획을 지금 확정 물량처럼 보면 안 돼.\n\n💰 2025년 공식 추정비례율은 113.37%!\n\n숫자는 매력적이지만 공사비·분양가가 달라지면 비례율도 바뀌니까 꼭 같이 봐야 해.\n\n(2/4)","🚇 상봉13구역 입지는 망우역·상봉역을 함께 이용할 수 있다는 게 강점이야.\n\n망우역에서 경의중앙선·경춘선, 상봉역에서 7호선을 탈 수 있어. 코스트코 상봉점과 엔터식스 같은 상권도 가까운 편이고!\n\n🏫 망우초와 혜원여중·여고 등 학교도 주변에 있어. 실제 배정은 따로 확인해야 하지만 말이야.\n\n🚄 GTX-B 상봉역도 계획돼 있어. 다만 아직 개통 전이니 현재 교통과 미래 호재는 구분해서 봐야 해.\n\n(3/4)","💡 상봉13구역, 내가 눈여겨보는 이유는 이거야.\n\n✔ 1,249세대·최고 37층 재개발 계획\n✔ 조합설립인가 완료로 사업 단계 진전\n✔ 기존 철도·쇼핑시설이 갖춰진 생활권\n✔ 상봉9구역 복합개발과 GTX-B 기대감\n\n다만 4.3억 매물의 분양대상자격, 토지거래허가, 실제 초투와 추가분담금은 매수 전에 꼭 확인해야 해.\n\n조감도부터 사업비·일반분양 차이까지 블로그에 자세히 정리했어 👇\n\n(4/4)\nhttps://blog.naver.com/comfunny_lj/224454397062"]''')
FORMAL=re.compile(r"(?:입니다|습니다|합니다|됩니다|있습니다|없습니다|하세요|주세요|드립니다|해요|이에요|예요|네요|거예요|싶어요|바랍니다|십시오)")
state={"dedup_key":KEY,"job_id":JOB_ID,"account":ACCOUNT,
       "topic":TOPIC,"blog_url":BLOG,"expected_parts":4,"expected_images":3,
       "phase":"initialized"}

def run(*args):
    r=subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
    if r.returncode:
        raise RuntimeError("Command failed: "+str(args)+" "+r.stderr[-1100:])
    return r.stdout.strip()

def git(*args):
    return run("git",*args)

def commit_push(message):
    git("commit","-m",message)
    for attempt in range(8):
        try:
            git("push","origin","HEAD:main")
            return git("rev-parse","HEAD")
        except Exception as e:
            if attempt==7:
                raise
            git("pull","--rebase","origin","main")
            time.sleep(2)
    raise AssertionError("git push did not succeed")

def save(phase,**updates):
    state.update(phase=phase,checked_at=dt.datetime.now(KST).isoformat(timespec="seconds"),**updates)
    STATUS.parent.mkdir(parents=True,exist_ok=True)
    STATUS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    git("add",str(STATUS.relative_to(ROOT)))
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=ROOT).returncode:
        commit_push("record Sangbong13 Threads "+phase)
    print("STATE",phase,json.dumps(updates,ensure_ascii=False)[:2000],flush=True)

def fetch(url,timeout=28):
    req=urllib.request.Request(url,headers={
      "User-Agent":"Mozilla/5.0 (compatible; Sangbong13-Threads/1.0)",
      "Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return response.read(9*1024*1024)

def receipt():
    return json.loads(fetch(RECEIPT+"?fresh="+str(time.time_ns()),timeout=22))

def matched(r):
    return [j for j in r.get("jobs",[]) if j.get("dedup_key")==KEY or str(j.get("id",""))==JOB_ID]

def checks():
    assert len(PARTS)==4,"Need exactly four parts"
    lengths=[preflight.utf16_length(p) for p in PARTS]
    assert all(40<=n<=450 for n in lengths),("Post exceeds 450 UTF16 code units",lengths)
    assert all(FORMAL.search(p) is None for p in PARTS),"존댓말 탐지: 게시 불가"
    assert "3.11억" in PARTS[0] and PARTS[0].index("3.11억")<48,"First-screen investment missing"
    assert "4.3억" in PARTS[0] and "2026.10.26" in PARTS[0]
    assert BLOG in PARTS[-1] and PARTS[-1].rstrip().endswith(BLOG)
    assert all(BLOG not in p for p in PARTS[:-1])
    ctl=json.loads((ROOT/"social-publisher/automation/control.json").read_text())
    reg=json.loads((ROOT/"social-publisher/automation/tasks.json").read_text())
    task=next((t for t in reg["tasks"] if t["id"]==SOURCE),None)
    assert ctl.get("enabled") is True and ctl.get("bridge_id")=="sp-oracle-genie-carrot-v1"
    assert task and task["enabled"] is True and task["account"]==ACCOUNT and task["topic"]==TOPIC
    assert task["outbox"]=="realestate.json" and task["image_required"] is True
    assert task.get("max_utf16",0)>=max(lengths)
    out=json.loads(OUTBOX.read_text())
    assert out.get("protocol")==1 and out.get("source")==SOURCE
    assert not any(j.get("dedup_key")==KEY for j in out["jobs"]),"Existing key, no duplicate"
    assert not any("224454397062" in str(j.get("text","")) for j in out["jobs"]),"Blog URL already queued"
    return out

def build_images():
    source=MEDIA/"sangbong13_20261026_official_original.jpg"
    if source.exists():
        raise RuntimeError("Existing original image asset: review before any overwrite")
    raw=fetch(OFFICIAL_RENDER,timeout=38)
    with Image.open(io.BytesIO(raw)) as im:
        im.verify()
    with Image.open(io.BytesIO(raw)) as im:
        w,h=im.size
        assert w>=650 and h>=350 and im.format=="JPEG","Official artwork invalid"
        print("OFFICIAL_SOURCE",w,h,len(raw),flush=True)
    source.parent.mkdir(parents=True,exist_ok=True)
    source.write_bytes(raw)
    files=[
      source,
      MEDIA/"sangbong13_03_entry_price.png",
      MEDIA/"sangbong13_04_supply_scenarios.png",
    ]
    dests=[]
    for i,path in enumerate(files,1):
        assert path.exists() and path.stat().st_size>15000, "Expected chart image missing"
        dest=MEDIA/("realestate-sangbong13-20261026-"+str(i).zfill(2)+".jpg")
        assert not dest.exists(),"Destination already exists: do not duplicate/overwrite"
        meta=preflight.normalize_image(path,dest,target_width=1080)
        dests.append((dest,meta))
    git("add",*[str(p.relative_to(ROOT)) for p,meta in dests])
    # Do not upload original source bytes; only the selected resized post media.
    sha=commit_push("Add Sangbong13 three validated carousel images, official render first")
    refs=[]
    for path,meta in dests:
        url=f"https://raw.githubusercontent.com/{REPO}/{sha}/{path.relative_to(ROOT).as_posix()}"
        for n in range(6):
            try:
                remote=fetch(url,timeout=25)
                assert len(remote)==meta["size"],"Media size mismatch"
                assert hashlib.sha256(remote).hexdigest()==meta["sha256"],"Media hash mismatch"
                preflight.inspect_image(remote)
                break
            except Exception:
                if n==5:raise
                time.sleep(5)
        refs.append({"url":url,"sha256":meta["sha256"],"size":meta["size"]})
    return sha,refs

def main():
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("pull","--ff-only","origin","main")
    checks()
    first=receipt()
    preflight.validate_receipt(first,source=SOURCE,images=3)
    assert not matched(first),"Oracle already has this key; no requeue"
    save("health_and_banmal_checked",lengths=[preflight.utf16_length(p) for p in PARTS],
         publisher_version=first.get("publisher_version"))
    media_commit,images=build_images()
    save("remote_media_verified",media_commit=media_commit,
         images=[{"sha256":x["sha256"],"size":x["size"]} for x in images])
    now=dt.datetime.now(KST)
    due=now+dt.timedelta(minutes=5)
    job={"dedup_key":KEY,"created_at":now.isoformat(timespec="seconds"),
         "not_before":due.isoformat(timespec="seconds"),
         "expires_at":(due+dt.timedelta(minutes=5)).isoformat(timespec="seconds"),
         "topic":TOPIC,"text":"".join(PARTS),"parts":PARTS,"images":images}
    # Two final gates: validated exact payload and live receiver state.
    git("pull","--ff-only","origin","main")
    before=checks()
    preflight.validate_job(job,existing_jobs=before["jobs"],remote=True)
    current=receipt()
    preflight.validate_receipt(current,source=SOURCE,images=3)
    assert not matched(current),"Oracle now has this job: do not submit twice"
    before["jobs"].append(job)
    OUTBOX.write_text(json.dumps(before,ensure_ascii=False,indent=2)+"\n")
    git("add",str(OUTBOX.relative_to(ROOT)))
    commit=commit_push("Queue approved Sangbong13 four casual banmal Threads with three verified images")
    persisted=json.loads(git("show",commit+":social-publisher/automation/realestate.json"))
    exact=[j for j in persisted["jobs"] if j.get("dedup_key")==KEY]
    assert len(exact)==1 and exact[0]==job,"Outbox write not verified"
    save("queued",outbox_commit=commit,not_before=job["not_before"],expires_at=job["expires_at"])
    end=time.monotonic()+680
    previous="queued"
    while time.monotonic()<end:
        try:
            r=receipt()
            found=matched(r)
            if found:
                j=found[0]
                status=str(j.get("status"))
                if status!=previous:
                    save("receipt_"+status,receipt_status=status,receipt_image_count=j.get("image_count"),
                         published_count=sum(p.get("status")=="published" for p in j.get("parts",[])))
                    previous=status
                result=preflight.classify_result(r,KEY,4,3)
                if result["decision"]=="confirmed":
                    save("published",root=result["links"][0],links=result["links"],
                         verified_parts=4,verified_images=3,verified_topic=TOPIC)
                    return
                if result["decision"] in ("hold","investigate"):
                    save("requires_reconciliation",reason=result.get("reason"),
                         receipt_status=status,receipt_parts=j.get("parts",[]))
                    return
                print("RECEIPT",status,flush=True)
            else:
                print("AWAITING_ORACLE",flush=True)
        except Exception as exc:
            print("RECEIPT_TRANSIENT",type(exc).__name__,str(exc)[:220],flush=True)
        time.sleep(18)
    save("verification_pending",note="No duplicate retry. Inspect stable job on Oracle.")

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("PUBLISH_ERROR",type(exc).__name__,str(exc),flush=True)
        try:save("error_review_required",error=type(exc).__name__+": "+str(exc)[:650])
        except Exception as other:print("STATUS_SAVE_ERROR",type(other).__name__,str(other)[:230],flush=True)
        raise
