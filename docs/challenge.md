# No Limit pokerbot challenge research

**Reviewed:** 2026-10-31. Research is based on the official [tournament homepage](https://pokerbot.sequoiacap.com/) and [official rules](https://pokerbot.sequoiacap.com/rules.html). No form was submitted, no one was contacted, and no official match was run.

## Verified tournament specifications

| Area | What the official rules say |
| --- | --- |
| Game format | Six scored tournaments, T1–T6. Each has 10,000 randomly seated, eight-bot sit-and-gos; bots play only other bots, and simulated chips/points have no cash value. Each table ends when one bot has all chips or after 200 hands. Bots start with 2,000 chips; blinds start at 10/20 and rise every 25 hands. The final uses a different poker variant from regionals. Rules §§3.1–3.2, 3.9, 4.1–4.4. |
| Variant | **Not published ahead of the event.** It is announced at the start of each event's build phase and remains confidential until that announcement. Rules §3.2. |
| Bot interface | A Python bot must implement a provided `Agent` interface. The event starter kit is to include an agent template, local simulator, ICM calculator, payout structure, and blind schedule. Rules §3.3. |
| Submission | Teams may submit one bot every five minutes; the most recently accepted submission is active. The rules refer to a submission endpoint but do not publish its URL, client, or request format. Rules §§3.5, 6.1. |
| Runtime | Isolated sandbox with no network access; no OpenAI tools, external APIs, or outside service for live decisions. Decision deadline is 1 ms; maximum file size is 100 MB. An error or timeout folds, or checks if checking is available. Bot state resets at the start of each table; opponents are anonymized. Rules §§3.6–3.8. |
| Scoring | Finish position earns points; the variant-specific point distribution is announced at build time. At 200 hands, remaining points are allocated among survivors by ICM. Team score is average points per table over 10,000 runs, weighted T1×1 through T6×6. Non-divisible table counts are filled with random submitted-bot copies that earn no points. Rules §§4.3–4.7. |
| Build-time help and prep | Astra and Codex may be used during the build phase to write, debug, and refine; public documentation is permitted. AI may not make live decisions for the submitted bot. Rules §§3.4, 7.1, 7.3. The rules prohibit collusion, copying another team's code, platform interference, and misuse of the submission endpoint; they also require code/data rights and prohibit malware, credentials, personal or confidential data. Rules §§6.1, 8.4. |

The public rules do **not** specify the full legal action set, action encoding, observation fields, bet-size constraints, hand/state schema, `Agent` method signature, packaging or launch command, submission protocol, or CPU, memory, operating-system, Python-version, and dependency limits. Only the 1 ms decision deadline, 100 MB file cap, offline sandbox, and table-level state reset are stated publicly.

## Homepage exhibits are simulations, not tournament rules

The homepage labels its poker displays as exhibits and repeatedly calls them “simulated play.” They depict no-limit Hold'em, including an eight-bot table, and show UI labels such as blind, check, call, bet, raise, all-in, and fold (plus “win” as an outcome label). The displays also use example blinds and stacks that differ from the rules' tournament starting values. These are interface/demo examples, not an authoritative action contract or announcement of the tournament variant. The official rules explicitly reserve the variant announcement until build time (§3.2). Source: [homepage exhibits](https://pokerbot.sequoiacap.com/), [rules](https://pokerbot.sequoiacap.com/rules.html).

## Public SDK / technical-spec status

As of the review date, the official site links the rules and privacy notice but does not expose a public starter repository, SDK, downloadable interface definition, or protocol documentation. The rules say the starter kit is provided to teams at the event. Therefore there is no public SDK integration to describe, and it would be unsafe to infer one from the homepage's message-trace exhibit. The actual integration must be taken from the event's `Agent` template and submission instructions when released.

## Unresolved preparation question

The rules explicitly permit public documentation and define the 60-minute build phase, but do not say whether participants may bring prewritten generic code or other pre-event implementation work. The homepage's “from scratch” wording is promotional copy, not a detailed code-preparation policy in the rules. Clarify this with the event gamemaster at kickoff before relying on pre-event code.

## Best next steps

1. Prepare from public poker, Python, and algorithm documentation; keep the hidden variant and all unreleased event details confidential.
2. At kickoff, read the provided interface and simulator first; confirm legal actions, input/output contract, package format, runtime resources, blind schedule, and point distribution from the kit.
3. Build the smallest legal bot, validate it with the local simulator, then profile decisions against the 1 ms limit and verify the timeout/error fallback behavior.
4. Ask the gamemaster to resolve the prewritten-code policy and any runtime or submission details absent from the public rules.
