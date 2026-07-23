# Project: claude-oracle (cc-oracle)

Dir: `C:\proga\claude-oracle`. Public marketplace plugin (`github.com/exPardus/cc-oracle`), stdlib-only Python, py3.9 floor. Stop-hook "derangement detector": scans session transcript for stuck-markers, can block a stop to force an oracle consult. Trunk `main`.

## Why it's a good fleet target
Only external candidate (2026-07-23 council audit) that is simultaneously: git-tracked, clean-tree, secret-free, no live processes, no deploy path. Worst-case total fence failure costs nothing external. First fleet campaign here 2026-07-23 (overnight dogfood).

## Spawning workers here — rules that earned their place
- **NEVER let a worker install/enable the plugin globally** (no `claude plugin install`, no marketplace-add, no `~/.claude` edits) — hooks would fire in EVERY session on the machine incl. fleet workers (the D7 injection sin). Hard-deny `Bash(claude plugin:*)` in the worktree allowlist.
- **NEVER push** — public marketplace repo; a broken overnight push ships to anyone installing. Hard-deny `Bash(git push:*)`; operator pushes after review.
- Live hook testing ONLY via headless `claude -p --settings <scratch>/oracle-smoke-settings.json` (pattern demonstrated in `docs/plans/2026-07-23-oracle-plugin.md`).
- Suite is fast; run on `python` AND `py -3.10`; floor-guard test in `tests/test_config.py` enforces 3.9 grammar.

## Domain traps (all bitten or nearly-bitten 2026-07-23)
- **Marker matching**: unanchored idiom substrings false-block benign text (10/11 fabricated benign completions blocked pre-fix). Doctrine: miss beats false-positive; anchors are first-person + closed intensifier allowlist (NOT `\w+` — negation must break adjacency).
- **`CLAUDE_PLUGIN_DATA` is untrusted**: foreign plugins' env leaks in; basename allowlist is derived from the manifest JSONs at import — the marketplace name is `cc-oracle`, NOT `claude-oracle` (a stale plan-doc value shipped a SPURIOUS-FIX whose own test encoded the same wrong name).
- **Prune sweeps in user-configurable `state_dir`**: age-based deletion must allowlist the hook's own filename patterns (`^[0-9a-f]{16}\.json$`, `^tmp*.tmp$`) — anything else deletes user files.
- Hook must never crash a Stop: `main()` catch-all exits 0; manifest reads fail-open to hardcoded names.

## State at 2026-07-23 close
`mf/integration` (local, UNPUSHED): both feature branches merged + 2 fix waves, 147/0 both interpreters, hostile-review final gate MERGE VERDICT sound. Operator to merge→main and push.
