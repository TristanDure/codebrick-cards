import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.audit_curated_review_queue import audit

class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name in ["data/curated","data/reports","data/study"]:(self.root/name).mkdir(parents=True)
        self.write("data/articles.json",{"articles":[{"sourceId":"os","title":"Example","url":"https://example.test/a"}]})
        self.write("data/study/index.json",{"articles":[]})
    def write(self,p,d):
        target=self.root/p;target.write_text(json.dumps(d),encoding="utf-8");return hashlib.sha256(target.read_bytes()).hexdigest()
    def draft(self,p="data/curated/a.json",cards=None):
        return self.write(p,{"articleUrl":"https://example.test/a","cards":[{"id":"a"}] if cards is None else cards,"unitDisposition":[],"issues":[]})
    def review(self,digest,ids=("a",),decision="PASS"):
        return self.write("data/reports/a-independent-review.json",{"candidate":{"file":"data/curated/a.json","sha256":digest},"decision":decision,"cards":[{"cardId":i,"decision":"PASS"} for i in ids]})
    def row(self):return audit(self.root)["articles"][0]
    def test_exact_hash_and_ids_required(self):
        h=self.draft();self.review(h);self.assertTrue(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
        self.review(h,ids=("wrong",));self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
        self.review("0"*64);self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
    def test_legacy_candidate_path_is_hash_bound_and_conflicts_are_rejected(self):
        h=self.draft()
        report={"candidate":{"path":"data/curated/a.json","sha256":h},"decision":"PASS","cards":[{"cardId":"a","decision":"PASS"}]}
        self.write("data/reports/a-independent-review.json",report)
        self.assertTrue(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
        report["candidate"]["sha256"]="0"*64
        self.write("data/reports/a-independent-review.json",report)
        self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
        report["candidate"].update(sha256=h,file="data/curated/other.json")
        self.write("data/reports/a-independent-review.json",report)
        self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
    def test_fail_and_correction_do_not_count(self):
        h=self.draft();self.review(h,decision="FAIL");self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
        r=self.review(h)
        self.write("data/reports/a-provenance-correction.json",{"target":{"file":"data/reports/a-independent-review.json","sha256":r},"eligibleAsIndependentPass":False})
        self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
    def test_versions_not_articles(self):
        self.draft();self.draft("data/curated/a-r2.json")
        x=audit(self.root);self.assertEqual(x["summary"]["candidateArticles"],1);self.assertEqual(x["summary"]["candidateVersions"],2)
    def test_metadata_and_non_candidate_json_not_counted_as_drafts(self):
        self.draft()
        for name,value in {
            "metadata": {"articleUrl":"https://example.test/a","cards":3},
            "audit": {"article":{"url":"https://example.test/a"},"ok":True},
            "array": [],
            "bad-card": {"articleUrl":"https://example.test/a","cards":[None]},
            "bad-article": {"article":None,"cards":[]},
            "unknown": {"articleUrl":"https://example.test/outside","cards":[{"id":"x"}]},
        }.items():
            self.write("data/curated/"+name+".json",value)
        self.assertEqual(audit(self.root)["summary"]["candidateVersions"],1)

    def test_bom_candidate_and_manifest_do_not_break_inventory(self):
        self.draft()
        for relative in ["data/curated/a.json","data/articles.json"]:
            path=self.root/relative
            path.write_bytes(b"\xef\xbb\xbf"+path.read_bytes())
        self.assertEqual(audit(self.root)["summary"]["candidateVersions"],1)

    def test_empty_cards_not_vacuous_pass(self):
        h=self.draft(cards=[]);self.review(h,ids=());self.assertFalse(self.row()["candidateVersions"][0]["hasExactHashPassClaim"])
    def test_corrupt_published_shard_fails_closed(self):
        self.write("data/study/shard.json",{"curated":[]})
        self.write("data/study/index.json",{"articles":[{"file":"shard.json","sha256":"0"*64,"bytes":1}]})
        with self.assertRaisesRegex(ValueError,"binding mismatch"):audit(self.root)
if __name__=="__main__":unittest.main()
