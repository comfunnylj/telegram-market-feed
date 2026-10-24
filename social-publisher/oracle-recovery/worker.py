import fcntl
import os
import signal
import threading
import time
from core import DATA
from recovery import Publisher, recover_one
from bridge import Bridge
from scheduler import Scheduler


def main():
    os.umask(0o077)
    DATA.mkdir(parents=True, exist_ok=True)
    lock = (DATA / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    scheduler = Scheduler(DATA / 'schedule.sqlite3', recover=True)
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    bridge = Bridge(scheduler)
    bridge.export_status()
    threading.Thread(target=bridge.run,args=(stopping,),daemon=True).start()
    last_status = 0
    last_recovery = 0
    print('Social Publisher worker ready; account: genie_carrot; no inbound port', flush=True)
    while not stopping.is_set():
        claimed = scheduler.claim()
        if claimed:
            identifier, payload = claimed
            publisher = Publisher()
            # Durable same-ID state, read-only reconciliation and bounded safe retries.
            meta = payload.get('automation')
            if meta and time.time()>meta['expires_at']:
                record = {'job_id':identifier,'status':'expired','parts':[]}
            else:
                record = publisher.send(payload['text'],payload['topic'],payload['parts'],payload.get('image'),
                                        scheduled=True,images=payload.get('images'),job_id=identifier)
            if meta:
                record['automation'] = meta
            record['schedule_id'] = identifier
            publisher.save(record)
            scheduler.finish(identifier,record)
            print('job',identifier,'status',record['status'],flush=True)
            try:bridge.export_status()
            except Exception as exc:print('status export error:',type(exc).__name__,flush=True)
        else:
            if time.monotonic()-last_recovery>30:
                try:recover_one(scheduler)
                except Exception as exc:print('recovery check error:',type(exc).__name__,flush=True)
                last_recovery=time.monotonic()
            stopping.wait(1)
        if time.monotonic()-last_status>10:
            try:bridge.export_status()
            except Exception as exc:print('status export error:',type(exc).__name__,flush=True)
            last_status=time.monotonic()


if __name__ == '__main__':
    main()
