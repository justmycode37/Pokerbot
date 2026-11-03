"""Tournament-local, public-action adaptations for evolved poker genomes.

The policy keeps a small, resettable profile for anonymous opponents. Profiles
contain only counts of public actions that appeared in observations seen by the
hero. The estimates are deliberately shrunk toward broad priors and only affect
small probability/range adjustments; they are not opponent EV estimates.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from . import fast
from .evolution_strategies import (
    DEFAULT_PARAMS,
    Genome,
    _decision,
    _evolved_postflop,
    _evolved_preflop,
    _mix_salt,
    _raise_target,
)
from .preflop import preflop_equity
from .state import Observation


_MAX_PROFILES = 8
_MAX_ACTIONS_PER_HAND = 512
_MAX_PROFILE_COUNT = 4096
_KNOWN_STREETS = frozenset({"preflop", "flop", "turn", "river"})
_AGGRESSIVE_ACTIONS = frozenset({"raise", "bet", "all-in", "all_in"})
_KNOWN_ACTIONS = frozenset({"fold", "check", "call"}) | _AGGRESSIVE_ACTIONS


@dataclass
class _Profile:
    """Saturating public action counts for one anonymous opponent."""

    actions: int = 0
    folds: int = 0
    checks: int = 0
    calls: int = 0
    raises: int = 0
    large_raises: int = 0
    preflop_actions: int = 0
    preflop_folds: int = 0
    preflop_checks: int = 0
    preflop_calls: int = 0
    preflop_raises: int = 0
    preflop_large_raises: int = 0
    postflop_actions: int = 0
    postflop_folds: int = 0
    postflop_checks: int = 0
    postflop_calls: int = 0
    postflop_raises: int = 0
    preflop_faced_actions: int = 0
    preflop_faced_folds: int = 0
    preflop_faced_calls: int = 0
    postflop_faced_actions: int = 0
    postflop_faced_folds: int = 0
    postflop_faced_calls: int = 0

    def observe(self, street: str, action: str, *, large_raise: bool = False,
                facing_price: bool | None = None) -> None:
        if self.actions >= _MAX_PROFILE_COUNT:
            return
        self.actions += 1
        prefix = "preflop" if street == "preflop" else "postflop"
        setattr(self, f"{prefix}_actions", min(
            _MAX_PROFILE_COUNT, getattr(self, f"{prefix}_actions") + 1,
        ))
        if facing_price is True:
            field = f"{prefix}_faced_actions"
            setattr(self, field, getattr(self, field) + 1)
            if action in {"fold", "call"}:
                field = f"{prefix}_faced_{'folds' if action == 'fold' else 'calls'}"
                setattr(self, field, getattr(self, field) + 1)
        if action in {"fold", "check", "call", "raise"}:
            name = {"fold": "folds", "check": "checks", "call": "calls", "raise": "raises"}[action]
            field = f"{prefix}_{name}"
            setattr(self, field, min(_MAX_PROFILE_COUNT, getattr(self, field) + 1))
        if action == "fold":
            self.folds = min(_MAX_PROFILE_COUNT, self.folds + 1)
        elif action == "check":
            self.checks = min(_MAX_PROFILE_COUNT, self.checks + 1)
        elif action == "call":
            self.calls = min(_MAX_PROFILE_COUNT, self.calls + 1)
        elif action == "raise":
            self.raises = min(_MAX_PROFILE_COUNT, self.raises + 1)
            if large_raise:
                self.large_raises = min(_MAX_PROFILE_COUNT, self.large_raises + 1)
                self.preflop_large_raises = min(
                    _MAX_PROFILE_COUNT, self.preflop_large_raises + 1,
                )

    def _faced_actions(self, street: str) -> int:
        prefix = "preflop" if street == "preflop" else "postflop"
        return getattr(self, f"{prefix}_faced_actions")

    def fold_rate(self, street: str) -> float | None:
        if self._faced_actions(street) < 4:
            return None
        # Beta(2, 2) prior: 4 pseudo-decisions centered on 50% folds.
        prefix = "preflop" if street == "preflop" else "postflop"
        folds = getattr(self, f"{prefix}_faced_folds")
        return (folds + 2.0) / (self._faced_actions(street) + 4.0)

    def call_rate(self, street: str) -> float | None:
        if self._faced_actions(street) < 4:
            return None
        # Only actions taken facing a price enter this response tendency.
        prefix = "preflop" if street == "preflop" else "postflop"
        calls = getattr(self, f"{prefix}_faced_calls")
        return (calls + 2.0) / (self._faced_actions(street) + 4.0)


def _player_key(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if type(value) is int:
        return str(value)
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


class _AdaptivePolicy:
    """A callable policy object whose state belongs to one tournament table."""

    def __init__(self, genome: Genome) -> None:
        if not isinstance(genome, Genome):
            raise TypeError("make_adaptive_policy expects a Genome")
        self._params = dict(DEFAULT_PARAMS)
        self._params.update(genome.params)
        self._salt = _mix_salt(genome.bot_id, 401)
        self._profiles: OrderedDict[str, _Profile] = OrderedDict()
        self._hand_index: int | None = None
        self._seen_actions: set[tuple[int, str, int]] = set()

    def reset(self) -> None:
        """Forget all opponent and hand-deduplication state for a new table."""
        self._profiles.clear()
        self._hand_index = None
        self._seen_actions.clear()

    def _metadata_hand_index(self, raw: Mapping[str, Any]) -> int | None:
        if "hand_index" not in raw:
            return None
        value = raw["hand_index"]
        if type(value) is not int or value < 0:
            raise ValueError("hand_index must be a nonnegative integer")
        return value

    def _advance_hand(self, hand_index: int) -> None:
        if self._hand_index is not None and hand_index < self._hand_index:
            # A new tournament or a restarted hand counter must not inherit a
            # previous table's reads.
            self.reset()
        if self._hand_index != hand_index:
            self._seen_actions.clear()
            self._hand_index = hand_index

    def _profile_for(self, player: str) -> _Profile:
        profile = self._profiles.get(player)
        if profile is not None:
            self._profiles.move_to_end(player)
            return profile
        if len(self._profiles) >= _MAX_PROFILES:
            self._profiles.popitem(last=False)
        profile = _Profile()
        self._profiles[player] = profile
        return profile

    def _learn(self, obs: Observation, hand_index: int | None,
               public_prices: tuple[int | None, ...] = ()) -> None:
        # Without both the tournament hand counter and our anonymous seat ID,
        # history cannot safely be distinguished from a repeat or our own act.
        if hand_index is None or obs.player_id is None:
            return
        self._advance_hand(hand_index)
        hero = _player_key(obs.player_id)
        if hero is None:
            return
        for prefix_position, item in enumerate(obs.history):
            street = item.get("street")
            if not isinstance(street, str) or street not in _KNOWN_STREETS:
                continue
            action = item.get("action")
            if not isinstance(action, str):
                continue
            action = action.lower()
            if action not in _KNOWN_ACTIONS:
                continue
            if action in _AGGRESSIVE_ACTIONS:
                action = "raise"
            player = _player_key(item.get("player"))
            if player is None or player == hero:
                continue
            key = (hand_index, street, prefix_position)
            if key in self._seen_actions:
                continue
            # Keep per-hand memory bounded even on malformed/very long traces.
            if len(self._seen_actions) >= _MAX_ACTIONS_PER_HAND:
                continue
            self._seen_actions.add(key)
            amount = item.get("added", item.get("amount", 0))
            large_raise = (
                street == "preflop"
                and action == "raise"
                and type(amount) is int
                and amount >= 4 * obs.big_blind
            )
            price = public_prices[prefix_position] if prefix_position < len(public_prices) else None
            if type(price) is int:
                facing_price = price > 0
            else:
                # Without price metadata, folds/calls imply a price. An old
                # raise record could be an opening bet, so its context is unknown.
                facing_price = True if action in {"fold", "call"} else False if action == "check" else None
            self._profile_for(player).observe(
                street, action, large_raise=large_raise, facing_price=facing_price,
            )

    def _current_actor_keys(self, obs: Observation, *, include_folded: bool = False,
                            table_players: tuple[str, ...] | None = None) -> list[str]:
        hero = _player_key(obs.player_id)
        actors: set[str] = set(table_players or ())
        actors.discard(hero)
        folded: set[str] = set()
        for item in obs.history:
            player = _player_key(item.get("player"))
            if player is None or player == hero:
                continue
            actors.add(player)
            if str(item.get("action", "")).lower() == "fold":
                folded.add(player)
        if not include_folded:
            actors.difference_update(folded)
        return sorted(actors)

    def _profile_mean(self, players: list[str], method: str, street: str) -> float | None:
        estimates = []
        for player in players:
            profile = self._profiles.get(player)
            if profile is None:
                continue
            estimate = getattr(profile, method)(street)
            if estimate is not None:
                estimates.append(estimate)
        if not estimates:
            return None
        return sum(estimates) / len(estimates)

    def _current_preflop_raiser(self, obs: Observation) -> tuple[_Profile | None, int]:
        hero = _player_key(obs.player_id)
        for item in reversed(obs.history):
            if item.get("street") != "preflop":
                continue
            if str(item.get("action", "")).lower() not in _AGGRESSIVE_ACTIONS:
                continue
            player = _player_key(item.get("player"))
            if player is None or player == hero:
                continue
            amount = item.get("added", item.get("amount", 0))
            size = amount if type(amount) is int and amount > 0 else 0
            return self._profiles.get(player), size
        return None, 0

    def _range_adjustment(self, profile: _Profile | None, amount: int, big_blind: int) -> tuple[float, float]:
        """Return a small public raise-range shift and its confidence signal."""
        if profile is None or profile.preflop_actions < 6:
            return 0.0, 0.0
        # The prior has ten pseudo-actions at a 12% raise rate. It keeps a few
        # observed raises from being mistaken for a permanent loose range.
        raise_rate = (profile.preflop_raises + 1.2) / (profile.preflop_actions + 10.0)
        loose = _clamp((raise_rate - 0.15) / 0.30, 0.0, 1.0)
        rare = _clamp((0.16 - raise_rate) / 0.14, 0.0, 1.0)
        large_now = amount >= 4 * big_blind if amount else False
        # A rare, large observed raise is a caution signal; a small raise does
        # not turn a generally tight player into a loose caller.
        tight_large = rare if large_now else 0.0
        return _clamp(0.075 * loose - 0.055 * tight_large, -0.055, 0.075), max(loose, tight_large)

    @staticmethod
    def _rescale_raise(
        probabilities: Mapping[str, float], target_raise: float,
    ) -> dict[str, float]:
        result = dict(probabilities)
        old_raise = result.get("raise", 0.0)
        remainder = max(0.0, 1.0 - old_raise)
        new_raise = _clamp(target_raise, 0.0, 0.95)
        if remainder <= 0.0:
            result["raise"] = new_raise
            return result
        scale = (1.0 - new_raise) / remainder
        for action in tuple(result):
            if action != "raise":
                result[action] *= scale
        result["raise"] = new_raise
        return result

    def _adaptive_decision(
        self, obs: Observation, original_position: str, *, use_profiles: bool,
        table_players: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        params = self._params
        decision_salt = self._salt + (101 if obs.street == "preflop" else 211 + len(obs.board))
        if obs.street == "preflop":
            decision = _evolved_preflop(obs, params, decision_salt)
        else:
            decision = _evolved_postflop(obs, params, decision_salt)

        details = dict(decision.get("diagnostics", {}))
        probabilities = dict(decision.get("probabilities", {}))
        if not probabilities:
            return decision

        # Exact shared-board ties and provably unbeatable hands retain the
        # evolved policy's no-random-fold handling without profile changes.
        exact = bool(details.get("exact_shared_board_tie") or details.get("exact_unbeatable_hand"))
        if exact:
            return decision

        if obs.street == "preflop":
            equity = preflop_equity(obs.hole_cards)
            threshold = details.get("open_threshold")
            situation = details.get("preflop_situation")
            targets = self._current_actor_keys(obs, table_players=table_players) if use_profiles else []
            fold_rate = self._profile_mean(targets, "fold_rate", "preflop") if use_profiles else None

            # A steal can target only live opponents, including players yet to
            # act when the public roster is supplied. Folded players cannot be
            # pressured and must not influence this adjustment.
            completion_eligible = (
                original_position == "SB"
                and situation in {"unopened", "limped"}
                and fast._raise_count(obs, "preflop") == 0
                and "call" in obs.legal_actions
                and "fold" in obs.legal_actions
                and 0 < obs.to_call <= obs.big_blind
                and obs.to_call <= 0.20 * obs.stack
                and obs.pot_odds <= 0.35
                and threshold is not None
                and equity < float(threshold)
                and equity >= max(0.42, float(threshold) - 0.10)
            )
            if completion_eligible and probabilities.get("call", 0.0) == 0.0:
                edge = equity - (float(threshold) - 0.10)
                call_mix = _clamp(0.22 + 1.5 * edge, 0.15, 0.55)
                passive = probabilities.get("call", 0.0) + probabilities.get("fold", 0.0)
                call_mix = min(passive, call_mix)
                probabilities["call"] = call_mix
                probabilities["fold"] = passive - call_mix
                details["adaptive_sb_completion"] = True
                details["completion_call_probability"] = round(call_mix, 4)

            elif (
                situation == "unopened"
                and not completion_eligible
                and threshold is not None
                and fold_rate is not None
                and fold_rate >= 0.58
                and equity >= float(threshold) - 0.05
                and "raise" in obs.legal_actions
                and "fold" in obs.legal_actions
            ):
                # Low-equity trash stays folded.
                edge = fold_rate - 0.50
                bonus = min(0.16, 0.42 * edge)
                old_raise = probabilities.get("raise", 0.0)
                new_raise = max(old_raise, bonus)
                increase = new_raise - old_raise
                if increase > 0.0:
                    probabilities["raise"] = new_raise
                    probabilities["fold"] = max(0.0, probabilities.get("fold", 0.0) - increase)
                    details["adaptive_steal_probability"] = round(new_raise, 4)

            profile, raise_size = self._current_preflop_raiser(obs) if use_profiles else (None, 0)
            range_shift, confidence = self._range_adjustment(profile, raise_size, obs.big_blind)
            estimated = details.get("estimated_equity_after_range_adjustment")
            cutoff = details.get("continue_threshold")
            if (
                range_shift != 0.0
                and estimated is not None
                and cutoff is not None
                and "call" in obs.legal_actions
                and "fold" in obs.legal_actions
            ):
                base_equity = float(estimated)
                adjusted = _clamp(base_equity + range_shift, 0.0, 1.0)
                cutoff = float(cutoff)
                call_weight = probabilities.get("call", 0.0)
                fold_weight = probabilities.get("fold", 0.0)
                passive = call_weight + fold_weight
                if passive > 0.0 and range_shift > 0.0 and adjusted >= cutoff:
                    margin = adjusted - cutoff
                    target = min(params["call_frequency"], 0.20 + 1.4 * margin)
                    call_weight = max(call_weight, min(passive, target * confidence))
                elif passive > 0.0 and range_shift < 0.0 and call_weight > 0.0:
                    tightness = confidence
                    marginal = _clamp((cutoff + 0.10 - base_equity) / 0.10, 0.0, 1.0)
                    call_weight *= 1.0 - 0.75 * tightness * marginal
                probabilities["call"] = call_weight
                probabilities["fold"] = max(0.0, passive - call_weight)
                details["opponent_range_adjustment"] = round(range_shift, 4)
                details["opponent_adjusted_equity"] = round(adjusted, 4)
                details["opponent_profile_actions"] = profile.actions if profile is not None else 0

        else:
            active = self._current_actor_keys(obs, table_players=table_players) if use_profiles else []
            fold_rate = self._profile_mean(active, "fold_rate", "postflop") if use_profiles else None
            call_rate = self._profile_mean(active, "call_rate", "postflop") if use_profiles else None
            reason = str(details.get("reason", ""))
            old_raise = probabilities.get("raise", 0.0)
            if fold_rate is not None and ("bluff" in reason or reason == "position bluff mix"):
                fold_edge = fold_rate - 0.50
                multiplier = _clamp(1.0 + 1.6 * fold_edge, 0.25, 1.8)
                bonus = max(0.0, fold_edge) * 0.12
                target = min(0.30, old_raise * multiplier + bonus)
                if target != old_raise:
                    probabilities = self._rescale_raise(probabilities, target)
                    details["adaptive_bluff_probability"] = round(target, 4)
            elif call_rate is not None and "value" in reason and old_raise > 0.0:
                # A likely caller makes thin value more attractive; the mix is
                # capped and shrunk so a small sample cannot dominate genes.
                target = old_raise * _clamp(1.0 + 0.60 * (call_rate - 0.50), 0.80, 1.20)
                if target != old_raise:
                    probabilities = self._rescale_raise(probabilities, target)
                    details["adaptive_value_probability"] = round(target, 4)

        # Re-run deterministic public-seed selection after changing a mix.
        # _decision also clamps the raise to legal street-total bounds.
        raise_amount = int(decision.get("raise_amount", decision.get("amount", 0)))
        if probabilities.get("raise", 0) > 0 and raise_amount == 0:
            raise_amount = _raise_target(
                obs, params, preflop=obs.street == "preflop", unopened=True,
                short_stack=(obs.street == "preflop" and
                             (obs.stack + obs.current_bet) / obs.big_blind <= params["short_stack_bb"]),
            )
        return _decision(
            probabilities,
            obs,
            decision_salt,
            raise_amount=raise_amount,
            diagnostics=details,
        )

    def __call__(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        # Observation.from_dict is the protocol boundary: profiles only see its
        # whitelisted public history. No other raw fields are inspected below.
        obs = Observation.from_dict(raw)
        hand_index = self._metadata_hand_index(raw)
        public_prices = []
        for action in raw.get("history", []):
            price = action.get("to_call")
            if "to_call" in action and (type(price) is not int or price < 0):
                raise ValueError("public history to_call must be a nonnegative integer")
            public_prices.append(price)
        table_players = None
        if "table_player_ids" in raw:
            players = raw["table_player_ids"]
            if not isinstance(players, (list, tuple)) or not 2 <= len(players) <= 8:
                raise ValueError("table_player_ids must contain 2 to 8 public player IDs")
            keys = tuple(_player_key(player) for player in players)
            if None in keys or len(set(keys)) != len(keys) or _player_key(obs.player_id) not in keys:
                raise ValueError("table_player_ids must be unique and include hero")
            table_players = keys
        self._learn(obs, hand_index, tuple(public_prices))

        original_position = obs.position
        if obs.table_size == 2 and obs.position == "SB":
            # Match the evolved helper's heads-up SB-as-button convention.
            obs = replace(obs, position="BTN")
        return self._adaptive_decision(
            obs,
            original_position,
            use_profiles=(hand_index is not None and _player_key(obs.player_id) is not None),
            table_players=table_players,
        )


def make_adaptive_policy(genome: Genome) -> _AdaptivePolicy:
    """Return a fresh, resettable adaptive policy for one table.

    The policy accepts an existing bounded ``Genome``. ``family='evolved'``
    genomes are useful before the evolution engine adds the new family; a
    later ``family='adaptive'`` genome uses the same thirteen genes.
    """
    return _AdaptivePolicy(genome)


__all__ = ["make_adaptive_policy"]
