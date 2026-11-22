"""Validate hash-bound rich-source evidence; never grant semantic approval.

Snapshot schema v1 preserves capture payloads and binds each item with a JSON
Pointer. Static extraction/ledger records remain unchanged.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
SNAPSHOT_SCHEMA = "codebrick-supplement-snapshot"


def _url_key(value):
    """Only explicit CodeBrick www/embed aliases; keep other query context."""
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("must be an absolute HTTP(S) source URL")
    p = urlparse(value)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("must be an absolute HTTP(S) source URL without credentials")
    host = p.hostname.lower()
    port = p.port
    if port == {"http": 80, "https": 443}[p.scheme]:
        port = None
    query = parse_qsl(p.query, keep_blank_values=True)
    if host in ("codebrick.tech", "www.codebrick.tech"):
        host = "www.codebrick.tech"
        query = [(k, v) for k, v in query if (k, v) != ("embed", "1")]
    return p.scheme, host, port, p.path or "/", tuple(sorted(query)), p.fragment


def _material(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(v, (str, list)) for v in value) and any(_material(v) for v in value)
    return False


def _snapshot_payload(snapshot, url):
    fields = {"schema", "version", "url", "capturedAt", "captureMethod", "payloadType", "payload"}
    if not isinstance(snapshot, dict) or set(snapshot) != fields:
        raise ValueError("snapshot must use the documented versioned evidence envelope")
    if snapshot["schema"] != SNAPSHOT_SCHEMA or type(snapshot["version"]) is not int or snapshot["version"] != 1:
        raise ValueError("unsupported snapshot schema/version")
    if snapshot["url"] != url:
        raise ValueError("snapshot URL must match supplemental source URL")
    captured = snapshot["capturedAt"]
    if not isinstance(captured, str):
        raise ValueError("capturedAt must be an ISO date or timezone-qualified timestamp")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured):
        datetime.date.fromisoformat(captured)
    else:
        stamp = datetime.datetime.fromisoformat(captured.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("capture timestamp must include timezone")
    if not isinstance(snapshot["captureMethod"], str) or not snapshot["captureMethod"].strip():
        raise ValueError("captureMethod must be nonempty text")
    payload = snapshot["payload"]
    if not isinstance(payload, dict) or payload.get("url") != url:
        raise ValueError("payload must be an evidence object bound to the same URL")
    if snapshot["payloadType"] == "dom-extract":
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            raise ValueError("DOM evidence must contain nonempty captured text")
        if "tables" in payload and (not isinstance(payload["tables"], list) or any(not isinstance(t, list) or not t or any(not isinstance(row, list) or not row or any(not isinstance(c, str) for c in row) for row in t) for t in payload["tables"])):
            raise ValueError("tables must be arrays of text rows and cells")
        return ("/payload/text", "/payload/tables/")
    if snapshot["payloadType"] == "site-question":
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("url") != url or not isinstance(evidence.get("stem"), str) or not evidence["stem"].strip():
            raise ValueError("question evidence must contain a URL-bound nonempty captured stem")
        options = evidence.get("options")
        if not isinstance(options, list):
            raise ValueError("question options must be an array (empty for open questions)")
        pointers = ["/payload/evidence/stem"]
        for n, option in enumerate(options):
            if isinstance(option, str) and option.strip():
                pointers.append(f"/payload/evidence/options/{n}")
            elif isinstance(option, dict) and isinstance(option.get("text"), str) and option["text"].strip():
                pointers.append(f"/payload/evidence/options/{n}/text")
            else:
                raise ValueError("question options must contain captured option text")
        return tuple(pointers)
    raise ValueError("unsupported evidence payload type")


def _evidence_pointer(snapshot, pointer, allowed):
    if not isinstance(pointer, str) or not any(pointer == p or (p.endswith("/") and pointer.startswith(p)) for p in allowed):
        raise ValueError("evidencePointer must address supported captured evidence, not metadata")
    value = snapshot
    for part in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", part):
            raise ValueError("invalid JSON Pointer escape")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            value = value[int(key)]
        else:
            raise ValueError("evidencePointer does not resolve")
    if not _material(value):
        raise ValueError("evidencePointer must resolve to nonempty captured text/rows")


def validate(document, root: Path, section_indices, static_units):
    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict) or "supplementalSources" not in metadata:
        return [], []
    errors, result = [], []
    def fail(path, message):
        errors.append({"code": "supplemental_source", "path": path, "message": message})
    sources = metadata["supplementalSources"]
    if not isinstance(sources, list):
        fail("$.metadata.supplementalSources", "must be an array")
        return [], errors
    cards = {c.get("id", c.get("cardId")): c for c in document.get("cards", []) if isinstance(c, dict)}
    units = static_units if isinstance(static_units, dict) else {}
    seen = set()
    for n, source in enumerate(sources):
        at = f"$.metadata.supplementalSources[{n}]"
        required = {"id", "parentSectionIndex", "url", "snapshotPath", "snapshotSha256", "anchorUnitIds", "items"}
        if not isinstance(source, dict) or set(source) != required:
            fail(at, "source must contain exactly the documented fields")
            continue
        sid = source["id"]
        if not isinstance(sid, str) or not sid.strip() or sid in seen:
            fail(at + ".id", "source id must be nonempty and unique")
        else:
            seen.add(sid)
        section = source["parentSectionIndex"]
        if type(section) is not int or section not in section_indices:
            fail(at + ".parentSectionIndex", "must refer to an existing source section")
        url = source["url"]
        try:
            target_key = _url_key(url)
        except ValueError as exc:
            target_key = None
            fail(at + ".url", str(exc))
        anchors = source["anchorUnitIds"]
        if not isinstance(anchors, list) or not anchors or any(not isinstance(v, str) or v not in units for v in anchors) or len(set(anchors)) != len(anchors):
            fail(at + ".anchorUnitIds", "must be unique existing static source units with metadata")
            anchors = []
        for uid in anchors:
            unit = units[uid]
            try:
                if not isinstance(unit, dict):
                    raise ValueError("anchor metadata must be an object")
                field = {"a": "href", "iframe": "src", "embed": "src", "img": "src"}.get(unit.get("tag"))
                if not field:
                    raise ValueError("anchor must be a static link or supported embedded resource")
                if target_key is None or _url_key(unit.get(field)) != target_key:
                    raise ValueError("static anchor target does not match supplemental source URL")
            except ValueError as exc:
                fail(at + ".anchorUnitIds", str(exc))
        relative, expected = source["snapshotPath"], source["snapshotSha256"]
        snapshot, allowed = None, ()
        try:
            if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or Path(relative).is_absolute():
                raise ValueError("snapshot path must be project-relative")
            target = (root / relative).resolve()
            if root.resolve() not in target.parents:
                raise ValueError("snapshot path escapes project root")
            with target.open("rb") as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                raise ValueError("supplemental snapshot exceeds size limit")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("snapshot SHA-256 mismatch")
            snapshot = json.loads(raw)
            allowed = _snapshot_payload(snapshot, url)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            fail(at + ".snapshotPath", str(exc))
        items = source["items"]
        if not isinstance(items, list) or not items:
            fail(at + ".items", "must be a nonempty array")
            continue
        seen_items = set()
        for j, item in enumerate(items):
            ip = at + f".items[{j}]"
            if not isinstance(item, dict) or set(item) != {"id", "locator", "text", "cardIds", "evidencePointer"}:
                fail(ip, "item must contain id, locator, text, cardIds, evidencePointer")
                continue
            for field in ("id", "locator", "text"):
                if not isinstance(item[field], str) or not item[field].strip():
                    fail(ip + "." + field, "must be nonempty text")
            try:
                _evidence_pointer(snapshot, item["evidencePointer"], allowed)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                fail(ip + ".evidencePointer", str(exc))
            iid = item["id"]
            if isinstance(iid, str):
                if iid in seen_items:
                    fail(ip + ".id", "item id must be unique within source")
                seen_items.add(iid)
            refs = item["cardIds"]
            if not isinstance(refs, list) or not refs or any(not isinstance(v, str) or v not in cards for v in refs):
                fail(ip + ".cardIds", "must reference existing candidate cards")
                continue
            if len(set(refs)) != len(refs):
                fail(ip + ".cardIds", "duplicate card reference")
            for cid in refs:
                c = cards[cid]
                if not set(c.get("unitIds", c.get("knowledgeUnitIds", []))) & set(anchors):
                    fail(ip + ".cardIds", "card must also cite a declared static anchor")
        result.append(source)
    return result, errors
