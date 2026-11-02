# CI portability correction

The initial GitHub CI run passed all 186 unit tests, then found two legacy
absolute source paths in immutable admission batch 001. The local verification
copy had still been able to read those original collector paths.

The ledger verifier now relocates legacy paths under the current checkout's
data directory, rejects paths outside the checkout, includes the two legacy
capture/request fixtures omitted by the original allowlist, and preserves admission
bytes and hashes. Two regression tests cover relocation, path rejection, and
confinement of every source-byte read in the real 606-decision ledger. The
updated local suite passes 188 tests; GitHub CI repeats all checks.
