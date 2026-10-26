import json,sqlite3,hashlib,os
import core,recovery
from recovery import read,MetaError,Publisher
db=sqlite3.connect('file:'+str(core.DATA/'schedule.sqlite3')+'?mode=ro',uri=True)
print(json.dumps({'version':recovery.VERSION,'uid':os.getuid(),'worker_sha':hashlib.sha256(open('/app/worker.py','rb').read()).hexdigest()}))
token=core.saved_token()
for jid,status,rawp,rawr in db.execute("SELECT id,status,payload,result FROM jobs WHERE id IN ('1bf31796-ced2-50e1-8f5e-7f531f683bef','83a99347-6f9c-5c6f-be90-242a88897b9f')"):
 p=json.loads(rawp);r=json.loads(rawr)
 out={'id':jid,'status':status,'diagnosis':r.get('diagnosis'),'error':r.get('error'),'attempts':r.get('automatic_recovery_attempts'),'events':r.get('recovery_events',[])[-5:],'parts':[{'status':x.get('status'),'post_id':x.get('post_id'),'last_error':x.get('last_error')} for x in r.get('parts',[])]}
 pub=Publisher();pub.root_image_count=len(core.image_list(p.get('image'),p.get('images')))
 try:out['root_verification']=pub.verify_post(token,r['parts'][0],p['topic'])
 except Exception as e:
  out['verify_error']={'type':type(e).__name__,'message':str(e),'detail':getattr(e,'detail',None)}
  try:out['minimal_post']=read(token,'/'+r['parts'][0]['post_id']+'?fields=id,permalink,topic_tag,media_type,media_url,username')
  except Exception as e:out['minimal_error']={'message':str(e),'detail':getattr(e,'detail',None)}
 post=read(token,'/'+r['parts'][0]['post_id']+'?fields=id,text,username,permalink,topic_tag')
 expected=r['parts'][0]['text'];actual=post.get('text','')
 out['text_comparison']={'expected_len':len(expected),'actual_len':len(actual),'equal_strip':expected.strip()==actual.strip(),'expected_tail':repr(expected[-30:]),'actual_tail':repr(actual[-30:]),'expected_head':repr(expected[:30]),'actual_head':repr(actual[:30]),'diff':[(i,repr(a),repr(b)) for i,(a,b) in enumerate(zip(expected,actual)) if a!=b][:6]}
 print(json.dumps(out,ensure_ascii=False))
