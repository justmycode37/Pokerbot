"""Independent read-only audit of the saved Nov 1 forum conversion artifacts.

Writes only audit results into this review folder. It does not invoke the
converter, replay policies, or alter the source records.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import tomllib
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
CONV = ROOT / "data/acquisition_resume/2026-11-01/forum_conversion"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_text(value: str) -> str:
    return sha_bytes(value.encode("utf-8"))


def sha_json(value) -> str:
    return sha_bytes(canonical(value))


def money(value) -> Decimal:
    return Decimal(str(value).replace("$", "").replace(",", ""))


def ticks(value, scale: int):
    scaled = Decimal(value) * scale
    return int(scaled) if scaled == int(scaled) else None


def parse_source(text: str):
    out = {"hand_id": None, "seats": {}, "blinds": {}, "button": None,
           "hero_cards": None, "events": [], "uncalled": [], "total": None,
           "awards": []}
    summary_started = False
    for line_no, line in enumerate(text.splitlines(), 1):
        if line == "*** SUMMARY ***":
            summary_started = True
        m = re.match(r"^Full Tilt Poker Game #(\d+)\s*:", line)
        if m:
            out["hand_id"] = m.group(1)
        m = (None if summary_started else
             re.match(r"^Seat (\d+): (.+?) \(\$([\d,]+(?:\.\d+)?)\)(?:, is sitting out)?$", line))
        if m:
            out["seats"][m.group(1)] = {"player": m.group(2), "stack": money(m.group(3)),
                                         "sitting_out": ", is sitting out" in line}
        m = re.match(r"^The button is in seat #(\d+)", line)
        if m:
            out["button"] = m.group(1)
        m = re.match(r"^(.+?) posts the (small|big) blind of \$([\d,]+(?:\.\d+)?)$", line)
        if m:
            out["blinds"][m.group(2)] = {"player": m.group(1), "amount": money(m.group(3))}
        m = re.match(r"^Phil Ivey shows \[([^\]]+)\]", line)
        if m:
            out["hero_cards"] = m.group(1).split()
        m = re.match(r"^Uncalled bet(?: of)? \$([\d,]+(?:\.\d+)?) returned to (.+)$", line)
        if m:
            out["uncalled"].append({"amount": money(m.group(1)), "player": m.group(2)})

        if line.startswith("*** FLOP ***"):
            groups = re.findall(r"\[([^\]]+)\]", line)
            out["events"].append({"kind": "board", "street": "flop",
                                  "cards": groups[-1].split() if groups else [], "line": line_no})
        elif line.startswith("*** TURN ***"):
            groups = re.findall(r"\[([^\]]+)\]", line)
            out["events"].append({"kind": "board", "street": "turn",
                                  "cards": groups[-1].split() if groups else [], "line": line_no})
        elif line.startswith("*** RIVER ***"):
            groups = re.findall(r"\[([^\]]+)\]", line)
            out["events"].append({"kind": "board", "street": "river",
                                  "cards": groups[-1].split() if groups else [], "line": line_no})

        action = None
        m = re.match(r"^(.+?) folds$", line)
        if m:
            action = {"player": m.group(1), "verb": "fold"}
        m = re.match(r"^(.+?) checks$", line)
        if m:
            action = {"player": m.group(1), "verb": "check"}
        m = re.match(r"^(.+?) calls \$([\d,]+(?:\.\d+)?)(?:, and is all in)?$", line)
        if m:
            action = {"player": m.group(1), "verb": "call", "amount": money(m.group(2))}
        m = re.match(r"^(.+?) bets \$([\d,]+(?:\.\d+)?)(?:, and is all in)?$", line)
        if m:
            action = {"player": m.group(1), "verb": "bet", "amount": money(m.group(2))}
        m = re.match(r"^(.+?) raises to \$([\d,]+(?:\.\d+)?)(?:, and is all in)?$", line)
        if m:
            action = {"player": m.group(1), "verb": "raise", "amount": money(m.group(2))}
        if action:
            action.update({"kind": "action", "line": line_no})
            out["events"].append(action)

    m = re.search(r"(?im)^Total pot \$?([\d,]+(?:\.\d+)?) \| Rake \$?([\d,]+(?:\.\d+)?)\s*$", text)
    if m:
        out["total"] = (money(m.group(1)), money(m.group(2)))
    summary = text.split("*** SUMMARY ***", 1)
    out["awards"] = ([money(x) for x in re.findall(
        r"(?i)\b(?:collected|won)\s*\(\$([\d,]+(?:\.\d+)?)\)", summary[1])]
        if len(summary) == 2 else [])
    if not out["awards"]:
        out["awards"] = [money(x) for x in re.findall(
            r"(?i)\bwins? the pot\s*\(\$([\d,]+(?:\.\d+)?)\)", summary[0])]
    return out


def positions(n):
    if n == 2:
        return ["BB", "BTN"]
    if n == 3:
        return ["SB", "BB", "BTN"]
    if n == 4:
        return ["SB", "BB", "UTG", "BTN"]
    return ["SB", "BB", "UTG"] + ["MP"] * max(0, n - 5) + ["CO", "BTN"]


def audit():
    source_path = CONV / "source_records.jsonl"
    source_rows = [json.loads(x) for x in source_path.read_text().splitlines()]
    candidates_doc = json.loads((CONV / "review_candidates.json").read_text())
    by_source_id = {str(s.get("hand_id")): s for s in source_rows if s.get("hand_id") is not None}
    grouped = collections.defaultdict(list)
    for row in candidates_doc["records"]:
        grouped[row["hand_id"].split(":", 1)[1]].append(row)
    for ftid in {"5258419612", "5228844526", "5229856787", "5229878446"}:
        grouped.setdefault(ftid, [])

    hand_results, decision_results = [], []
    for ftid, candidates in sorted(grouped.items()):
        candidates.sort(key=lambda r: r["strict_action_prefix_identity"]["action_index"])
        src = by_source_id.get(ftid)
        if src is None:
            hand_results.append({"fulltilt_hand_id": ftid, "checks": {"source_record_exists": False},
                                 "issues": ["source_record_not_found"], "candidate_decisions": len(candidates)})
            continue
        raw = src["raw_source_text"]
        source = parse_source(raw)
        phh_path = CONV / "normalized_phh" / f"fulltilt_{ftid}.phh"
        phh_raw = phh_path.read_bytes()
        phh = tomllib.loads(phh_raw.decode("utf-8"), parse_float=Decimal)
        players, actions = phh["players"], phh["actions"]
        n = len(players)
        hero_i = next((i for i, player in enumerate(players)
                       if player.strip().casefold() == "phil ivey"), -1)
        hero_name = players[hero_i] if hero_i >= 0 else "Phil Ivey"
        seats_by_player = {v["player"]: (k, v["stack"]) for k, v in source["seats"].items()}
        source_money = [seat["stack"] for seat in source["seats"].values()]
        source_money.extend(blind["amount"] for blind in source["blinds"].values())
        source_money.extend(event["amount"] for event in source["events"] if "amount" in event)
        source_money.extend(item["amount"] for item in source["uncalled"])
        if source["total"] is not None:
            source_money.extend(source["total"])
        source_money.extend(source["awards"])
        precision = max([0] + [-value.as_tuple().exponent for value in source_money])
        source_scale = 10 ** precision
        pos = positions(n)
        hand_checks = {
            "exact_id_matches_raw_header_and_structured_id": source["hand_id"] == ftid == str(src.get("hand_id")),
            "source_extract_hash_matches_all_candidate_rows": all(r["raw_extract_sha256"] == sha_text(raw) for r in candidates),
            "source_url_matches_all_candidate_rows": all(r["source_url"] == src["source"]["url"] for r in candidates),
            "candidate_source_evidence_matches_snapshot_text": all(r["source_evidence"].get("raw_source_text") == raw for r in candidates),
            "raw_seat_stacks_match_structured_source": set(source["seats"]) == set(src["seats"]) and all(
                source["seats"][k]["player"] == v["player"] and source["seats"][k]["stack"] == money(v["starting_stack"])
                for k, v in src["seats"].items()),
            "raw_blinds_button_match_structured_source": all(
                source["blinds"].get(short, {}).get("player") == src["forced_bets"][key]["player"] and
                source["blinds"].get(short, {}).get("amount") == money(src["forced_bets"][key]["amount"])
                for short, key in (("small", "small_blind"), ("big", "big_blind"))) and
                source["button"] == str(src["button_seat"]),
            "source_hero_cards_match_structured_source_or_remain_unknown": (
                source["hero_cards"] == src["hero_hole_cards"] if isinstance(src["hero_hole_cards"], list)
                else source["hero_cards"] is None and isinstance(src["hero_hole_cards"], str)
                    and src["hero_hole_cards"].startswith("unknown")),
            "normalized_phh_id_and_player_set_match_source": str(phh.get("hand")) == ftid and
                set(players) == {seat["player"] for seat in source["seats"].values() if not seat["sitting_out"]},
            "normalized_phh_hash_matches_checkpoint": sha_bytes(phh_raw) == next(
                h["normalized_phh_sha256"] for h in candidates_doc["hand_reports"] if h["fulltilt_hand_id"] == ftid),
            "source_url_is_public_https_attribution": src["source"]["url"].startswith("https://"),
            "raw_money_exactly_represented_at_decimal_scale": all(ticks(value, source_scale) is not None for value in source_money),
            "candidate_tick_scale_matches_raw_source_precision": all(r["chip_ticks_per_currency_unit"] == source_scale for r in candidates),
        }
        if n > 1 and hero_i >= 0:
            blind_positions_match = (players[pos.index("SB")] == source["blinds"]["small"]["player"]
                                     if n > 2 else players[-1] == source["blinds"]["small"]["player"])
            blind_positions_match = (blind_positions_match and players[pos.index("BB")] == source["blinds"]["big"]["player"]
                                     and players[-1] == source["seats"][source["button"]]["player"])
        else:
            blind_positions_match = False
        hand_checks["player_order_matches_blinds_and_button_positions"] = blind_positions_match

        start = {name: seats_by_player[name][1] for name in players if name in seats_by_player}
        stacks = dict(start)
        if hero_name not in stacks:
            raise RuntimeError(f"hero stack missing for {ftid}: {players!r} / {list(seats_by_player)!r}")
        committed = {name: Decimal(0) for name in players}
        street_bets = {name: Decimal(0) for name in players}
        folded, history, board = set(), [], []
        small, big = source["blinds"]["small"], source["blinds"]["big"]
        if small["player"] in stacks and big["player"] in stacks:
            for blind in (small, big):
                stacks[blind["player"]] -= blind["amount"]
                committed[blind["player"]] += blind["amount"]
                street_bets[blind["player"]] += blind["amount"]
        bb = big["amount"]
        last_full_raise = bb
        action_count, board_count, candidate_ix = 0, 0, 0
        source_action_ids = []
        for event in source["events"]:
            if event["kind"] == "board":
                if event["street"] == "flop":
                    board = list(event["cards"])
                else:
                    board.extend(event["cards"])
                street_bets = {name: Decimal(0) for name in players}
                last_full_raise = bb
                board_count += 1
                continue

            actor, verb = event["player"], event["verb"]
            if actor not in players:
                hand_checks["all_source_action_actors_exist_in_normalized_players"] = False
                continue
            actor_i = players.index(actor)
            action_index = n + action_count + board_count
            source_action_ids.append((actor, verb, event.get("amount")))
            before = street_bets[actor]
            max_bet = max(street_bets.values()) if street_bets else Decimal(0)
            target = before
            if verb == "call":
                target = before + event["amount"]
            elif verb in ("bet", "raise"):
                target = event["amount"]

            if actor.strip().casefold() == "phil ivey":
                if candidate_ix >= len(candidates):
                    row = None
                    checks = {"source_hero_action_has_candidate": False}
                else:
                    row = candidates[candidate_ix]
                    candidate_ix += 1
                    obs = row["observations"]
                    identity = row["strict_action_prefix_identity"]
                    scale = row["chip_ticks_per_currency_unit"]
                    phh_action = actions[action_index] if action_index < len(actions) else None
                    phh_actor = f"p{actor_i + 1}"
                    expected_suffix = {"fold": "f", "check": "cc", "call": "cc", "bet": "cbr", "raise": "cbr"}[verb]
                    action_at_index_matches = False
                    if phh_action:
                        parts = phh_action.split()
                        action_at_index_matches = len(parts) >= 2 and parts[0] == phh_actor and parts[1] == expected_suffix
                        if action_at_index_matches and verb in ("bet", "raise"):
                            action_at_index_matches = len(parts) == 3 and Decimal(parts[2]) == event["amount"]
                    prefix_hash = sha_json(actions[:action_index]) if action_index <= len(actions) else None
                    action = {"fold": "fold", "check": "check", "call": "call", "bet": "raise", "raise": "raise"}[verb]
                    to_call_raw = max(Decimal(0), max_bet - before)
                    if action == "call" and to_call_raw == 0:
                        action = "check"
                    expected_label = {"action": action}
                    if action == "raise":
                        expected_label["amount"] = ticks(target, scale)

                    expected_history = []
                    for item in history:
                        expected_history.append({
                            "street": item["street"], "player": item["player"], "action": item["action"],
                            "amount": ticks(item["amount"], scale), "added": ticks(item["added"], scale),
                            "position": item["position"],
                        })
                    full_min_raise = (max_bet + last_full_raise) if max_bet else bb
                    to_call = min(to_call_raw, stacks[hero_name])
                    opponent_can_respond = any(name != hero_name and name not in folded and stacks[name] > 0
                                               for name in players)
                    max_raise = before + stacks[hero_name]
                    can_raise = opponent_can_respond and max_raise > before + to_call
                    min_raise = min(full_min_raise, max_raise) if can_raise else Decimal(0)
                    report_max_raise = max_raise if can_raise else Decimal(0)
                    raise_bounds_ok = obs.get("max_raise_to") == ticks(report_max_raise, scale) and \
                        obs.get("min_raise_to") == ticks(min_raise, scale)
                    legal = sorted((["fold"] if to_call_raw > 0 else []) +
                                   (["call"] if to_call_raw > 0 else ["check"]) +
                                   (["raise"] if can_raise else []))
                    money_ok = all(ticks(x, scale) is not None for x in [
                        stacks[hero_name], committed[hero_name], max_bet, before, bb, *committed.values()])
                    pot = sum(committed.values(), Decimal(0))
                    hero_limit = committed[hero_name] + to_call
                    opponent_limits = [committed[name] + stacks[name] for name in players
                                       if name != hero_name and name not in folded]
                    bounds = set(committed.values()) | {hero_limit} | set(opponent_limits)
                    contestable, previous = Decimal(0), Decimal(0)
                    for level in sorted(x for x in bounds if x > 0):
                        layer = (level - previous) * sum(value >= level for value in committed.values())
                        if hero_limit >= level and any(value >= level for value in opponent_limits):
                            contestable += layer
                        previous = level
                    contestable = min(contestable, pot)
                    allowed_keys = {"hole_cards", "board", "pot", "to_call", "stack", "current_bet",
                        "min_raise_to", "max_raise_to", "big_blind", "position", "players_active",
                        "players_to_act", "legal_actions", "street", "seed", "history", "player_id",
                        "contestable_pot", "table_size"}
                    opponent_cards = []
                    for m in re.finditer(r"^(.+?) shows \[([^\]]+)\]", raw, re.M):
                        if m.group(1) != "Phil Ivey":
                            opponent_cards.extend(m.group(2).split())
                    checks = {
                        "source_action_index_and_prefix_count_match": identity["action_index"] == action_index and identity["prefix_action_count"] == action_index,
                        "actor_id_maps_to_source_player": identity["actor"] == phh_actor and obs.get("player_id") == f"p{actor_i}",
                        "canonical_fulltilt_action_identity_matches": identity["namespace"] == "fulltilt" and identity["hand_id"] == ftid and
                            identity["identity"] == f"fulltilt:{ftid}:{phh_actor}:action:{action_index}:prefix:{identity['prefix_actions_sha256']}",
                        "prefix_digest_matches_normalized_action_prefix": identity["prefix_actions_sha256"] == prefix_hash,
                        "normalized_action_at_index_matches_saved_source_action": action_at_index_matches,
                        "preaction_history_matches_raw_source_actions": obs.get("history") == expected_history,
                        "board_cutoff_and_street_match_source_prefix": obs.get("board") == board and
                            obs.get("street") == {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board)),
                        "hero_cards_match_source_shown_cards": obs.get("hole_cards") == source["hero_cards"] == src["hero_hole_cards"],
                        "expected_action_and_raise_target_match_raw_source": row["expected"] == expected_label,
                        "exact_decimal_currency_scale_has_no_truncation": money_ok and all(type(obs.get(k)) is int for k in (
                            "pot", "to_call", "stack", "current_bet", "min_raise_to", "max_raise_to", "big_blind", "contestable_pot")),
                        "preaction_pot_stack_to_call_and_current_bet_match_source": obs.get("pot") == ticks(pot, scale) and
                            obs.get("stack") == ticks(stacks[hero_name], scale) and
                            obs.get("current_bet") == ticks(before, scale) and obs.get("to_call") == ticks(to_call, scale),
                        "min_max_raise_bounds_match_source_state": raise_bounds_ok,
                        "legal_actions_match_source_bet_and_raise_bounds": obs.get("legal_actions") == legal,
                        "actor_position_matches_source_blinds_button_and_seat_order": hero_i >= 0 and obs.get("position") == pos[hero_i],
                        "active_player_count_matches_source_folds": obs.get("players_active") == n - len(folded) and obs.get("table_size") == n,
                        "contestable_pot_matches_source_contributions_and_stacks": obs.get("contestable_pot") == ticks(contestable, scale),
                        "observation_contains_no_opponent_cards_future_board_or_label": set(obs) == allowed_keys and
                            not (set(obs.get("hole_cards", [])) & set(opponent_cards)) and obs.get("board") == board and
                            "expected" not in obs and "source_evidence" not in obs,
                        "row_marked_inspected_not_fresh_holdout": row.get("inspected_label_no_fresh_holdout_claim") is True,
                        "decision_id_recomputes_from_canonical_hand_and_observation": row["decision_id"] == sha_json({
                            "hand_id": f"fulltilt:{ftid}", "state": {k: v for k, v in obs.items() if k != "seed"}}),
                    }
                    # Missing machine-readable award is recorded separately and does not invalidate an action-prefix fact.
                    award_pending = not source["awards"]
                    decision_results.append({
                        "decision_id": row["decision_id"], "hand_id": row["hand_id"],
                        "source_record_id": src["record_id"], "source_url": src["source"]["url"],
                        "raw_extract_sha256": row["raw_extract_sha256"], "source_action_line": event["line"],
                        "action_index": action_index, "source_actor": actor, "source_action": verb,
                        "chip_ticks_per_currency_unit": scale, "checks": checks,
                        "prefix_facts_supported": all(checks.values()),
                        "terminal_award_status": "unverified_award" if award_pending else "award_present",
                        "recommendation": "prefix_supported_award_reconciliation_pending" if award_pending and all(checks.values()) else
                            ("eligible_for_parent_review" if all(checks.values()) else "hold_for_source_or_conversion_mismatch"),
                    })

            # Apply this source action only after checking its pre-action state.
            if verb == "fold":
                folded.add(actor); action_name = "fold"; new_target = before; added = Decimal(0)
            elif verb == "check":
                action_name = "check"; new_target = before; added = Decimal(0)
            elif verb == "call":
                new_target = before + event["amount"]
                added = event["amount"]
                action_name = "call" if max(Decimal(0), max_bet - before) else "check"
            else:
                new_target = event["amount"]
                added = new_target - before
                action_name = "raise"
                increment = new_target - max_bet
                if increment >= last_full_raise:
                    last_full_raise = increment
            stacks[actor] -= added
            street_bets[actor] = new_target
            committed[actor] += added
            history.append({"street": {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board)),
                            "player": f"p{actor_i}", "action": action_name, "amount": new_target,
                            "added": added, "position": pos[actor_i]})
            action_count += 1

        if candidate_ix != len(candidates):
            hand_checks["candidate_decision_count_matches_source_hero_actions"] = False
        else:
            hand_checks["candidate_decision_count_matches_source_hero_actions"] = True
        if source["total"] is not None:
            gross = sum(committed.values(), Decimal(0)) - sum((r["amount"] for r in source["uncalled"]), Decimal(0))
            hand_checks["source_total_pot_matches_contributions_after_uncalled_returns"] = gross == source["total"][0]
            hand_checks["awards_plus_rake_reconcile_total_pot_if_present"] = (
                not source["awards"] or sum(source["awards"], Decimal(0)) + source["total"][1] == source["total"][0])
        else:
            gross = None
            hand_checks["source_total_pot_matches_contributions_after_uncalled_returns"] = False
            hand_checks["awards_plus_rake_reconcile_total_pot_if_present"] = False
        award_reconciliation = ("pending_award_evidence" if not source["awards"] else
            ("reconciled" if hand_checks["awards_plus_rake_reconcile_total_pot_if_present"] else "mismatch"))
        hand_results.append({
            "fulltilt_hand_id": ftid, "canonical_hand_id": f"fulltilt:{ftid}",
            "source_record_id": src["record_id"], "source_url": src["source"]["url"],
            "raw_extract_sha256": sha_text(raw), "candidate_decisions": len(candidates),
            "source_hero_decisions": candidate_ix, "chip_ticks_per_currency_unit": candidates[0]["chip_ticks_per_currency_unit"] if candidates else source_scale,
            "source_total_pot": str(source["total"][0]) if source["total"] else None,
            "source_rake": str(source["total"][1]) if source["total"] else None,
            "recomputed_gross_pot_after_uncalled_returns": str(gross) if gross is not None else None,
            "machine_readable_award_count": len(source["awards"]),
            "known_hero_cards": bool(src["hero_hole_cards"] and not str(src["hero_hole_cards"]).startswith("unknown")),
            "award_reconciliation": award_reconciliation,
            "hand_recommendation": ("hold_no_known_hero_cards_no_decision_rows" if not candidates else
                ("eligible_prefix_facts_award_pending" if award_reconciliation == "pending_award_evidence" else "eligible_for_parent_review")),
            "checks": hand_checks,
        })

    # Candidate-level duplicate checks and exact state identity against admitted 80.
    admitted = []
    for path in [ROOT / "data/corpus_splits/development-after-prospective-v1.json",
                 ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-001.json",
                 ROOT / "data/acquisition_resume/2026-11-01/admissions/batch-002.json"]:
        obj = json.loads(path.read_text())
        admitted.extend(obj.get("records", []))
    admitted_ids = {r.get("decision_id") for r in admitted}
    admitted_hands = {str(r.get("canonical_hand_id") or r.get("hand_id")) for r in admitted}
    admitted_states = collections.defaultdict(list)
    for r in admitted:
        if isinstance(r.get("state"), dict):
            sig = sha_json({k: v for k, v in r["state"].items() if k != "seed"})
            admitted_states[sig].append(r.get("decision_id"))
    prefix_ids = [r["strict_action_prefix_identity"]["identity"] for r in candidates_doc["records"]]
    decision_ids = [r["decision_id"] for r in candidates_doc["records"]]
    def source_signature(rec):
        seat_rows = rec.get("seats", {})
        seat_sig = tuple(sorted((v.get("player"), str(money(v.get("starting_stack", v.get("stack", 0)))))
                                for v in seat_rows.values()))
        forced = rec.get("forced_bets", {})
        blind_sig = tuple((k, forced.get(k, {}).get("player"),
                           str(money(forced.get(k, {}).get("amount", 0))))
                          for k in ("small_blind", "big_blind"))
        button_seat = str(rec.get("button_seat")) if rec.get("button_seat") is not None else None
        button_player = rec.get("button_player")
        if button_player is None and button_seat is not None:
            button_player = seat_rows.get(button_seat, {}).get("player")
        cards = rec.get("hero_hole_cards")
        card_sig = tuple(sorted(cards)) if isinstance(cards, list) else cards
        return (rec.get("game"), rec.get("stakes"), seat_sig, blind_sig, button_player,
                card_sig, tuple(rec.get("board", [])))

    pending_sources = []
    for item in candidates_doc.get("pending_cross_source_identity_review", []):
        source_record = source_rows[item["input_record_index"]]
        pending_sources.append(source_record)
    exact_candidate_sources = [s for s in source_rows if str(s.get("hand_id")) in grouped and s.get("hand_id")]
    full_signature_matches = []
    card_board_matches = []
    for pending_source in pending_sources:
        for exact_source in exact_candidate_sources:
            if source_signature(pending_source) == source_signature(exact_source):
                full_signature_matches.append({"pending_record_id": pending_source["record_id"],
                                               "exact_record_id": exact_source["record_id"]})
            p = source_signature(pending_source)
            e = source_signature(exact_source)
            if (p[0], p[1], p[5], p[6]) == (e[0], e[1], e[5], e[6]):
                card_board_matches.append({"pending_record_id": pending_source["record_id"],
                                           "exact_record_id": exact_source["record_id"]})
    progress_path = ROOT / "data/acquisition_resume/2026-11-01/forum_2012_plus/progress.json"
    progress = json.loads(progress_path.read_text())
    candidate_ftids = {r["hand_id"].split(":", 1)[1] for r in candidates_doc["records"]}
    source_raw_ids = [m.group(1) for s in source_rows
                      if (m := re.search(r"(?im)^Full Tilt Poker Game #(\d+)\s*:", s.get("raw_source_text", "")))]
    cross = {
        "admitted_record_count_including_45_baseline": len(admitted),
        "new_candidate_hand_ids_overlap_admitted_hand_ids": sorted({r["hand_id"] for r in candidates_doc["records"]} & admitted_hands),
        "new_candidate_decision_ids_overlap_admitted_decision_ids": sorted(set(decision_ids) & admitted_ids),
        "duplicate_prefix_identity_count_within_111": len(prefix_ids) - len(set(prefix_ids)),
        "duplicate_candidate_decision_id_count_within_111": len(decision_ids) - len(set(decision_ids)),
        "exact_state_matches_to_admitted_80": [
            {"decision_id": r["decision_id"], "hand_id": r["hand_id"],
             "admitted_decision_ids": admitted_states[sha_json({k:v for k,v in r["observations"].items() if k != "seed"})]}
            for r in candidates_doc["records"]
            if sha_json({k:v for k,v in r["observations"].items() if k != "seed"}) in admitted_states],
    }
    cross["additional_converted_source_reconciliation"] = {
        "pending_no_visible_id_records": len(pending_sources),
        "exact_full_signature_matches_to_candidate_hands": full_signature_matches,
        "same_game_stakes_hero_cards_and_full_board_matches": card_board_matches,
        "candidate_exact_ids_already_in_existing_id_exclusion_ledger": len(candidate_ftids & set(progress.get("excluded_existing_fulltilt_hand_ids", []))),
        "all_candidate_ids_covered_by_existing_id_exclusion_ledger": candidate_ftids <= set(progress.get("excluded_existing_fulltilt_hand_ids", [])),
        "source_snapshot_exact_id_count": len(set(source_raw_ids)),
        "source_snapshot_exact_id_collision_count": len(source_raw_ids) - len(set(source_raw_ids)),
        "source_snapshot_exact_ids_are_unique": len(source_raw_ids) == len(set(source_raw_ids)),
    }
    current_forum_dir = ROOT / "data/acquisition_resume/2026-11-02/forum_2008"
    current_forum_file = current_forum_dir / "records.jsonl"
    current_forum_rows = [json.loads(x) for x in current_forum_file.read_text().splitlines()]
    current_forum_raw_ids = [m.group(1) for s in current_forum_rows
                             if (m := re.search(r"(?im)^Full Tilt Poker Game #(\d+)\s*:", s.get("raw_source_text", "")))]
    current_forum_progress = json.loads((current_forum_dir / "progress.json").read_text())
    secondary_review_path = ROOT / "data/acquisition_resume/2026-11-02/converted_forum/review_candidates.json"
    secondary_review = json.loads(secondary_review_path.read_text())
    secondary_fp_failures = secondary_review.get("original_fulltilt_fingerprint_failures", [])
    source_position_checks = {h["fulltilt_hand_id"]: h["checks"].get("player_order_matches_blinds_and_button_positions")
                              for h in hand_results}
    cross["2026_11_02_acquisition_overlap"] = {
        "forum_2008_new_record_rows": len(current_forum_rows),
        "forum_2008_new_record_exact_id_collisions_with_31_candidates": sorted(set(current_forum_raw_ids) & candidate_ftids),
        "forum_2008_progress_exact_id_duplicate_references_to_candidates": sorted(
            candidate_ftids & set(re.findall(r"\b\d{10}\b", json.dumps(current_forum_progress)))),
        "forum_2008_progress_quantified_duplicate_occurrences": current_forum_progress.get("counts", {}).get("dedup_skipped"),
        "forum_2008_progress_note_for_5260871551": next((x["result"] for x in current_forum_progress.get("sources_visited", [])
            if "index9" in x.get("url", "") and "5260871551" in x.get("result", "")), None),
        "converted_forum_secondary_review_records": len(secondary_review.get("records", [])),
        "converted_forum_secondary_review_pending_decisions": secondary_review.get("counts", {}).get("pending_review_decisions"),
        "converted_forum_original_fingerprint_failure_ids_and_reasons": [
            {"fulltilt_hand_id": x.get("fulltilt_hand_id"), "reason": x.get("reason")}
            for x in secondary_fp_failures],
        "seat_order_fingerprint_warnings_independently_resolved_for_reviewed_hands": {
            ftid: source_position_checks.get(ftid) for ftid in ("9327292808", "9327359467", "5228844526")},
        "second_source_review_no_new_rows_or_admissions": not secondary_review.get("records") and
            secondary_review.get("counts", {}).get("newly_admitted_decisions") == 0,
        "forum_2008_record_file_sha256": sha_bytes(current_forum_file.read_bytes()),
        "forum_2008_record_file_exact_ids": current_forum_raw_ids,
    }
    id_pattern = re.compile(rb"(?<![0-9])(?:" + b"|".join(x.encode() for x in sorted(candidate_ftids)) + rb")(?![0-9])")
    scan_roots = [ROOT / "data"]
    scanned_files, scanned_bytes, id_files = 0, 0, []
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt", ".phh", ".csv"}:
                continue
            if path.is_relative_to(HERE):
                continue
            try:
                if path.stat().st_size > 25_000_000:
                    continue
                content = path.read_bytes()
            except OSError:
                continue
            scanned_files += 1
            scanned_bytes += len(content)
            found_ids = sorted(set(match.decode("ascii") for match in id_pattern.findall(content)))
            if found_ids:
                id_files.append({"path": str(path.relative_to(ROOT)), "candidate_id_count": len(found_ids),
                                 "is_raw_source_copy": path in {
                                     ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl",
                                     CONV / "source_records.jsonl"},
                                 "is_existing_id_ledger": path == progress_path})
    cross["workspace_source_copy_scan"] = {
        "roots": [str(p.relative_to(ROOT)) for p in scan_roots],
        "text_files_scanned": scanned_files, "bytes_scanned": scanned_bytes,
        "files_containing_candidate_ids": len(id_files), "matching_files": id_files,
        "raw_source_copy_paths": [x["path"] for x in id_files if x["is_raw_source_copy"]],
        "other_raw_source_copies_found": [x["path"] for x in id_files if x["is_raw_source_copy"] and
            x["path"] not in ("data/acquisition_sprint_1h/online_forum/records.jsonl",
                              "data/acquisition_resume/2026-11-01/forum_conversion/source_records.jsonl")],
    }
    decision_recommendations = collections.Counter(d["recommendation"] for d in decision_results)
    hand_recommendations = collections.Counter(h["hand_recommendation"] for h in hand_results)
    result = {
        "review_status": "completed_independent_saved_extract_review",
        "source_snapshot": {"path": str(source_path.relative_to(ROOT)), "rows": len(source_rows),
                             "sha256": sha_bytes(source_path.read_bytes())},
        "input_source": {"path": "data/acquisition_sprint_1h/online_forum/records.jsonl",
                         "sha256": sha_bytes((ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl").read_bytes()),
                         "byte_identical_to_snapshot": (ROOT / "data/acquisition_sprint_1h/online_forum/records.jsonl").read_bytes() == source_path.read_bytes()},
        "audited_exact_id_hands": len(hand_results), "audited_decisions": len(decision_results),
        "decision_recommendation_counts": dict(decision_recommendations),
        "hand_recommendation_counts": dict(hand_recommendations),
        "hands": hand_results, "decisions": decision_results, "cross_dedup": cross,
    }
    (HERE / "source_review.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "hands": len(hand_results), "decisions": len(decision_results),
        "hand_failures": [{"hand": h["fulltilt_hand_id"], "checks": [k for k,v in h["checks"].items() if not v]}
                          for h in hand_results if not all(h["checks"].values())],
        "decision_failure_counts": dict(collections.Counter(k for d in decision_results for k,v in d["checks"].items() if not v)),
        "award_hands": [(h["fulltilt_hand_id"], h["candidate_decisions"], h["machine_readable_award_count"], h["award_reconciliation"])
                        for h in hand_results if h["award_reconciliation"] == "pending_award_evidence"],
        "cross_dedup": cross,
    }, indent=2))


if __name__ == "__main__":
    audit()
