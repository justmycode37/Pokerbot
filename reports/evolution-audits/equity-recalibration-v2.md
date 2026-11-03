# Equity recalibration v2 candidate audit

Protocol: `equity-recalibration-v2-frozen-candidate`. The optional per-player isotonic correction was fixed from grouped OOF predictions before fresh-sample labels were opened.

## Overall fresh public-state assessment

| Estimator | Rows / groups | MAE (descriptive 95% group-bootstrap interval) | RMSE (interval) | Bias (interval) |
|---|---:|---:|---:|---:|
| Pinned v1 raw share | 4200 / 2100 | 0.0769 [0.0743, 0.0797] | 0.0993 [0.0958, 0.1033] | +0.0010 [-0.0030, +0.0053] |
| Optional corrected share | 4200 / 2100 | 0.0524 [0.0499, 0.0550] | 0.0777 [0.0739, 0.0821] | -0.0008 [-0.0039, +0.0028] |

Corrected minus v1: MAE -0.0245 (interval -0.0265 to -0.0225); RMSE -0.0216 (interval -0.0241 to -0.0191); bias -0.0018 (interval -0.0043 to +0.0009).

## By street

| Street | Rows / groups | v1 MAE / RMSE / bias | Corrected MAE / RMSE / bias | Delta MAE / RMSE / bias |
|---|---:|---:|---:|---:|
| flop | 1400 / 700 | 0.0648 / 0.0846 / -0.0246 | 0.0434 / 0.0624 / -0.0197 | -0.0213 / -0.0223 / +0.0049 |
| turn | 1400 / 700 | 0.0731 / 0.0932 / +0.0066 | 0.0511 / 0.0719 / +0.0008 | -0.0220 / -0.0213 / -0.0058 |
| river | 1400 / 700 | 0.0928 / 0.1172 / +0.0211 | 0.0626 / 0.0953 / +0.0166 | -0.0302 / -0.0219 / -0.0045 |

## By active player count

| Players | Rows / groups | v1 MAE / RMSE / bias | Corrected MAE / RMSE / bias | Delta MAE / RMSE / bias |
|---:|---:|---:|---:|---:|
| 2 | 600 / 300 | 0.1128 / 0.1328 / -0.0836 | 0.0642 / 0.0822 / +0.0064 | -0.0485 / -0.0507 / +0.0900 |
| 3 | 600 / 300 | 0.0865 / 0.1102 / -0.0274 | 0.0660 / 0.0933 / -0.0118 | -0.0205 / -0.0169 / +0.0156 |
| 4 | 600 / 300 | 0.0684 / 0.0922 / -0.0192 | 0.0541 / 0.0779 / -0.0208 | -0.0143 / -0.0143 / -0.0016 |
| 5 | 600 / 300 | 0.0614 / 0.0802 / +0.0034 | 0.0467 / 0.0680 / +0.0057 | -0.0147 / -0.0122 / +0.0023 |
| 6 | 600 / 300 | 0.0649 / 0.0871 / +0.0306 | 0.0493 / 0.0788 / +0.0086 | -0.0156 / -0.0084 / -0.0220 |
| 7 | 600 / 300 | 0.0675 / 0.0861 / +0.0418 | 0.0425 / 0.0702 / +0.0008 | -0.0250 / -0.0160 / -0.0410 |
| 8 | 600 / 300 | 0.0769 / 0.0964 / +0.0616 | 0.0439 / 0.0709 / +0.0059 | -0.0330 / -0.0255 / -0.0557 |

## Interpretation and limits

The fresh assessment used 2,100 legal public states, 4,200 independent Monte Carlo label rows, and 4,300,800 joint reference deals. Each state contributed two 1,024-trial labels; states were balanced across three streets and seven active-player counts.

Bootstrap intervals resample canonical public-state groups and retain both replicate labels. They describe this sampled public-state set and Monte Carlo process; they are not a promotion or 95% superiority claim. The reference target is uniform-random-opponent showdown share, not action EV or playing strength.

This artifact is a separate optional research candidate. It does not change or replace v1 and was not evaluated in poker matches. Any later policy use requires separate review and future full-match evaluation. No SDK or runtime claim follows from these measurements.

The full 21 street/player strata, per-stratum bootstrap intervals, provenance, hashes, and fold audit are in the JSON. Row-level scored outputs are in the CSV. The MAE comparison with group-bootstrap intervals is shown in [the chart](equity-recalibration-v2-chart.html).

## Integrity and data flow

- v1 model SHA-256: `7dd0457e02c5bf5d3e3d1c9f06b4f3d043c7343a068092b23c3c3bb6ad6e48fd`.
- Original labels SHA-256: `b2259261a9be67ae20619f4aac860a63f7b0e9356a6656522cf97fb6adc4a9cb`; only 33,592 rows in 16,783 saved training groups supplied labels to the OOF fit.
- OOF folds: three; fold assignment SHA-256 `a6b590a209b51a1586f2a3aede0d756eddc30bddc13e8e3ded5e3e7f044e7910`; all group-disjointness checks passed.
- Fresh test states were frozen before labeling and disjoint from all original public-state groups; sample states SHA-256 `500e5ca19635631cd372a9d5926e6d5c1620a24d2a56ef2739fb9c8bd6c93eec`.
- Sealed correction candidate SHA-256 `d8321112b47ed593d61f036d40ca9a3a29869ff3a02d04dd735f055d7ea734d3`; portable transform SHA-256 `64b4efb1ef361d7b631206f8707815868186336f3030409b08f70633492934d6`.
- Original calibration share values were not consumed as targets, passed to the trainer row parser, scored, fitted, or used for choices; public card fields were used only to reconstruct the freeze groups before non-training rows were excluded. Match validation, confirmation, paired outcomes, and match generation were not read or used.
