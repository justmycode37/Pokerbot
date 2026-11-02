"""Evidence-grounded qualitative comparison packets, without hindsight."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .state import Observation
from .ivey import policy_observation


def review_packet(decisions, decide_callable, *, policy_name="fast"):
    """Freeze facts and bot output before revealing the recorded action.

    Questions and hypotheses are review aids. This module does not claim to
    know Ivey's intent or estimate EV without an explicit opponent model.
    """
    rows = []
    for number, decision in enumerate(decisions, 1):
        raw = copy.deepcopy(decision["state"])
        obs = Observation.from_dict(raw)
        prediction = decide_callable(policy_observation(raw))
        recorded = copy.deepcopy(decision["expected"])
        probabilities = prediction.get("probabilities", {})
        issues = []
        if prediction.get("action") != recorded["action"]:
            if probabilities.get(recorded["action"], 0) > 0:
                issues.append("The recorded action is in the bot's mix; one sampled disagreement does not show that its strategy excludes the line.")
            elif recorded["action"] == "raise":
                issues.append("Inspect value/bluff coverage and the opponent range behind the bot's passive choice.")
            elif prediction.get("action") == "raise":
                issues.append("Inspect whether the bot's aggression gains calls from worse hands or folds from better hands.")
            else:
                issues.append("Inspect the continue range, price, future play and available opponent reads.")
        if recorded["action"] == "raise" and prediction.get("action") == "raise":
            if prediction.get("amount") != recorded.get("amount"):
                issues.append("Both select aggression, but different sizes represent different decisions and may face different continuing ranges.")
        if not issues:
            issues.append("Action agreement alone does not establish the same strategic reason or the same decision quality.")

        def sizing(action):
            if action.get("action") != "raise":
                return None
            target = action.get("amount")
            if type(target) is not int:
                return None
            return {"street_total": target,
                    "extra_chips": target - obs.current_bet,
                    "raise_over_call_fraction_of_pot_after_call":
                        (target - obs.current_bet - obs.to_call) / max(1, obs.contestable_pot + obs.to_call)}

        rows.append({
            "decision_number": number, "hand_id": decision["hand_id"],
            "source": decision["source"], "format": decision.get("format", "unknown"),
            "evidence_tier": decision.get("evidence_tier", "unknown"),
            "visible_facts": {"hole_cards": list(obs.hole_cards), "board": list(obs.board),
                              "position": obs.position, "street": obs.street,
                              "pot": obs.pot, "contestable_pot": obs.contestable_pot,
                              "to_call": obs.to_call, "pot_odds": obs.pot_odds,
                              "remaining_stack": obs.stack, "big_blind": obs.big_blind,
                              "players_active": obs.players_active,
                              "prior_public_actions": list(obs.history)},
            "bot": prediction, "recorded_ivey_action": recorded,
            "bot_sizing": sizing(prediction), "ivey_sizing": sizing(recorded),
            "bot_probability_of_recorded_action": probabilities.get(recorded["action"]),
            "review_hypotheses_not_verdicts": issues,
            "source_limitations": decision.get("derivation_notes", []),
            "unknowns": ["Opponent range, tendencies and live reads",
                         "Ivey's intended mixed-strategy frequencies",
                         "Counterfactual responses to a different bot action"]
                        + (["Tournament payouts and utility of chips"] if "tournament" in decision.get("format", "") else []),
        })
    root = Path(__file__).resolve().parent
    fingerprints = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.glob("*.py"))}
    table = root.parent / "data/preflop_equity.json"
    if table.exists():
        fingerprints["preflop_equity.json"] = hashlib.sha256(table.read_bytes()).hexdigest()
    return {"policy": policy_name, "source_fingerprints": fingerprints,
            "review_kind": "qualitative_comparison_not_imitation_accuracy_or_solver_verdict",
            "rubric": [
                "Range and position: value, bluff and defense coverage; opponents' likely ranges",
                "Aggression: whether worse hands continue or better hands fold",
                "Sizing: price offered, stack commitment and response to alternative sizes",
                "Equity and pot odds: current information, draws and future action",
                "Adaptation: public opponent tendencies; label missing live reads as unknown",
            ], "decisions": rows,
            "caveat": "Selected public hands illustrate behavior. They do not establish Ivey's full strategy, counterfactual EV, or a general percentage match."}


def packet_markdown(packet):
    lines = ["# Qualitative Ivey comparison", "", packet["caveat"], "",
             f"Policy: `{packet['policy']}`. Source fingerprints are retained in the JSON packet.", "",
             "Review each difference as a hypothesis to investigate, not proof that either player is wrong.", ""]
    for row in packet["decisions"]:
        facts = row["visible_facts"]
        bot = row["bot"]
        ivey = row["recorded_ivey_action"]
        lines.extend([
            f"## {row['decision_number']}. {row['hand_id']} — {facts['street']}", "",
            f"[Source]({row['source']}); {row['evidence_tier']}; {row['format']}.", "",
            f"Ivey holds **{' '.join(facts['hole_cards'])}**, position **{facts['position']}**. "
            f"Board: **{' '.join(facts['board']) or 'not dealt'}**. "
            f"Pot {facts['pot']:,}; facing {facts['to_call']:,}; remaining stack {facts['remaining_stack']:,}; "
            f"{facts['players_active']} active players.", "",
            f"Recorded Ivey action: **{ivey['action']}" + (f" to {ivey['amount']:,}" if ivey.get("action") == "raise" else "") + "**. "
            f"Bot action: **{bot['action']}" + (f" to {bot['amount']:,}" if bot.get("action") == "raise" else "") + "**.", "",
            f"Bot probability assigned to Ivey's action class: {row['bot_probability_of_recorded_action']}. "
            f"Immediate pot-odds threshold: {facts['pot_odds']:.1%}. "
            "This threshold alone omits future betting and range assumptions.", "",
            f"Bot's stated reason: {bot.get('diagnostics', {}).get('reason', 'not provided')}.", "",
        ])
        for label, size in (("Ivey", row["ivey_sizing"]), ("Bot", row["bot_sizing"])):
            if size:
                lines.extend([f"{label} sizing: {size['extra_chips']:,} extra chips; raise beyond a call "
                              f"is {size['raise_over_call_fraction_of_pot_after_call']:.1%} of the pot after calling.", ""])
        lines.append("Review:")
        lines.append("")
        lines.extend(f"- {issue}" for issue in row["review_hypotheses_not_verdicts"])
        lines.extend(["", "Unknown: " + "; ".join(row["unknowns"]) + ".", ""])
        if row["source_limitations"]:
            lines.extend(["Source limitations: " + " ".join(row["source_limitations"]), ""])
    lines.extend(["## Review rubric", ""])
    lines.extend(f"- {item}" for item in packet["rubric"])
    return "\n".join(lines) + "\n"


def write_packet(packet, destination):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(packet_markdown(packet))
    path.with_suffix(".json").write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
