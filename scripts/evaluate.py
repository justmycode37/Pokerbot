"""Freeze policy evidence for one local revision, including Ivey reviews."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerbot.__main__ import policy, profile_policy
from pokerbot.benchmarks import load_ivey_corpus, load_video_reviews
from pokerbot.ivey import compare_decisions
from pokerbot.review import review_packet, write_packet


def fingerprints():
    paths = [*ROOT.glob("pokerbot/*.py"), *ROOT.glob("scripts/*.py"),
             ROOT / "pyproject.toml", ROOT / "data/ivey/LICENSE"]
    paths.extend((ROOT / "data").rglob("*.json"))
    paths.extend((ROOT / "data").rglob("*.phh"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def save(directory, name, result):
    (directory / (name + ".json")).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


def evaluate(label, *, hands=800, samples=5000, seed=20261031, skip_matches=False):
    before = fingerprints()
    directory = ROOT / "reports" / label
    directory.mkdir(parents=True, exist_ok=True)
    primary, _ = load_ivey_corpus()
    extended, _ = load_ivey_corpus(include_reconstructed=True)
    for name in ("fast", "mc-range", "mc-uniform"):
        decide = policy(name, samples)
        save(directory, name + "-ivey", {
            "primary": compare_decisions(primary, decide),
            "reconstructed_only": compare_decisions([r for r in extended if r["format"] == "tournament_nlhe"], decide),
            "goal_gt99_all_ivey_decisions_proven": False,
            "policy": name, "reference_samples": samples if name != "fast" else None})
    decide = policy("fast")
    save(directory, "fast-profile", profile_policy(decide, count=10000))
    write_packet(review_packet(extended + load_video_reviews(), decide, policy_name="fast"),
                 directory / "qualitative-ivey.md")
    if not skip_matches:
        from pokerbot.simulation import benchmark
        for opponent in ("calling-station", "tight-passive", "random-legal"):
            result = benchmark(decide, [policy(opponent)] * 7, hands=hands, seed=seed)
            result.update(policy="fast", opponent=opponent,
                          benchmark_kind="local_cash_reset_not_official_tournament", seed=seed)
            save(directory, "fast-vs-" + opponent, result)
    after = fingerprints()
    if before != after:
        raise RuntimeError("Source changed during evaluation; rerun after edits finish.")
    manifest = {"revision_label": label, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "python": sys.version, "platform": platform.platform(),
                "pokerkit_version": importlib.metadata.version("pokerkit"),
                "source_fingerprints": before, "match_seed": seed,
                "hands_per_opponent": hands if not skip_matches else None,
                "matches_skipped": skip_matches, "reference_samples": samples,
                "limits": ["Unknown official event variant, interface and payouts",
                           "Selected Ivey examples cannot establish a population imitation rate",
                           "Local cash-reset matches do not evaluate tournament utility",
                           "Local warm-call timings do not certify the event sandbox"]}
    save(directory, "manifest", manifest)
    archive_sources(directory, before)
    return directory


def archive_sources(directory, recorded):
    """Retain the exact files, not just hashes of files later overwritten."""
    temporary = directory / ".source.tmp.zip"
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, expected in recorded.items():
                filename = ROOT / relative
                if hashlib.sha256(filename.read_bytes()).hexdigest() != expected:
                    raise RuntimeError(f"Source changed before archival: {relative}")
                archive.write(filename, relative)
            if "data/ivey/LICENSE" not in recorded:
                archive.write(ROOT / "data/ivey/LICENSE", "data/ivey/LICENSE")
            archive.write(directory / "manifest.json", "evaluation-manifest.json")
        temporary.replace(directory / "source.zip")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="New report directory name, e.g. revision-3")
    parser.add_argument("--hands", type=int, default=800)
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--skip-matches", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.label) or args.hands < 8 or args.samples < 1:
        parser.error("label must be a safe directory name, hands >= 8 and samples >= 1")
    if (ROOT / "reports" / args.label / "manifest.json").exists():
        parser.error("that revision already has a manifest; use a new label to preserve it")
    print(evaluate(args.label, hands=args.hands, samples=args.samples, seed=args.seed,
                   skip_matches=args.skip_matches))
