# Qualitative review of Ivey poker videos

## Feasibility

YouTube extraction works for a **small, public, human-reviewed sample**. In a limited proof, `yt-dlp` fetched public metadata and a 720p stream from an official PokerGO upload without cookies or an account; `ffmpeg` produced a few review frames. The first `best[height<=720]` selector failed because the page exposed separate video and audio streams. Selecting the listed 720p video and audio formats explicitly succeeded. English automatic captions were listed, but were not used to identify the hand or its actions. The source video itself is not retained in this repository.

This establishes a practical way to compare selected decisions. It does not establish that arbitrary Ivey videos can be scraped into complete, representative hand histories. Edited video can omit actions, stack graphics can be rounded, and broadcasts can show opponent cards and equity graphics that were not available to Ivey. See the [recorded example](../data/video_reviews/phil_ivey_pokergo_yfjdfpk7e1e/review-notes.md) and [source metadata](../data/video_reviews/phil_ivey_pokergo_yfjdfpk7e1e/metadata.json).

## Review workflow

1. **Pick a direct source.** Record the exact video URL, video ID, title, uploader/channel, channel identity, duration, and whether a public download or caption track was actually available. Prefer official, verified channels. Do not use cookies, accounts, paywalled pages, or access workarounds.
2. **Mark the decision before reading the rest of the hand.** Use the clip offset and a frame just before Ivey acts. Keep the observed action in a separate review note; do not put it in the bot input.
3. **Redact future and private information.** Hide every opponent hole-card panel and equity percentage. Exclude later board cards, later actions, showdown, result banners, and commentary that gives away the answer. Keep only Ivey's cards, the board dealt so far, and public action up to the decision.
4. **Rebuild a public state.** Record hero cards, visible board, position, pot, amount to call, hero stack, effective stack where recoverable, legal actions, and the complete visible action prefix. Tag each field `observed`, `derived`, or `unknown`; do not fill gaps with guesses. For a state the bot cannot represent faithfully, mark the comparison unscorable.
5. **Run the unchanged bot on the frozen state.** Save its action and, if useful, its action mix. The observation must not contain Ivey's observed action, opponent cards, future board, hand outcome, or hand label. Use the repository's [`fast` policy](../pokerbot/fast.py) and protocol fields; a one-hand review is not a training example.
6. **Write a short qualitative review.** Record whether the choices align, differ, or cannot be compared, then explain why under the rubric below. Do not collapse this into an invented similarity score.

| Dimension | Review prompts |
| --- | --- |
| Range and position | What position is explicit? What range does the preceding public action support? Which parts are inferred or missing? |
| Aggression | Who had initiative? Did the choice check, call, lead, raise, or fold, and how did that change the line? |
| Sizing and price | Record bet size, pot, call amount, effective stack, and pot odds when the values are visible. Separate arithmetic from assumptions about opponent range. |
| Reads | Cite an observable action/history cue. Treat private live information and facial-expression interpretations as unknown unless independently documented. |
| Uncertainty | Mark edits, missing actions, rounded stacks, unknown positions, payout context, and any broadcast leakage. |

Use neutral tags such as `aligned`, `different—review the assumptions`, or `unscorable`; keep the explanation in prose. Review a hand/session sample chosen before seeing outcomes if the goal is broader assessment. Highlight clips alone are selection-biased and cannot support a general imitation claim.

## Demonstration: one public PokerGO clip

The [official PokerGO upload, “The Most Confusing Hand Phil Ivey EVER Played!”](https://www.youtube.com/watch?v=YfjDfPk7e1E) is 2:34. The video metadata identifies PokerGO as the channel and reports the upload as public; the verified-channel video result also identifies PokerGO as the uploader. I downloaded only a temporary 720p copy for inspection and retained seven sparse stills with opponent cards and the on-screen equity percentages masked. The time offsets below were checked against extracted frames.

The review is the river decision at **02:05**, when Ivey checks and faces Viera's 1.21M all-in with a 2.62M displayed pot. At **02:15**, the video shows Ivey folding. The visible decision state is Ivey's `K♠ 4♦`, board `Q♦ 4♠ 2♣ 4♣ 3♣`, big blind, about 6.0M behind as rounded on the overlay, and 1.21M to call. The public line in the clip is: preflop raise to 200K and call; flop check, 130K bet and call; turn 300K bet and call; river check, 1.21M shove. The opener's exact position is not explicit in the decision overlay, so the review does not assign one.

On the sanitized state in [`decision-state.json`](../data/video_reviews/phil_ivey_pokergo_yfjdfpk7e1e/decision-state.json), the unchanged `fast` policy chooses **call**. Ivey's observed action is **fold**. This is a useful difference to discuss, not a quality verdict: the call is 1.21M into a pot of 2.62M after the shove, requiring 31.6% equity by pot odds alone. The bot sees trips and applies its generic price/hand-strength heuristic. A human may weigh the preflop-to-river line, an opponent range, or tournament considerations differently; this short clip cannot establish Ivey's private read or the payout context. The broadcast reveals opponent-card/equity graphics before the decision, so those panels are masked and are absent from the state file and the review rationale.

Retained stills are under [`frames/`](../data/video_reviews/phil_ivey_pokergo_yfjdfpk7e1e/frames/). The post-decision fold is recorded as the observed label only; no post-hand cards or result are used to judge the choice.

## Other source candidates

- [PokerStars, “Phil Ivey's EPIC poker READS — Best of Shark Cage”](https://www.youtube.com/watch?v=GvGUFKiZL5Y), 11:44, official verified PokerStars channel. Public metadata and an English automatic-caption track were listed; it is a compilation, so individual hands need separate boundary and completeness checks.
- [PokerStars, “Phil Ivey: The Ultimate Poker Legend | ALL His Shark Cage Hands!”](https://www.youtube.com/watch?v=fcegeGil86M), 1:08:11, official verified PokerStars channel. A longer compilation, useful for hand discovery rather than direct state reconstruction.
- [Jonathan Little — Poker Coaching, “Phil IVEY In A HUGE COOLER With $5,000,000 On The LINE!”](https://www.youtube.com/watch?v=5JezcxfExag), 9:33, public upload on Jonathan Little - Poker Coaching. The [linked PokerCoaching article](https://pokercoaching.com/blog/phil-ivey-coolers-in-a-high-stakes-poker-tournament/) supplies a structured hand narrative, but the video was not used for this demo.
- The previously referenced [Dwan–Ivey clip](https://youtu.be/GnxFohpljqM) is public but its uploader is G4mblers, not an official PokerGO, PokerStars, Triton, or WPT channel. Keep the PHH record as the structured source; do not call that YouTube upload an official source.

## What the method cannot recover

Video can show actions, cards that the broadcast elects to reveal, board, some stack and pot values, seat markers, and visible timing. It cannot reliably supply Ivey's real-time opponent ranges, private reads, unseen table history, exact values hidden by rounding, or missing actions cut from an edit. Captions can help locate dialogue but do not certify card identities, chip amounts, or action order. Public clips are selected for entertainment and are not a representative sample. Keep this as a review aid; do not train or tune the strategy to highlighted actions or outcomes.
