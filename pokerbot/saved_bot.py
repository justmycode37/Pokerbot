"""Run the saved, self-contained Ivey transfer checkpoint on JSON observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.resources import files

from . import preflop, transfer_policy


def _resource(name):
    return files("pokerbot").joinpath("models", name).read_bytes()


def load_bot():
    """Load the versioned model and equity table once, then return a callable."""
    manifest = json.loads(_resource("ivey-transfer-v1-manifest.json"))
    payloads = {}
    for name, expected in manifest["bundled_files_sha256"].items():
        payload = _resource(name)
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"saved checkpoint checksum mismatch: {name}")
        payloads[name] = payload
    table = json.loads(payloads["preflop-equity-v1.json"])
    equities = table.get("equity_vs_one_random_opponent")
    if table.get("variant") != "no-limit-texas-holdem" or not isinstance(equities, dict) or len(equities) != 169:
        raise ValueError("saved checkpoint equity table is invalid")
    # The frozen preflop module supports a source-checkout table and an analytic
    # fallback. Prime its table cache with this checkpoint's packaged resource
    # so wheel installs reproduce the same policy without checkout data files.
    preflop._EQUITIES = {name: float(value) for name, value in equities.items()}
    model = json.loads(payloads["ivey-transfer-v1.json"])
    transfer_policy._validate_model(model)
    return lambda raw: transfer_policy.decide(raw, model)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("decide", "profile"), nargs="?", default="decide")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        bot = load_bot()
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.command == "profile":
        if args.count < 4:
            parser.error("count must be at least four")
        from .__main__ import profile_policy, write_result
        result = profile_policy(bot, count=args.count)
        result["checkpoint"] = "ivey-transfer-v1"
        write_result(result, args.output)
        return 0
    errors = 0
    for index, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue
        try:
            result = bot(json.loads(line))
        except (ValueError, TypeError, KeyError) as exc:
            result = {"error": str(exc), "line": index}
            errors += 1
        print(json.dumps(result, allow_nan=False), flush=True)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
