# Campaign template

Use this generic checklist for a multi-lane campaign. Store the concrete
campaign, decisions, project facts, and receipts in the selected fleet home's
ignored local storage.

## Before dispatch

- Confirm the explicit fleet home and read its interface board, goals, journal,
  pending decisions, and relevant local project note.
- Inspect repository status and establish one immutable base commit.
- Define the outcome, scope, write ownership, risks, acceptance checks, and
  irreversible actions that require operator approval.
- Split only independent work. Give each lane one bounded brief, one worktree,
  one result contract, and no overlapping writer.

## Lane contract

- State `DONE means`, the base commit, allowed files, required tests, and the
  structured local result path.
- Require test-first evidence for behavior changes and both supported Python
  interpreters for Fleet changes.
- Keep full evidence in local artifacts; return a concise verdict, exact head,
  test counts, blockers, and follow-ups.

## Review and landing

- Reconcile every required child result and independent review.
- Inspect the actual diff and rerun affected tests; named checks are a floor.
- Refuse unowned files, unexplained blockers, missing evidence, or ambiguous
  external state.
- Land one lane at a time, then run the merged floor from a clean clone.

## Close

- Record throughput and unresolved work in local interface/supervisor state.
- Update generic public docs only for reusable product or design changes.
- Put host quirks, project facts, operator decisions, and lane reports in local
  ignored storage; never commit them to the public Fleet source tree.
