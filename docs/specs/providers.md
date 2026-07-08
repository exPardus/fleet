# Spec: Provider profiles — proxies & alternate AI backends

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md principles. Independent of watchtower; can be specced/built any time after Phase 1.5 (needs `fleet init` machinery).

## Goal

Run any worker against a non-default backend: an API proxy (LiteLLM/self-hosted gateway exposing an Anthropic-compatible API), a different Anthropic account/region, Bedrock/Vertex, or any provider reachable through such a proxy — chosen per worker at spawn, without touching global machine config.

## Scope

In: named provider profiles, per-worker env injection at turn launch AND attach, registry/provenance, doctor checks, cost-accounting caveats, and the **token-ceiling kernel as the functional spend bound behind proxies** (see F14 below — the kernel itself is `phase1-hardening-kernels.md` item 10, referenced here and shipped early in **C2**; phase-5 records it shipped ahead of its home phase). Out: non-Claude-Code worker CLIs (Codex etc. — that's Phase 6 "Reach"; this spec keeps the claude CLI and swaps what's behind it), automatic provider failover, load balancing.

**Demand-gate note (build-only):** the BUILD waits on the §0.4 demand check; the spec task runs on schedule regardless. Mirrors PLAN §0.4 exactly — the demand check gates the build only, the spec is drafted regardless.

## Mechanism (fixed)

<!-- F10 --> (= review M17 — attach-env transport made feasible; secrets-storage "or" removed)

- Profiles are named entries in git-tracked `providers.toml`, on disk at the repo root (`providers.toml` beside `fleet.py`'s data root, git-tracked): each profile is an env-var map (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, model aliases/overrides, etc.) plus references to secrets by NAME — never secret values.
- **Secrets storage — one model (the "or" is resolved):** secret values live only in gitignored `state/secrets.toml`, written 0600-equivalent (owner-only; the platform adapter sets the ACL — invariant 8, no scattered `if platform`). `providers.toml` holds only the secret's key name; `state/secrets.toml` maps that name → value. There is no second "env-var names resolved at launch" path — the previously-open alternative is dropped.
- **Env delivery is a platform-adapter contract, not process-env inheritance.** Naive `Popen(env=merged)` on the terminal launcher silently fails on the primary paths (wt.exe hands the tab to the already-running WindowsTerminal.exe monarch, which inherits the SERVER's env; tmux `new-window` runs in the tmux server's env; macOS `osascript "do script"` shells are parented by Terminal.app/launchd) — and attach never checks the child, so the operator's interactive session silently talks to the default Anthropic backend on their own account. The fix, uniform across turn-launch and attach: **a per-attach generated env script (0600-equivalent, under gitignored `state/`, deleted on release) that the launched shell sources before exec'ing `claude --resume`.** Secret VALUES never appear in argv, command strings, logs, events, registry, or echo output (names may). This kills the string-workaround (`$env:ANTHROPIC_API_KEY='sk-...'; claude --resume ...`) that would leak secrets into `Win32_Process.CommandLine`, script-block logging, and `ps auxww`. Per-terminal-path verification rows + the no-secrets-in-argv doctor/test assertion live in `portability.md` OQ3 (owned by `stub-inject-portability` — cross-ref, not edited here).
- `fleet spawn <name> --provider <profile>` merges the profile's env over the inherited env for every turn process of that worker via the same generated-env-script contract. Profile name recorded in registry (an additive provenance field under the M1 additive-schema rule — invariant 6, single writer `fleet.py` still the sole author of `fleet.json`); immutable per worker (like cwd) unless respawned with a different one — provenance must stay honest.
- `fleet attach` sources the same generated env script into the launched terminal before exec (otherwise the interactive session silently talks to the default backend — a correctness bug, not a nicety).
- Doctor gains a **secret-presence check**: verifies each profile's referenced secret name resolves in `state/secrets.toml` and reports presence/absence WITHOUT printing values.
- Hooks are unaffected (they run locally, no API calls).

## Open questions (answer all)

1. Exact env-var surface to support v1: `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY` (proxy case), `CLAUDE_CODE_USE_BEDROCK`/`CLAUDE_CODE_USE_VERTEX` + their region/credential vars, `ANTHROPIC_MODEL`/`ANTHROPIC_SMALL_FAST_MODEL` overrides — verify each against current CLI docs; which combinations are coherent?
2. Model-name mapping: profiles pointing at proxies serving non-Anthropic models need model aliasing (`--model` value the proxy understands). Per-profile `models` table with fleet-side aliases? How does spawn `--model` interact with profile default?
3. Cost accounting: stream-json result cost fields are Anthropic-priced; behind a proxy/other provider they're wrong or absent. Registry `cost_usd` per worker must be marked untrusted for non-default profiles (token counts stay valid — prefer tokens everywhere anyway, cf. phase-5 token-ceiling kernel).
4. Session compatibility: does resuming a session across a provider/model switch (respawn --provider) behave — transcript is local, so it should; verify no session-state ties to backend identity.
5. Doctor checks: per-profile reachability ping (cheap `claude -p 'ok' --model <alias>` against the profile? cost vs confidence), secret-presence check without printing values, warn when a profile shadows global env the user already set.
6. Auth handoff: profiles using OAuth (claude.ai login) vs API-key — can a worker run API-key auth while the human's interactive sessions stay OAuth? (`ANTHROPIC_API_KEY` presence changes CLI auth path — verify precedence and that attach inherits correctly.)
7. Where does the manager itself run? (Default backend always, or can manager-on-call turns use a cheap-proxy profile? Recommend: default only in v1 — the manager is the last thing to economize on.)
8. Failure modes: proxy down mid-campaign (turn fails — how does status classify and report backend vs task failure), token expiry, rate-limit semantics differing behind proxies.

<!-- F14 --> (= review M18 — --max-budget-usd is toothless behind proxies; OQ9 added, token-ceiling kernel referenced)

9. `--max-budget-usd` × untrusted proxy costs: the flag enforces against the claude CLI's own Anthropic-priced accounting, which OQ3 already concedes is wrong-or-absent behind a proxy (absent/zero ⇒ cap never trips, worker unbounded; inflated ⇒ early mid-task trip). Decide: warn/refuse the flag on non-default profiles, or translate it to a token ceiling (the C2-shipped `phase1-hardening-kernels.md` item-10 kernel). Define the **budget-trip classification** (backend-cost trip vs task failure vs token-ceiling trip in `status`/`result`), extending OQ8.

## Done criteria

A worker completes a real task through a LiteLLM (or equivalent) proxy profile end-to-end — spawn, mid-turn send, attach (env verified pointing at proxy), respawn — with provenance visible in `fleet status` and no secret ever landing in git or logs. Two anchored sub-criteria:
- **Attach-env (F10):** env verification runs specifically on the **wt path with a pre-existing Terminal window open** — the exact configuration where naive process-env inheritance silently passes in acceptance and fails in production.
- **Spend bound (F14):** a proxy-profile worker demonstrably halted by the token ceiling.

## Invariants touched

Cites the numbered architectural invariants in `SPEC.md` (§"Architectural invariants (numbered)").

- **8 — platform-adapter-only OS branching** (F10): env delivery is an adapter contract. The per-attach generated env script and its 0600-equivalent permissions are set behind the platform adapter (Windows ACL / POSIX mode), so the wt / tmux / osascript path differences stay inside the adapter — no scattered `if platform` in core. **Preserved:** core spawn/attach call the adapter's "materialize env script" and "set owner-only perms" methods; they never branch on OS themselves.
- **6 — single-writer registry** (F10, F14): the profile-name **provenance field** and any budget-trip classification recorded on a worker are added under the M1 additive-schema rule. **Preserved:** only `fleet.py`, guarded by `fleet.lock`, writes `fleet.json`; these are additive fields on the existing record, not a new writer.
