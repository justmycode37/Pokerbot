# Source audit and admission of report batch 2

An independent Luna review checked the 22 decision snapshots against the
CardPlayer issue and matchup page, with PokerNews event cross-checks. It found
one numeric history error affecting two snapshots and two provenance wording
issues. The other stated chip ledgers and action labels reconciled.

Admission applies to the separately reconstructed records, not the unchanged
raw capture. `import_report_batch2.py` fixes Heath's live raise payment to
1,600,000. It marks reconstructed history as derived, including the small-blind
fold required by the three-player action order and the Ponakovs shove target
derived from exact starting chips. The Heath hand has no unknown earlier-position
folds: only three players remain. The raw capture's prose claiming otherwise
is superseded by these notes.

All four WSOP hands are one source-issue cluster and one event/session group.
They are not four independently selected test groups. Jeju is the second group.
The source review relied on searchable PDF content and report cross-checks;
PDF screenshot calls did not provide rendered diagrams. Card/stack transcription
therefore retains the limits of those published sources.

The parent additionally checked the original PDF's explicit three-player
description and the Jeju seven-player report. Engine replay supplies table sizes
of three, two and seven as applicable, avoiding the protocol's fallback table
size. See [normalization notes](report-batch2-normalization.md) for auxiliary
folded-stack handling, heads-up forced-bet reversal and replay tests.

All 22 derived observations are admitted for a descriptive, frozen-candidate
comparison, with the rounded-source all-ins explicitly derived from the exact
ledger. Neither legal replay nor source agreement establishes representative
coverage of Ivey's decisions. The requested greater-than-99% target remains
unverified.
