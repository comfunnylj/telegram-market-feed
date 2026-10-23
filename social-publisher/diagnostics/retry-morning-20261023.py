#!/usr/bin/env python3
"""One-time 2026-10-23 morning retry through the established Oracle outbox only.
No Meta token or SSH connection; public receipt read-only, GitHub Actions credential
is provided by actions/checkout and is never persisted into a public file.
"""
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

ROOT=Path.cwd()
SOURCE="morning"
KEY="morning:2026-10-23"
TOPIC="미국주식"
BRIDGE_ID="sp-oracle-genie-carrot-v1"
STATUS_URL="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
OUTBOX=ROOT/"social-publisher/automation/morning.json"
DRAFT=ROOT/"social-publisher/diagnostics/morning-20261023-draft.json"
SVG=ROOT/"social-publisher/diagnostics/morning-20261023-cover.svg"
IMAGE=ROOT/"social-publisher/media"/("morning-"+hashlib.sha256(KEY.encode()).hexdigest()+".png")
KST=dt.timezone(dt.timedelta(hours=9))

def git(*args):
    cmd=["git",*args]
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode!=0:
        raise RuntimeError(f"git {args[0]} failed: {p.stderr[-800:]}")
    return p.stdout.strip()

def read_url(url, timeout=12):
    req=urllib.request.Request(url,headers={"User-Agent":"Social-Publisher-Oracle-Diagnostics/1","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return resp.read()

def receipt():
    obj=json.loads(read_url(STATUS_URL+"?t="+str(time.time_ns())))
    bridge=obj.get("bridge") or {}
    if obj.get("account")!="genie_carrot" or obj.get("protocol")!=1:
        raise ValueError("receipt wrong account/protocol")
    if bridge.get("bridge_id")!=BRIDGE_ID or bridge.get("enabled") is not True:
        raise ValueError("bridge identity disabled/mismatch")
    if bridge.get("last_error") or (bridge.get("task_errors") or {}).get(SOURCE):
        raise ValueError("Oracle errors: "+str(bridge.get("last_error"))+"/"+str(bridge.get("task_errors")))
    last=bridge.get("last_success_at")
    if not isinstance(last,(float,int)) or time.time()-last>600:
        raise ValueError("Oracle stale last_success_at")
    tasks=bridge.get("tasks") or []
    found=next((x for x in tasks if x.get("id")==SOURCE),None)
    if not found or found.get("enabled") is not True or found.get("account")!="genie_carrot" or found.get("network")!="threads" or found.get("topic")!=TOPIC or found.get("outbox")!="morning.json":
        raise ValueError("Oracle task registry mismatch")
    return obj

def job_in_receipt(obj):
    return next((x for x in obj.get("jobs",[]) if x.get("dedup_key")==KEY),None)

def push_commit(path,message):
    git("add",str(path.relative_to(ROOT)))
    git("commit","-m",message)
    for attempt in range(2):
        try:
            git("push","origin","HEAD:main")
            return git("rev-parse","HEAD")
        except Exception:
            if attempt:raise
            git("pull","--rebase","origin","main")
    raise RuntimeError("push rejected")

def main():
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("pull","--ff-only","origin","main")
    control=json.loads((ROOT/"social-publisher/automation/control.json").read_text())
    registry=json.loads((ROOT/"social-publisher/automation/tasks.json").read_text())
    task=next(x for x in registry["tasks"] if x["id"]==SOURCE)
    if control.get("bridge_id")!=BRIDGE_ID or control.get("enabled") is not True:
        raise ValueError("local control disabled/mismatch")
    if dt.datetime.fromisoformat(control["activated_at"])>dt.datetime.now(KST):
        raise ValueError("control activation is in future")
    if task.get("enabled") is not True or task.get("topic")!=TOPIC or task.get("network")!="threads" or task.get("account")!="genie_carrot" or task.get("outbox")!="morning.json":
        raise ValueError("local task config mismatch")
    if task.get("image_required") is not True:
        raise ValueError("image policy mismatch")
    existing=json.loads(OUTBOX.read_text())
    if existing.get("protocol")!=1 or existing.get("source")!=SOURCE:
        raise ValueError("outbox envelope invalid")
    before=receipt()
    if any(x.get("dedup_key")==KEY for x in existing["jobs"]) or job_in_receipt(before):
        print("ABORT_DUPLICATE",KEY)
        return
    draft=json.loads(DRAFT.read_text())
    parts=draft["parts"]
    if draft["dedup_key"]!=KEY or draft["topic"]!=TOPIC or not parts or draft["text"]!="".join(parts):
        raise ValueError("draft invalid")
    for i,p in enumerate(parts):
        utf16=len(p.encode("utf-16-le"))//2
        if not p or utf16>task["max_utf16"] or len(p)>450:
            raise ValueError("invalid part length "+str(i))
    if len(parts)>task["max_posts"]:
        raise ValueError("too many parts")
    print("VALIDATED_TEXT",KEY,"parts",len(parts),"code_units",[len(p.encode("utf-16-le"))//2 for p in parts])
    # Render visually-reviewed vector source to actual immutable raster media.
    import cairosvg
    from PIL import Image as PILImage
    IMAGE.parent.mkdir(parents=True,exist_ok=True)
    if IMAGE.exists():
        raise ValueError("image path already exists, do not overwrite")
    cairosvg.svg2png(url=str(SVG),write_to=str(IMAGE),output_width=1080,output_height=1350)
    with PILImage.open(IMAGE) as im:
        if im.format!="PNG" or im.size!=(1080,1350):
            raise ValueError("image geometry invalid")
        im.verify()
    image_bytes=IMAGE.read_bytes()
    image_hash=hashlib.sha256(image_bytes).hexdigest()
    image_size=len(image_bytes)
    if image_size<=10000 or image_size>8*1024*1024:
        raise ValueError("image size invalid "+str(image_size))
    print("VALIDATED_IMAGE",image_size,image_hash)
    asset_commit=push_commit(IMAGE,"Add reviewed 2026-10-23 morning briefing 4:5 image")
    image_url=f"https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/{asset_commit}/{IMAGE.relative_to(ROOT).as_posix()}"
    # Verify exact public raster bytes from immutable commit URL before queuing.
    for i in range(6):
        try:
            remote=read_url(image_url,timeout=15)
            if hashlib.sha256(remote).hexdigest()!=image_hash or len(remote)!=image_size:
                raise ValueError("immutable image byte mismatch")
            break
        except Exception as exc:
            if i==5:raise
            print("RETRY_IMAGE_READ",i,str(exc)[:120])
            time.sleep(3)
    print("IMMUTABLE_IMAGE_VERIFIED",image_url)
    after=receipt()
    if job_in_receipt(after):
        print("ABORT_ALREADY_ACCEPTED",KEY)
        return
    # Refresh exact outbox head after media commit, preserving every existing source job.
    current=json.loads(OUTBOX.read_text())
    if any(x.get("dedup_key")==KEY for x in current["jobs"]):
        print("ABORT_OUTBOX_DUPLICATE",KEY)
        return
    now=dt.datetime.now(KST)
    not_before=now+dt.timedelta(minutes=5)
    expires_at=not_before+dt.timedelta(seconds=min(300,task["late_grace_seconds"]))
    job={"dedup_key":KEY,"created_at":now.isoformat(timespec="seconds"),
         "not_before":not_before.isoformat(timespec="seconds"),
         "expires_at":expires_at.isoformat(timespec="seconds"),
         "topic":TOPIC,"text":draft["text"],"parts":parts,
         "image":{"url":image_url,"sha256":image_hash,"size":image_size}}
    current["jobs"].append(job)
    OUTBOX.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n")
    outbox_commit=push_commit(OUTBOX,"Queue 2026-10-23 morning briefing via Oracle, single stable dedup key")
    # Post-commit check: immutable matching entry and unchanged previous jobs.
    final=json.loads(read_url(f"https://raw.githubusercontent.com/comfunnylj/telegram-market-feed/{outbox_commit}/social-publisher/automation/morning.json"))
    assert len(final["jobs"])==len(existing["jobs"])+1
    assert final["jobs"][-1]==job and final["jobs"][:-1]==existing["jobs"]
    print("OUTBOX_COMMITTED",outbox_commit,"JOB_ID",str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY)))
    print("OUTBOX_NOT_BEFORE",job["not_before"],"EXPIRES",job["expires_at"])
    # Best-effort live verification; never requeue on status uncertainty.
    until=time.time()+570
    while time.time()<until:
        try:
            obj=receipt()
            found=job_in_receipt(obj)
            if found:
                ps=found.get("parts") or []
                print("ORACLE_STATUS",json.dumps({"status":found.get("status"),"job_id":found.get("id"),"parts":[{"index":p.get("index"),"status":p.get("status"),"permalink":p.get("permalink"),"topic_tag":p.get("topic_tag")} for p in ps]},ensure_ascii=False))
                if found.get("status")=="published" and len(ps)==len(parts) and all(p.get("status")=="published" and p.get("permalink") for p in ps):
                    print("PUBLISHED_ALL_PARTS",json.dumps(ps,ensure_ascii=False))
                    if ps[0].get("topic_tag")==TOPIC:
                        print("OFFICIAL_TOPIC_VERIFIED",TOPIC)
                    else:
                        print("OFFICIAL_TOPIC_UNVERIFIED",ps[0].get("topic_tag"))
                    return
                if found.get("status") in ("partial_failed","publishing_unknown","needs_review","expired","missed","error","failed"):
                    print("STOP_NO_RETRY",found.get("status"))
                    return
            else:
                print("ORACLE_PENDING_INTAKE")
        except Exception as e:
            print("ORACLE_STATUS_UNAVAILABLE_NO_RETRY",type(e).__name__,str(e)[:200])
        time.sleep(20)
    print("VERIFY_TIMEOUT_KEEP_SAME_DEDUP_KEY",KEY)

if __name__=="__main__":
    try:
        main()
    except Exception as err:
        print("PIPELINE_ERROR",type(err).__name__,str(err))
        raise
