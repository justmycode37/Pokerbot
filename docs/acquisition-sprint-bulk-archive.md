# Acquisition sprint: bulk archive and replayer lane

**Checked:** 2026-10-31. **Scope:** existing raw hand batches and public replayer payloads. This lane made no bot, model, split, importer, or scoring changes.

## Result

No new raw Ivey hand history or complete public replay action payload was acquired, so this lane adds **0 usable decisions** toward the 1,000-decision target. I found a public archived HighStakesDB index with 24 partial hand candidates, but its individual replay pages depend on action data that is not preserved in the archive. Three indexed NLHE candidates show cards attributed to Polarizing; none exposes the action sequence, board, stacks, or forced bets needed to count a decision.

The structured index and its source hash are recorded in [highstakesdb-polarizing-2013-05-10-index.json](../data/acquisition_sprint_1h/bulk_archive/highstakesdb-polarizing-2013-05-10-index.json). The current checkpoint is [progress.json](../data/acquisition_sprint_1h/bulk_archive/progress.json).

## Archived HighStakesDB sample

The archived HighStakesDB page is a Full Tilt player hand index for `Polarizing`, sorted by pot size. Its paginator shows page 1 of 19; I inspected only page 1. It lists 24 replay IDs: four NLHE and 20 PLO. Three NLHE rows display two profile-player card images; the fourth has no cards listed. This is a selected high-pot index and not representative coverage.

| Replay ID | Date shown | Game / stakes shown | Polarizing cards shown | Pot shown |
|---|---|---|---|---:|
| 1230935 | 2013-01-31 06:57 | NLHE, $300/$600 | Td Ts | $135,597 |
| 1230922 | 2013-01-31 06:40 | NLHE, $300/$600 | Td Jh | $131,997 |
| 1230896 | 2013-01-31 06:13 | NLHE, $300/$600 | Ah 7c | $121,798 |
| 1243603 | 2013-02-22 01:33 | NLHE, $400/$800 | Not listed | $82,763 |

The archive snapshots for the first three replay pages contain an HTML page with title, pot/game metadata, and a `TexasReplayer.swf` embed passing the hand ID. They do not contain the actions. The SHA-256 values of those archived pages are:

- `1230935`: `bca0ad036e013998310e1b2430af82c4d335f80889688aa67bef1b9fc35cb033`
- `1230922`: `d5f4aa7993815d543e63d1caa312b592cefee049a491a9742064df98c1d77b49`
- `1230896`: `1978e1d714ff3752ee7872508453a21c69eb1a739135d783141851cef7bacb9b`

Later HighStakesDB replay popups embed `rePlayer.html?handid=...`; that page requests `/replayer/gethand-json.ashx?handid=...`. The relevant JSON responses do not appear in Wayback CDX for the sampled hand IDs, and a standard public GET to the current original endpoint returned HTTP 404. No access-control bypass was attempted. Two 2014 replay popups linked from the archived Polarizing profile are Omaha PL $300/$600, so they are excluded from NLHE candidates; their popup page hashes and details are in the checkpoint.

Card Player reports that it obtained a Full Tilt email identifying `Polarizing` as Phil Ivey's changed screen name. This is the identity evidence used for the archived index candidates: [Card Player, Dec. 12, 2012](https://www.cardplayer.com/poker-news/14617-phil-ivey-returns-to-full-tilt-poker-cash-games).

## Strongest bulk export lead: HHDealer

HHDealer currently advertises **780,000 FullTiltPoker high-stakes hands**, labelled “NL5K and above,” from mid-2013 to mid-2015 for **$80**. The offer names Phil Ivey but provides no Ivey alias, per-player count, variant split, limit breakdown, or known-holecard coverage. Its page directs interested buyers to contact HHDealer. The FAQ says hand histories are sent as ZIP files by email, but does not specify the format or contents of this particular package. The offer and FAQ are public at [HHDealer promotions](https://hhdealer.net/promotions.php) and [HHDealer FAQ](https://hhdealer.net/faq.php).

I did not purchase, register, or contact anyone. The only public sample surfaced through the replay pages. HHDealer's featured list includes `KidPoker vs philivey2694`, 12 PokerStars NLHE hands from March 2011, but PokerNews identifies `philivey2694` as Isaac Haxton, not Phil Ivey ([PokerNews](https://www.pokernews.com/news/2012/10/isaac-haxton-joins-team-pokerstars-online-13619.htm)). This is excluded as a false-positive Ivey alias. The other listed historic Full Tilt sample is Isildur1 vs WCGRider, 285 NLHE hands from October 2013, not Ivey. The public player-hands page says it highlights only selected high-pot hands, not all players or all hands. No Ivey-attributed raw public sample was found.

## Poker Hand Scout and original Isildur1 batch

PokerSoftware reports that Poker Hand Scout supplied it with 7,780 $500/$1,000 heads-up NLHE hands for Isildur1, alongside Omaha histories. It provides no raw file, download URL, replay ID, or batch format. The article's Poker Hand Scout link now redirects to PokerSoftware's generic categories. A separate 2010 PokerSoftware article says Poker Hand Scout once offered generic free sample files from its FAQ, but that page and download were not publicly recoverable. The reported batch is Isildur1's, not an Ivey-attributed batch; the article's written Ivey hand report is not treated as raw data here. Sources: [Isildur1 article](https://www.pokersoftware.com/articles/2009/11/isildur1-poker-hand-histories-and-vital-stats.html) and [Poker Hand Scout sample announcement](https://www.pokersoftware.com/articles/2010/01/poker-hand-scout-offering-free-hand-histories.html).

## Existing PHH candidate found, not duplicated

The upstream [PHH dataset](https://github.com/uoftcprg/phh-dataset) has a small `dwan-ivey-2009.phh` historical hand. It is already present in the workspace at `data/ivey/dwan-ivey-2009.phh` and is byte-identical to the upstream file at commit `e47fbd5816372360bade4de5d712346fe1bb70f6` (local SHA-256 `bfbdd09ac816d681a5262a6ca9869ab186d5533fedf7ef35f62a318dd411b24f`). I did not copy it into this lane.

That PHH record is a televised Full Tilt Million Dollar Cash Game S4E12 NLHE hand, not a verified online Full Tilt log. It contains Ivey's `Ac2d`, Dwan's `7h6h`, the complete recorded action prefix through the river, starting stacks, antes and blinds. Antonius's folded cards are unknown. It has four Ivey decision points and no explicit hand ID; its source video is [GnxFohpljqM](https://youtu.be/GnxFohpljqM). It remains a hero-complete candidate **pending review**, and it contributes no new decisions from this lane because it was already in the workspace.

## Blocker and handoff

After ten minutes, no live bulk data source or archived action payload was available without purchase, contact, or a missing replay API. A final bounded search for downloadable Polarizing/Phil Ivey Full Tilt histories and public replay payloads found no distinct raw sample; it reconfirmed the paid HHDealer lead and the already-present televised PHH candidate. The strongest concrete export lead remains HHDealer's $80 package. The public archive index is saved as partial metadata only; unknown action, board, stack, and forced-bet fields remain null. The index does not establish known-card coverage or completeness, and none of its 24 candidates is counted as a usable decision.
