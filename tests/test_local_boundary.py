import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

_task_state = tempfile.TemporaryDirectory(prefix='dork-boundary-')
os.environ['DORK_STATE_HOME'] = _task_state.name
os.environ['DORK_NO_ENV'] = '1'
os.environ['XAI_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''
_module_path = Path(__file__).resolve().parents[1] / 'app/dashboard.py'
spec = importlib.util.spec_from_file_location('dork_boundary', _module_path)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


class LocalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()

    def test_offline_editor_and_empty_local_libraries(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Draw to direct', response.data)
        self.assertIn(b'grok-imagine-video-1.5-lite', response.data)
        for endpoint in ['/api/image/list', '/api/video/list', '/api/artifacts/list', '/api/asset-library']:
            self.assertEqual(self.client.get(endpoint).status_code, 200)

    def test_no_inherited_keys_and_no_partial_key_disclosure(self):
        self.assertEqual(dashboard.get_api_key(), '')
        dashboard.save_settings({'xai_key': 'dummy-boundary-fixture'})
        result = self.client.get('/api/settings').get_json()
        self.assertNotIn('xai_key', result)
        self.assertEqual(result['xai_key_preview'], 'configured')
        self.assertNotIn('dummy', str(result))
        self.assertEqual(dashboard.SETTINGS_FILE.stat().st_mode & 0o777, 0o600)
        dashboard.save_settings({'xai_key': ''})

    def test_cross_site_and_rebinding_rejected(self):
        self.assertEqual(self.client.get('/api/settings', headers={'Host': 'attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings', json={}, headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/settings', headers={'Origin': 'null'}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings', json={}, headers={'Origin': 'http://localhost'}).status_code, 200)

    def test_filename_traversal_rejected(self):
        for filename in ['../settings/settings.json', '/tmp/victim', '..\\victim']:
            self.assertEqual(self.client.post('/api/image/delete', json={'filename': filename}).status_code, 400)

    def test_artifact_runs_in_opaque_network_blocked_sandbox(self):
        response = self.client.post('/api/artifacts/save', json={'title': 'Synthetic chart', 'html': '<p>hello</p>', 'js': 'document.body.dataset.ready="yes"'})
        self.assertEqual(response.status_code, 200)
        page = self.client.get(response.get_json()['url'])
        policy = page.headers['Content-Security-Policy']
        page.close()
        self.assertIn('sandbox allow-scripts', policy)
        self.assertNotIn('allow-same-origin', policy)
        self.assertIn("connect-src 'none'", policy)


if __name__ == '__main__':
    unittest.main()
