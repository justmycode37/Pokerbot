"""Score a locked candidate on new standardized source records, without fitting."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot.prospective import score_prospective


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('records', help='JSON list, or object with records, after source validation')
    p.add_argument('--lock', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    destination = Path(a.output)
    if destination.exists():
        p.error('output already exists; retain the original evaluation')
    data = json.loads(Path(a.records).read_text())
    rows = data['records'] if isinstance(data, dict) else data
    lock = json.loads(Path(a.lock).read_text())
    result = score_prospective(rows, lock)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as fp:
        json.dump(result, fp, indent=2, sort_keys=True, allow_nan=False)
        fp.write('\n')
    print(json.dumps({k: result[k] for k in ('decision_count','hand_count','source_group_count')}))
