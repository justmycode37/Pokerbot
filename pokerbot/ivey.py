"""Fail-closed PHH replay and descriptive Ivey comparison.

PokerKit owns poker rules in this offline evaluator. Runtime policies have
no dependency on PokerKit. PHH is parsed as TOML, never executed.
"""
from __future__ import annotations

import copy
import math
import re
import tomllib
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .cards import normalize_card
from .state import Observation

SOURCE_URL = "https://github.com/uoftcprg/phh-dataset/blob/main/data/dwan-ivey-2009.phh"
DEFAULT_PHH_PATH = Path(__file__).resolve().parents[1] / "data/ivey/dwan-ivey-2009.phh"


class PHHError(ValueError):
    """A record cannot be replayed without repairing or inventing facts."""


def _new_report():
    return dict(files_seen=0, files_included=0, files_excluded=0,
                decisions_seen=0, decisions_included=0, decisions_excluded=0,
                exclusions={})


LAST_LOAD_REPORT = _new_report()


def _exclude(report, reason, *, decision=False):
    key = ("decision:" if decision else "file:") + reason
    report["exclusions"][key] = report["exclusions"].get(key, 0) + 1
    report["decisions_excluded" if decision else "files_excluded"] += 1


def _parse_phh(path):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise PHHError("invalid_toml") from exc


def _scale_chips(phh):
    """Convert fractional currency to exact integer ticks, never truncate."""
    fields = ("starting_stacks", "antes", "blinds_or_straddles")
    monetary = []
    for key in fields:
        values = phh.get(key)
        if not isinstance(values, list) or not values:
            raise PHHError("missing_stack_ante_or_blind_list")
        monetary.extend(values)
    monetary.append(phh.get("min_bet"))
    for action in phh["actions"]:
        pieces = action.split("#", 1)[0].split()
        if len(pieces) >= 2 and pieces[1] == "cbr":
            if len(pieces) != 3:
                raise PHHError("malformed_raise")
            monetary.append(pieces[2])
    try:
        if any(isinstance(v, bool) for v in monetary):
            raise PHHError("boolean_chip_amount")
        decimals = [Decimal(str(v)) for v in monetary]
    except InvalidOperation as exc:
        raise PHHError("invalid_chip_amount") from exc
    if any(not v.is_finite() or v < 0 for v in decimals):
        raise PHHError("chip_amount_must_be_finite_and_nonnegative")
    precision = max(0, max(-v.as_tuple().exponent for v in decimals))
    if precision > 6:
        raise PHHError("chip_precision_exceeds_six_decimal_places")
    scale = 10 ** precision
    result = dict(phh)
    for key in fields:
        result[key] = [int(Decimal(str(v)) * scale) for v in phh[key]]
    result["min_bet"] = int(Decimal(str(phh["min_bet"])) * scale)
    result["actions"] = []
    for action in phh["actions"]:
        pieces = action.split("#", 1)[0].split()
        if len(pieces) >= 2 and pieces[1] == "cbr":
            pieces[2] = str(int(Decimal(pieces[2]) * scale))
        result["actions"].append(" ".join(pieces))
    return result, scale


def _replay_file(path, report):
    report["files_seen"] += 1
    try:
        raw = _parse_phh(path)
        if raw.get("variant") != "NT":
            raise PHHError("not_no_limit_holdem")
        names, actions = raw.get("players"), raw.get("actions")
        if not isinstance(names, list) or not 2 <= len(names) <= 8:
            raise PHHError("missing_or_unsupported_player_list")
        heroes = [i for i, name in enumerate(names) if isinstance(name, str)
                  and name.strip().casefold() == "phil ivey"]
        if len(heroes) != 1:
            raise PHHError("phil_ivey_not_uniquely_identified")
        hero = heroes[0]
        if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
            raise PHHError("missing_or_invalid_action_list")
        phh, scale = _scale_chips(raw)
        if any(len(phh[k]) != len(names) for k in
               ("starting_stacks", "antes", "blinds_or_straddles")):
            raise PHHError("player_field_length_mismatch")
        from pokerkit import Automation, Mode, NoLimitTexasHoldem, parse_action
        from .simulation import _observation, _positions
        automations = tuple(getattr(Automation, name) for name in (
            "ANTE_POSTING", "BET_COLLECTION", "BLIND_OR_STRADDLE_POSTING",
            "RUNOUT_COUNT_SELECTION", "HAND_KILLING", "CHIPS_PUSHING", "CHIPS_PULLING"))
        state = NoLimitTexasHoldem.create_state(
            automations, bool(phh.get("ante_trimming_status", False)), phh["antes"],
            phh["blinds_or_straddles"], phh["min_bet"], phh["starting_stacks"],
            len(names), mode=Mode.CASH_GAME)
        positions = _positions(len(names))
        hand_id = str(raw.get("hand") or raw.get("hand_id") or path.stem)
        history, decisions, seen_cards = [], [], set()
        hero_decisions = excluded_hero = 0
        for encoded in phh["actions"]:
            if not encoded:
                continue
            pieces = encoded.split()
            if state.can_burn_card():
                state.burn_card("??")
            actor = None
            betting = len(pieces) >= 2 and pieces[1] in ("f", "cc", "cbr")
            if betting:
                match = re.fullmatch(r"p([1-9]\d*)", pieces[0])
                if not match:
                    raise PHHError("invalid_betting_actor")
                actor = int(match.group(1)) - 1
                if actor != state.actor_index:
                    raise PHHError("action_order_inconsistent")
                if len(pieces) != (3 if pieces[1] == "cbr" else 2):
                    raise PHHError("malformed_betting_action")
            if pieces[:2] in (["d", "dh"], ["d", "db"]):
                text = pieces[-1]
                if len(text) % 2:
                    raise PHHError("malformed_dealt_cards")
                for offset in range(0, len(text), 2):
                    code = text[offset:offset + 2]
                    if code == "??":
                        continue
                    card = normalize_card(code)
                    if card in seen_cards:
                        raise PHHError("duplicate_dealt_card")
                    seen_cards.add(card)
            if betting:
                street = ("preflop", "flop", "turn", "river")[state.street_index]
                before = state.bets[actor]
                due = state.checking_or_calling_amount or 0
                action_name = {"f": "fold", "cc": "call" if due else "check", "cbr": "raise"}[pieces[1]]
                target = int(pieces[2]) if pieces[1] == "cbr" else (
                    before + due if pieces[1] == "cc" else before)
                expected = {"action": action_name}
                if action_name == "raise":
                    expected["amount"] = target
                if actor == hero:
                    hero_decisions += 1
                    hero_cards = [repr(c) for c in state.hole_cards[hero]]
                    if len(hero_cards) != 2 or any("?" in c for c in hero_cards):
                        excluded_hero += 1
                    else:
                        observation = _observation(state, hero, positions, 0,
                                                   hero_decisions - 1, history)
                        observation["hand_id"] = hand_id
                        observation["seed"] = 0
                        decisions.append({
                            "state": observation, "expected": expected,
                            "source": SOURCE_URL if path.resolve() == DEFAULT_PHH_PATH.resolve() else str(path),
                            "hand_id": hand_id, "chip_ticks_per_currency_unit": scale})
            # No repair, implicit fold or skipped bad transition is permitted.
            parse_action(state, encoded)
            if betting:
                history.append({"street": street, "player": f"p{actor}",
                                "position": positions[actor], "action": action_name,
                                "amount": target,
                                "added": max(0, target - before) if action_name != "fold" else 0})
        # Commit reporting only after the whole record passed validation.
        report["decisions_seen"] += hero_decisions
        report["decisions_included"] += len(decisions)
        for _ in range(excluded_hero):
            _exclude(report, "hero_hole_cards_not_visible_at_decision", decision=True)
        if decisions:
            report["files_included"] += 1
        else:
            _exclude(report, "no_usable_ivey_decisions")
        return decisions
    except ImportError as exc:
        raise RuntimeError("PHH replay needs the evaluation extra: pip install '.[evaluation]'") from exc
    except (OSError, PHHError, ValueError, TypeError, KeyError, IndexError) as exc:
        _exclude(report, str(exc) if isinstance(exc, PHHError) else "invalid_or_inconsistent_phh")
        return []


def load_decisions(path=None):
    requested = DEFAULT_PHH_PATH if path is None else Path(path)
    report = _new_report()
    if not requested.exists():
        report["files_seen"] = 1
        _exclude(report, "path_not_found")
        LAST_LOAD_REPORT.clear()
        LAST_LOAD_REPORT.update(report)
        return []
    paths = sorted(requested.rglob("*.phh")) if requested.is_dir() else [requested]
    rows = []
    if not paths:
        report["files_seen"] = 1
        _exclude(report, "directory_has_no_phh_files")
    for file in paths:
        rows.extend(_replay_file(file, report))
    LAST_LOAD_REPORT.clear()
    LAST_LOAD_REPORT.update(report)
    return rows


def _wilson_interval(successes, trials, z=1.959963984540054):
    if not trials:
        return None
    p = successes / trials
    den = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / den
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / den
    return [max(0, center - radius), min(1, center + radius)]


def policy_observation(state):
    """Rebuild modeled fields, excluding report IDs and arbitrary metadata."""
    obs = Observation.from_dict(state)
    result = {k: copy.deepcopy(getattr(obs, k)) for k in obs.__dataclass_fields__}
    for key in ("hole_cards", "board", "history", "legal_actions"):
        result[key] = sorted(result[key]) if key == "legal_actions" else list(result[key])
    return result


def _legal_prediction(prediction, state):
    if not isinstance(prediction, dict) or prediction.get("action") not in state["legal_actions"]:
        return False
    if prediction["action"] == "raise":
        value = prediction.get("amount")
        return type(value) is int and state["min_raise_to"] <= value <= state["max_raise_to"]
    return True


def compare_decisions(decisions, decide_callable, *, sizing_tolerance=0):
    """Describe legal action, exact decision, sizing and probability agreement.

    Row-wise Wilson intervals are descriptive only: supplied hands are selected
    and decisions within a hand are correlated. No population claim is made.
    """
    if type(sizing_tolerance) is not int or sizing_tolerance < 0:
        raise ValueError("sizing_tolerance must be nonnegative integer ticks")
    rows = list(decisions)
    predictions, errors, relative_errors, probabilities = [], [], [], []
    agreement = exact = within = illegal = bad_distributions = 0
    by_hand = defaultdict(list)
    for row in rows:
        if row.get("evidence_tier") == "video_snapshot_with_rounded_or_missing_context":
            raise ValueError("rounded or incomplete video snapshots are qualitative-only")
        state = policy_observation(row["state"])
        expected = row["expected"]
        if not _legal_prediction(expected, state):
            raise ValueError("benchmark contains an illegal expected action")
        prediction = decide_callable(copy.deepcopy(state))
        valid = _legal_prediction(prediction, state)
        illegal += not valid
        action = prediction.get("action", "invalid") if isinstance(prediction, dict) else "invalid"
        matches = valid and action == expected["action"]
        agreement += matches
        error = None
        if matches and action == "raise":
            error = abs(prediction["amount"] - expected["amount"])
            errors.append(error)
            relative_errors.append(error / max(1, state["contestable_pot"] + state["to_call"]))
            within += error <= sizing_tolerance
        exact_match = matches and (action != "raise" or error == 0)
        exact += exact_match
        hand_id = str(row["hand_id"])
        by_hand[hand_id].append(exact_match)
        p_expected = None
        dist = prediction.get("probabilities") if isinstance(prediction, dict) else None
        if dist is not None:
            valid_dist = (isinstance(dist, dict) and all(
                k in state["legal_actions"] and type(v) in (int, float)
                and math.isfinite(v) and 0 <= v <= 1 for k, v in dist.items())
                and abs(sum(dist.values()) - 1) < 1e-8)
            if valid_dist:
                p_expected = dist.get(expected["action"], 0.0)
                probabilities.append(p_expected)
            else:
                bad_distributions += 1
        predictions.append({
            "hand_id": hand_id, "expected_action": expected["action"],
            "predicted_action": action, "legal_prediction": valid,
            "action_match": matches, "exact_action_and_size_match": exact_match,
            "expected_amount": expected.get("amount"),
            "predicted_amount": prediction.get("amount") if isinstance(prediction, dict) else None,
            "probability_of_recorded_action_class": p_expected})
    n = len(rows)
    raise_count = sum(r["expected"]["action"] == "raise" for r in rows)
    return {
        "sample_count": n, "hand_count": len(by_hand),
        "action_agreement_count": agreement,
        "action_agreement": agreement / n if n else None,
        "action_agreement_ci95_wilson": _wilson_interval(agreement, n),
        "population_confidence_interval": None,
        "exact_action_and_size_agreement_count": exact,
        "exact_action_and_size_agreement": exact / n if n else None,
        "completely_exact_hands": sum(all(values) for values in by_hand.values()),
        "illegal_prediction_count": illegal,
        "raise_sizing": {
            "expected_raise_count": raise_count, "sized_raise_count": len(errors),
            "missing_or_unscored_count": raise_count - len(errors),
            "tolerance_chips": sizing_tolerance, "within_tolerance_count": within,
            "within_tolerance_rate": within / len(errors) if errors else None,
            "mean_absolute_error_chips": sum(errors) / len(errors) if errors else None,
            "mean_absolute_error_pot_after_call_fraction":
                sum(relative_errors) / len(relative_errors) if relative_errors else None},
        "mixed_action_comparison": {
            "scored_count": len(probabilities), "invalid_distributions": bad_distributions,
            "mean_probability_of_recorded_action_class":
                sum(probabilities) / len(probabilities) if probabilities else None,
            "zero_probability_count": probabilities.count(0)},
        "predictions": predictions,
        "representativeness_caveat":
            "Selected rows describe this corpus only. Decisions within a hand are correlated; "
            "the row-wise Wilson interval is descriptive, not a population confidence interval."}

