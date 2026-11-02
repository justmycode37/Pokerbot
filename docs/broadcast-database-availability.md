# Supplemental broadcast database check

The seven-query [availability ledger](../data/archive_discovery_broadcast/availability.json) investigated structured alternatives to manual transcription. No hand-level records were acquired in this pass.

[Highroll Poker's FAQ](https://highrollpoker.com/faq) describes a tracker for televised cash-game results. Its [Ivey profile](https://highrollpoker.com/tracker/players/1133?page=1&perPage=10&sort=%5B%22name.asc%22%5D&tab=breakdownByLivestream) lists 102 episodes and approximately 300 hours, with aggregate statistics by show. These figures are provider claims about its coverage, not verified hours of accessible video or decision rows. The sampled episode pages expose results and VPIP/PFR summaries; this check did not verify a hand-action, card or raw hand-history export.

Two episode-to-video links were checked using public YouTube metadata:

- [HSP S6E1's indexed session](https://highrollpoker.com/tracker/sessions/2448?page=1&perPage=10&sort=%5B%22netWinnings.desc%22%5D) links to an official [PokerGO Season 6 highlights compilation](https://www.youtube.com/watch?v=qCcG4qUXb4M), lasting 23 minutes 46 seconds. It is not the complete episode or a continuous session.
- [HSP S9E1's indexed session](https://highrollpoker.com/tracker/sessions/1228?page=1&perPage=10&sort=%5B%22netWinnings.desc%22%5D) links to a [seven-second Highroll placeholder](https://www.youtube.com/watch?v=AT9YOBbM6k0) stating that the session video is unavailable on YouTube. It contains no poker play.

The profile's episode-history requests were inaccessible to the web tool, and a direct public-page fetch returned HTTP 403. No access workaround was attempted. TrackingPoker's public pages timed out; that does not establish whether the service has Ivey coverage or usable records.

The episode index remains a discovery lead. Aggregate hours, percentages, episode names and placeholder videos add zero decisions to the corpus. The current collection route continues through attributable public broadcasts with source-level transcription and review.
