import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import core
import recovery as r


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = patch.object(core, 'DATA', Path(self.tmp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        self.addCleanup(self.tmp.cleanup)
        self.parts = ['approved root', 'approved reply']
        self.calls = []
        self.post_text = {}
        self.post_topics = {}
        self.containers = {}

    def api(self, token, path, data=None):
        self.calls.append((path, copy.deepcopy(data)))
        if path.startswith('/me?'):
            return {'id': core.ACCOUNT, 'username': 'genie_carrot'}
        if path.endswith('/threads') and data:
            cid = 'c' + str(len(self.containers) + 1)
            self.containers[cid] = data
            return {'id': cid}
        if path.endswith('/threads_publish'):
            cid = data['creation_id']
            pid = 'p' + cid
            self.post_text[pid] = self.containers[cid]['text']
            self.post_topics[pid] = self.containers[cid].get('topic_tag')
            return {'id': pid}
        ident = path.split('?', 1)[0].strip('/')
        if ident in self.post_text:
            return {'id': ident, 'text': self.post_text[ident], 'username': 'genie_carrot',
                    'permalink': 'https://www.threads.com/@genie_carrot/post/' + ident,
                    'topic_tag': self.post_topics.get(ident), 'media_type': 'TEXT'}
        if 'fields=id,status' in path:
            return {'id': ident, 'status': 'FINISHED'}
        if '/threads?' in path or '/replies?' in path:
            return {'data': []}
        raise AssertionError(path)

    def send(self, **kwargs):
        return r.Publisher().send(''.join(self.parts), '미국주식', self.parts,
                                  scheduled=True, job_id='stable-job', **kwargs)

    def patched(self, fn=None):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(core, 'saved_token', return_value='test-only-token'))
        stack.enter_context(patch.object(r, 'request', side_effect=fn or self.api))
        stack.enter_context(patch.object(r.time, 'sleep'))
        return stack

    def test_complete_chain_and_stable_id(self):
        with self.patched():
            result = self.send()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['job_id'], 'stable-job')
        creations = [d for p, d in self.calls if d and p.endswith('/threads')]
        self.assertEqual(creations[0]['topic_tag'], '미국주식')
        self.assertEqual(creations[1]['reply_to_id'], 'pc1')

    def test_ambiguous_publish_never_blindly_reposts(self):
        def api(t, p, d=None):
            if p.endswith('/threads_publish'):
                self.calls.append((p, d))
                raise TimeoutError('lost response')
            return self.api(t, p, d)
        with self.patched(api):
            result = self.send()
        self.assertEqual(result['status'], 'publishing_unknown')
        self.assertEqual(sum(p.endswith('/threads_publish') for p, d in self.calls), 1)
        self.assertTrue(result['parts'][0]['container_id'])

    def test_lost_response_adopts_verified_post(self):
        def api(t, p, d=None):
            if p.endswith('/threads_publish') and d['creation_id'] == 'c1':
                self.api(t, p, d)
                raise TimeoutError('accepted, response lost')
            return self.api(t, p, d)
        hit = {'id': 'pc1', 'text': self.parts[0], 'username': 'genie_carrot'}
        with self.patched(api), patch.object(r, 'own_matches', return_value=([hit], True)):
            result = self.send()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(sum(p.endswith('/threads_publish') for p, d in self.calls), 2)

    def test_explicit_429_reuses_same_container(self):
        seen = []
        def api(t, p, d=None):
            if p.endswith('/threads_publish'):
                seen.append(d['creation_id'])
                if len(seen) == 1:
                    raise r.MetaError(429, {'code': 4})
            return self.api(t, p, d)
        with self.patched(api):
            result = self.send()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(seen[:2], ['c1', 'c1'])

    def test_permanent_error_is_not_retried(self):
        seen = []
        def api(t, p, d=None):
            if p.endswith('/threads_publish'):
                seen.append(p)
                raise r.MetaError(400, {'code': 190, 'message': 'invalid credential'})
            return self.api(t, p, d)
        with self.patched(api):
            result = self.send()
        self.assertEqual(len(seen), 1)
        self.assertEqual(result['parts'][0]['last_error']['code'], 190)

    def test_resume_skips_existing_published_root(self):
        self.post_text['existing'] = self.parts[0]
        self.post_topics['existing'] = '미국주식'
        record = {'job_id': 'stable-job', 'created_at': 1, 'text': ''.join(self.parts),
                  'requested_topic': '미국주식', 'parts': [
                      {'text': self.parts[0], 'status': 'published', 'post_id': 'existing'},
                      {'text': self.parts[1], 'status': 'prepared'}]}
        with self.patched():
            result = self.send(record=record)
        self.assertEqual(result['status'], 'published')
        created = [d for p, d in self.calls if d and p.endswith('/threads')]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['reply_to_id'], 'existing')

    def test_wrong_account_has_no_side_effect(self):
        with self.patched(), patch.object(r, 'identity', side_effect=RuntimeError('wrong account')):
            result = self.send()
        self.assertEqual(result['status'], 'failed_before_publish')
        self.assertFalse(any(d for p, d in self.calls))

    def test_topic_mismatch_not_reported_success(self):
        def api(t, p, d=None):
            result = self.api(t, p, d)
            if p.startswith('/pc1?'):
                result['topic_tag'] = 'wrong'
            return result
        with self.patched(api):
            result = self.send()
        self.assertNotEqual(result['status'], 'published')

    def test_incomplete_timeline_cannot_authorize_retry(self):
        with self.patched(), patch.object(r, 'own_matches', return_value=([], False)):
            p = r.Publisher()
            record = {'job_id': 'stable-job', 'created_at': 1}
            with self.assertRaises(RuntimeError):
                p.reconcile('test', record, {'text': 'approved', 'container_id': 'c1'}, None)

    def test_changed_approved_text_rejected(self):
        record = {'job_id': 'stable-job', 'text': 'changed', 'parts': []}
        with self.assertRaises(ValueError), self.patched():
            self.send(record=record)

    def test_disk_failure_before_publish_never_posts(self):
        with self.patched(), patch.object(r.Publisher, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.send()
        self.assertFalse(any(p.endswith('/threads_publish') for p, d in self.calls))


if __name__ == '__main__':
    unittest.main()
