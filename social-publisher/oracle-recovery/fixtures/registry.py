"""Validate owner-managed task registrations without executing configuration as code."""
import re

SCHEMA_VERSION = 1
ACCOUNT_NAME = 'genie_carrot'
DEFAULT_POLL_SECONDS = 180
RESERVED_FILES = {'control.json','probe.json','tasks.json'}
ROOT_FIELDS = {'schema_version','poll_seconds','tasks'}
TASK_FIELDS = {'id','name','enabled','network','account','topic','outbox','image_required',
               'max_posts','max_utf16','late_grace_seconds'}


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_'+label)
    return value


def load_registry(raw):
    if not isinstance(raw,dict) or set(raw)-ROOT_FIELDS or type(raw.get('schema_version')) is not int or raw['schema_version']!=SCHEMA_VERSION:
        raise ValueError('invalid_registry_schema')
    poll=integer(raw.get('poll_seconds',DEFAULT_POLL_SECONDS),180,3600,'poll_seconds')
    entries=raw.get('tasks')
    if not isinstance(entries,list) or len(entries)>50:
        raise ValueError('invalid_task_list')
    tasks={};outboxes=set()
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)-TASK_FIELDS:
            raise ValueError('invalid_task_fields')
        task=entry.copy()
        identifier=task.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',identifier) or identifier in tasks:
            raise ValueError('invalid_or_duplicate_task_id')
        name=task.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>80:
            raise ValueError('invalid_task_name')
        if type(task.get('enabled')) is not bool:
            raise ValueError('invalid_task_enabled')
        if task.get('network')!='threads' or task.get('account')!=ACCOUNT_NAME:
            raise ValueError('unsupported_network_or_account')
        topic=task.get('topic')
        if not isinstance(topic,str) or not topic.strip() or len(topic)>100:
            raise ValueError('invalid_task_topic')
        outbox=task.get('outbox')
        if (not isinstance(outbox,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}\.json',outbox)
            or outbox in RESERVED_FILES or outbox in outboxes):
            raise ValueError('invalid_or_duplicate_outbox')
        task.setdefault('image_required',True)
        if type(task['image_required']) is not bool:
            raise ValueError('invalid_image_required')
        task['max_posts']=integer(task.get('max_posts',500),1,500,'max_posts')
        task['max_utf16']=integer(task.get('max_utf16',450),1,450,'max_utf16')
        task['late_grace_seconds']=integer(task.get('late_grace_seconds',300),1,300,'late_grace_seconds')
        tasks[identifier]=task
        outboxes.add(outbox)
    return {'schema_version':SCHEMA_VERSION,'poll_seconds':poll,'tasks':tasks}


if __name__ == '__main__':
    import json
    import sys
    try:
        if len(sys.argv)!=2:
            raise ValueError('usage: python registry.py <tasks.json|->')
        if sys.argv[1]=='-':
            raw=json.load(sys.stdin)
        else:
            with open(sys.argv[1],encoding='utf-8-sig') as stream:
                raw=json.load(stream)
        checked=load_registry(raw)
        print(json.dumps({'ok':True,'task_count':len(checked['tasks']),
                          'task_ids':list(checked['tasks']),'poll_seconds':checked['poll_seconds']},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
