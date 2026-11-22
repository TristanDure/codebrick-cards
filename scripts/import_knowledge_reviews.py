from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from . import audit_coverage
except ImportError:  # direct script execution
    import audit_coverage

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "codebrick-knowledge-unit-review-ledger"
ENVELOPE_FIELDS = {"schema", "version", "exportedAt", "records"}
RECORD_FIELDS = {
    "knowledgeUnitId", "decision", "reason", "reviewer", "examPoints",
    "acceptedCardIds", "reviewedAt", "sourceHash", "textHash",
}
UNIT_ID_RE = re.compile(r"^[a-f0-9]{16}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_DECISIONS = {"accepted", "rejected", "needs-more-evidence"}
MAX_EXPORT_BYTES = 64 * 1024 * 1024
REVIEW_LEDGER_FIELDS = (
    "reviewerDecision", "reviewerNote", "reviewer", "reviewedAt",
    "acceptedCardIds", "examPointIds", "reviewSourceSha256", "bodySha256",
)
STALE_FIELDS = ("reviewStaleReason", "staleFromSourceSha256", "staleFromBodySha256")


class ImportValidationError(ValueError):
    """Raised when an import cannot be proven safe to merge."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ImportValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ImportValidationError(f"non-standard JSON numeric constant: {value}")

def _decode_json(raw: bytes, path: Path) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportValidationError(f"invalid UTF-8 JSON in {path}: {exc}") from exc


def _read_json(path: Path, *, max_bytes: int | None = None) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ImportValidationError(f"cannot read {path}: {exc}") from exc
    if max_bytes is not None and len(raw) > max_bytes:
        raise ImportValidationError(f"file exceeds the {max_bytes}-byte safety limit: {path}")
    return _decode_json(raw, path)


def _validate_timestamp(value: Any, field: str, record_label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImportValidationError(f"{record_label} has an invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImportValidationError(f"{record_label} has an invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ImportValidationError(f"{record_label} {field} must include a timezone")
    return value


def _validate_export(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path, max_bytes=MAX_EXPORT_BYTES)
    if (
        not isinstance(raw, dict)
        or set(raw) != ENVELOPE_FIELDS
        or raw.get("schema") != SCHEMA
        or type(raw.get("version")) is not int
        or raw["version"] != 2
        or not isinstance(raw.get("records"), list)
    ):
        raise ImportValidationError("export must use the exact version-2 knowledge-unit review schema")
    _validate_timestamp(raw.get("exportedAt"), "exportedAt", "review export")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw["records"]):
        label = f"review export record {index}"
        if not isinstance(item, dict) or set(item) != RECORD_FIELDS:
            raise ImportValidationError(f"{label} has missing or unknown fields")
        unit_id = item.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not UNIT_ID_RE.fullmatch(unit_id):
            raise ImportValidationError(f"{label} has an invalid knowledgeUnitId")
        if unit_id in seen_ids:
            raise ImportValidationError(f"duplicate knowledgeUnitId in export: {unit_id}")
        seen_ids.add(unit_id)

        decision = item.get("decision")
        if not isinstance(decision, str) or decision not in ALLOWED_DECISIONS:
            raise ImportValidationError(f"{label} {unit_id} has an invalid decision")
        reason, reviewer = item.get("reason"), item.get("reviewer")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            raise ImportValidationError(f"{label} {unit_id} needs a non-empty reason (max 4000 characters)")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 240:
            raise ImportValidationError(f"{label} {unit_id} needs an explicit reviewer (max 240 characters)")

        points = item.get("examPoints")
        card_ids = item.get("acceptedCardIds")
        if not isinstance(points, list) or any(
            not isinstance(point, str) or not point.strip() or len(point) > 2400 for point in points
        ):
            raise ImportValidationError(f"{label} {unit_id} has invalid examPoints")
        if not isinstance(card_ids, list) or any(
            not isinstance(card_id, str) or not UNIT_ID_RE.fullmatch(card_id) for card_id in card_ids
        ):
            raise ImportValidationError(f"{label} {unit_id} has invalid acceptedCardIds")
        normalized_points = [point.strip() for point in points]
        if len(set(normalized_points)) != len(normalized_points):
            raise ImportValidationError(f"{label} {unit_id} contains duplicate examPoints")
        if len(set(card_ids)) != len(card_ids):
            raise ImportValidationError(f"{label} {unit_id} contains duplicate acceptedCardIds")
        if decision == "accepted":
            if not normalized_points or not card_ids:
                raise ImportValidationError(
                    f"accepted review {unit_id} needs explicit examPoints and acceptedCardIds"
                )
        elif normalized_points or card_ids:
            raise ImportValidationError(
                f"non-accepted review {unit_id} must not claim examPoints or acceptedCardIds"
            )

        reviewed_at = _validate_timestamp(item.get("reviewedAt"), "reviewedAt", label)
        source_hash, text_hash = item.get("sourceHash"), item.get("textHash")
        if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
            raise ImportValidationError(f"{label} {unit_id} has an invalid sourceHash")
        if not isinstance(text_hash, str) or not SHA256_RE.fullmatch(text_hash):
            raise ImportValidationError(f"{label} {unit_id} has an invalid textHash")

        records.append({
            "knowledgeUnitId": unit_id,
            "decision": decision,
            "reason": reason,
            "reviewer": reviewer.strip(),
            "examPoints": normalized_points,
            "acceptedCardIds": list(card_ids),
            "reviewedAt": reviewed_at,
            "sourceHash": source_hash,
            "textHash": text_hash,
        })
    return records


def _load_current_data(ledger_path: Path, cards_path: Path, ledger_bytes: bytes) -> tuple[dict[str, Any], dict[str, dict], list[dict]]:
    ledger = _decode_json(ledger_bytes, ledger_path)
    cards_doc = _read_json(cards_path)
    if (
        not isinstance(ledger, dict)
        or type(ledger.get("version")) is not int
        or ledger.get("version") not in (1, 2)
        or not isinstance(ledger.get("units"), list)
    ):
        raise ImportValidationError("knowledge-units.json must contain version 1 or 2 and a units list")
    if not isinstance(cards_doc, dict) or not isinstance(cards_doc.get("cards"), list):
        raise ImportValidationError("cards.json must contain a cards list")

    units_by_id: dict[str, dict] = {}
    for index, unit in enumerate(ledger["units"]):
        if not isinstance(unit, dict):
            raise ImportValidationError(f"knowledge ledger unit {index} must be an object")
        unit_id = unit.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not UNIT_ID_RE.fullmatch(unit_id):
            raise ImportValidationError(f"knowledge ledger unit {index} has an invalid knowledgeUnitId")
        if unit_id in units_by_id:
            raise ImportValidationError(f"duplicate knowledgeUnitId in current ledger: {unit_id}")
        units_by_id[unit_id] = unit

    cards = cards_doc["cards"]
    if any(not isinstance(card, dict) for card in cards):
        raise ImportValidationError("every card entry must be an object")
    return ledger, units_by_id, cards


def _check_record_against_current(record: dict[str, Any], unit: dict, cards: list[dict]) -> None:
    unit_id = record["knowledgeUnitId"]
    if unit.get("presentInCurrentSource") is not True:
        raise ImportValidationError(f"knowledge unit {unit_id} is not confirmed in the current source")
    text = unit.get("text")
    if not isinstance(text, str):
        raise ImportValidationError(f"knowledge unit {unit_id} has no current source text")

    current_source_hash = audit_coverage._review_source_sha256(unit)
    current_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if unit.get("reviewSourceSha256") != current_source_hash:
        raise ImportValidationError(f"current ledger source fingerprint is inconsistent for {unit_id}")
    if unit.get("bodySha256") != current_text_hash:
        raise ImportValidationError(f"current ledger text fingerprint is inconsistent for {unit_id}")
    if record["sourceHash"] != current_source_hash or record["textHash"] != current_text_hash:
        raise ImportValidationError(f"stale sourceHash or textHash for knowledge unit {unit_id}")

    if record["decision"] != "accepted":
        return
    cards_by_id: dict[str, list[dict]] = {}
    for card in cards:
        card_id = card.get("id")
        if isinstance(card_id, str) and card_id in record["acceptedCardIds"]:
            cards_by_id.setdefault(card_id, []).append(card)
    for card_id in record["acceptedCardIds"]:
        matches = cards_by_id.get(card_id, [])
        if len(matches) != 1 or not audit_coverage._is_concrete_unit_card(unit, matches[0]):
            raise ImportValidationError(
                f"acceptedCardId {card_id} is missing, duplicated, non-concrete, or not bound to {unit_id}"
            )


def _incoming_ledger_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "reviewerDecision": record["decision"],
        "reviewerNote": record["reason"],
        "reviewer": record["reviewer"],
        "reviewedAt": record["reviewedAt"],
        "acceptedCardIds": list(record["acceptedCardIds"]),
        "examPointIds": list(record["examPoints"]),
        "reviewSourceSha256": record["sourceHash"],
        "bodySha256": record["textHash"],
    }


def _existing_decision_conflicts(unit: dict, incoming: dict[str, Any], unit_id: str) -> bool:
    old_decision = unit.get("reviewerDecision", "pending")
    if old_decision in (None, "", "pending", "stale"):
        return False
    if old_decision not in ALLOWED_DECISIONS:
        raise ImportValidationError(f"current ledger has an unknown decision for {unit_id}: {old_decision!r}")
    return any(
        field != "reviewSourceSha256" and unit.get(field) != incoming[field]
        for field in REVIEW_LEDGER_FIELDS
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def import_reviews(
    export_path: Path,
    ledger_path: Path,
    cards_path: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate and optionally atomically merge a signed human-review export.

    The reviewer name is an explicit human attestation from the browser export;
    this offline tool does not authenticate identities or generate approvals.
    """
    export_path, ledger_path, cards_path = map(Path, (export_path, ledger_path, cards_path))
    export_records = _validate_export(export_path)
    try:
        original_bytes = ledger_path.read_bytes()
    except OSError as exc:
        raise ImportValidationError(f"cannot read {ledger_path}: {exc}") from exc
    ledger, units_by_id, cards = _load_current_data(ledger_path, cards_path, original_bytes)

    planned = deepcopy(ledger)
    planned_units = {unit["knowledgeUnitId"]: unit for unit in planned["units"]}
    changed: list[str] = []
    unchanged: list[str] = []
    for record in export_records:
        unit_id = record["knowledgeUnitId"]
        unit = units_by_id.get(unit_id)
        if unit is None:
            raise ImportValidationError(f"export references unknown knowledgeUnitId: {unit_id}")
        _check_record_against_current(record, unit, cards)
        incoming = _incoming_ledger_record(record)
        if _existing_decision_conflicts(unit, incoming, unit_id):
            raise ImportValidationError(
                f"conflicting prior human decision for {unit_id}; refusing to overwrite it"
            )
        if all(unit.get(field) == value for field, value in incoming.items()):
            unchanged.append(unit_id)
            continue
        target = planned_units[unit_id]
        target.update(incoming)
        for field in STALE_FIELDS:
            target.pop(field, None)
        changed.append(unit_id)

    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "imported": len(changed),
        "unchanged": len(unchanged),
        "knowledgeUnitIds": changed + unchanged,
        "backup": None,
    }
    if not apply or not changed:
        return report

    serialized = (json.dumps(planned, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = ledger_path.with_name(
        f"{ledger_path.stem}.pre-review-import-{stamp}-{uuid.uuid4().hex[:8]}{ledger_path.suffix}"
    )
    try:
        if ledger_path.read_bytes() != original_bytes:
            raise ImportValidationError("knowledge ledger changed during import; refusing to overwrite concurrent edits")
    except OSError as exc:
        raise ImportValidationError(f"cannot recheck {ledger_path} before writing: {exc}") from exc
    _atomic_write(backup_path, original_bytes)
    _atomic_write(ledger_path, serialized)
    report["backup"] = str(backup_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely merge a browser version-2 human knowledge review export into the local ledger."
    )
    parser.add_argument("export", type=Path, help="browser-exported version-2 review JSON")
    parser.add_argument("--apply", action="store_true", help="write the merge and create a dated backup (default: dry-run)")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data" / "knowledge-units.json")
    parser.add_argument("--cards", type=Path, default=ROOT / "data" / "cards" / "cards.json")
    args = parser.parse_args(argv)
    try:
        result = import_reviews(args.export, args.ledger, args.cards, apply=args.apply)
    except (ImportValidationError, OSError) as exc:
        print(f"导入拒绝：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.apply:
        print("dry-run：未写入文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



