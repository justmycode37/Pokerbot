"""Freeze named policy artifacts, or compare them with a new admitted batch."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot.candidate_evaluation import REGISTRY, compare_new_batch, freeze_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--inspected-manifest", required=True)
    freeze.add_argument("--candidates", nargs="+", choices=tuple(REGISTRY), default=list(REGISTRY))
    freeze.add_argument("--output", required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("records")
    compare.add_argument("--lock", required=True)
    compare.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error("output exists; preserve the earlier artifact and use a new version")
    if args.command == "freeze":
        result = freeze_candidates(args.inspected_manifest, args.candidates)
    else:
        source = json.loads(Path(args.records).read_text())
        if isinstance(source, dict):
            if source.get("admission_status", "").startswith("pending"):
                parser.error("batch admission is pending")
            rows = source["records"]
        else:
            rows = source
        result = compare_new_batch(rows, json.loads(Path(args.lock).read_text()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as fp:
        json.dump(result, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write("\n")
    print(json.dumps({k: result[k] for k in ("candidate_ids", "decision_count", "hand_count", "source_group_count") if k in result}))


if __name__ == "__main__":
    main()
