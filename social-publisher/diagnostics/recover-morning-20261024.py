#!/usr/bin/env python3
"""Prepare an exact-content, same-job candidate. Never append a retry outbox job."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.request
from PIL import Image

KEY = 'morning:2026-10-24'
REPO = 'comfunnylj/telegram-market-feed'
OUT = Path('social-publisher/media/morning-20261024-recovery1080.jpg')


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Threads-Recovery/20261024'}), timeout=30) as r:
        b = r.read(8 * 1024 * 1024 + 1)
    if len(b) > 8 * 1024 * 1024:
        raise ValueError('Oversize media')
    return b


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout.strip()


def prepare(publish_asset=False):
    source = json.loads(Path('social-publisher/automation/morning.json').read_text())
    hits = [j for j in source['jobs'] if j.get('dedup_key') == KEY]
    if len(hits) != 1:
        raise ValueError('Original approved job is not unique')
    original = hits[0]
    assert original['topic'] == '미국주식' and len(original['parts']) == 8
    assert ''.join(original['parts']) == original['text']
    assert all(p.strip() and len(p.encode('utf-16-le')) // 2 <= 450 for p in original['parts'])
    raw = get(original['image']['url'])
    assert len(raw) == original['image']['size']
    assert hashlib.sha256(raw).hexdigest() == original['image']['sha256']
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        height = round(im.height * 1080 / im.width)
        assert 320 <= height <= 3200
        normalized = im.convert('RGB').resize((1080, height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        normalized.save(buf, 'JPEG', quality=95, subsampling=0, optimize=True)
    data = buf.getvalue()
    assert 20000 < len(data) < 8 * 1024 * 1024
    with Image.open(io.BytesIO(data)) as check:
        check.verify()
    OUT.parent.mkdir(exist_ok=True, parents=True)
    if OUT.exists() and OUT.read_bytes() != data:
        raise ValueError('Existing asset differs; never overwrite immutable media')
    OUT.write_bytes(data)
    image = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    if publish_asset:
        git('config', 'user.name', 'github-actions[bot]')
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        git('add', str(OUT))
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
            git('commit', '-m', 'Normalize original October 24 morning image for same-job recovery')
            for attempt in range(3):
                try:
                    git('push', 'origin', 'HEAD:main')
                    break
                except subprocess.CalledProcessError:
                    if attempt == 2:
                        raise
                    git('pull', '--rebase', 'origin', 'main')
        revision = git('rev-parse', 'HEAD')
        image['url'] = f'https://raw.githubusercontent.com/{REPO}/{revision}/{OUT}'
        assert get(image['url']) == data
    candidate = {'dedup_key': KEY, 'text': original['text'], 'parts': original['parts'],
                 'topic': original['topic'], 'image': image, 'original_image': original['image']}
    Path('morning-recovery-candidate.json').write_text(json.dumps(candidate, ensure_ascii=False, indent=2))
    print(json.dumps({'key': KEY, 'parts': len(original['parts']), 'image_pixels': [1080, height],
                      'image_bytes': len(data), 'asset_uploaded': publish_asset,
                      'outbox_mutated': False}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish-asset', action='store_true')
    prepare(parser.parse_args().publish_asset)
