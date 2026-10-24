import json
import os
import pathlib
import queue
import re
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
import hashlib

API = 'https://graph.threads.com/v1.0'
ACCOUNT = '29153815030881952'
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 20
VERSION = '0.4'
DATA = pathlib.Path(os.environ.get('SP_DATA', '/data'))

def image_list(image=None, images=None):
    """Keep legacy one-image jobs readable; never silently discard a media field."""
    if images is not None:
        if image is not None or not isinstance(images, list):
            raise ValueError('image와 images를 함께 지정할 수 없으며 images는 배열이어야 합니다.')
        result = images
    else:
        result = [] if image is None else [image]
    if len(result) > MAX_IMAGES or any(not isinstance(item, dict) for item in result):
        raise ValueError('이미지는 순서대로 최대 20장까지 지정할 수 있습니다.')
    return result

def saved_token():
    token = (DATA / 'threads-token').read_text().strip()
    if not token:
        raise RuntimeError('서버 토큰을 먼저 등록해 주세요.')
    return token

def units(text):
    return len(text.encode('utf-16-le')) // 2

def split_posts(text, limit=450):
    if not text.strip():
        raise ValueError('본문을 입력해 주세요.')
    # Keep each URL, number and whitespace-delimited word intact.
    for word in re.findall(r'\S+', text):
        if units(word) > limit:
            raise ValueError('450자를 넘는 URL 또는 공백 없는 구절이 있습니다. 해당 구절을 편집해 주세요.')
    parts = []
    rest = text
    while units(rest) > limit:
        used = 0
        end = 0
        for char in rest:
            used += units(char)
            if used > limit:
                break
            end += 1
        window = rest[:end]
        # Prefer paragraphs, then lines, then sentences, then word boundaries.
        candidates = []
        for pattern in (r'\n\s*\n', r'\n', r'[.!?。！？]\s+', r'\s+'):
            matches = [m.end() for m in re.finditer(pattern, window)
                       if rest[:m.end()].strip() and units(rest[:m.end()]) >= limit // 2]
            if matches:
                candidates = matches
                break
        if not candidates:
            candidates = [m.end() for m in re.finditer(r'\s+', window)
                          if rest[:m.end()].strip()]
        if not candidates:
            raise ValueError('안전한 분할 지점을 찾지 못했습니다. 긴 구절 사이에 공백을 넣어 주세요.')
        cut = candidates[-1]
        parts.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        parts.append(rest)
    assert ''.join(parts) == text
    assert all(part.strip() and units(part) <= limit for part in parts)
    return parts

def read_public(url, maximum):
    req = urllib.request.Request(url, headers={'User-Agent': 'SocialPublisher/0.3'})
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError('파일이 프로그램의 크기 제한을 넘었습니다. 이미지는 8MB 이하로 준비해 주세요.')
        return content

def image_bytes(url):
    content = read_public(url, MAX_IMAGE_BYTES)
    if content.startswith(b'\xff\xd8\xff'):
        extension = '.jpg'
    elif content.startswith(b'\x89PNG\r\n\x1a\n'):
        extension = '.png'
    else:
        raise ValueError('로그인 없이 JPEG/PNG 원본을 가져오지 못했습니다. 공유 권한과 다운로드 허용 설정을 확인해 주세요.')
    return content, extension

def resolve_drive_image(shared_url, cache):
    parsed = urllib.parse.urlparse(shared_url)
    if parsed.scheme != 'https' or parsed.hostname != 'drive.google.com':
        raise ValueError('https://drive.google.com/ 으로 시작하는 드라이브 파일 공유 링크를 입력해 주세요.')
    match = re.fullmatch(r'/file/d/([A-Za-z0-9_-]+)/view/?', parsed.path)
    if not match:
        raise ValueError('드라이브 파일의 공유 링크(/file/d/…/view)를 입력해 주세요. 폴더 링크는 지원하지 않습니다.')
    page = read_public(shared_url, 4 * 1024 * 1024).decode('utf-8', errors='replace')
    found = re.search(r'"(https://drive\.usercontent\.google\.com/uc[^" ]+)"', page)
    if not found:
        raise ValueError('공개 다운로드 주소를 찾지 못했습니다. 링크가 있는 모든 사용자 → 뷰어로 공유해 주세요.')
    download_url = json.loads('"' + found.group(1) + '"')
    target = urllib.parse.urlparse(download_url)
    query = urllib.parse.parse_qs(target.query)
    if (target.scheme != 'https' or target.hostname != 'drive.usercontent.google.com'
            or query.get('id') != [match.group(1)]):
        raise ValueError('다운로드 주소의 파일 ID를 확인하지 못했습니다.')
    content, extension = image_bytes(download_url)
    digest = hashlib.sha256(content).hexdigest()
    path = pathlib.Path(cache) / (digest + extension)
    path.write_bytes(content)
    return {'shared_url': shared_url, 'image_url': download_url,
            'sha256': digest, 'size': len(content), 'path': str(path)}

def request(token, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(API + path, data=body,
        headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace').replace(token, '[REDACTED]')
        raise RuntimeError(f'HTTP {exc.code}: {raw}') from None

class Publisher:
    def __init__(self):
        self.store = DATA / 'history'
        self.store.mkdir(parents=True, exist_ok=True)
        self.events = queue.Queue()

    def save(self, record):
        path = self.store / (record['job_id'] + '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def wait_ready(self, token, container):
        for _ in range(12):
            state = request(token, f'/{container}?fields=status,error_message')
            if state.get('status') == 'FINISHED':
                return
            if state.get('status') in ('ERROR', 'EXPIRED'):
                raise RuntimeError(str(state))
            time.sleep(5)
        raise RuntimeError('처리 대기 시간이 초과되었습니다. 이 글의 발행은 실행하지 않았습니다.')

    def send(self, text, topic, parts=None, image=None, scheduled=False, images=None):
        record = {'job_id': str(uuid.uuid4()), 'created_at': time.time(),
                  'text': text, 'requested_topic': topic, 'status': 'prepared', 'parts': []}
        active = None
        try:
            media = image_list(image, images)
            if images is not None:
                record['images'] = [{k: item[k] for k in ('shared_url','image_url','sha256','size')} for item in media]
            elif image:
                record['image'] = {k: image[k] for k in ('shared_url','image_url','sha256','size')}
            parts = parts if parts is not None else split_posts(text)
            if ''.join(parts) != text or any(not p.strip() or units(p) > 450 for p in parts):
                raise ValueError('분할 본문 검증에 실패했습니다.')
            record['parts'] = [{'text': p, 'status': 'prepared'} for p in parts]
            token = saved_token()
            account = request(token, '/me?fields=id,username')
            if account['id'] != ACCOUNT:
                raise RuntimeError('연결된 계정 ID가 예상 계정과 다릅니다.')
            for position, item in enumerate(media, 1):
                self.events.put(('progress', f'이미지 원본을 다시 확인하고 있습니다… {position}/{len(media)}'))
                content, _ = image_bytes(item['image_url'])
                if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                    raise ValueError('미리보기 이후 이미지가 바뀌었습니다. 다시 미리보기를 확인해 주세요.')
            self.save(record)
            previous_id = None
            for index, active in enumerate(record['parts']):
                self.events.put(('progress', f'{index+1}/{len(parts)}번째 글을 처리하고 있습니다…'))
                payload = {'media_type': 'TEXT', 'text': active['text'], 'auto_publish_text': 'false'}
                if index == 0 and len(media) == 1:
                    payload = {'media_type': 'IMAGE', 'text': active['text'], 'image_url': media[0]['image_url']}
                elif index == 0 and len(media) > 1:
                    active['children'] = []
                    self.save(record)
                    for position, item in enumerate(media, 1):
                        self.events.put(('progress', f'캐러셀 이미지 처리 중… {position}/{len(media)}'))
                        child = {'index':position,'status':'creating'}
                        active['children'].append(child)
                        self.save(record)
                        child_id = request(token, f'/{ACCOUNT}/threads', {
                            'media_type':'IMAGE', 'image_url':item['image_url'], 'is_carousel_item':'true'})['id']
                        child.update(container_id=child_id, status='container_created')
                        self.save(record)
                        self.wait_ready(token, child_id)
                        child['status'] = 'ready'
                        self.save(record)
                    payload = {'media_type':'CAROUSEL', 'text':active['text'],
                               'children':','.join(child['container_id'] for child in active['children'])}
                if index == 0 and topic:
                    payload['topic_tag'] = topic
                if previous_id:
                    payload['reply_to_id'] = previous_id
                    active['reply_to_id'] = previous_id
                container = request(token, f'/{ACCOUNT}/threads', payload)['id']
                active.update(container_id=container, status='container_created')
                self.save(record)
                self.wait_ready(token, container)
                active['status'] = 'publishing_unknown'
                self.save(record)
                published = request(token, f'/{ACCOUNT}/threads_publish', {'creation_id': container})['id']
                active.update(post_id=published, status='published_unverified')
                self.save(record)
                post = request(token, f'/{published}?fields=id,text,permalink,topic_tag')
                if post.get('id') != published or not post.get('permalink'):
                    raise RuntimeError('게시물 ID 또는 공개 링크 조회를 확인하지 못했습니다.')
                active.update(status='published', result=post)
                self.save(record)
                previous_id = published
            record['status'] = 'published'
            self.save(record)
            if not scheduled:
                self.events.put(('published', {'root': record['parts'][0]['result'], 'count': len(parts)}))
        except Exception as exc:
            record['error'] = str(exc)
            completed = sum(p['status'] == 'published' for p in record['parts'])
            if active is not None and active['status'] in ('publishing_unknown', 'published_unverified'):
                record['status'] = active['status']
            else:
                record['status'] = 'partial_failed' if completed else 'failed_before_publish'
            try:
                self.save(record)
            except OSError:
                pass
            if not scheduled:
                self.events.put(('error', f'확인된 게시: {completed}/{len(record["parts"])}개\n상태: {record["status"]}\n{exc}\n기록: {record["job_id"]}\n자동 재시도하지 않았습니다. 전체 글을 다시 게시하면 중복될 수 있으니 Threads와 이력을 확인해 주세요.'))

        return record
