# Phil Ivey archive availability and provenance

**Checked:** 2026-10-31. **Scope:** availability, provenance, format, coverage, licensing, and public-source attribution only. This review used eight fixed web searches across three source families. See the [search ledger](../data/archive_discovery/search-ledger.csv) and [source registry](../data/archive_discovery/source-registry.csv).

## Finding

I did not verify a large public machine-readable archive of hand histories that can be attributed to Phil Ivey using primary-source identity evidence. HighStakesDB is the strongest lead for broad historical online coverage: it describes public results dating to 2007, player profiles/results, and replays of tracked hands. Those are publisher claims, not a published hand-count audit. The public pages reviewed did not establish a downloadable raw archive or API, a reuse license, Ivey-specific completeness, official account-name attribution, or whether hole cards are recorded for folds.

The PHH dataset has a public 20.3 GB archive, but its Full Tilt component is an anonymized HandHQ dump and cannot be linked to Ivey. Its public description lists only four selected historical hands; project context identifies the current Dwan–Ivey 2009 material as four decisions. That is a small selected sample, not evidence of representative or broad decision coverage.

## Source assessment

| Source | What is publicly visible | Provenance and coverage limits | Availability decision |
|---|---|---|---|
| [HighStakesDB](https://highstakesdb.com/about-us) | The site says its database has results dating to 2007, covers a majority of online high-stakes games, offers player profiles/results, and replays all hands tracked by its system. | No record counts, denominator, Ivey-specific coverage, raw export/API, data format, or hand-data reuse license were established. The publisher mentions Ivey as a player but does not provide primary-source account-name verification. Hole-card visibility after folds is unspecified. | Public pages/replay service are a promising lead, but a large reusable machine-readable Ivey archive is not verified. |
| Official Full Tilt / online account records | Eight-query budget included three searches for Full Tilt and official government records. No qualifying public primary-source archive or account-name attribution surfaced. | No official alias was confirmed. No account names were inferred, and no anonymized player identity was linked to Ivey. | No qualifying source found in this bounded search; this does not establish that no such official record exists elsewhere. |
| [PHH dataset on GitHub](https://github.com/uoftcprg/phh-dataset) and [Zenodo archive](https://doi.org/10.5281/zenodo.17136841) | The public repository describes hand histories in PHH format. Zenodo lists a 20.3 GB `poker-hand-histories.zip`; the description gives source counts and date span. | The archive description lists 21,605,687 anonymized HandHQ no-limit histories scraped July 1–23, 2009, including 1,299,503 Full Tilt hands, plus four selected historical hands. The anonymized Full Tilt histories do not establish Ivey attribution. Zenodo's displayed license field is blank. GitHub's MIT license text covers the “Software and associated documentation files”; this review did not treat it as a data-content license. | Machine-readable records are publicly listed, but the archive is not verified as a broad Ivey archive and its data reuse status is unclear. No archive or sample was downloaded. |

## PHH schema and hole cards

The [PHH specification](https://phh.readthedocs.io/en/stable/spec.html) describes a TOML-derived text format. Its required fields include variant, antes, blinds/straddles, betting limits, starting stacks, and an ordered action list. Optional fields can record time, venue, players, and hand number. Actions can encode dealt hole cards and board cards, betting/check/call/fold actions, and show/muck actions. The specification allows unknown cards (`??`) and both complete and partial hand histories.

This format can represent private cards without making them known in a public record. The specification therefore cannot answer whether Ivey's cards are present on folds in any candidate archive. I did not inspect any raw candidate hand because no qualifying, clearly licensed and attributable sample was established. Fold-versus-showdown card coverage remains unknown for HighStakesDB and the four selected historical PHH hands.

## Search record and negative findings

The ledger records all eight fixed search strings and their outcomes. The three families were HighStakesDB public records, official Full Tilt/online account records, and public GitHub/data archives. The searches did not produce:

- A public, licensed machine-readable archive with large Ivey-attributed decision coverage.
- A primary official source verifying any Full Tilt or other online account alias for Ivey.
- A documented bulk export/API, Ivey-specific completeness statistic, or reuse license for HighStakesDB.
- Evidence that Ivey's hole cards are known in folded hands rather than only shown at showdown.
- A reason to treat the 45 complete cases selected from public reports, or the four historical PHH decisions, as representative.

The Zenodo listing exposes a 20.3 GB archive, above the 10 MB sample ceiling. No archive or sample was downloaded, no source was authenticated through an account, and no paywall or access control was bypassed. No subscription was purchased and no private rail data was used.

## Sources

- [HighStakesDB home](https://highstakesdb.com/) and [About HighStakesDB](https://highstakesdb.com/about-us)
- [PHH dataset repository](https://github.com/uoftcprg/phh-dataset), [repository LICENSE](https://raw.githubusercontent.com/uoftcprg/phh-dataset/main/LICENSE), and [Zenodo dataset record](https://doi.org/10.5281/zenodo.17136841)
- [PHH format specification](https://phh.readthedocs.io/en/stable/spec.html) and [required fields and action descriptions](https://phh.readthedocs.io/en/stable/required.html)
