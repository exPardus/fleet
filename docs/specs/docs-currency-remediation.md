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
that the repair is an ancestor of HEAD, that the receipt in both HEAD and the working copy remains byte-identical
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

The views-doctrine detector retains its original conservative AST graph:
every branch and statement in each reachable source function is inspected.
Dedicated `_cmd_status_view` and `_sup_guard_view` functions contain only the
existing read-only behavior; mutation bodies are separate. Public CLI routers
are structurally pinned to direct `--stale-ok` / `--do` dispatch and tested at
both flag values, so an unguarded prelude or swapped destination is rejected.
No cached Python argument facts or partial abstract interpreter are used.
OperationJournal, host startup and reconciliation remain prohibited on view
roots, including nested, annotated, setter or starred-call mutations.
