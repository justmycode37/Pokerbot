"""Independent offline card-rank audit, not an imitation-accuracy metric."""
import argparse
import itertools
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokerbot.cards import RANKS, SUITS, _evaluate_normalized


def audit(*, full_five=False, comparisons=5000, seed=713009):
    from pokerkit import StandardHighHand
    deck = tuple(r + s for r in RANKS for s in SUITS)
    rng = random.Random(seed)
    failures = []
    for index in range(comparisons):
        a, b = rng.sample(deck, 7), rng.sample(deck, 7)
        ra, rb = _evaluate_normalized(a), _evaluate_normalized(b)
        pa, pb = StandardHighHand.from_game(''.join(a)), StandardHighHand.from_game(''.join(b))
        ours = (ra > rb) - (ra < rb)
        reference = (pa > pb) - (pa < pb)
        if ours != reference:
            failures.append({'a': a, 'b': b, 'ours': ours, 'pokerkit': reference})
    result = {'seed': seed, 'independent_pokerkit_seven_card_comparisons': comparisons,
              'comparison_failures': failures,
              'scope': 'Hand-rank correctness only; not Ivey action agreement or playing strength.'}
    if full_five:
        start = time.perf_counter()
        actual = Counter(_evaluate_normalized(cards)[0] for cards in itertools.combinations(deck, 5))
        # Category frequencies derived independently from choose/count formulas.
        expected = {8: 10*4, 7: 13*12*4, 6: 13*math.comb(4,3)*12*math.comb(4,2),
                    5: 4*(math.comb(13,5)-10), 4: 10*(4**5-4),
                    3: 13*math.comb(4,3)*math.comb(12,2)*4**2,
                    2: math.comb(13,2)*math.comb(4,2)**2*11*4,
                    1: 13*math.comb(4,2)*math.comb(12,3)*4**3}
        expected[0] = math.comb(52,5)-sum(expected.values())
        result['five_card_exhaustive'] = {'combinations': sum(actual.values()),
            'elapsed_seconds': time.perf_counter()-start, 'actual_categories': dict(actual),
            'expected_categories': expected, 'all_category_counts_match': actual == expected}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-five', action='store_true')
    parser.add_argument('--comparisons', type=int, default=5000)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.comparisons < 1:
        parser.error('comparisons must be positive')
    report = audit(full_five=args.full_five, comparisons=args.comparisons)
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    if report['comparison_failures'] or not report.get('five_card_exhaustive',{}).get('all_category_counts_match',True):
        raise SystemExit(1)
    print(json.dumps({'independent_comparisons':args.comparisons,
                      'five_card_exhaustive':args.full_five,'passed':True}))
