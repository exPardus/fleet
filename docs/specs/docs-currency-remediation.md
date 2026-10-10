# Forward documentation repair receipts

The last20 non-merge commit docs-currency gate remains forward-only from its
original adoption base. Missing documentation is a failure; neither a later
unrelated docs commit nor a bare historical SHA exemption repairs it. Shared
ancestry is not rewritten to add an old trailer.

A reviewed forward repair may add a live owning document and one JSON receipt
at `docs/currency-remediations/<original-full-commit>.json` in the same commit.
The receipt has schema1, `code_commit`, the exact sorted `code_paths` changed
under direct `bin/*.py`, and `documents` mapping live docs paths to SHA256 of
their exact bytes. The introducing commit is derived from Git's addition
history, avoiding a circular self-commit reference.

The gate verifies that original code is an ancestor of the introducing repair,
that the repair is an ancestor of HEAD, that the receipt remains byte-identical
to its introduction, and that each pinned doc was changed in that introducing
commit. Docs must be tracked and live, outside archive and receipt directories;
HEAD, introducing commit and working bytes must all match the digest. Missing,
altered, wrongly scoped or unrelated receipts fail. Future code omissions
remain failures; a receipt never covers a new commit automatically.

This is evidence of a scoped forward repair, not proof of prose correctness.
An independent reviewer must assess whether the document actually covers the
original behavior and current limitations before merge. Keep the original
omission and its exact source identity visible in that document. If a pinned
document needs revision, replace the forward repair through a separately
reviewed design rather than silently updating its frozen receipt.

The views-doctrine detector specializes the read-only CLI variants:
`status --stale-ok` and `sup-guard` without `--do`. It propagates only known
argument fields and constants; unknown/rebound arguments and unknown branches
stay conservative. Mutating journal construction, host startup and host
reconciliation remain forbidden on the read-only execution paths. Tests retain
unguarded-call, unknown-branch, rebinding and mutating-variant controls.
