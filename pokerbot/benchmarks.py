"""Load attributed comparison examples and expose their evidence limits."""

import json
from pathlib import Path

from . import ivey
from .state import Observation


def load_ivey_corpus(path=None, *, include_reconstructed=False, include_verified_video=False,
                     include_public_reports=False):
    """Default to the verified PHH; optionally include reported reconstruction.

    Reconstructed examples have disclosed assumptions and are never silently
    merged into the primary benchmark. Unknown formats remain separate.
    """
    decisions = ivey.load_decisions(path)
    report = dict(ivey.LAST_LOAD_REPORT)
    for row in decisions:
        row["format"] = "cash_nlhe"
        row["evidence_tier"] = "machine_readable_source"
    if include_reconstructed:
        directory = Path(__file__).resolve().parents[1] / "data/ivey_normalized"
        count = 0
        for filename in sorted(directory.glob("*.json")):
            record = json.loads(filename.read_text())
            if record["hero"] != "Phil Ivey" or not record.get("source"):
                raise ValueError("comparison examples need hero attribution and source")
            for row in record["decisions"]:
                Observation.from_dict(row["state"])
                row["evidence_tier"] = "reported_hand_with_disclosed_assumptions"
                row["derivation_notes"] = record["derivation_notes"]
                decisions.append(row)
                count += 1
        report["additional_reconstructed_decisions"] = count
    if include_verified_video:
        video_rows = ivey.load_decisions(Path(__file__).resolve().parents[1] / "data/ivey_video_verified")
        for row in video_rows:
            row["format"] = "tournament_nlhe"
            row["evidence_tier"] = "video_reconstructed_exact_header_and_pot_arithmetic"
            row["source"] = "https://www.youtube.com/watch?v=YfjDfPk7e1E"
            row["derivation_notes"] = [
                "Exact starting stacks, blinds and BB ante read from the opening video header.",
                "Unshown preflop folds derived from seat order and displayed pot; all later pots reconcile.",
                "Payouts, live reads and earlier table history are unknown.",
            ]
            decisions.append(row)
        report["additional_verified_video_decisions"] = len(video_rows)
    if include_public_reports:
        from .public_reports import load_public_report_decisions
        report_rows = load_public_report_decisions()
        decisions.extend(report_rows)
        report["additional_public_report_decisions"] = len(report_rows)
    return decisions, report


def load_video_reviews():
    """Qualitative snapshots only; rounded/incomplete footage is not scored."""
    root = Path(__file__).resolve().parents[1] / "data/video_reviews"
    rows = []
    for label_file in sorted(root.glob("*/recorded-action.json")):
        label = json.loads(label_file.read_text())
        state = json.loads(label_file.with_name("decision-state.json").read_text())
        metadata = json.loads(label_file.with_name("metadata.json").read_text())
        Observation.from_dict(state)
        if label["action"] not in state["legal_actions"]:
            raise ValueError("video action is inconsistent with reconstructed legal actions")
        rows.append({"state": state, "expected": {"action": label["action"]},
            "source": metadata["watch_url"] + f"&t={label['frozen_decision_offset_seconds']}s",
            "hand_id": "video-" + metadata["video_id"], "format": "tournament_nlhe",
            "evidence_tier": "video_snapshot_with_rounded_or_missing_context",
            "derivation_notes": label["limitations"]})
    return rows
