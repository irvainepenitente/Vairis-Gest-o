import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from server import Jobs, make_handler
from portal import NeedsReview


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        def execute(path):
            path.write_bytes(b'PNG test')
            return {'visibleCount': 0, 'message': 'Nenhum evento.', 'events': []}
        self.jobs = Jobs(self.temp.name, execute)
        self.token = 'test-token-' * 5
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.jobs, self.token))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.previous = {k: os.environ.get(k) for k in ('EVENTOS_USERNAME', 'EVENTOS_PASSWORD')}
        os.environ['EVENTOS_USERNAME'] = 'fixture'
        os.environ['EVENTOS_PASSWORD'] = 'fixture'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()
        for k, v in self.previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def call(self, path, method='GET', owner='a'*64, token=True, data=None):
        headers = {'X-Vairis-Owner': owner}
        if token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = Request(self.url+path, method=method, headers=headers, data=json.dumps(data).encode() if data is not None else None)
        try:
            with urlopen(req) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, e.read()

    def test_job_persistence_image_isolation_and_idempotency(self):
        job_id = str(uuid.uuid4())
        self.assertEqual(self.call('/jobs', 'POST', data={'id': job_id, 'owner': 'a'*64})[0], 202)
        for _ in range(100):
            if self.jobs.get('a'*64, job_id)['status'] == 'succeeded':
                break
            time.sleep(.01)
        self.assertEqual(self.jobs.get('a'*64, job_id)['status'], 'succeeded')
        self.assertEqual(self.call('/jobs/'+job_id, owner='b'*64)[0], 404)
        self.assertEqual(self.call('/jobs/'+job_id+'/image', owner='b'*64)[0], 404)
        self.assertEqual(self.call('/jobs/'+job_id+'/image')[0], 200)
        self.assertEqual(self.call('/jobs', 'POST', data={'id': job_id, 'owner': 'a'*64})[0], 202)
        self.assertEqual(json.loads(self.call('/jobs/latest')[1])['job']['id'], job_id)
        self.assertIsNone(json.loads(self.call('/jobs/latest', owner='b'*64)[1])['job'])
        self.assertEqual(Jobs(self.temp.name).get('a'*64, job_id)['status'], 'succeeded')

    def test_auth_invalid_body_and_missing_credentials(self):
        self.assertEqual(self.call('/health', token=False)[0], 200)
        self.assertEqual(self.call('/status', token=False)[0], 401)
        self.assertEqual(self.call('/jobs', 'POST', data={'id': '../../secret', 'owner': 'a'*64})[0], 400)
        os.environ.pop('EVENTOS_PASSWORD')
        self.assertFalse(json.loads(self.call('/status')[1])['ready'])
        self.assertEqual(self.call('/jobs', 'POST', data={'id': str(uuid.uuid4()), 'owner': 'a'*64})[0], 409)

    def test_restart_marks_running_interrupted_and_review_is_sanitized(self):
        job_id = str(uuid.uuid4())
        with self.jobs.connect() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,NULL)', (job_id, 'a'*64, 'running', 'Executando', time.time()))
        self.assertEqual(Jobs(self.temp.name).get('a'*64, job_id)['status'], 'interrupted')
        def reject(_):
            raise NeedsReview('Verificação de login necessária.')
        self.jobs.executor = reject
        self.jobs.run('a'*64, job_id)
        self.assertEqual(self.jobs.get('a'*64, job_id)['status'], 'needs_review')
        def fail(_):
            raise RuntimeError('secret password fixture')
        self.jobs.executor = fail
        self.jobs.run('a'*64, job_id)
        self.assertNotIn('secret', self.jobs.get('a'*64, job_id)['message'])


if __name__ == '__main__':
    unittest.main()
