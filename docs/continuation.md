# Acquisition continuation

Recovered on 2026-10-31 from
<t3-thread://v2/d24ed819-cb7a-48e8-bf3c-a5bad185a206/e741da70-f515-404b-95ea-074bfd4a19e6>.
The user moved work here after a workspace routing timeout. The old parent
and its three unfinished workers have been stopped to avoid overlapping edits.

The latest user priority is to collect **thousands of Phil Ivey decisions in
varied contexts before further bot development**. Preserve existing strategy,
model candidates, and evaluation splits. No new accuracy claim is established.
The earlier request to publish the finished project to the `Pokerbot` GitHub
repository remains outstanding; the origin is configured, but the project is
currently untracked and unfinished. Temporary source media must not be included
in a future source commit.

The recovery checkpoint is
[`checkpoint-2026-10-31.json`](../data/acquisition_resume/checkpoint-2026-10-31.json).
It records the strategy/model hashes at takeover. The existing 139 tests pass.
An independent rerun of the combined WPT windows 01–02 replay confirmed 80
recorded decisions with no replay exclusions. These remain pending source and
continuity review; replay is an accounting and legality check.

Resume these disjoint work lanes:

- `data/public_ivey_session_wpt_windows/w03/` and `docs/wpt-window03.md`:
  continue the official WPT source from 01:07:24 to 01:31:24. Canonical H36
  continues from window 02; its next Ivey decision is D04. Preserve conditional
  stack precision and record any game boundary explicitly. An interrupted
  bounded extraction exists under `.work/`; verify its readability before reuse.
- `data/public_ivey_session_hcl_2021_window01/` and `docs/hcl-2021-window01.md`:
  finish the first 24 minutes of actual HCL play. The interrupted worker left
  local working video, redacted samples and three retained evidence images.
  Recover them and its source timing before downloading anything again. No
  completed decision ledger was present at takeover.
- `data/wpt_2021_continuity_audit/` and
  `docs/wpt-2021-continuity-audit.md`: finish the dense window 01 source audit.
  Existing temporary review assets cover hand transitions. The prior worker
  reported no extra hand in 19 inspected boundary windows, an earlier H11 deal
  at 00:50:46.500, and an H12 deal/blind transition by 00:51:23.750. These are
  recovery leads, requiring evidence-backed findings in the completed report.

Checkpoint factual records frequently, distinguish drafts from reviewed rows,
keep labels separate from observations, and retain every routine decision in
the selected intervals. Count canonical decisions once across boundary hands,
derived replays and source corrections. Unknown fields remain unknown; partial
cash-game records are useful acquisition evidence but cannot become exact
benchmark states by silently filling gaps.

## One-hour acquisition sprint

The user set a target of 1,000 usable decisions by **2026-10-31 12:58:41 UTC**.
Coordination is with
<t3-thread://v2/d24ed819-cb7a-48e8-bf3c-a5bad185a206/d2381900-2d92-4d75-a806-3fd99ccf2b50>.
That thread owns bulk structured-source/archive search,
`data/acquisition_sprint_1h/`, `scripts/acquisition_*.py`, and its sprint docs.
Its Luna worker owns `data/acquisition_sprint_1h/report_bulk/` and
`docs/acquisition-sprint-report-bulk.md`. Do not duplicate those searches or edits.
This thread retains the existing WPT/HCL collectors and WPT source integration.

The continuity audit has completed. See
[the audit report](wpt-2021-continuity-audit.md) and
[parent integration](../data/acquisition_resume/wpt-continuity-integration-v1.json).
The parent crosschecked all 20 opening/ending hand stacks, H20's eight tail
actions against window 02, and four audit images. The audit adds no decisions:
its H20 tail already belongs to window 02. It supports a conditional ledger;
full independent action review remains outstanding. Comparison-ready count
remains 45, with 80 WPT replayable decisions pending source action review.
The earlier after-H20 handoff is already covered by window 02; current new
WPT acquisition is window 03, continuing canonical H36.
