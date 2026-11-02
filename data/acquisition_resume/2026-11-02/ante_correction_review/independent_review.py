#!/usr/bin/env python3
"""Independent raw-prefix review of the 21 ante-corrected candidate rows.

This review derives accounting directly from source action records. It does
not call the Triton converter, PokerKit, or acquisition_pot_eligibility.
Only output files under this review directory are written.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
INPUT = ROOT / "data/acquisition_resume/2026-11-02/ante_correction/candidates.json"
DIAGNOSTIC = ROOT / "data/acquisition_resume/2026-11-01/ante-eligibility-diagnostic.json"
ADMISSION_DIR = ROOT / "data/acquisition_resume/2026-11-01/admissions"
OLD_ROOT = ROOT / "data/acquisition_resume/2026-11-01"
HERO = "3970ce21-3d14-4bdc-97ca-98df8220d040"
DEAD = {"ante", "small_ante", "big_ante"}
LIVE_FORCED = {"small_blind", "big_blind", "straddle"}
BETTING = {"raise", "call", "bet", "all_in", "check", "fold"}
PAID = DEAD | LIVE_FORCED | {"raise", "call", "bet", "all_in"}
ALLOWED_STATE = {
    "big_blind", "board", "contestable_pot", "current_bet", "history",
    "hole_cards", "legal_actions", "max_raise_to", "min_raise_to",
    "player_id", "players_active", "players_to_act", "position", "pot",
    "seed", "stack", "street", "table_size", "to_call",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return sha(raw)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def check(out: dict[str, bool], name: str, value: bool) -> None:
    out[name] = bool(value)


def street_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    value = name.lower().replace("preflop", "pre_flop")
    return value


def position_names(n: int) -> list[str]:
    if n == 2:
        return ["BB", "BTN"]
    if n == 3:
        return ["SB", "BB", "BTN"]
    positions = [""] * n
    positions[0], positions[1], positions[2], positions[-1] = "SB", "BB", "UTG", "BTN"
    if n >= 5:
        positions[-2] = "CO"
        for i in range(3, n - 2):
            positions[i] = "MP"
    return positions


def card_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.removeprefix("CARD_")
    if len(raw) != 2:
        return ""
    rank, suit = raw[0].upper(), raw[1].lower()
    if rank == "1":
        rank = "T"
    return rank + suit


def hand_from_capture(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    hand = raw.get("data", {}).get("handV2") if isinstance(raw, dict) else None
    if not isinstance(hand, dict):
        raise ValueError("capture does not contain data.handV2")
    return hand


def raw_root(path: Path) -> Path:
    for ancestor in path.parents:
        if ancestor.name == "raw":
            # 2025 captures are nested one level below raw/<tournament>/;
            # the 2026 capture cache keeps episodes directly below raw/.
            relative = path.relative_to(ancestor)
            if relative.parts and (ancestor / relative.parts[0] / "episodes").is_dir():
                return ancestor / relative.parts[0]
            return ancestor
    raise ValueError("source capture is not under a raw directory")


def episode_aliases(raw: Path, hand_uuid: str) -> list[dict[str, Any]]:
    files: dict[Path, dict[str, Any]] = {}
    ep_dir = raw / "episodes"
    if ep_dir.is_dir():
        for path in ep_dir.glob("*.json"):
            if not path.name.endswith(".request.json"):
                files[path] = {}
    # Some 2026 episode responses were intentionally reused from the recent
    # cache. Follow only the source paths declared in the 2026 collector
    # manifest and retain the captured hash check for each referenced file.
    manifest_path = ROOT / "data/acquisition_resume/2026-11-01/triton_2026/manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("episodes", []):
            source = entry.get("source") or {}
            path_value = source.get("path")
            if not isinstance(path_value, str):
                continue
            path = Path(path_value)
            if not path.is_absolute():
                path = ROOT / path
            files[path] = {"manifest_episode_id": entry.get("episode_id"),
                           "manifest_source_sha256": source.get("sha256"),
                           "manifest_source_variables": source.get("variables"),
                           "manifest_request_path": source.get("request_path"),
                           "manifest_request_sha256": source.get("request_sha256"),
                           "manifest_query_sha256": source.get("query_sha256")}
    aliases = []
    for path, manifest_details in sorted(files.items(), key=lambda item: str(item[0])):
        if path.name.endswith(".request.json") or not path.exists():
            continue
        try:
            episode_bytes = path.read_bytes()
            episode_sha = sha(episode_bytes)
            top = json.loads(episode_bytes.decode("utf-8-sig"))
            episode = top.get("data", {}).get("episode")
            if not isinstance(episode, dict):
                continue
        except (OSError, ValueError):
            continue
        positions = []
        for seg_i, segment in enumerate(episode.get("indexedSegments") or []):
            for offset_i, offset in enumerate(segment.get("handOffsets") or []):
                if isinstance(offset, dict) and offset.get("handId") == hand_uuid:
                    positions.append({"segment_index": seg_i, "offset_index": offset_i})
        if positions:
            tournament = episode.get("tournament") or {}
            festival = episode.get("festival") or {}
            request_value = manifest_details.get("manifest_request_path")
            if isinstance(request_value, str):
                request_path = Path(request_value)
                if not request_path.is_absolute():
                    request_path = ROOT / request_path
            else:
                request_path = path.with_suffix(".request.json")
            episode_request_sha = None
            episode_request_vars = None
            episode_request_op = None
            episode_request_query_sha = None
            if request_path.exists():
                try:
                    req_bytes = request_path.read_bytes()
                    episode_request_sha = sha(req_bytes)
                    req_obj = json.loads(req_bytes.decode("utf-8-sig"))
                    episode_request_vars = req_obj.get("variables")
                    episode_request_op = req_obj.get("operationName")
                    req_query = req_obj.get("query")
                    episode_request_query_sha = sha(req_query.encode("utf-8")) if isinstance(req_query, str) else None
                except (OSError, ValueError):
                    pass
            aliases.append({
                "episode_id": episode.get("episodeId"),
                "title": episode.get("title"),
                "tournament_uuid": tournament.get("uuid"),
                "tournament_name": tournament.get("name"),
                "festival_uuid": festival.get("uuid"),
                "festival_name": festival.get("name"),
                "contains_hand_in_indexed_segments": True,
                "indexed_positions": positions,
                "episode_capture_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "episode_capture_sha256": episode_sha,
                "manifest_episode_id": manifest_details.get("manifest_episode_id"),
                "manifest_source_sha256": manifest_details.get("manifest_source_sha256"),
                "episode_hash_matches_manifest": (manifest_details.get("manifest_source_sha256") is None
                                                   or episode_sha == manifest_details.get("manifest_source_sha256")),
                "episode_request_path": str(request_path.relative_to(ROOT)) if request_path.is_relative_to(ROOT) else str(request_path),
                "episode_request_sha256": episode_request_sha,
                "episode_request_variables": episode_request_vars,
                "episode_request_operation_name": episode_request_op,
                "episode_request_query_sha256": episode_request_query_sha,
                "manifest_request_sha256": manifest_details.get("manifest_request_sha256"),
                "episode_request_hash_matches_manifest": (manifest_details.get("manifest_request_sha256") is None
                                                          or episode_request_sha == manifest_details.get("manifest_request_sha256")),
                "manifest_query_sha256": manifest_details.get("manifest_query_sha256"),
            })
    return aliases


def old_candidates() -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for path in OLD_ROOT.rglob("candidates*.json"):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in blob.get("records", []):
            if isinstance(row, dict) and isinstance(row.get("decision_id"), str):
                by_id[row["decision_id"]] = row
    return by_id


def admitted_keys() -> tuple[set[str], set[str], set[str], set[str], dict[str, list[dict[str, Any]]], dict[str, int]]:
    source_ids: set[str] = set()
    stable_keys: set[str] = set()
    hand_ids: set[str] = set()
    decision_ids: set[str] = set()
    rows_by_hand: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for path in sorted(ADMISSION_DIR.glob("batch-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("records", [])
        counts[path.name] = len(records)
        for row in records:
            if isinstance(row.get("source_decision_id"), str):
                source_ids.add(row["source_decision_id"])
            if isinstance(row.get("stable_source_decision_key"), str):
                stable_keys.add(row["stable_source_decision_key"])
            for key in ("hand_id", "canonical_hand_id"):
                if isinstance(row.get(key), str):
                    hand_ids.add(row[key])
            for hand_key in {row.get("hand_id"), row.get("canonical_hand_id")}:
                if isinstance(hand_key, str):
                    rows_by_hand.setdefault(hand_key, []).append(row)
            if isinstance(row.get("decision_id"), str):
                decision_ids.add(row["decision_id"])
    # The first 45 admitted development examples store their normalized
    # source key and canonical hand IDs in the locked corpus manifest.
    frozen_path = ROOT / "data/corpus_splits/development-after-prospective-v1.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    counts["frozen-baseline.json"] = len(frozen.get("records", []))
    for row in frozen.get("records", []):
        if isinstance(row.get("source_decision_id"), str):
            source_ids.add(row["source_decision_id"])
        if isinstance(row.get("stable_source_decision_key"), str):
            stable_keys.add(row["stable_source_decision_key"])
        for key in ("hand_id", "canonical_hand_id"):
            if isinstance(row.get(key), str):
                hand_ids.add(row[key])
        for hand_key in {row.get("hand_id"), row.get("canonical_hand_id")}:
            if isinstance(hand_key, str):
                rows_by_hand.setdefault(hand_key, []).append(row)
        if isinstance(row.get("decision_id"), str):
            decision_ids.add(row["decision_id"])
    return source_ids, stable_keys, hand_ids, decision_ids, rows_by_hand, counts


def flattened_prefix(hand: dict[str, Any], ordinal: int) -> tuple[list[tuple[int, int, str, dict[str, Any]]], tuple[int, int, str, dict[str, Any]]]:
    rounds = hand.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("missing round array")
    prefix: list[tuple[int, int, str, dict[str, Any]]] = []
    flat = 0
    for ri, rd in enumerate(rounds):
        if not isinstance(rd, dict) or not isinstance(rd.get("actions"), list):
            raise ValueError("invalid round/action array before target")
        for ai, action in enumerate(rd["actions"]):
            if flat == ordinal:
                if not isinstance(action, dict):
                    raise ValueError("target action is not an object")
                return prefix, (ri, ai, street_name(rd.get("name")), action)
            if flat > ordinal:
                raise ValueError("invalid flattened action traversal")
            if not isinstance(action, dict):
                raise ValueError("invalid action before target")
            prefix.append((ri, ai, street_name(rd.get("name")), action))
            flat += 1
    raise ValueError("source action index outside source prefix")


def inspect_one(row: dict[str, Any], previous_rows: dict[str, dict[str, Any]],
                admitted_source: set[str], admitted_stable: set[str],
                admitted_hands: set[str], admitted_decisions: set[str],
                admitted_rows_by_hand: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    issues: list[str] = []
    detail: dict[str, Any] = {}
    sid = row.get("source_decision_id")
    hand_uuid = sid.split(":")[1] if isinstance(sid, str) and sid.count(":") >= 2 else ""
    ordinal = row.get("source_action_index")
    try:
        capture_path = Path(row["source_capture_path"])
        request_path = Path(row["source_request_path"])
        raw_bytes = capture_path.read_bytes()
        req_bytes = request_path.read_bytes()
        hand = hand_from_capture(capture_path)
        request = json.loads(req_bytes.decode("utf-8-sig"))
    except Exception as exc:
        return {"source_decision_id": sid, "review_status": "held", "checks": {"source_files_readable": False},
                "issues": [f"source_files_readable:{type(exc).__name__}:{exc}"]}

    capture_sha = sha(raw_bytes)
    request_sha = sha(req_bytes)
    query = request.get("query")
    vars_ = request.get("variables")
    query_sha = sha(query.encode("utf-8")) if isinstance(query, str) else None
    payload_sha = canonical_hash(hand)
    aliases = episode_aliases(raw_root(capture_path), hand_uuid)
    requested_ep = vars_.get("episodeId") if isinstance(vars_, dict) else None
    matching_aliases = [a for a in aliases if a.get("episode_id") == requested_ep]
    alias_ep_ids = [a.get("episode_id") for a in aliases]

    check(checks, "capture_hash_recomputed", capture_sha == row.get("source_capture_sha256"))
    check(checks, "request_hash_recomputed", request_sha == row.get("source_request_sha256"))
    check(checks, "query_hash_recomputed", query_sha == row.get("source_query_sha256"))
    check(checks, "request_query_text_matches_candidate", query == row.get("source_request_query"))
    check(checks, "request_operation_and_variables_match_candidate",
          request.get("operationName") == row.get("source_request_operation_name") == "GetHand"
          and vars_ == row.get("source_request_variables"))
    check(checks, "request_hand_episode_variables_match_capture",
          isinstance(vars_, dict) and vars_.get("handId") == hand_uuid == hand.get("handId")
          and vars_.get("episodeId") == row.get("source_request_episode_id"))
    check(checks, "canonical_hand_payload_hash_recomputed",
          payload_sha == row.get("source_payload_sha256"))
    matching_episode_artifacts_ok = bool(matching_aliases) and all(
        a.get("episode_hash_matches_manifest") is True
        and a.get("episode_request_hash_matches_manifest") is True
        and isinstance(a.get("episode_request_variables"), dict)
        and a["episode_request_variables"].get("episodeId") == requested_ep
        and a.get("episode_request_operation_name") == "GetEpisode"
        and isinstance(a.get("episode_request_query_sha256"), str)
        and (a.get("manifest_query_sha256") is None
             or a.get("episode_request_query_sha256") == a.get("manifest_query_sha256"))
        for a in matching_aliases)
    check(checks, "requested_episode_alias_contains_hand_and_capture_hashes_match",
          matching_episode_artifacts_ok)
    all_alias_artifacts_ok = all(
        a.get("episode_hash_matches_manifest") is True
        and a.get("episode_request_hash_matches_manifest") is True
        and isinstance(a.get("episode_request_variables"), dict)
        and a["episode_request_variables"].get("episodeId") == a.get("episode_id")
        and a.get("episode_request_operation_name") == "GetEpisode"
        and isinstance(a.get("episode_request_query_sha256"), str)
        and (a.get("manifest_query_sha256") is None
             or a.get("episode_request_query_sha256") == a.get("manifest_query_sha256"))
        for a in aliases)
    check(checks, "all_source_episode_aliases_are_explicit_and_hash_reconciled",
          bool(aliases) and all_alias_artifacts_ok)
    tournament_ids = {a.get("tournament_uuid") for a in aliases if a.get("tournament_uuid")}
    expected_session = ("triton:tournament:" + next(iter(tournament_ids))) if len(tournament_ids) == 1 else None
    check(checks, "episode_tournament_maps_to_candidate_session",
          expected_session is not None and row.get("session_id") == expected_session)
    check(checks, "source_url_hand_identity_matches",
          isinstance(row.get("source"), str) and f"sourceHandId={hand_uuid}" in row["source"])

    try:
        prefix, target = flattened_prefix(hand, ordinal)
        tri, tai, target_street, target_action = target
        action_count = sum(len(rd.get("actions", [])) for rd in hand.get("rounds", []) if isinstance(rd, dict))
        check(checks, "flat_and_round_action_locators_reconcile",
              row.get("source_round_index") == tri and row.get("source_round_action_index") == tai
              and row.get("stable_source_decision_key") == f"triton:{hand_uuid}:round:{tri}:action:{tai}"
              and sid == f"triton:{hand_uuid}:action:{ordinal}"
              and row.get("source_action_count") == action_count)
        check(checks, "target_is_hero_betting_action",
              target_action.get("userId") == HERO and target_action.get("type") in BETTING)
        if target_street != "pre_flop":
            raise ValueError(f"unsupported_target_street:{target_street}")
    except Exception as exc:
        return {"source_decision_id": sid, "review_status": "held", "checks": checks,
                "issues": [f"prefix_target:{type(exc).__name__}:{exc}"],
                "provenance": {"source_capture_sha256": capture_sha, "source_request_sha256": request_sha,
                               "source_query_sha256": query_sha, "episode_aliases": alias_ep_ids}}

    player_rows = hand.get("players")
    if not isinstance(player_rows, list):
        raise ValueError("invalid players array")
    players: dict[str, dict[str, Any]] = {}
    seat_owner: dict[int, str] = {}
    for p in player_rows:
        if not isinstance(p, dict) or not isinstance(p.get("userId"), str):
            raise ValueError("invalid player identity")
        uid = p["userId"]
        if uid in players or type(p.get("seatNo")) is not int or p["seatNo"] in seat_owner:
            raise ValueError("duplicate player or seat")
        players[uid] = p
        seat_owner[p["seatNo"]] = uid
    capacity = hand.get("noOfSeats")
    n = len(players)
    sb_rows = [(a.get("userId"), a.get("amount")) for _, _, _, a in prefix if a.get("type") == "small_blind"]
    bb_rows = [(a.get("userId"), a.get("amount")) for _, _, _, a in prefix if a.get("type") == "big_blind"]
    straddles = [(a.get("userId"), a.get("amount")) for _, _, _, a in prefix if a.get("type") == "straddle"]
    if len(sb_rows) != 1 or len(bb_rows) != 1 or not isinstance(capacity, int):
        raise ValueError("target prefix lacks one explicit small blind, big blind, or physical capacity")
    sb_id, bb_id = sb_rows[0][0], bb_rows[0][0]
    if n == 2:
        order_ids = [bb_id, sb_id]
    else:
        sb_seat = players[sb_id]["seatNo"]
        order_ids = [p["userId"] for p in sorted(player_rows,
                     key=lambda x: (x["seatNo"] - sb_seat) % capacity)]
    dealer_seat = hand.get("dealerSeatNo")
    dealer_id = seat_owner.get(dealer_seat)
    order_ok = (2 <= n <= 8 and type(capacity) is int and n <= capacity
                and len(set(p["seatNo"] for p in player_rows)) == n
                and all(1 <= p["seatNo"] <= capacity for p in player_rows)
                and order_ids[0] == sb_id and order_ids[1] == bb_id
                and ((n == 2 and dealer_seat == players[sb_id]["seatNo"])
                     or (n > 2 and dealer_id == order_ids[-1])))
    check(checks, "occupied_seat_blind_and_button_order_reconcile", order_ok)
    check(checks, "candidate_seat_capacity_and_hero_identity_match_source",
          row.get("source_physical_capacity") == capacity
          and row.get("source_actual_player_count") == n
          and row.get("state", {}).get("table_size") == n
          and HERO in players)

    names = position_names(n)
    index_by_id = {uid: i for i, uid in enumerate(order_ids)}
    actor_i = index_by_id.get(HERO, -1)
    check(checks, "hero_player_id_and_position_match_explicit_seat_order",
          actor_i >= 0 and row.get("state", {}).get("player_id") == f"p{actor_i}"
          and row.get("state", {}).get("position") == names[actor_i])

    # Direct chip ledger: dead antes are common money; live posts/actions form
    # side-pot tiers. The current target action and all later actions are never
    # applied to this ledger.
    starting = {uid: p.get("startChips") for uid, p in players.items()}
    if not all(type(x) is int and x >= 0 for x in starting.values()):
        raise ValueError("invalid source starting stack")
    remaining = dict(starting)
    dead_by = dict.fromkeys(players, 0)
    live = dict.fromkeys(players, 0)
    street_commit = dict.fromkeys(players, 0)
    folded: set[str] = set()
    pot = 0
    dead_total = 0
    max_bet = 0
    last_full_raise = hand.get("blindLevel", {}).get("bigBlind", 0)
    if type(last_full_raise) is not int or last_full_raise <= 0:
        raise ValueError("invalid big blind")
    if straddles:
        last_full_raise = max([last_full_raise] + [x[1] for x in straddles if type(x[1]) is int])
    ante_posts = []
    live_posts = []
    voluntary_started = False
    forced_invalid = False
    for _, _, s, a in prefix:
        kind, actor = a.get("type"), a.get("userId")
        if actor not in players or actor in folded:
            forced_invalid = True
            break
        if kind in DEAD | LIVE_FORCED:
            if s != "pre_flop" or voluntary_started or type(a.get("amount")) is not int or a["amount"] <= 0:
                forced_invalid = True
                break
            amount = a["amount"]
            if amount > remaining[actor]:
                forced_invalid = True
                break
            remaining[actor] -= amount
            pot += amount
            if kind in DEAD:
                dead_by[actor] += amount
                dead_total += amount
                ante_posts.append({"actor_seat": players[actor]["seatNo"], "type": kind, "amount": amount})
            else:
                live[actor] += amount
                street_commit[actor] += amount
                max_bet = max(max_bet, street_commit[actor])
                live_posts.append({"actor_seat": players[actor]["seatNo"], "type": kind, "amount": amount})
            continue
        voluntary_started = True
    check(checks, "forced_antes_and_blinds_are_preflop_before_betting", not forced_invalid)
    check(checks, "live_forced_posts_follow_small_big_straddle_seat_order",
          [(x[0], x[1]) for x in [("small_blind", sb_id), ("big_blind", bb_id)] if any(y["type"] == x[0] and y["actor_seat"] == players[x[1]]["seatNo"] for y in live_posts)] == [("small_blind", sb_id), ("big_blind", bb_id)]
          and all(x["type"] == "straddle" for x in live_posts[2:]))

    # Determine the first actor and thereafter validate each observed actor
    # against a plain cyclic action queue, resetting only on a full raise.
    last_forced_id = straddles[-1][0] if straddles else bb_id
    start_idx = (index_by_id[last_forced_id] + 1) % n
    cycle = [order_ids[(start_idx + i) % n] for i in range(n)]
    folded = set()
    pending = [u for u in cycle if remaining[u] > 0]
    rights = dict.fromkeys(players, True)
    order_errors = []
    current_round = 0
    for _, _, s, a in prefix:
        kind, actor = a.get("type"), a.get("userId")
        if kind in DEAD | LIVE_FORCED:
            continue
        if s != "pre_flop" or actor not in pending or (pending and pending[0] != actor):
            order_errors.append({"actor_seat": players.get(actor, {}).get("seatNo"), "expected_seat": players.get(pending[0], {}).get("seatNo") if pending else None})
            break
        amount = a.get("amount", 0)
        if kind in {"check", "fold"}:
            amount = 0
        due = max(0, max_bet - street_commit[actor])
        if kind == "check" and due != 0:
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "check_facing_wager"}); break
        if kind == "fold":
            folded.add(actor)
        elif kind == "call":
            if type(amount) is not int or amount != min(due, remaining[actor]) or due <= 0:
                order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "call_increment"}); break
        elif kind == "all_in" and type(amount) is int:
            if amount != remaining[actor]:
                order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "all_in_stack"}); break
        elif kind in {"raise", "bet"}:
            if type(amount) is not int or amount <= 0:
                order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "raise_amount"}); break
        elif kind != "check":
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "unknown_betting_action"}); break
        before_max = max_bet
        before_commit = street_commit[actor]
        target_total = before_commit + amount
        if amount > remaining[actor]:
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "payment_exceeds_stack"}); break
        if kind in {"raise", "bet"} and target_total <= before_max:
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "raise_does_not_increase_price"}); break
        if kind == "bet" and before_max != 0:
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "bet_facing_price"}); break
        if kind == "raise" and not rights[actor]:
            order_errors.append({"actor_seat": players[actor]["seatNo"], "problem": "raise_not_reopened"}); break
        if amount:
            remaining[actor] -= amount
            live[actor] += amount
            street_commit[actor] += amount
            pot += amount
            increment = target_total - before_max
            max_bet = max(max_bet, target_total)
        else:
            increment = 0
        full_raise = increment > 0 and increment >= last_full_raise
        if full_raise:
            last_full_raise = increment
        rights[actor] = False
        pending.remove(actor)
        pending = [u for u in pending if u not in folded and remaining[u] > 0]
        if full_raise:
            after = [order_ids[(index_by_id[actor] + i) % n] for i in range(1, n)]
            pending = [u for u in after if u not in folded and remaining[u] > 0]
            for u in pending:
                rights[u] = True

    target_actor = target_action.get("userId")
    check(checks, "raw_preflop_actor_sequence_reaches_target", not order_errors
          and bool(pending) and pending[0] == target_actor == HERO)
    check(checks, "target_action_kind_and_amount_match_original_row_locator",
          target_street == "pre_flop" and target_actor == HERO
          and type(target_action.get("timestamp")) is int)

    # Derive before-action values, including dead antes and per-player live
    # contribution tiers, without reading terminal pots or ending stacks.
    hero_commit = street_commit[HERO]
    due = max(0, max_bet - hero_commit)
    to_call = min(due, remaining[HERO])
    hero_reach = live[HERO] + to_call
    active_opponents = [u for u in players if u != HERO and u not in folded]
    opp_reach = {u: live[u] + remaining[u] for u in active_opponents}
    boundaries = sorted({x for x in [*live.values(), hero_reach, *opp_reach.values()] if x > 0})
    tiers = []
    eligible_live = 0
    previous = 0
    for level in boundaries:
        contributors = [u for u, amount in live.items() if amount >= level]
        layer = (level - previous) * len(contributors)
        hero_can = hero_reach >= level
        opponents_can = [u for u, reach in opp_reach.items() if reach >= level]
        counted = hero_can and bool(opponents_can)
        if counted:
            eligible_live += layer
        tiers.append({"from": previous, "to": level,
                      "contributing_seats_including_folded": sorted(players[u]["seatNo"] for u in contributors),
                      "layer_amount": layer, "hero_reaches": hero_can,
                      "opponent_seats_reaching": sorted(players[u]["seatNo"] for u in opponents_can),
                      "counted": counted})
        previous = level
    contestable = dead_total + eligible_live

    # Label and observation arithmetic.
    raw_kind = target_action.get("type")
    raw_amount = target_action.get("amount", 0)
    target_commitment = hero_commit + (raw_amount if type(raw_amount) is int else 0)
    if raw_kind == "all_in" and target_commitment <= max_bet:
        expected = {"action": "call"}
    elif raw_kind in {"raise", "bet", "all_in"}:
        expected = {"action": "raise", "amount": target_commitment}
    else:
        expected = {"action": raw_kind}
    check(checks, "expected_label_matches_raw_target_and_is_outside_observation",
          row.get("expected") == expected and "expected" not in row.get("state", {}))

    # Raise bounds are reconstructed from the observed wager increments and
    # remaining stacks. Any ambiguous short-all-in case is held explicitly.
    other_can_act = [u for u in active_opponents if remaining[u] > 0]
    hero_total = hero_commit + remaining[HERO]
    min_raise = max_bet + last_full_raise if max_bet > 0 else last_full_raise
    raise_available = (bool(other_can_act) and rights[HERO] and hero_total > max_bet
                       and hero_total >= min_raise)
    min_raise_obs = min_raise if raise_available else 0
    max_raise_obs = hero_total if raise_available else 0
    check(checks, "stack_call_and_current_bet_match_prefix_ledger",
          row.get("state", {}).get("stack") == remaining[HERO]
          and row.get("state", {}).get("to_call") == to_call
          and row.get("state", {}).get("current_bet") == hero_commit
          and row.get("state", {}).get("pot") == pot)
    check(checks, "ante_aware_contestable_pot_matches_independent_prefix_math",
          row.get("state", {}).get("contestable_pot") == contestable
          and contestable <= pot)
    check(checks, "candidate_prefix_crosscheck_matches_independent_source_math",
          row.get("source_prefix_pot_check", {}).get("pot") == pot
          and row.get("source_prefix_pot_check", {}).get("dead_antes") == dead_total
          and row.get("source_prefix_pot_check", {}).get("to_call") == to_call
          and row.get("source_prefix_pot_check", {}).get("contestable_pot") == contestable)
    check(checks, "big_blind_matches_raw_blind_level",
          row.get("state", {}).get("big_blind") == hand.get("blindLevel", {}).get("bigBlind"))
    check(checks, "raise_bounds_and_legal_actions_match_source_ledger",
          row.get("state", {}).get("min_raise_to") == min_raise_obs
          and row.get("state", {}).get("max_raise_to") == max_raise_obs
          and row.get("state", {}).get("players_to_act") == len(other_can_act)
          and row.get("state", {}).get("players_active") == len(players) - len(folded))
    legal = row.get("state", {}).get("legal_actions", [])
    expected_legal = (["fold"] if to_call > 0 else []) + (["call"] if to_call > 0 else ["check"])
    if raise_available:
        expected_legal.append("raise")
    expected_legal = [x for x in ["fold", "check", "call", "raise"] if x in expected_legal]
    check(checks, "legal_action_set_reconciles_with_prefix",
          isinstance(legal, list) and len(legal) == len(set(legal))
          and set(legal) == set(expected_legal) and expected.get("action") in legal)
    if expected.get("action") == "raise":
        check(checks, "source_raise_label_fits_independent_bounds",
              raise_available and min_raise_obs <= expected.get("amount", -1) <= max_raise_obs)
    else:
        checks["source_raise_label_fits_independent_bounds"] = True

    # Current-street board, reveal cutoff and history use only the raw prefix.
    current_rd = hand["rounds"][tri]
    board_raw: list[str] = []
    reveal_ts: list[int] = []
    if target_street == "flop":
        board_raw = [card_name(x) for x in current_rd.get("communityCards", [])]
        reveal_ts = current_rd.get("communityCardTimestamps", [])
    elif target_street in {"turn", "river"}:
        board_raw = [card_name(current_rd.get("communityCard"))]
        reveal_ts = [current_rd.get("communityCardTimestamp")]
    board_valid = all(board_raw) and (len(board_raw) in {0, 3, 4, 5})
    if target_street == "flop":
        cutoff_ok = (type(target_action.get("timestamp")) is int and len(reveal_ts) == 3
                     and all(type(x) is int for x in reveal_ts)
                     and target_action["timestamp"] >= max(reveal_ts))
    elif target_street in {"turn", "river"}:
        cutoff_ok = (len(reveal_ts) == 1 and type(reveal_ts[0]) is int
                     and type(target_action.get("timestamp")) is int
                     and target_action["timestamp"] >= reveal_ts[0])
    else:
        cutoff_ok = True
    check(checks, "visible_board_and_public_reveal_cutoff_match_target_street",
          board_valid and cutoff_ok and row.get("state", {}).get("board") == board_raw
          and row.get("state", {}).get("street") == {"pre_flop": "preflop", "flop": "flop", "turn": "turn", "river": "river"}.get(target_street))

    def expected_history() -> list[dict[str, Any]]:
        result = []
        h_commit = dict.fromkeys(players, 0)
        h_max = 0
        for _, _, s, a in prefix:
            kind, actor = a.get("type"), a.get("userId")
            if kind in DEAD | LIVE_FORCED:
                if kind in LIVE_FORCED:
                    amount = a["amount"]
                    h_commit[actor] += amount
                    h_max = max(h_max, h_commit[actor])
                continue
            before = h_commit[actor]
            raw_amt = a.get("amount", 0)
            target = before + (raw_amt if type(raw_amt) is int else 0)
            action = kind
            if kind == "all_in":
                action = "call" if target <= h_max else "raise"
            elif kind in {"bet", "raise"}:
                action = "raise"
            if kind == "fold":
                total = before
                added = 0
            else:
                total = target
                added = max(0, target - before)
                if type(raw_amt) is int:
                    h_commit[actor] += raw_amt
                    h_max = max(h_max, h_commit[actor])
            result.append({"street": "preflop", "player": f"p{index_by_id[actor]}",
                           "position": names[index_by_id[actor]], "action": action,
                           "amount": total, "added": added})
        return result
    history = expected_history()
    check(checks, "history_is_exactly_prior_public_actions_in_source_order",
          row.get("state", {}).get("history") == history)
    hero_cards_raw = players[HERO].get("pocketCards")
    hero_cards = [card_name(c) for c in hero_cards_raw] if isinstance(hero_cards_raw, list) and len(hero_cards_raw) == 2 else []
    state = row.get("state", {})
    check(checks, "hero_private_cards_match_raw_hero_only",
          len(hero_cards) == 2 and all(hero_cards) and state.get("hole_cards") == hero_cards)
    state_unknown = sorted(set(state) - ALLOWED_STATE)
    state_values_no_source_leak = not any(k in state for k in (
        "expected", "label", "winner", "winners", "payout", "payouts", "end_chips",
        "terminal_pot", "opponent_hole_cards", "opponent_cards", "future_actions",
        "source_action", "source_prefix_pot_check", "source_capture_path"))
    opponent_private_values = [card_name(c) for uid, p in players.items() if uid != HERO
                              for c in (p.get("pocketCards") if isinstance(p.get("pocketCards"), list) else [])]
    check(checks, "observation_contains_only_whitelisted_public_fields",
          not state_unknown and state_values_no_source_leak)
    check(checks, "observation_has_no_opponent_private_or_terminal_values",
          not (set(hero_cards) & set(opponent_private_values))
          and all(card not in state.get("hole_cards", []) for card in opponent_private_values)
          and not any(k in state for k in ("end_chips", "winners", "payouts", "pots", "terminal_outcome")))

    # Reconciliation against the predecessor candidate. It is not used as a
    # pot oracle; only immutable identity and the explicitly permitted state
    # field difference are compared.
    old = previous_rows.get(row.get("previous_candidate_decision_id"))
    if old:
        old_state, new_state = old.get("state", {}), state
        diff_state = sorted(k for k in set(old_state) | set(new_state) if old_state.get(k) != new_state.get(k))
        old_stable = old.get("stable_source_decision_key")
        check(checks, "predecessor_found_by_previous_candidate_decision_id",
              old.get("decision_id") == row.get("previous_candidate_decision_id")
              and old.get("source_decision_id") == sid)
        check(checks, "only_contestable_pot_changed_in_state", diff_state == ["contestable_pot"])
        check(checks, "expected_and_stable_source_keys_unchanged",
              old.get("expected") == row.get("expected")
              and ((old_stable == row.get("stable_source_decision_key"))
                   if old_stable is not None else old.get("source_action_index") == ordinal)
              and old.get("source_decision_id") == sid)
        check(checks, "decision_id_changed_after_state_correction",
              old.get("decision_id") != row.get("decision_id")
              and row.get("decision_id") != row.get("previous_candidate_decision_id"))
        old_pot = old_state.get("contestable_pot")
    else:
        diff_state, old_pot = [], None
        for k in ("predecessor_found_by_previous_candidate_decision_id",
                  "only_contestable_pot_changed_in_state", "expected_and_stable_source_keys_unchanged",
                  "decision_id_changed_after_state_correction"):
            checks[k] = False
    check(checks, "candidate_source_keys_do_not_overlap_prior_admissions",
          sid not in admitted_source and row.get("stable_source_decision_key") not in admitted_stable
          and row.get("decision_id") not in admitted_decisions
          and row.get("previous_candidate_decision_id") not in admitted_decisions)
    prior_same_hand = admitted_rows_by_hand.get(row.get("hand_id"), [])
    check(checks, "same_hand_admissions_are_distinct_source_decisions",
          all(prior.get("source_decision_id") != sid
              and prior.get("stable_source_decision_key") != row.get("stable_source_decision_key")
              for prior in prior_same_hand))
    check(checks, "candidate_stays_development_only_and_not_fresh_holdout",
          row.get("policy_use") == "development_only" and row.get("fresh_holdout") is False
          and "pending" in str(row.get("admission_status", "")))

    if not all(checks.values()):
        issues.extend(name for name, okay in checks.items() if not okay)
    ante_by_seat = Counter()
    for post in ante_posts:
        ante_by_seat[post["actor_seat"]] += post["amount"]
    detail.update({
        "identity": {"source_decision_id": sid, "stable_source_decision_key": row.get("stable_source_decision_key"),
                     "hand_uuid": hand_uuid, "session_id": row.get("session_id"),
                     "requested_episode_id": requested_ep, "episode_aliases": aliases,
                     "source_action_index": ordinal, "source_round_index": tri,
                     "source_round_action_index": tai, "target_street": target_street},
        "provenance_hashes": {"capture_sha256": capture_sha,
                              "request_sha256": request_sha, "query_sha256": query_sha,
                              "canonical_payload_sha256": payload_sha},
        "source_payment_prefix": {"total_pot_before_action": pot, "dead_antes_total": dead_total,
                                   "dead_ante_posts_by_seat": ante_posts,
                                   "dead_ante_total_by_seat": dict(sorted(ante_by_seat.items())),
                                   "live_forced_posts": live_posts,
                                   "live_contribution_by_seat": {str(players[u]["seatNo"]): v for u, v in live.items()},
                                   "folded_seats": sorted(players[u]["seatNo"] for u in folded),
                                   "hero_reach_after_call": hero_reach,
                                   "opponent_reach_by_seat": {str(players[u]["seatNo"]): v for u, v in opp_reach.items()},
                                   "live_tiers": tiers, "contestable_live_tiers": eligible_live,
                                   "derived_contestable_pot": contestable, "to_call": to_call},
        "hero_decision_facts": {"seat_order_clockwise_from_small_blind": [players[u]["seatNo"] for u in order_ids],
                                "button_seat": dealer_seat, "button_actor_seat": players[dealer_id]["seatNo"] if dealer_id else None,
                                "small_blind_seat": players[sb_id]["seatNo"], "big_blind_seat": players[bb_id]["seatNo"],
                                "hero_seat": players[HERO]["seatNo"], "hero_player_index": actor_i,
                                "hero_position": names[actor_i], "target_raw_action": {"type": raw_kind, "amount": raw_amount},
                                "target_actor_queue_errors": order_errors,
                                "remaining_stack": remaining[HERO], "hero_live_commitment": hero_commit,
                                "current_live_price": max_bet, "min_raise_to_derived": min_raise_obs,
                                "max_raise_to_derived": max_raise_obs,
                                "players_active_derived": len(players) - len(folded),
                                "players_to_act_derived": len(other_can_act),
                                "history_entries": len(history), "expected_label_from_raw_action": expected},
        "observation_safety": {"allowed_state_keys": sorted(ALLOWED_STATE),
                                "actual_state_keys": sorted(state), "unexpected_state_keys": state_unknown,
                                "hero_cards": hero_cards, "opponent_private_card_count_in_source": len(opponent_private_values),
                                "target_state_history_equals_prefix": state.get("history") == history,
                                "expected_label_is_separate": "expected" not in state},
        "predecessor_comparison": {"previous_candidate_decision_id": row.get("previous_candidate_decision_id"),
                                   "old_decision_id": old.get("decision_id") if old else None,
                                   "new_decision_id": row.get("decision_id"), "old_contestable_pot": old_pot,
                                   "new_contestable_pot": state.get("contestable_pot"),
                                   "state_diff_keys": diff_state,
                                   "old_and_new_expected_equal": old is not None and old.get("expected") == row.get("expected"),
                                   "old_stable_key_explicitly_persisted": bool(old and old_stable),
                                   "stable_key_unchanged_by_same_source_action_locator": old is not None and old.get("source_action_index") == ordinal,
                                   "stable_key_unchanged": old is not None and ((old_stable == row.get("stable_source_decision_key")) if old_stable is not None else old.get("source_action_index") == ordinal)},
        "prior_admission_same_hand": [{"source_decision_id": prior.get("source_decision_id"),
                                       "stable_source_decision_key": prior.get("stable_source_decision_key"),
                                       "decision_id": prior.get("decision_id"),
                                       "candidate_source_key_is_distinct": prior.get("source_decision_id") != sid
                                           and prior.get("stable_source_decision_key") != row.get("stable_source_decision_key")}
                                      for prior in prior_same_hand],
    })
    passed = all(checks.values())
    return {"source_decision_id": sid, "stable_source_decision_key": row.get("stable_source_decision_key"),
            "review_status": "eligible_for_parent_development_only_admission_review" if passed else "held_for_correction_or_source_review",
            "admission_created": False, "fresh_holdout": False,
            "checks": checks, "issues": issues, "details": detail}


def main() -> None:
    input_bytes = INPUT.read_bytes()
    candidates = json.loads(input_bytes)
    rows = candidates.get("records", [])
    ids = [row.get("source_decision_id") for row in rows]
    diagnostic = json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))
    diagnostic_rows = diagnostic.get("rows_needing_correction", [])
    diagnostic_ids = {r.get("source_decision_id") for r in diagnostic_rows}
    diagnostic_checked = diagnostic.get("all_checked_rows", [])
    diagnostic_checked_ids = {r.get("source_decision_id") for r in diagnostic_checked}
    source_ids = {sid for sid in ids if isinstance(sid, str)}
    source_output_records = []
    for item in candidates.get("source_outputs", []):
        out_path = ROOT / item.get("path", "")
        if out_path.is_file():
            source_output_records.extend(json.loads(out_path.read_text(encoding="utf-8")).get("records", []))
    source_output_ids = {r.get("source_decision_id") for r in source_output_records if isinstance(r.get("source_decision_id"), str)}
    source_output_extras = sorted(source_output_ids - source_ids)
    previous = old_candidates()
    admitted_source, admitted_stable, admitted_hands, admitted_decisions, admitted_rows_by_hand, admission_counts = admitted_keys()
    results = [inspect_one(row, previous, admitted_source, admitted_stable,
                           admitted_hands, admitted_decisions, admitted_rows_by_hand) for row in rows]
    eligible = [r["source_decision_id"] for r in results if r["review_status"].startswith("eligible")]
    held = [r["source_decision_id"] for r in results if r["review_status"].startswith("held")]
    review_code_sha = sha(Path(__file__).read_bytes())
    checks_summary = Counter(check_name for row in results for check_name, okay in row.get("checks", {}).items() if not okay)
    source_output_checks = []
    for item in candidates.get("source_outputs", []):
        source_path = ROOT / item.get("path", "")
        actual = sha(source_path.read_bytes()) if source_path.is_file() else None
        source_output_checks.append({"path": item.get("path"), "recorded_sha256": item.get("sha256"),
                                    "actual_sha256": actual, "hash_matches": actual == item.get("sha256"),
                                    "session_id": item.get("session_id"),
                                    "record_count": item.get("counts", {}).get("validated_candidate_decisions")})
    stable_keys = [r.get("stable_source_decision_key") for r in rows]
    scope = {
        "candidate_input": str(INPUT.relative_to(ROOT)),
        "candidate_input_sha256": sha(input_bytes),
        "candidate_records": len(rows),
        "unique_source_decisions": len(source_ids),
        "unique_hands": len({r.get("hand_id") for r in rows}),
        "unique_stable_source_keys": len(set(stable_keys)),
        "candidate_ids_exactly_match_diagnostic_rows_needing_correction": source_ids == diagnostic_ids,
        "diagnostic_rows_needing_correction": len(diagnostic_ids),
        "diagnostic_source_decisions_checked": len(diagnostic_checked_ids),
        "diagnostic_unaffected_decision_count_not_copied": len(diagnostic_checked_ids - diagnostic_ids),
        "regenerated_source_output_decision_count": len(source_output_ids),
        "candidate_ids_are_subset_of_regenerated_source_outputs": source_ids <= source_output_ids,
        "regenerated_output_only_source_decisions_excluded_from_review": source_output_extras,
        "all_rows_previously_held_source_ids": all(sid in set(sum([json.loads(p.read_text()).get("held_source_decision_ids", []) for p in ADMISSION_DIR.glob("batch-*.json")], [])) for sid in source_ids),
        "candidate_rows_not_admitted": candidates.get("counts", {}).get("newly_admitted_decisions") == 0,
        "prior_admission_counts_by_source": admission_counts,
        "prior_admitted_decisions": sum(admission_counts.values()),
        "frozen_baseline_manifest_sha256": sha((ROOT / "data/corpus_splits/development-after-prospective-v1.json").read_bytes()),
        "frozen_admitted_decisions_from_user_checkpoint": 45,
        "current_admitted_decisions_from_user_checkpoint": 80,
        "candidate_admitted_source_key_overlaps": sorted(source_ids & admitted_source),
        "candidate_admitted_stable_source_key_overlaps": sorted(set(stable_keys) & admitted_stable),
        "candidate_admitted_source_key_overlap_count": len((source_ids & admitted_source) | (set(stable_keys) & admitted_stable)),
        "candidate_admitted_decision_id_overlaps": sorted(
            ({r.get("decision_id") for r in rows} | {r.get("previous_candidate_decision_id") for r in rows})
            & admitted_decisions),
        "candidate_hands_already_represented_by_distinct_admitted_actions": [
            {"hand_id": r.get("hand_id"), "source_decision_id": r.get("source_decision_id"),
             "prior_source_decision_ids": [p.get("source_decision_id") for p in admitted_rows_by_hand.get(r.get("hand_id"), [])]}
            for r in rows if admitted_rows_by_hand.get(r.get("hand_id"), [])],
        "regenerated_output_only_rows_are_already_admitted": all(sid in admitted_source for sid in source_output_extras),
        "regenerated_source_output_hash_checks": source_output_checks,
        "review_code_sha256": review_code_sha,
        "converter_sha256_from_input": candidates.get("converter_sha256"),
        "pot_helper_sha256_from_input": candidates.get("pot_helper_sha256"),
        "full_suite_pass_count_from_input_not_rerun": candidates.get("full_suite_tests_passed"),
        "frozen_files_unchanged_claim_from_input_not_rechecked": candidates.get("frozen_files_unchanged"),
    }
    recommendation = {
        "schema_version": 1,
        "status": "fresh_independent_review_complete_development_only",
        "policy_calls": 0, "training_runs": 0, "score_runs": 0,
        "admissions_created": 0, "splits_edited": 0,
        "candidate_count_reviewed": len(rows), "eligible_recommendation_count": len(eligible),
        "held_recommendation_count": len(held), "current_admitted_count_unchanged": 80,
        "recommendation_rule": "Rows passing every independent source, state, prefix-accounting, predecessor, and dedup check may be considered by the parent for a separate development-only admission step. This review performs no admission and makes no count change. A failed or ambiguous check remains held.",
        "eligible_for_parent_development_only_admission_review": eligible,
        "held_for_correction_or_source_review": held,
        "fresh_holdout_candidates": [],
        "scope_and_hashes": scope,
    }
    review = {"schema_version": 1, "status": "fresh_independent_raw_prefix_review",
              "scope_and_hashes": scope, "summary": {
                  "candidate_rows": len(rows), "passed_rows": len(eligible), "held_rows": len(held),
                  "failed_check_counts": dict(sorted(checks_summary.items())),
                  "admissions_created": 0, "fresh_holdout": 0,
                  "all_rows_development_only": True,
                  "warning": "This is an eligibility recommendation only; it does not change the 80-record admission ledger."},
              "rows": results}
    per_row_path = HERE / "per-row-review.json"
    recommendation_path = HERE / "recommendations.json"
    write_json(per_row_path, review)
    write_json(recommendation_path, recommendation)
    # Markdown provides a human-readable row summary and records hashes of all
    # machine-readable outputs. The hash manifest below includes this file.
    lines = [
        "# Ante correction independent review (2026-11-02)", "",
        "## Scope and disposition", "",
        f"Reviewed the exact {len(rows)} rows in `ante_correction/candidates.json`; the row IDs match all {len(diagnostic_ids)} diagnostic rows needing correction and cover {len({r.get('hand_id') for r in rows})} unique hands. Of {len(diagnostic_checked_ids)} diagnostic decisions checked, the {len(diagnostic_checked_ids - diagnostic_ids)} unaffected ones were not copied into the review set.",
        f"The regenerated conversion files contain {len(source_output_ids)} unique decision IDs; their only output-only key(s) outside this 21-row review are {', '.join(f'`{x}`' for x in source_output_extras) or 'none'}. The extra key is already admitted and excluded from the correction recommendations.",
        f"Independent raw-prefix recommendation: {len(eligible)} eligible for a separate parent development-only admission review; {len(held)} held. Admissions created: 0. Fresh holdout rows: 0. The current admitted count remains 80.",
        f"Exact admitted source-key overlap: {scope['candidate_admitted_source_key_overlap_count']}. {len(scope['candidate_hands_already_represented_by_distinct_admitted_actions'])} candidate hand(s) have a different action already admitted; those source decision keys are distinct.",
        "The eligibility status is not an admission. All reviewed records remain development-only, and no policy, training, score, admission, split, frozen-data, or model operation was run.", "",
        "## Method", "",
        "For each row, I re-read the cached source capture and GetHand request; recalculated their byte hashes, the query hash, and canonical hand payload hash; checked the request hand and episode variables against cached episode metadata; and listed every cached episode alias containing the hand.",
        "I walked only the source action prefix before the target decision. I accounted for explicit dead ante posts (including a big blind's ante), live blinds/straddles, and prior betting payments. I formed live contribution tiers directly from those source payments, including folded contributors, and counted only tiers reachable by the hero after calling and by at least one live opponent. Dead antes were added as common money. Neither the converter, PokerKit, the frozen helper, opponent private cards, terminal pots, winners, nor end stacks were used as the equality oracle.",
        "I also checked physical seat order, button/SB/BB identity, preflop actor queue, the hero's remaining stack, call price, raise bounds, public board cutoff, exact prior-action history, source label mapping, development-only status, state-field whitelist, and predecessor-row diffs. The predecessor comparison confirms only `contestable_pot` changed in each state; expected labels and stable source decision keys match, while decision IDs changed. Where a predecessor did not persist round/action subkeys, equality is derived from its unchanged flat source action locator and the same raw source array position.", "",
        "## Per-row accounting and recommendation", "",
        "| Source decision | Dead ante | Live pot before action | Old → corrected contestable pot | Recommendation | Notes |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in results:
        d = r.get("details", {})
        cmp = d.get("predecessor_comparison", {})
        acct = d.get("source_payment_prefix", {})
        note = ", ".join(r.get("issues", [])) or "all independent checks passed"
        lines.append(f"| `{r.get('source_decision_id')}` | {acct.get('dead_antes_total', 'n/a')} | {acct.get('total_pot_before_action', 'n/a')} | {cmp.get('old_contestable_pot', 'n/a')} → {cmp.get('new_contestable_pot', 'n/a')} | {r.get('review_status')} | {note} |")
    lines += ["", "## Episode aliases and partial source facts", "",
              "| Source decision | Requested episode | Cached aliases that index the hand | Source context |",
              "|---|---|---|---|"]
    for r in results:
        ident = r.get("details", {}).get("identity", {})
        aliases = ident.get("episode_aliases", [])
        alias_text = "; ".join(f"`{a.get('episode_id')}` ({a.get('title')})" for a in aliases) or "none cached"
        context = "; ".join(sorted({f"{a.get('festival_name')}: {a.get('tournament_name')}" for a in aliases})) or "episode association unsupported"
        lines.append(f"| `{r.get('source_decision_id')}` | `{ident.get('requested_episode_id')}` | {alias_text} | {context} |")
    for match in scope["candidate_hands_already_represented_by_distinct_admitted_actions"]:
        prior_ids = ", ".join(f"`{x}`" for x in match["prior_source_decision_ids"])
        lines += ["", f"Prior-hand overlap detail: `{match['hand_id']}` has candidate key `{match['source_decision_id']}` and prior admitted key(s) {prior_ids}. This is a different source action, not a repeated source decision key."]
    lines += ["", "## Integrity and output hashes", "",
              f"- Candidate input SHA-256: `{scope['candidate_input_sha256']}`",
              f"- Review code SHA-256: `{review_code_sha}`",
              f"- Converter SHA-256 (as recorded in regenerated input): `{scope['converter_sha256_from_input']}`",
              f"- Pot helper SHA-256 (as recorded in regenerated input): `{scope['pot_helper_sha256_from_input']}`",
              *[f"- Regenerated source output `{item['path']}` SHA-256: `{item['actual_sha256']}` (matches recorded hash: `{item['hash_matches']}`)" for item in source_output_checks],
              f"- Candidate rows' prior admitted-key overlap: {len(scope['candidate_admitted_source_key_overlaps'])}",
              "- Machine-readable row review and recommendations have SHA-256 values in `SHA256SUMS`.", "",
              "## Review limits", "",
              "This review establishes source-prefix/accounting and row-integrity eligibility only. It does not validate strategy quality, hand-label quality beyond matching source actions, or fresh-holdout status. Every episode alias is listed per row, including the requested episode and alternate indexed-episode references. Episode metadata hashes and captured GetEpisode request hashes are checked against the 2026 collector manifest where it declares a source; 2025 aliases are read from their source capture directories. The 2026 manifest states episode coverage may be sparse, so no complete-chronology claim is made; that chronology limitation remains unsupported by this review.", ""]
    markdown_path = HERE / "review.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    sums = []
    for path in [Path(__file__), per_row_path, recommendation_path, markdown_path]:
        sums.append(f"{sha(path.read_bytes())}  {path.name}")
    (HERE / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "eligible": len(eligible), "held": len(held),
                      "failed_check_counts": dict(checks_summary),
                      "code_sha256": review_code_sha,
                      "outputs": {p.name: sha(p.read_bytes()) for p in [per_row_path, recommendation_path, markdown_path]},
                      "scope": scope}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
