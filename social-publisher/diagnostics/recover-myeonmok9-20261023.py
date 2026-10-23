#!/usr/bin/env python3
"""Explicitly user-authorized one-time recovery attempt; no indefinite retries."""
import datetime as dt, hashlib, io, json, subprocess, time, urllib.request, uuid
from pathlib import Path
from PIL import Image, ImageOps
ROOT=Path.cwd()
KST=dt.timezone(dt.timedelta(hours=9))
OLD_KEY="realestate:myeonmok9-20261023"
KEY="realestate:myeonmok9-20261023-retry1"
REPO="comfunnylj/telegram-market-feed"
BASE="https://161-33-141-193.sslip.io/social-publisher-status/status.json"
OUTBOX=Path("social-publisher/automation/realestate.json")
STATE=Path("social-publisher/diagnostics/myeonmok9-recovery-status.json")
STABLE_ID=str(uuid.uuid5(uuid.NAMESPACE_URL,"social-publisher/"+KEY))
def cmd(*args):
    p=subprocess.run(["git",*args],capture_output=True,text=True)
    if p.returncode:raise RuntimeError("git "+args[0]+": "+p.stderr[-400:])
    return p.stdout.strip()
def get(url,timeout=20):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(9*1024*1024)
def commit(message):
    cmd("commit","-m",message)
    for i in range(3):
        try:
            cmd("push","origin","HEAD:main")
            return cmd("rev-parse","HEAD")
        except Exception:
            if i==2:raise
            cmd("pull","--rebase","origin","main")
def save(status,**extra):
    data={"key":KEY,"job_id":STABLE_ID,"time":dt.datetime.now(KST).isoformat(timespec="seconds"),"status":status,**extra}
    STATE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    cmd("add",STATE.as_posix())
    p=subprocess.run(["git","diff","--cached","--quiet"])
    if p.returncode:commit("Track Myeonmok9 retry: "+status)
    print("STATE",json.dumps(data,ensure_ascii=False)[:4000],flush=True)
def receipt():
    j=json.loads(get(BASE+"?t="+str(time.time_ns())))
    b=j.get("bridge") or {}
    if j.get("account")!="genie_carrot" or j.get("protocol")!=1 or b.get("bridge_id")!="sp-oracle-genie-carrot-v1" or b.get("enabled") is not True:
        raise RuntimeError("Oracle identity or bridge mismatch")
    if b.get("last_error") or (b.get("task_errors") or {}).get("realestate"):
        raise RuntimeError("Oracle task error")
    if not isinstance(b.get("last_success_at"),(int,float)) or time.time()-b["last_success_at"]>900:
        raise RuntimeError("Oracle stale heartbeat")
    caps=j.get("capabilities") or {}
    if j.get("publisher_version")!="0.4" or caps.get("carousel") is not True or int(caps.get("max_images",0))<2:
        raise RuntimeError("Carousel unavailable")
    tasks=b.get("tasks") or []
    if not any(x.get("id")=="realestate" and x.get("enabled") is True and x.get("topic")=="부동산" and x.get("outbox")=="realestate.json" for x in tasks):
        raise RuntimeError("Real-estate task mismatch")
    return j
def match(j,k):return next((v for v in j.get("jobs",[]) if v.get("dedup_key")==k),None)
def main():
    cmd("config","user.name","github-actions[bot]")
    cmd("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    cmd("pull","--ff-only","origin","main")
    old=json.loads(OUTBOX.read_text())
    original=next((x for x in old["jobs"] if x.get("dedup_key")==OLD_KEY),None)
    if not original or len(original["parts"])!=6 or len(original.get("images",[]))!=2:
        raise RuntimeError("Original approved request missing or malformed")
    if any(x.get("dedup_key")==KEY for x in old["jobs"]):save("already_queued");return
    live=receipt()
    if match(live,OLD_KEY) and match(live,OLD_KEY).get("status")=="published":
        save("old_published_skip",first_post=match(live,OLD_KEY).get("parts",[{}])[0].get("permalink"));return
    if match(live,KEY):save("retry_received_skip");return
    assets=[]
    for i,item in enumerate(original["images"],1):
        # Same two previously reviewed photos, lossless geometry-preserving resample.
        raw=get(item["url"])
        assert hashlib.sha256(raw).hexdigest()==item["sha256"] and len(raw)==item["size"]
        with Image.open(io.BytesIO(raw)) as picture:
            picture.load()
            w,h=picture.size
            nw=1080
            nh=round(h*nw/w)
            if nh<320 or nh>3200:raise ValueError("unexpected aspect ratio")
            dst=Path("social-publisher/media")/("realestate-myeonmok9-retry1-"+str(i).zfill(2)+".jpg")
            if dst.exists():raise RuntimeError("refusing to overwrite verified asset")
            picture.convert("RGB").resize((nw,nh),Image.Resampling.LANCZOS).save(dst,"JPEG",quality=95,optimize=True,subsampling=0)
        b=dst.read_bytes()
        if not (20000<len(b)<8*1024*1024):raise ValueError("image size invalid")
        with Image.open(dst) as check:check.verify()
        assets.append({"path":dst,"sha256":hashlib.sha256(b).hexdigest(),"size":len(b),"width":nw,"height":nh})
        print("MEDIA_VALIDATED",i,nw,nh,len(b),flush=True)
    cmd("add",*[p["path"].as_posix() for p in assets])
    rev=commit("Prepare 1080px original-source images for Myeonmok9 authorized recovery")
    for p in assets:
        p["url"]=f"https://raw.githubusercontent.com/{REPO}/{rev}/{p['path'].as_posix()}"
        for attempt in range(5):
            try:
                b=get(p["url"])
                if len(b)!=p["size"] or hashlib.sha256(b).hexdigest()!=p["sha256"]:
                    raise ValueError("immutable media readback mismatch")
                break
            except Exception:
                if attempt==4:raise
                time.sleep(4)
    save("media_ready",image_urls=[p["url"] for p in assets])
    current=receipt()
    if match(current,OLD_KEY) and match(current,OLD_KEY).get("status")=="published":
        save("old_published_skip");return
    if match(current,KEY):save("retry_received_skip");return
    cmd("pull","--ff-only","origin","main")
    fresh=json.loads(OUTBOX.read_text())
    if any(x.get("dedup_key")==KEY for x in fresh["jobs"]):save("already_queued");return
    now=dt.datetime.now(KST)
    due=now+dt.timedelta(minutes=5)
    task={"dedup_key":KEY,"created_at":now.isoformat(timespec="seconds"),
      "not_before":due.isoformat(timespec="seconds"),
      "expires_at":(due+dt.timedelta(minutes=5)).isoformat(timespec="seconds"),
      "topic":"부동산","text":original["text"],"parts":original["parts"],
      "images":[{k:p[k] for k in ("url","sha256","size")} for p in assets]}
    fresh["jobs"].append(task)
    OUTBOX.write_text(json.dumps(fresh,ensure_ascii=False,indent=2)+"\n")
    cmd("add",OUTBOX.as_posix())
    revision=commit("Submit user-authorized Myeonmok9 recovery retry via Oracle bridge")
    verify=json.loads(get(f"https://raw.githubusercontent.com/{REPO}/{revision}/{OUTBOX.as_posix()}"))
    hits=[x for x in verify["jobs"] if x.get("dedup_key")==KEY]
    if len(hits)!=1 or hits[0]!=task:raise ValueError("outbox readback failed")
    save("queued",due=task["not_before"],outbox_commit=revision)
    last=None
    deadline=time.time()+520
    while time.time()<deadline:
        try:
            j=receipt()
            hit=match(j,KEY)
            if hit:
                status=hit.get("status")
                if status!=last:
                    save(status,parts=[{"index":p.get("index"),"status":p.get("status"),"permalink":p.get("permalink")} for p in hit.get("parts",[])])
                    last=status
                if status=="published":
                    pp=hit.get("parts",[])
                    if len(pp)==6 and all(p.get("status")=="published" and p.get("permalink") for p in pp):
                        save("verified_published",urls=[p["permalink"] for p in pp],image_count=hit.get("image_count"),topic=pp[0].get("topic_tag"))
                    return
                if status in ["publishing_unknown","partial_failed","failed","needs_review","published_unverified","expired","missed"]:
                    save("stopped_"+status,note="Do not automatically repeat under another id")
                    return
        except Exception as exc:print("CHECK_FAILED",type(exc).__name__,str(exc)[:200],flush=True)
        time.sleep(15)
    save("receipt_timeout")
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("RETRY_ERROR",type(exc).__name__,str(exc),flush=True)
        try:save("setup_error",error=type(exc).__name__+": "+str(exc)[:350])
        except Exception:pass
        raise
