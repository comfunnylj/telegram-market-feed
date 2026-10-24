"""Authenticated Oracle-only deployment; no schedules or other containers touched."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
NAME = 'social-publisher'


def docker(*args, check=True):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check).stdout.strip()


def main():
    os.umask(0o077)
    snapshot = json.loads(docker('inspect', NAME))[0]
    if not snapshot['State']['Running']:
        raise RuntimeError('Existing worker must already be running')
    mounts = snapshot['Mounts']
    if any(m['Type'] != 'bind' for m in mounts):
        raise RuntimeError('Unsupported mount layout; preserve existing deployment')
    data = next(Path(m['Source']) for m in mounts if m['Destination'] == '/data')
    assert any(m['Destination'] == '/status' for m in mounts)
    if data != Path('/home/ubuntu/social-publisher/data'):
        raise RuntimeError('Unexpected data mount')
    host = snapshot['HostConfig']
    if host.get('PortBindings') or host.get('Privileged') or host.get('CapAdd'):
        raise RuntimeError('Unsupported runtime configuration')
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    installed = docker('exec', NAME, 'python', '-c',
        'import hashlib,json,pathlib;print(json.dumps({n:hashlib.sha256(pathlib.Path("/app/"+n).read_bytes()).hexdigest() for n in ["core.py","worker.py"]}))')
    actual = json.loads(installed)
    if actual['core.py'] != manifest['baseline']['core.py']:
        raise RuntimeError('Live core differs from reviewed v0.4 source; no blind patch')
    already = actual['worker.py'] == manifest['patched']['worker.py']
    if not already and actual['worker.py'] != manifest['baseline']['worker.py']:
        raise RuntimeError('Live worker differs from reviewed baseline')
    def queue_gate():
        db = sqlite3.connect(data.joinpath('schedule.sqlite3').as_uri() + '?mode=ro', uri=True)
        assert not db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone(), 'Publication in progress'
        assert not db.execute("SELECT 1 FROM jobs WHERE status='pending' AND due<? LIMIT 1", (time.time() + 180,)).fetchone(), 'Existing job is due soon'
        db.close()
    queue_gate()
    tag = 'social-publisher:recovery-20261024'
    if not already:
        (ROOT / 'Dockerfile.recovery').write_text('FROM ' + snapshot['Image'] + '\nCOPY recovery.py worker.py /app/\n')
        docker('build', '-q', '-f', str(ROOT / 'Dockerfile.recovery'), '-t', tag, str(ROOT))
    queue_gate()
    backup = data.parent / 'backups' / ('recovery-20261024-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    (backup / 'container.json').write_text(json.dumps(snapshot))
    stopped = False
    renamed = False
    old_name = NAME + '-before-recovery-' + str(time.time_ns())
    report = None
    try:
        docker('update', '--restart', 'no', NAME)
        docker('kill', '--signal=SIGTERM', NAME)
        for _ in range(180):
            if docker('inspect', '--format', '{{.State.Running}}', NAME) == 'false':
                stopped = True
                break
            time.sleep(1)
        if not stopped:
            raise RuntimeError('Worker still finishing; no forced stop')
        source = sqlite3.connect(str(data / 'schedule.sqlite3'))
        target = sqlite3.connect(str(backup / 'schedule.sqlite3'))
        source.backup(target)
        source.close()
        target.close()
        shutil.copytree(data / 'history', backup / 'history')
        command = ['run', '--rm', '--network', host.get('NetworkMode') or 'default',
                   '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--memory', str(host.get('Memory') or 134217728), '--pids-limit', '64',
                   '--volumes-from', NAME, '--mount', 'type=bind,src=' + str(ROOT) + ',dst=/recovery,readonly',
                   '--entrypoint', 'python', snapshot['Image'], '/recovery/run_recovery.py',
                   '--candidate', '/recovery/candidate.json', '--apply']
        raw = docker(*command)
        report = json.loads(raw.splitlines()[-1])
        enabled = data / 'recovery-enabled-at'
        if not enabled.exists():
            enabled.write_text(str(time.time()))
        if already:
            docker('update', '--restart', snapshot['HostConfig']['RestartPolicy']['Name'], NAME)
            docker('start', NAME)
            stopped = False
        else:
            docker('rename', NAME, old_name)
            renamed = True
            args = ['create', '--name', NAME, '--restart', host['RestartPolicy']['Name'],
                    '--network', host.get('NetworkMode') or 'default', '--stop-timeout',
                    str(snapshot['Config'].get('StopTimeout') or 180)]
            for flag, key in [('--memory', 'Memory'), ('--memory-swap', 'MemorySwap'), ('--pids-limit', 'PidsLimit')]:
                if host.get(key):
                    args += [flag, str(host[key])]
            if host.get('NanoCpus'):
                args += ['--cpus', str(host['NanoCpus'] / 1000000000)]
            if snapshot['Config'].get('User'):
                args += ['--user', snapshot['Config']['User']]
            if host.get('ReadonlyRootfs'):
                args += ['--read-only']
            for value in host.get('CapDrop') or []:
                args += ['--cap-drop', value]
            for value in host.get('SecurityOpt') or []:
                args += ['--security-opt', value]
            for dst, opts in (host.get('Tmpfs') or {}).items():
                args += ['--tmpfs', dst + ':' + opts]
            for name, val in (host.get('LogConfig', {}).get('Config') or {}).items():
                args += ['--log-opt', name + '=' + val]
            for env in snapshot['Config'].get('Env') or []:
                args += ['--env', env]
            for mount in mounts:
                args += ['--mount', 'type=bind,src=' + mount['Source'] + ',dst=' + mount['Destination'] + ('' if mount['RW'] else ',readonly')]
            args += [tag]
            docker(*args)
            docker('start', NAME)
            for _ in range(20):
                if docker('inspect', '--format', '{{.State.Running}}', NAME) == 'true':
                    try:
                        version = docker('exec', NAME, 'python', '-c', 'import recovery;print(recovery.VERSION)')
                        if version == '2026-10-24.1':
                            stopped = False
                            break
                    except subprocess.CalledProcessError:
                        pass
                time.sleep(1)
            if stopped:
                raise RuntimeError('New worker readiness unconfirmed; inspect retained backup')
        report['worker_patch_deployed'] = True
        report['schedules_changed'] = False
        report['other_containers_changed'] = False
        print(json.dumps(report, ensure_ascii=False))
    finally:
        # Never restore an old DB, which could replay already published posts.
        if not renamed:
            docker('update', '--restart', host['RestartPolicy']['Name'], NAME, check=False)
            if stopped:
                docker('start', NAME, check=False)
        elif stopped and renamed:
            # Keep an active new worker rather than interrupt any started publish.
            state = docker('inspect', '--format', '{{.State.Running}}', NAME, check=False)
            if state == 'false':
                docker('rm', NAME, check=False)
                docker('rename', old_name, NAME, check=False)
                docker('update', '--restart', host['RestartPolicy']['Name'], NAME, check=False)
                docker('start', NAME, check=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'worker_patch_deployed': False,
                          'error_type': type(exc).__name__,
                          'reason': 'Oracle preflight or deployment failed; no credentials logged'}))
        raise SystemExit(1)
