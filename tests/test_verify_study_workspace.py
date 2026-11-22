"""Publication verifier rejects tampered, missing and escaping shards."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts.verify_study_workspace import verify


class VerifyWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'data/study'
        self.base.mkdir(parents=True)
        self.raw = b'{"article":{"id":"demo"}}'
        (self.base / 'demo.json').write_bytes(self.raw)
        self.index = {'schema': 'codebrick-article-workspace', 'summary': {'articles': 1},
                      'articles': [{'id': 'demo', 'file': 'demo.json', 'bytes': len(self.raw),
                                    'sha256': hashlib.sha256(self.raw).hexdigest()}]}

    def check(self):
        (self.base / 'index.json').write_text(json.dumps(self.index), encoding='utf-8')
        return verify(self.root)

    def test_intact(self):
        self.assertEqual(self.check(), 1)

    def test_tampered(self):
        (self.base / 'demo.json').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.check()

    def test_path_escape(self):
        self.index['articles'][0]['file'] = '../private.json'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.check()

    def test_missing(self):
        (self.base / 'demo.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()
