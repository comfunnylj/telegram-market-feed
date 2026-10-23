#!/usr/bin/env python3
"""One-shot approved Myeonmok9 two-image carousel and linked Threads.
All actions take place through existing realestate Oracle bridge.
Never publish reduced images or text only. Never retry same accepted dedup key.
"""
import datetime as dt
import hashlib
import io
import json
import subprocess
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

ROOT=Path.cwd()
BRIDGE_ID="sp-oracle-genie-carrot-v1"
SOURCE="realestate"
TOPIC="부동산"
KEY="realestate:myeonmok9-20261023"
ACCOUNT="genie_carrot"
BASE="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
KST=dt.timezone(dt.timedelta(hours=9))
DRAFT=ROOT/"social-publisher/diagnostics/myeonmok9-20261023-draft.json"
OUTBOX=ROOT/"social-publisher/automation/realestate.json"
STATUS=ROOT/"social-publisher/diagnostics/myeonmok9-20261023-result.json"
MEDIA=ROOT/"social-publisher/media"
REPO="comfunnylj/telegram-market-feed"
JOB_ID=str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY))
state={"dedup_key":KEY,"job_id":JOB_ID,"status":"starting","account":ACCOUNT,"topic":TOPIC,"image_count":2}

def git(*args, check=True):
    proc=subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True)
    if check and proc.returncode!=0:
        raise RuntimeError("git "+str(args)+" "+proc.stderr[-600:])
    return proc.stdout.strip()

def remote(url,timeout=30):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; SocialPublisherVerifiedAsset/1.0)","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=r.read(9*1024*1024)
        if len(data)>=9*1024*1024:raise ValueError("response too big")
        return data

def write_state(stage,**extra):
    state.update({"status":stage,"checked_at":dt.datetime.now(KST).isoformat(timespec="seconds"),**extra})
    STATUS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n")
    git("add",str(STATUS.relative_to(ROOT)))
    if git("diff","--cached","--quiet",check=False) is None:pass
    pending=subprocess.run(["git","diff","--cached","--quiet"],cwd=ROOT)
    if pending.returncode!=0:
        git("commit","-m","Record Myeonmok9 Threads "+stage)
        for retry in range(3):
            try:
                git("push","origin","HEAD:main")
                break
            except Exception:
                if retry==2:raise
                git("pull","--rebase","origin","main")
    print("STATE",stage,json.dumps(extra,ensure_ascii=False)[:2000],flush=True)

def receipt(require_active=True):
    j=json.loads(remote(BASE+"?t="+str(time.time_ns()),timeout=18))
    bridge=j.get("bridge") or {}
    if j.get("protocol")!=1 or j.get("account")!=ACCOUNT:raise ValueError("receipt account/protocol mismatch")
    if bridge.get("bridge_id")!=BRIDGE_ID or bridge.get("enabled") is not True:
        raise ValueError("Oracle bridge mismatch / disabled")
    if bridge.get("last_error") or (bridge.get("task_errors") or {}).get(SOURCE):
        raise ValueError("Oracle error "+str(bridge.get("last_error"))+"/"+str(bridge.get("task_errors")))
    if require_active:
        last=bridge.get("last_success_at")
        if not isinstance(last,(int,float)) or time.time()-last>600:
            raise ValueError("Oracle stale health")
        ver=str(j.get("publisher_version") or "")
        caps=j.get("capabilities") or {}
        if (not ver.startswith(("0.4","0.5","0.6","0.7","0.8","0.9","1.","2."))) or caps.get("carousel") is not True or int(caps.get("max_images") or 0)<2:
            raise ValueError("Two-photo carousel capability not verified: "+str(ver)+" "+str(caps))
        task=next((t for t in bridge.get("tasks",[]) if t.get("id")==SOURCE),None)
        if not task or task.get("enabled") is not True or task.get("account")!=ACCOUNT or task.get("topic")!=TOPIC or task.get("outbox")!="realestate.json":
            raise ValueError("Oracle task mismatch")
    return j

def found(j):
    return next((it for it in j.get("jobs",[]) if it.get("dedup_key")==KEY or str(it.get("id"))==JOB_ID),None)

def push_staged(message):
    git("commit","-m",message)
    for i in range(3):
        try:
            git("push","origin","HEAD:main")
            return git("rev-parse","HEAD")
        except Exception:
            if i==2:raise
            git("pull","--rebase","origin","main")

def get_verified_images():
    from PIL import Image
    import pillow_avif
    draft=json.loads(DRAFT.read_text())
    assert len(draft["images"])==2
    files=[]
    for i,item in enumerate(draft["images"],1):
        urls=[item["url"]]
        if i==2:
            urls+= [
               "https://thumb.mt.co.kr/cdn-cgi/image/f=jpg/21/2025/12/2025120709540126018_1.jpg",
               "https://thumb.mt.co.kr/21/2025/12/2025120709540126018_1.jpg",
               "https://image.mt.co.kr/21/2025/12/2025120709540126018_1.jpg",
            ]
        last_err=None
        for url in urls:
            try:
                raw=remote(url,timeout=35)
                if len(raw)<18000:raise ValueError("image too small "+str(len(raw)))
                with Image.open(io.BytesIO(raw)) as im:
                    fmt=im.format
                    width,height=im.size
                    im.verify()
                if width<450 or height<330:raise ValueError("image dimension too small")
                with Image.open(io.BytesIO(raw)) as im:
                    im.load()
                    out=MEDIA/("realestate-myeonmok9-20261023-"+str(i).zfill(2)+".jpg")
                    if out.exists():raise ValueError("asset already exists: do not overwrite")
                    im.convert("RGB").save(out,format="JPEG",quality=94,optimize=True)
                blob=out.read_bytes()
                if not (18000<len(blob)<=8*1024*1024):raise ValueError("converted file size invalid")
                with Image.open(out) as check:
                    check.verify()
                info={"path":out,"sha256":hashlib.sha256(blob).hexdigest(),"size":len(blob),
                      "source_url":url,"width":width,"height":height,"original_format":fmt}
                print("IMAGE_READY",i,info["sha256"],info["size"],width,height,url,flush=True)
                files.append(info)
                break
            except Exception as e:
                last_err=e
                print("IMAGE_SOURCE_FAILED",i,url,type(e).__name__,str(e)[:250],flush=True)
        else:
            raise RuntimeError("Image "+str(i)+" could not be verified: "+str(last_err))
    return files

def main():
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("pull","--ff-only","origin","main")
    draft=json.loads(DRAFT.read_text())
    if draft.get("dedup_key")!=KEY or draft.get("topic")!=TOPIC or draft.get("source")!=SOURCE:
        raise ValueError("Draft identity invalid")
    parts=draft["parts"]
    if not parts or len(parts)!=6 or "".join(parts)!=draft["text"]:raise ValueError("invalid draft/parts")
    for p in parts:
        if not p or len(p.encode("utf-16-le"))//2>450 or len(p)>450:
            raise ValueError("part length out of range")
    local_control=json.loads((ROOT/"social-publisher/automation/control.json").read_text())
    registry=json.loads((ROOT/"social-publisher/automation/tasks.json").read_text())
    task=next(t for t in registry["tasks"] if t["id"]==SOURCE)
    if local_control.get("bridge_id")!=BRIDGE_ID or local_control.get("enabled") is not True:
        raise ValueError("local control mismatch")
    if task.get("enabled") is not True or task.get("account")!=ACCOUNT or task.get("topic")!=TOPIC or task.get("image_required") is not True or task.get("max_utf16",0)<max(len(p.encode("utf-16-le"))//2 for p in parts):
        raise ValueError("local task mismatch")
    original=json.loads(OUTBOX.read_text())
    if any(it.get("dedup_key")==KEY for it in original["jobs"]):
        write_state("already_queued",note="Existing entry must be checked, not retried")
        return
    before=receipt()
    if found(before):
        write_state("already_received",existing_job=found(before))
        return
    MEDIA.mkdir(parents=True,exist_ok=True)
    images=get_verified_images()
    # Two files from verified original image sources in the immutable GitHub commit.
    git("add",str(images[0]["path"].relative_to(ROOT)),str(images[1]["path"].relative_to(ROOT)))
    asset_commit=push_staged("Add two verified official Myeonmok9 original-source carousel images")
    for i,info in enumerate(images,1):
        info["url"]="https://raw.githubusercontent.com/"+REPO+"/"+asset_commit+"/"+info["path"].relative_to(ROOT).as_posix()
        for attempt in range(5):
            try:
                uploaded=remote(info["url"],20)
                if len(uploaded)!=info["size"] or hashlib.sha256(uploaded).hexdigest()!=info["sha256"]:
                    raise ValueError("immutable image mismatch")
                break
            except Exception:
                if attempt==4:raise
                time.sleep(4)
        print("IMMUTABLE_IMAGE_VERIFIED",i,info["url"],flush=True)
    write_state("images_verified",asset_commit=asset_commit,image_hashes=[i["sha256"] for i in images],image_sizes=[i["size"] for i in images])
    refreshed=receipt()
    if found(refreshed):
        write_state("already_received",existing_job=found(refreshed))
        return
    git("pull","--ff-only","origin","main")
    current=json.loads(OUTBOX.read_text())
    if any(it.get("dedup_key")==KEY for it in current["jobs"]):
        write_state("already_queued",note="Outbox contains same key")
        return
    now=dt.datetime.now(KST)
    due=now+dt.timedelta(minutes=5)
    expires=due+dt.timedelta(seconds=min(int(task.get("late_grace_seconds",300)),300))
    job={
      "dedup_key":KEY,
      "created_at":now.isoformat(timespec="seconds"),
      "not_before":due.isoformat(timespec="seconds"),
      "expires_at":expires.isoformat(timespec="seconds"),
      "topic":TOPIC,
      "text":draft["text"],
      "parts":parts,
      "images":[{"url":i["url"],"sha256":i["sha256"],"size":i["size"]} for i in images]
    }
    current["jobs"].append(job)
    OUTBOX.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n")
    git("add",str(OUTBOX.relative_to(ROOT)))
    outbox_commit=push_staged("Queue approved Myeonmok9 two-image six-part Threads post")
    check=json.loads(remote("https://raw.githubusercontent.com/"+REPO+"/"+outbox_commit+"/social-publisher/automation/realestate.json",20))
    matches=[x for x in check["jobs"] if x.get("dedup_key")==KEY]
    if len(matches)!=1 or matches[0]!=job:raise ValueError("outbox commit readback mismatch")
    write_state("queued",outbox_commit=outbox_commit,not_before=job["not_before"],expires_at=job["expires_at"])
    stop=time.time()+540
    last_status="queued"
    while time.time()<stop:
        try:
            rec=receipt(require_active=False)
            record=found(rec)
            if record:
                status=str(record.get("status"))
                print("RECEIPT_STATUS",status,flush=True)
                if status!=last_status:
                    write_state(status,parts=[{"index":p.get("index"),"status":p.get("status"),"permalink":p.get("permalink")} for p in record.get("parts",[])])
                    last_status=status
                post_parts=record.get("parts",[])
                if status=="published" and len(post_parts)==len(parts) and all(x.get("status")=="published" and x.get("permalink") for x in post_parts):
                    write_state("published",permalinks=[p["permalink"] for p in post_parts],
                      verified_topic=post_parts[0].get("topic_tag")==TOPIC,
                      root_topic=post_parts[0].get("topic_tag"),receipt_image_count=record.get("image_count"))
                    return
                if status in ["partial_failed","publishing_unknown","published_unverified","needs_review","expired","missed","failed"]:
                    write_state("stopped_"+status,note="No retry under new key")
                    return
            else:print("ORACLE_AWAITING_INTAKE",flush=True)
        except Exception as err:
            print("RECEIPT_TEMPORARILY_UNAVAILABLE",type(err).__name__,str(err)[:300],flush=True)
        time.sleep(18)
    write_state("verification_pending",note="Same stable key must be checked, do not submit duplicate")

if __name__=="__main__":
    try:
        main()
    except BaseException as exc:
        print("PIPELINE_ERROR",type(exc).__name__,str(exc),flush=True)
        traceback.print_exc()
        try:
            write_state("failed_before_or_during_submission",error=type(exc).__name__+": "+str(exc)[:500])
        except Exception as second:
            print("FAILED_TO_RECORD_STATUS",str(second),flush=True)
        raise
