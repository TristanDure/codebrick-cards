"""Verify the app's expected static assets and the isolated demo shard allowlist."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts.build_public_demo import build


class PublicDemoTests(unittest.TestCase):
    def fixture(self, parent):
        root = parent / 'root'
        root.mkdir()
        (root / 'web').mkdir()
        for name in ('workbench.html', 'workbench.js', 'workbench.css', 'workbench-progress.js'):
            (root / 'web' / name).write_text('fixture', encoding='utf-8')
        return root

    def test_build_does_not_touch_existing_study_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = self.fixture(parent)
            index = root / 'data/study/index.json'
            index.parent.mkdir(parents=True)
            index.write_bytes(b'keep real study data')
            site = parent / 'site'
            self.assertEqual(build(root, site), 0)
            self.assertEqual(index.read_bytes(), b'keep real study data')
            self.assertIn('web/workbench.html', (site / 'index.html').read_text(encoding='utf-8'))
            data = json.loads((site / 'data/study/index.json').read_bytes())
            self.assertEqual(data['summary']['atomicCandidates'], 4)
            self.assertFalse(data['contentApproved'])
            self.assertEqual(data['summary']['approvedCards'], 0)
            self.assertEqual({p.name for p in (site / 'web').iterdir()},
                             {'workbench.html', 'workbench.js', 'workbench.css', 'workbench-progress.js'})

    def test_invalid_destination_leaves_root_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                build(root, root / 'site')
            self.assertEqual(list(root.iterdir()), [])

    def test_nonempty_site_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = self.fixture(parent)
            site = parent / 'site'
            site.mkdir()
            sentinel = site / 'keep.txt'
            sentinel.write_text('keep', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not empty'):
                build(root, site)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'keep')
            self.assertFalse((root / 'data').exists())
