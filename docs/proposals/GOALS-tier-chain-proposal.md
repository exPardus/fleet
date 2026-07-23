# Proposal: add the tier-policy block to `supervisor/GOALS.md`

**Owner: operator.** The three-tier build slice (`tt/build-slice`) implemented the
role→tier→model **resolver** (`read_tier_policy` / `resolve_model_for_role` in
`bin/fleet.py`), per `docs/specs/three-tier-command.md` §3.1/§3.3/§3.5. The
resolver **reads** its policy from `supervisor/GOALS.md`; it does **not** write
GOALS (operator-owned, never edited by the build — `tt-build` task rule). Until
the operator adds the block below, the resolver applies its **documented
defaults** and omits `--model` (§3.3(d): let the namespace daemon's default
govern rather than invent a model id).

## Why this lives in GOALS, not in code

§3.3 fixes where each piece lives: the **role → tier alias** mapping is
fleet-level policy and belongs in `supervisor/GOALS.md` (git-tracked,
human-editable, operator-owned), **not** as a constant in a code path. The
tier → concrete model step lives *below* fleet, in the provider daemon's env
(`ANTHROPIC_DEFAULT_*_MODEL`); fleet only emits the tier alias. `bin/fleet.py`
carries **no** model id (§3.2 receipt: `grep -c "claude-opus\|claude-sonnet\|
claude-haiku\|claude-fable" bin/fleet.py` → 0), and this proposal keeps it that
way — the aliases below (`opus`, `sonnet`) are the CLI's tier aliases, resolved
by the daemon, not model ids.

## The block to add (verbatim)

Paste this anywhere in `supervisor/GOALS.md`. It is an HTML comment — invisible
in rendered markdown, greppable in source, parsed by `read_tier_policy`:

```
<!-- fleet-tier-policy
supervisor-tier-chain: top, second
worker-tiers: second, third
tier-model: top=opus, second=opus, third=sonnet
-->
```

- `supervisor-tier-chain: top, second` — the supervisor **prefers the top tier
  and falls back to the second** when the top tier's usage limit is hit (§3.5).
  A length-1 chain is legal (no fallback; a single-model provider collapses to
  it). Today's illustrative Anthropic resolution is `[Fable 5, Opus 4.8]` — but
  those are examples, never normative; you set the aliases.
- `worker-tiers: second, third` — workers are **Opus or Sonnet, never Haiku**
  (§3.4; Haiku is a subagent *inside* a worker, never a worker). On a
  single-model provider this rule is moot.
- `tier-model: top=opus, second=opus, third=sonnet` — the tier → `--model`
  alias map for **your active namespace**. Fleet passes the resolved alias as
  `--model`; the daemon resolves it to a concrete model. Leave a tier out to
  make the resolver **omit** `--model` for it (the daemon default governs).

## What the resolver does once the block is present

- `resolve_model_for_role("supervisor")` → the alias for `supervisor-tier-chain[0]`
  (the preferred tier) — the default `--model` `sup-spawn` uses when the
  operator does not pass one explicitly.
- `resolve_model_for_role("worker")` → the alias for `worker-tiers[0]` (a
  starting suggestion; the supervisor still overrides per-spawn).
- `resolve_model_for_role("interface")` → advisory only; **fleet never launches
  the interface tier** (§3.1), so this is a note, not a dispatch.

Nothing here changes the daemon-level tier→model resolution (§3.3): a
cross-provider fleet still needs separate `CLAUDE_CONFIG_DIR` namespaces, one
daemon each, and each namespace's daemon resolves the same alias to its own
model.
