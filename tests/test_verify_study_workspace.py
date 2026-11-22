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
        self.raw = json.dumps({"contentApproved": False, "article": {"id": "demo", "summary": {"approvedCards": 0}}, "atomicCandidates": [], "curated": []}, separators=(",", ":")).encode()
        (self.base / 'demo.json').write_bytes(self.raw)
        self.index = {'schema': 'codebrick-article-workspace', 'contentApproved': False,
                      'summary': {'articles': 1, 'approvedCards': 0},
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

    def test_rejects_forged_approval_claim(self):
        self.index["contentApproved"] = True
        self.index["summary"]["approvedCards"] = 1
        with self.assertRaisesRegex(ValueError, "approval|approved"):
            self.check()

    def test_rejects_shard_identity_mismatch(self):
        shard = json.loads(self.raw)
        shard["article"]["id"] = "other"
        self.raw = json.dumps(shard, separators=(",", ":")).encode()
        (self.base / "demo.json").write_bytes(self.raw)
        self.index["articles"][0]["bytes"] = len(self.raw)
        self.index["articles"][0]["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "identity"):
            self.check()

    def test_rejects_approved_shard_or_candidate_claim(self):
        shard = json.loads(self.raw)
        shard["contentApproved"] = True
        self.raw = json.dumps(shard, separators=(",", ":")).encode()
        (self.base / "demo.json").write_bytes(self.raw)
        self.index["articles"][0]["bytes"] = len(self.raw)
        self.index["articles"][0]["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "approval|approved"):
            self.check()

    def test_rejects_approved_curated_candidate_status(self):
        shard = json.loads(self.raw)
        shard["curated"] = [{"cards": [{"id": "card-1", "status": "approved"}]}]
        self.raw = json.dumps(shard, separators=(",", ":")).encode()
        (self.base / "demo.json").write_bytes(self.raw)
        self.index["articles"][0]["bytes"] = len(self.raw)
        self.index["articles"][0]["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "approved status"):
            self.check()

    def test_rejects_approved_candidate_status(self):
        shard = json.loads(self.raw)
        shard["atomicCandidates"] = [{"id": "card-1", "status": "approved"}]
        self.raw = json.dumps(shard, separators=(",", ":")).encode()
        (self.base / "demo.json").write_bytes(self.raw)
        self.index["articles"][0]["bytes"] = len(self.raw)
        self.index["articles"][0]["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "approved status"):
            self.check()

    def test_rejects_nonzero_article_approved_count(self):
        shard = json.loads(self.raw)
        shard["article"]["summary"]["approvedCards"] = 1
        self.raw = json.dumps(shard, separators=(",", ":")).encode()
        (self.base / "demo.json").write_bytes(self.raw)
        self.index["articles"][0]["bytes"] = len(self.raw)
        self.index["articles"][0]["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "approval|approved"):
            self.check()

    def test_path_escape(self):
        self.index['articles'][0]['file'] = '../private.json'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.check()

    def test_missing(self):
        (self.base / 'demo.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()
