# Integration handoff after routing recovery

The recovery thread `f8c6e111-d52f-4f87-b4f5-d5ba1d3a4833` owns replacement Luna
workers for HCL transcription, WPT window 03, and the WPT continuity investigation.
One thread inventory confirmed the original three workers interrupted and those
replacement workers running. Do not restart the interrupted assignments. This is
a coordination snapshot, not a live job-status file.

The old provider run could still edit local files, but a T3 steer to the old worker
failed with `parent_not_active`: “The calling provider no longer owns an active
thread run.” The recovery thread had already requested the old run stop. The final
local integration work below has no ownership overlap with those replacement workers.

Completed integration:

- `scripts/stitch_wpt_windows.py` now recomputes the combined root counts and source
  time range, retains original metadata per source, validates adjacent windows and
  the H20 boundary, and canonicalizes output paths before relativizing evidence
  paths. The latter matters for macOS `/var` and `/private/var` temporary paths.
- `data/public_ivey_session_wpt_derived/windows01-02-v3/` is the current combined
  capture: 80 decisions, 36 observed contexts, four zero-decision walks, 35 completed
  contexts and one truncated H36. All 80 replay; all remain pending source review.
  H20-D01 is counted once and its continuation adds D02–D04.
- `windows01-02-v2/SUPERSEDED.md` flags the earlier draft's stale first-window root
  time range/counts. Do not count v2 and v3 as distinct evidence. The empty failed
  v1 directory was removed. Raw source captures were not changed.
- Nine focused tests pass using `.venv/bin/python -m unittest discover -s tests
  -p 'test_wpt*.py' -v`. No full-suite result is claimed for this integration turn.
- `docs/wpt-window-stitching.md` documents the current capture and remaining source
  limits. `data/acquisition/data-first-milestone-v4.json` updates the acquisition
  snapshot without admitting pending or partial rows.

The candidate lock hash is unchanged. No strategy/model files were edited, no
policy was called, and no agreement score was generated. The data-first priority
and original greater-than-99% objective remain unchanged and unachieved.

Useful continuity lead for the replacement auditor: window 02 records 500/1,000
at H20–H22, 600/1,200 at H23–H33, and 800/1,600 at H34–H36. The observed transition
aliases are H12, H23 and H34. These do not establish an eleven-hand rule or gap-free
official chronology; retain the existing conditional-stack treatment.

Next unassigned source review work includes independent audits of WPT window 02
and Triton day-2 window 01's 13 partial decisions. The Triton continuation window
03:42:50–03:54:50 has not been locked or acquired by this integration turn. Its
initial boundary is canonical H05 with Ivey Tc5c in CO facing Tan Xuan's raise to
12,000, pot 21,000. H05's expected action remains uncounted in window 01.

Subsequent acquisition update: the original goal continuation has now locked
Triton day-2 window 02, 03:42:50–03:54:50, under
`data/public_ivey_session_triton_cgi_2024_day2_window02/selection.json`.
The original parent owns that transcription; do not assign a duplicate collector.
The HCL, WPT w03 and continuity worker ownership is unchanged.

Triton window02 acquisition is now complete: five partial preflop folds, all with
source-visible hero cards, 19 sparse privacy crops, collector validation passed,
zero exact admissions or policy calls. Current records and validation are under
`data/public_ivey_session_triton_cgi_2024_day2_window02/`; temporary media is removed.
H08 cards are 6c3c, established from the retained full-size crop. The video shows a
mandatory-straddle graphic at source 13762 seconds. A full-number chip-count chart
reports Ivey 253000 at 13594 seconds, with actual precision unspecified; it is
retained outside observations. The next unassigned interval starts at 03:54:50,
source 14090; H09 is still between opponents and Ivey has already folded.
The two Triton windows have 18 within-source distinct partial labels; no global
cross-corpus identity certification is claimed. See acquisition snapshot v5.

The original parent has now locked Triton Day2 window03, 03:54:50–04:18:50
(source 14090–15530), in `data/public_ivey_session_triton_cgi_2024_day2_window03/`.
This is disjoint from the recovery Luna assignments. Do not assign a duplicate.
