"""Read-only inventory of article candidates and hash-bound independent review claims.

Counts are triage evidence only: this does not certify review quality or 408 readiness.
"""
from __future__ import annotations
import argparse, collections, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def audit(root=ROOT):
    root=Path(root).resolve(); articles=load(root/"data/articles.json")["articles"]
    reviews=collections.defaultdict(list)
    excluded_reviews=set()
    for correction_path in sorted((root/"data/reports").glob("*provenance-correction*.json")):
        correction=load(correction_path)
        target=correction.get("target",{})
        if correction.get("eligibleAsIndependentPass") is False and target.get("file") and target.get("sha256"):
            excluded_reviews.add((target["file"],target["sha256"]))
    for path in sorted((root/"data/reports").glob("*independent*review*.json")):
        r=load(path); c=r.get("candidate",{})
        if not isinstance(c,dict): c={}
        scope=r.get("scope",{})
        if not isinstance(scope,dict): scope={}
        # Older independent reports use candidate.path. Conflicting aliases
        # must never associate one verdict with two different candidates.
        if c.get("file") and c.get("path") and c["file"] != c["path"]:
            continue
        candidate=c.get("file") or c.get("path") or scope.get("candidate")
        digest=c.get("sha256") or scope.get("candidateSha256")
        if not isinstance(candidate,str) or not isinstance(digest,str): continue
        verdict=r.get("decision") or r.get("result",{}).get("cardTextVerdict")
        cards=r.get("cards",[])
        if not isinstance(cards,list) or any(not isinstance(card,dict) for card in cards):
            continue
        if any(card.get("cardId") and card.get("id") and card["cardId"] != card["id"] for card in cards):
            continue
        report_ids=[card.get("cardId",card.get("id")) for card in cards]
        if any(not isinstance(cid,str) or not cid.strip() for cid in report_ids):
            continue
        if len(report_ids) != len(set(report_ids)):
            continue
        counts=collections.Counter(v.get("decision",v.get("verdict","UNPROVEN")) for v in cards)
        reviews[(candidate.replace("\\","/"),digest)].append({"file":path.relative_to(root).as_posix(),"sha256":sha(path),"decision":verdict,"cardCounts":dict(counts),"cardIds":[v.get("cardId",v.get("id")) for v in cards],"scopeClaimOnly":True,"excludedByProvenanceCorrection":(path.relative_to(root).as_posix(),sha(path)) in excluded_reviews})
    published={}; index_path=root/"data/study/index.json"
    if index_path.exists():
        index=load(index_path)
        for a in index["articles"]:
            shardpath=root/"data/study"/a["file"]
            if sha(shardpath)!=a["sha256"] or shardpath.stat().st_size!=a["bytes"]: raise ValueError("published shard binding mismatch: "+a["file"])
            for d in load(shardpath)["curated"]:published[d["file"]]=d["sha256"]
    article_urls={a["url"] for a in articles}
    drafts=collections.defaultdict(list)
    for path in sorted((root/"data/curated").glob("*.json")):
        d=load(path)
        # This directory also contains author metadata and structure audit JSON.
        # Count only candidate-shaped objects with a URL in the frozen manifest;
        # shape filtering is not structure validation or content approval.
        if not isinstance(d,dict) or not isinstance(d.get("cards"),list):
            continue
        article=d.get("article",{})
        if not isinstance(article,dict): article={}
        if d.get("articleUrl") and article.get("url") and d["articleUrl"] != article["url"]:
            continue
        url=d.get("articleUrl") or article.get("url")
        if not isinstance(url,str) or url not in article_urls:
            continue
        if any(not isinstance(card,dict) for card in d["cards"]):
            continue
        if any(card.get("id") and card.get("cardId") and card["id"] != card["cardId"] for card in d["cards"]):
            continue
        card_ids=[card.get("id",card.get("cardId")) for card in d["cards"]]
        if any(not isinstance(cid,str) or not cid.strip() for cid in card_ids):
            continue
        if len(card_ids) != len(set(card_ids)):
            continue
        rel=path.relative_to(root).as_posix(); digest=sha(path)
        matches=reviews.get((rel,digest),[])
        # PASS here is only a report claim tied to the exact file; NOT a semantic certification.
        claims=[r for r in matches if not r["excludedByProvenanceCorrection"] and str(r["decision"]).startswith("PASS") and r["cardCounts"].get("FAIL",0)==0 and r["cardCounts"].get("PASS",0)==len(d.get("cards",[])) and len(d.get("cards",[]))>0 and r["cardIds"]==[c.get("id",c.get("cardId")) for c in d.get("cards",[])]]
        drafts[url].append({"file":rel,"sha256":digest,"cards":len(d.get("cards",[])),"publishedExactBytes":published.get(rel)==digest,"reviewReports":matches,"hasExactHashPassClaim":bool(claims),"unresolved":sum(u.get("action")=="unresolved" for u in d.get("unitDisposition",[])),"openIssues":sum(str(i.get("status","")).lower()=="open" for i in d.get("issues",[]))})
    rows=[]; totals=collections.defaultdict(collections.Counter)
    for a in articles:
        ds=drafts.get(a["url"],[]); status="missing-author-candidate" if not ds else "candidate-awaits-or-failed-review"
        if any(d["hasExactHashPassClaim"] for d in ds):status="exact-hash-pass-claim-present"
        if any(d["publishedExactBytes"] for d in ds):status="published-unapproved-trial"
        totals[a["sourceId"]][status]+=1
        rows.append({"sourceId":a["sourceId"],"title":a["title"],"url":a["url"],"status":status,"candidateVersions":ds,"contentApproved":False})
    return {"schema":"codebrick-article-review-queue-audit","version":1,"articleManifestSha256":sha(root/"data/articles.json"),"publishedIndexSha256":sha(index_path),"articles":rows,"summary":{"articles":len(rows),"candidateArticles":sum(bool(r["candidateVersions"]) for r in rows),"candidateVersions":sum(len(r["candidateVersions"]) for r in rows),"publishedArticles":sum(r["status"]=="published-unapproved-trial" for r in rows),"subjects":{s:dict(c) for s,c in sorted(totals.items())}},"limits":["PASS is an exact-file-bound report claim only; semantic evidence quality, source coverage, outline, exams and rendering require separate audit.","Multiple candidate versions never count as multiple articles; historical FAIL reports remain visible.","Published trial packages include historical unapproved material; publication is not content approval."],"contentApproved":False,"wholeCorpusApproved":False}
if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--root",type=Path,default=ROOT);args=ap.parse_args()
    print(json.dumps(audit(args.root),ensure_ascii=False,indent=2))
