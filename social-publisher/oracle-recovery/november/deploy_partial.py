"""Backed-up same-runtime rollout and four same-ID repairs. No old DB restore."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

ROOT=Path(__file__).resolve().parent.parent
NAME='social-publisher'
VERSION='2026-11-14.1'
TAG='social-publisher:partial-20261114'
STAGE='preflight'
SECRET=''


def run(*args,check=True):
    result=subprocess.run(['docker',*args],capture_output=True,text=True)
    if check and result.returncode:
        error=(result.stderr+result.stdout)[-2500:]
        if SECRET:error=error.replace(SECRET,'[REDACTED]')
        raise RuntimeError('docker '+args[0]+' failed: '+error)
    return result.stdout.strip()


def restart_arg(policy):
    return policy['Name']+(':'+str(policy['MaximumRetryCount']) if policy['Name']=='on-failure' and policy.get('MaximumRetryCount') else '')


def rows(path):
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    data=db.execute('SELECT id,due,status,payload,result,created FROM jobs ORDER BY id').fetchall();db.close()
    return {r[0]:r for r in data}


def clone_args(snapshot,old_name):
    host=snapshot['HostConfig'];config=snapshot['Config']
    args=['create','--name',NAME,'--restart',restart_arg(host['RestartPolicy']),
          '--network',host.get('NetworkMode') or 'default','--stop-timeout',str(config.get('StopTimeout') or 180)]
    for flag,key in [('--memory','Memory'),('--memory-swap','MemorySwap'),('--pids-limit','PidsLimit'),('--cpu-shares','CpuShares')]:
        if host.get(key):args.extend([flag,str(host[key])])
    if host.get('NanoCpus'):args.extend(['--cpus',str(host['NanoCpus']/1e9)])
    if config.get('User'):args.extend(['--user',config['User']])
    if config.get('WorkingDir'):args.extend(['--workdir',config['WorkingDir']])
    if host.get('ReadonlyRootfs'):args.append('--read-only')
    if host.get('LogConfig',{}).get('Type'):args.extend(['--log-driver',host['LogConfig']['Type']])
    for value in host.get('CapDrop') or []:args.extend(['--cap-drop',value])
    for value in host.get('SecurityOpt') or []:args.extend(['--security-opt',value])
    for dst,opts in (host.get('Tmpfs') or {}).items():args.extend(['--tmpfs',dst+':'+opts])
    for name,val in (host.get('LogConfig',{}).get('Config') or {}).items():args.extend(['--log-opt',name+'='+val])
    for env in config.get('Env') or []:args.extend(['--env',env])
    for name,value in (config.get('Labels') or {}).items():args.extend(['--label',name+'='+value])
    for mount in snapshot['Mounts']:
        args.extend(['--mount','type=bind,src='+mount['Source']+',dst='+mount['Destination']+('' if mount['RW'] else ',readonly')])
    args.append(TAG)
    # COPY-only child image inherits Entrypoint/Cmd. Verify after creation.
    return args


def main():
    global STAGE,SECRET
    os.umask(0o077)
    ROOT.chmod(0o755);(ROOT/'november').chmod(0o755)
    for folder in [ROOT,ROOT/'november']:
        for p in folder.iterdir():
            if p.is_file() and p.suffix in ('.py','.json'):p.chmod(0o644)
    manifest=json.loads((ROOT/'november/manifest.json').read_text())
    snapshot=json.loads(run('inspect',NAME))[0]
    assert snapshot['State']['Running'],'Original worker is not running'
    host=snapshot['HostConfig']
    assert not host.get('Privileged') and not host.get('CapAdd') and not host.get('PortBindings'),'Unsupported runtime layout'
    assert all(m['Type']=='bind' for m in snapshot['Mounts'])
    data=Path(next(m['Source'] for m in snapshot['Mounts'] if m['Destination']=='/data'))
    assert data==Path('/home/ubuntu/social-publisher/data')
    SECRET=(data/'threads-token').read_text().strip()
    code="import pathlib,hashlib,json;print(json.dumps({n:hashlib.sha256(pathlib.Path('/app/'+n).read_bytes()).hexdigest() for n in "+repr(list(manifest['reviewed_live']))+"}))"
    actual=json.loads(run('exec',NAME,'python','-c',code))
    already=all(actual.get(n)==digest for n,digest in manifest['deploy'].items() if n in actual)
    for name,digest in manifest['reviewed_live'].items():
        assert actual[name] in {digest,manifest['deploy'].get(name)},'Unreviewed live code '+name
    for name,digest in manifest['deploy'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    plan=json.loads((ROOT/'november/plan.json').read_text());targets={x['job_id'] for x in plan['incidents']}
    def gate():
        current=rows(data/'schedule.sqlite3')
        assert not any(r[2]=='running' for r in current.values()),'Publication in progress'
        assert not any(r[2]=='pending' and r[1]<time.time()+180 for r in current.values()),'An existing job is due soon'
    gate();STAGE='build'
    dockerfile=ROOT/'november/Dockerfile.rollout'
    dockerfile.write_text('FROM '+snapshot['Image']+'\nCOPY recovery.py worker.py durable.py /app/\nCOPY november/resume_incidents.py november/plan.json /app/maintenance/\n')
    run('build','-q','-f',str(dockerfile),'-t',TAG,str(ROOT));gate()
    backup=data.parent/'backups'/('partial-20261114-'+str(time.time_ns()));backup.mkdir(mode=0o700)
    (backup/'container.json').write_text(json.dumps(snapshot))
    old_name=NAME+'-before-partial-'+str(time.time_ns())
    stopped=False;renamed=False;new_started=False
    try:
        STAGE='graceful_stop'
        run('update','--restart','no',NAME);run('kill','--signal=SIGTERM',NAME)
        for _ in range(180):
            if run('inspect','--format','{{.State.Running}}',NAME)=='false':stopped=True;break
            time.sleep(1)
        assert stopped,'Worker did not stop; never force kill a publication'
        STAGE='backup'
        src=sqlite3.connect(str(data/'schedule.sqlite3'));dest=sqlite3.connect(str(backup/'schedule.sqlite3'));src.backup(dest);src.close();dest.close()
        shutil.copytree(data/'history',backup/'history')
        before=rows(backup/'schedule.sqlite3')
        STAGE='same_job_repair'
        # Recovery code is in the reviewed new image, not a mutable /app bind mount.
        args=['run','--rm','--network',host.get('NetworkMode') or 'default',
              '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
              '--memory',str(host.get('Memory') or 134217728),'--pids-limit','64','--volumes-from',NAME]
        if snapshot['Config'].get('User'):args.extend(['--user',snapshot['Config']['User']])
        for env in snapshot['Config'].get('Env') or []:args.extend(['--env',env])
        args.extend(['--entrypoint','python',TAG,'/app/maintenance/resume_incidents.py','--plan','/app/maintenance/plan.json'])
        # Keep non-secret repair output for operator review even if a job remains unresolved.
        result=subprocess.run(['docker',*args],capture_output=True,text=True)
        stdout=result.stdout.replace(SECRET,'[REDACTED]');stderr=result.stderr.replace(SECRET,'[REDACTED]')
        (backup/'repair-output.txt').write_text(stdout+'\n'+stderr)
        print(stdout,flush=True)
        if result.returncode:print('REPAIR_ERROR '+json.dumps({'exit':result.returncode,'detail':stderr[-1000:]}),flush=True)
        after_repair=rows(data/'schedule.sqlite3')
        assert {k:v for k,v in before.items() if k not in targets}=={k:v for k,v in after_repair.items() if k not in targets},'Other job data changed'
        STAGE='replace_worker'
        run('rename',NAME,old_name);renamed=True
        run(*clone_args(snapshot,old_name));run('start',NAME);new_started=True
        STAGE='health'
        for _ in range(420):
            if run('inspect','--format','{{.State.Running}}',NAME)=='true':
                logs=subprocess.run(['docker','logs',NAME],capture_output=True,text=True)
                if 'Social Publisher worker ready' in logs.stdout:
                    health=json.loads((data/'bridge-health.json').read_text())
                    if health.get('enabled') and health.get('last_error') is None and health.get('last_success_at',0)>backup.stat().st_mtime:break
            time.sleep(1)
        else:raise RuntimeError('Worker health or fresh bridge poll unconfirmed')
        installed=json.loads(run('exec',NAME,'python','-c',"import pathlib,hashlib,json;print(json.dumps({n:hashlib.sha256(pathlib.Path('/app/'+n).read_bytes()).hexdigest() for n in ['worker.py','recovery.py','durable.py']}))"))
        assert installed==manifest['deploy'],'Installed patch differs from tested code'
        fresh=json.loads(run('inspect',NAME))[0]
        envdict=lambda x:dict(v.split('=',1) for v in x['Config']['Env'])
        preservation={'other_jobs_unchanged':{k:v for k,v in before.items() if k not in targets}=={k:v for k,v in rows(data/'schedule.sqlite3').items() if k not in targets},
            'environment_unchanged':envdict(snapshot)==envdict(fresh),'user_unchanged':snapshot['Config']['User']==fresh['Config']['User'],
            'restart_policy_unchanged':snapshot['HostConfig']['RestartPolicy']==fresh['HostConfig']['RestartPolicy'],
            'command_unchanged':snapshot['Config']['Cmd']==fresh['Config']['Cmd'] and snapshot['Config'].get('Entrypoint')==fresh['Config'].get('Entrypoint')}
        assert all(preservation.values()),'Runtime preservation check failed'
        report={'status':'deployed','version':VERSION,'backup':str(backup),'old_container':old_name,
            'repair_exit':result.returncode,'preservation':preservation,'other_job_count':len(before)-len(targets),'installed_hashes':installed}
        (backup/'deployment-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('DEPLOYMENT_RESULT '+json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        if not renamed:
            run('update','--restart',restart_arg(host['RestartPolicy']),NAME,check=False)
            if stopped:run('start',NAME,check=False)
        elif not new_started or run('inspect','--format','{{.State.Running}}',NAME,check=False)!='true':
            # Roll back executable only. Never restore the pre-publication database.
            run('rm',NAME,check=False);run('rename',old_name,NAME,check=False)
            run('update','--restart',restart_arg(host['RestartPolicy']),NAME,check=False);run('start',NAME,check=False)


if __name__=='__main__':
    try:main()
    except Exception as e:
        text=str(e).replace(SECRET,'[REDACTED]') if SECRET else str(e)
        print('DEPLOYMENT_BLOCKED '+json.dumps({'stage':STAGE,'type':type(e).__name__,'message':text[:1800]}),flush=True)
        raise SystemExit(1)
