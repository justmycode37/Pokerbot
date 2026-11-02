# Ivey 2009 Hand 175: bounded stack evidence

## Scope and selection

This is a source precision follow-up for WSOP Main Event Hand 175, Phil Ivey A-Ks first to act seven-handed against Darvin Moon. The hand outcome is already known; this evidence is outcome-selected and cannot support a representative bot-accuracy claim.

I ran one fixed search batch before reviewing any footage or caption content, using these queries in order:

1. `site:youtube.com WSOP 2009 November Nine hand 175 Ivey Moon PokerGO`
2. `site:youtube.com PokerNews 2009 Ivey Moon hand 175 WSOP final table`
3. `site:pokergo.com 2009 Ivey Moon hand 175 WSOP November Nine`
4. `site:wsop.com 2009 Ivey Moon hand 175 final table`

The first metadata-eligible official clip in the returned results was locked before review. It is the PokerGO YouTube video [2009 WSOP Main Event - Top 5 Hands](https://www.youtube.com/watch?v=af0YJSnZMOs), uploaded `2020-07-22 09:00:02 -07:00`, duration 769 seconds. The [official WSOP article](https://www.wsop.com/news/wsop-highlights-powered-by-pokergo-2009-wsop-main-event-top-5-hands/) links the video and identifies Ivey's seventh-place hand against Moon; its displayed publication time is `Apr 26 2021 09:12 AM EST`. The video is unlisted on YouTube but publicly playable from that official link without an account. One eligible clip was found; the remaining two lock slots were not filled, and no further query was added.

## Evidence from the locked clip

All timestamps below are elapsed time in the YouTube clip, not the original broadcast clock.

| Clip time | Source observation | Precision and limits |
| --- | --- | --- |
| 00:04:08.4 | The broadcast graphic reads `BLINDS 300 / 600k`. | No ante or stack amount appears in the sampled crop. |
| 00:04:08.720 | Auto-generated English caption: “come all in and he does move all in for” | Narration confirms the all-in declaration, with no amount in this segment. |
| 00:04:11.2 | Auto-generated English caption: “about six and a half million” | Approximate narration only; it is not an exact numeric shove. |
| 00:04:11.2 | The graphic reads `IVEY / ALL IN`; a separate display reads `POT 7,875,000`. | The graphic does not state a numeric shove amount. `7,875,000` is labeled as the pot, not as Ivey's street target or remaining stack. |

The retained artifacts are cropped to the relevant broadcast labels: [blinds crop](../data/ivey_2009_hand175_video/evidence/clip_00408_blinds.jpg), [all-in crop](../data/ivey_2009_hand175_video/evidence/clip_00411_all-in-label.jpg), and [pot crop](../data/ivey_2009_hand175_video/evidence/clip_00411_pot.jpg). No full video is retained.

The pot value would reconcile to a 6,450,000 shove only if seven individual 75,000 antes and both blinds were already included. The clip does not show those ante postings or the pre-action pot, so that arithmetic remains conditional and is not admitted as an observed exact amount. The broadcast also does not establish whether the 6,525,000 header stack is pre-ante or net of the ante.

## Disposition

The new primary clip supports only a rounded narration of “about six and a half million,” an all-in declaration, the 300,000/600,000 blind graphic, and an exact displayed pot total of 7,875,000. It does not settle ante posting or predecision stack timing. Leave `numeric_expected_shove` null and retain the existing partial/no-exact-admission status. Existing references remain [CardPlayer](https://www.cardplayer.com/hand-matchups/1064) and [PokerNews](https://www.pokernews.com/tours/wsop/wsop-2009-final-table/november-nine/post.125257.htm).
