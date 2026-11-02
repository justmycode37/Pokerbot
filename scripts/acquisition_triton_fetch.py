"""Cache read-only queries used by Triton Poker Plus's public web client."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://prod-public-serverless.triton-poker.com/graphql"
QUERY_PATH = ROOT / "data/acquisition_sprint_1h/triton_public/public-query-definitions.json"
HERO_ID = "3970ce21-3d14-4bdc-97ca-98df8220d040"


def query_text(operation, definitions_path=QUERY_PATH):
    definitions = json.loads(Path(definitions_path).read_text())
    if not re.match(r"\s*query\s+", definitions[operation]):
        raise ValueError("only observed public read-only queries are permitted")
    bodies, pending, included = [], [operation], set()
    while pending:
        name = pending.pop(0)
        if name in included:
            continue
        included.add(name)
        body = re.sub(r"\$\{[^}]+\}", "", definitions[name])
        bodies.append(body)
        pending.extend(n for n in re.findall(r"\.\.\.(\w+)", body) if n != "on")
    return "\n".join(bodies)


def _write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fetch(operation, variables, destination, *, timeout=20, attempts=3):
    """Return cached JSON or save an unmodified public GraphQL response.

    No authentication, cookies, account state, introspection, or write operation
    is used. An access-denied response is terminal. Retry only transient errors.
    """
    destination = Path(destination)
    if destination.exists():
        result = json.loads(destination.read_text())
        if result.get("errors"):
            raise ValueError(f"cached GraphQL error: {result['errors']}")
        return result
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"operationName": operation, "query": query_text(operation), "variables": variables}
    _write_json(destination.with_suffix(".request.json"), payload)
    request = Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                      headers={"Content-Type": "application/json", "Origin": "https://tritonpoker.plus"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ValueError("response exceeds bounded 20MB acquisition limit")
            result = json.loads(raw)
            if result.get("errors"):
                _write_json(destination.with_suffix(".error.json"), result)
                raise ValueError(f"public GraphQL query error: {result['errors']}")
            temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
            temporary.write_bytes(raw)
            temporary.replace(destination)
            return result
        except HTTPError as exc:
            detail = exc.read(4000).decode(errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 == attempts:
                _write_json(destination.with_suffix(".error.json"), {"http_status": exc.code, "detail": detail})
                raise
            time.sleep(min(5, 0.5 * 2 ** attempt))
        except (TimeoutError, ConnectionError):
            if attempt + 1 == attempts:
                raise
            time.sleep(0.5 * 2 ** attempt)
    raise RuntimeError("query attempts exhausted")


def payload_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation")
    parser.add_argument("--variables", type=json.loads, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch(args.operation, args.variables, args.output)
    print(json.dumps({"output": str(args.output), "sha256": payload_hash(args.output),
                      "data_fields": list(result.get("data", {}))}))


if __name__ == "__main__":
    main()
