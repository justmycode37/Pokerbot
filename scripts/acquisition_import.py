"""Batch-validate attributed acquisition files without fitting or scoring a policy.

Inputs and source reviews stay separate. Passing protocol/replay checks produces
review candidates, never an automatic source-admission or accuracy claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
import tomllib
import warnings
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot import ivey
from pokerbot.corpus import validate_rows


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def read_document(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source_path(entry, directory):
    path = Path(entry["path"])
    return path if path.is_absolute() else directory / path


def _history_documents(entry, path):
    text = path.read_text(encoding="utf-8-sig")
    if entry["format"] == "phh":
        return [(path.stem, tomllib.loads(text, parse_float=Decimal), text)]
    if entry["format"] != "full_tilt":
        raise ValueError("unsupported acquisition format")
    # PokerKit's Full Tilt parser caps starting stacks for cap games and does
    # not parse antes. Those transformations cannot silently become NLHE facts.
    if re.search(r"\bCap\b|\bposts?\s+(?:the\s+)?ante\b", text, re.I):
        raise ValueError("cap/ante Full Tilt histories require a dedicated importer")
    from pokerkit import HandHistory
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        histories = list(HandHistory.from_full_tilt_poker(
            text.rstrip() + "\n\n\n",
            parse_value=lambda value: Decimal(value.replace(",", "")), error_status=True))
    if not histories:
        raise ValueError("no complete Full Tilt history parsed")
    result = []
    for index, history in enumerate(histories):
        encoded = history.dumps()
        document = tomllib.loads(encoded, parse_float=Decimal)
        result.append((str(document.get("hand", index + 1)), document, encoded))
    return result


def _canonical_hand(entry, document, fallback):
    if entry.get("canonical_hand_id"):
        return str(entry["canonical_hand_id"])
    hand = str(document.get("hand") or document.get("hand_id") or fallback)
    namespace = "fulltilt" if entry["format"] == "full_tilt" else entry["source_namespace"]
    return f"{namespace}:{hand}"


def import_manifest(manifest_path, output_path, *, baseline_path=None):
    manifest_path, output_path = Path(manifest_path), Path(output_path)
    if output_path.exists():
        raise FileExistsError("use a new import run; previous outputs are retained")
    manifest = read_document(manifest_path)
    baseline = read_document(baseline_path)["records"] if baseline_path else []
    baseline_ids = {row["decision_id"] for row in validate_rows(baseline)}
    accepted, rejected, source_reports, seen, conflicts = [], [], [], {}, set()
    duplicates = baseline_duplicates = 0

    def keep(row, entry, source_hash, validation):
        nonlocal duplicates, baseline_duplicates
        row = copy.deepcopy(row)
        row["source"] = entry["source_url"]
        row["source_capture_sha256"] = source_hash
        row["source_manifest_path"] = str(manifest_path)
        row["source_validation"] = validation
        row["admission_status"] = "pending_independent_source_review"
        row["evidence_tier"] = "acquired_history_pending_independent_source_review"
        if entry.get("session_id"):
            row["session_id"] = entry["session_id"]
        row["hero_cards_source_basis"] = entry.get("hero_cards_source_basis", "unspecified")
        clean = validate_rows([row])[0]
        key = clean["decision_id"]
        if key in baseline_ids:
            baseline_duplicates += 1
            return
        if key in seen:
            if clean["expected"] != seen[key]["expected"]:
                conflicts.add(key)
                rejected.append({"decision_id": key, "reason": "conflicting source labels"})
            else:
                duplicates += 1
            return
        seen[key] = clean
        accepted.append(clean)

    with tempfile.TemporaryDirectory(prefix="ivey-acquisition-replay-") as temporary:
        for entry in manifest["sources"]:
            report = {"source_url": entry.get("source_url"), "path": entry.get("path")}
            checkpoint = (len(accepted), dict(seen), set(conflicts), duplicates,
                          baseline_duplicates, len(rejected))
            try:
                if not str(entry.get("source_url", "")).startswith(("https://", "http://")):
                    raise ValueError("public source URL required")
                path = _source_path(entry, manifest_path.parent)
                raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                report["source_capture_sha256"] = raw_hash
                if entry["format"] == "decision_rows":
                    document = read_document(path)
                    rows = document if isinstance(document, list) else document["records"]
                    for row in rows:
                        if not row.get("canonical_hand_id"):
                            raise ValueError("decision rows require a canonical hand ID")
                        keep(row, entry, raw_hash, "protocol_only_not_engine_replayed")
                    report["input_decisions"] = len(rows)
                else:
                    documents = _history_documents(entry, path)
                    report["parsed_hands"] = len(documents)
                    for number, (name, document, encoded) in enumerate(documents):
                        # Alias normalization is explicit and preserves its source.
                        alias = entry.get("hero_alias", "Phil Ivey")
                        if alias != "Phil Ivey":
                            raise ValueError("alias histories need source-reviewed PHH normalization first")
                        canonical = _canonical_hand(entry, document, name)
                        replay_path = Path(temporary) / f"{number}.phh"
                        replay_path.write_text(encoded, encoding="utf-8")
                        rows = ivey.load_decisions(replay_path)
                        replay_report = copy.deepcopy(ivey.LAST_LOAD_REPORT)
                        if replay_report["files_excluded"]:
                            rejected.append({"hand_id": canonical, "source_url": entry["source_url"],
                                             "reason": "history rejected by strict replay", "replay": replay_report})
                            continue
                        for row in rows:
                            row["hand_id"] = row["canonical_hand_id"] = canonical
                            keep(row, entry, raw_hash, "engine_replayed")
                        report.setdefault("replays", []).append({"hand_id": canonical, **replay_report})
                report["status"] = "processed_pending_source_review"
            except (OSError, ValueError, TypeError, KeyError, IndexError, Warning) as exc:
                # A malformed later row cannot leave an earlier row from the
                # same rejected source silently included in the candidate set.
                accepted_length, seen_before, conflicts_before, duplicates, baseline_duplicates, rejected_length = checkpoint
                del accepted[accepted_length:]
                seen.clear()
                seen.update(seen_before)
                conflicts.clear()
                conflicts.update(conflicts_before)
                del rejected[rejected_length:]
                report["status"] = "rejected"
                report["reason"] = str(exc)
                rejected.append(copy.deepcopy(report))
            source_reports.append(report)

    records = [row for row in accepted if row["decision_id"] not in conflicts]
    # A final whole-batch pass catches duplicate identities and invalid labels.
    records = validate_rows(records)
    result = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "validated_candidates_pending_independent_source_review",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "counts": {"validated_candidate_decisions": len(records),
                   "engine_replayed_decisions": sum(r["source_validation"] == "engine_replayed" for r in records),
                   "protocol_only_decisions": sum(r["source_validation"] != "engine_replayed" for r in records),
                   "unique_hands": len({r["canonical_hand_id"] for r in records}),
                   "duplicate_decisions_removed": duplicates,
                   "baseline_duplicates_removed": baseline_duplicates,
                   "conflicting_decision_identities_excluded": len(conflicts),
                   "newly_admitted_decisions": 0},
        "records": records, "source_reports": source_reports, "rejections": rejected,
        "limitations": ["Replay/protocol validity does not establish source transcription accuracy.",
                        "All new rows await independent source review; no policy is fitted or scored.",
                        "Cross-source aliases must be reconciled before an evaluation split is frozen."]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    result = import_manifest(args.manifest, args.output, baseline_path=args.baseline)
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
