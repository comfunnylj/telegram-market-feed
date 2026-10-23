#!/usr/bin/env python3
"""Read-only Myeonmok9 Threads uncertain-publish diagnosis.
Run INSIDE the existing social-publisher container. Never prints credentials.
Does NOT send posts, change SQLite, reset unknown states, or requeue jobs.
"""
import json,os,sqlite3,re,urllib.request,urllib.error,datetime
from pathlib import Path

JOB="a6c3f9cc-46cd-5911-80d4-8e91159ac6ec"
KEY="realestate:myeonmok9-20261023"
MARKERS=["면목9구역","5,700만"]
D=Path("/data")

def redact(v):
    s=str(v)
    s=re.sub(r'(?i)(access[_-]?token|authorization|app[_-]?secret|password|api[_-]?key)\s*["=: ]+\s*[\w\-.]{10,}',r'\1=[REDACTED]',s)
    s=re.sub(r'(?i)(Bearer\s+)[a-z0-9_.-]+',r'\1[REDACTED]',s)
    if len(s)>2200:s=s[:2200]+"...[TRUNCATED]"
    return s

def show(label,obj):
    print(label,json.dumps(obj,ensure_ascii=False,default=str))

print("DIAG_START",datetime.datetime.now(datetime.timezone.utc).isoformat(),KEY)
show("FILES", {"data_dir_exists":D.exists(),
 "history_exists":(D/"history"/(JOB+".json")).exists(),
 "db_exists":(D/"schedule.sqlite3").exists(),
 "token_exists":(D/"threads-token").exists()})

hist=D/"history"/(JOB+".json")
if hist.exists():
    try:
        h=json.loads(hist.read_text())
        # Print limited fields around each stage, no full user text or tokens.
        def summarize(x,depth=0):
            if depth>5:return "<depth-limit>"
            if isinstance(x,dict):
                o={}
                for k,v in x.items():
                    if re.search("token|secret|authorization|cookie|password|image_url",k,re.I):
                        continue
                    if k in ("text","parts","body","content","media","images","headers"):
                        o[k]="[REDACTED CONTENT]"
                        continue
                    o[k]=summarize(v,depth+1)
                return o
            if isinstance(x,list):return [summarize(v,depth+1) for v in x[-12:]]
            if isinstance(x,str):return redact(x)
            return x
        show("JOB_HISTORY",summarize(h))
    except Exception as e:show("HISTORY_ERROR",{"type":type(e).__name__,"message":redact(e)})
else:
    show("HISTORY_MISSING",{"expected":str(hist)})

db=D/"schedule.sqlite3"
if db.exists():
    try:
        con=sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True,timeout=4)
        names=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        show("SQLITE_TABLES",names)
        for n in names:
            if not re.fullmatch(r"[A-Za-z_]\w*",n):continue
            cols=[x[1] for x in con.execute("PRAGMA table_info("+n+")")]
            key_cols=[c for c in cols if re.search("(^id$|job_id|dedup_key|request_id)",c,re.I)]
            match=[]
            for col in key_cols:
                if not re.fullmatch(r"\w+",col):continue
                try:
                    data=con.execute('SELECT * FROM "'+n+'" WHERE "'+col+'" IN (?,?) LIMIT 3',(JOB,KEY)).fetchall()
                    for row in data:
                        vals=dict(zip(cols,row))
                        match.append({k:redact(v) for k,v in vals.items()
                                      if re.search("status|id$|error|failure|attempt|step|publish|container|permalink|updated|created",k,re.I)
                                      and not re.search("token|secret",k,re.I)})
                except Exception:pass
            if match:show("SQLITE_MATCH_"+n,match[:3])
        con.close()
    except Exception as e:show("SQLITE_ERROR",{"type":type(e).__name__,"message":redact(e)})

token_file=D/"threads-token"
if token_file.exists():
    try:
        raw=token_file.read_text().strip()
        if raw.startswith("{"):
            j=json.loads(raw)
            token=next((j[k] for k in ("access_token","token","threads_token") if isinstance(j.get(k),str)),None)
        else:token=raw
        if not token or len(token)<20:
            show("META_QUERY",{"status":"no recognized token; no posting attempted"})
        else:
            url="https://graph.threads.net/v1.0/me/threads?fields=id,text,permalink,timestamp,media_type&limit=100"
            all_own=[]
            for page in range(3):
                req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"Threads-Reconcile-ReadOnly/1"})
                try:
                    with urllib.request.urlopen(req,timeout=20) as resp: p=json.load(resp)
                except urllib.error.HTTPError as e:
                    # Consume only bounded error body; Meta may include details. Never leak token.
                    show("META_QUERY_ERROR",{"http_status":e.code,"detail":redact(e.read(2000).decode("utf8","replace"))})
                    break
                all_own.extend(p.get("data") or [])
                nxt=(p.get("paging") or {}).get("next")
                if not nxt:break
                if not nxt.startswith("https://graph.threads.net/"):break
                url=nxt
            hits=[]
            for item in all_own:
                t=(item.get("text") or "").replace(" ","")
                if all(x.replace(" ","") in t for x in MARKERS):
                    hits.append({"id":item.get("id"),"permalink":item.get("permalink"),
                                 "timestamp":item.get("timestamp"),"media_type":item.get("media_type"),
                                 "text_start":redact((item.get("text") or "")[:105])})
            show("META_OWN_POST_MATCHES",{"queried_posts":len(all_own),"matching_count":len(hits),"matches":hits})
            show("META_OWN_POST_NOTE",{"no_matches_is_not_proof_of_no_publish":len(hits)==0})
    except Exception as e:show("META_QUERY_EXCEPTION",{"type":type(e).__name__,"message":redact(e)})
else:show("META_QUERY",{"status":"token file missing, skipped"})

print("DIAG_END_NO_MUTATIONS_NO_POSTS")
