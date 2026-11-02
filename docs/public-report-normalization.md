# Corrections made during independent normalization

The raw acquisition file remains unchanged in `data/public_ivey_reports/`.
`pokerbot.public_reports` normalizes its six snapshots and derives two further
calls from the complete preflop betting lines, producing eight snapshots.
Expected actions remain outside observations.

- The Sochi snapshots put Ivey last after the other players checked.
  `players_to_act` is therefore zero before he chooses a new bet; it does not
  count players who would respond if he bet. The original acquisition counted
  those potential responses.
- In the five-handed Bonomo report, action folds to Ivey in the cutoff. Four
  players are still active when he acts; five is the number dealt, not the
  number still in the pot. The unchanged forced-bet pot corroborates no limp.
- The Haxton final-hand line has Ivey complete to 160,000 before Haxton shoves
  to 2,180,000. Ivey then owes **2,020,000**, not 2,100,000. The latter derived
  `added` field in the acquisition forgot the completed 80,000. The normalized
  call state is computed from street totals and does not use that field.
- The Quoss line gives a 530,000 Ivey raise and a 1,410,000 Quoss all-in. The
  derived Ivey call is 880,000 into 2,070,000, with 2,180,000 behind before
  calling. The omitted BB fold is implied by action order and the reported
  heads-up all-in. Both additional call records expose only the public prefix.

The 2014 Aussie Millions hands share an event-level session group and cannot
be separated across fitting and evaluation. Exact table size for the Sochi
hand is not supplied; its required postflop active-player counts and betting
facts are known, while its coarse `MP` position mapping stays disclosed. The
Bonomo record remains preflop-only because later source amounts conflict.
