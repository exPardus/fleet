# Design: External provider support for fleet workers (native `--bg` era)

**Status:** approved design — ready for implementation plan
**Date:** 2026-07-21
**Branch:** `feat/worker-providers`
**Re-bases:** `docs/specs/providers.md` (the reviewed "Provider profiles" stub). That stub predates the native `--bg` pivot (M-B); its central env-delivery mechanism — a per-attach env script sourced by a launched terminal (wt/tmux/osascript) — is **obsolete** now that workers are `claude --bg` daemon sessions with no fleet-launched shell. This design supersedes the delivery section and simplifies the storage model. The stub's open questions that still bind v1 are carried forward in §7.

---

## 1. Goal

Run a fleet worker against a non-default Anthropic-compatible backend — an API proxy (e.g. LongCat, LiteLLM, a self-hosted gateway) — **chosen per worker at spawn**, without mutating global machine config or the manager's own backend. v1 target: `fleet spawn w1 --provider longcat` boots a native `--bg` worker that talks to LongCat, while an Anthropic worker spawned alongside it stays on Anthropic.

## 2. Scope

**In:** named provider profiles in a gitignored config file; per-worker selection via `--provider`; env injection at `--bg` dispatch; provenance on the worker record (respawn/fork-steer inherit it); refuse-early validation; a doctor secret-presence check; SPEC §5 spawn-row doc.

**Out (YAGNI for v1):** fleet-wide default provider (per-worker only, per user decision); Bedrock/Vertex (`CLAUDE_CODE_USE_BEDROCK`/`_USE_VERTEX`) — env surface is designed to extend to them but v1 ships proxy-only; provider failover/load-balancing; non-claude CLIs (Codex etc. — Phase 6); trustworthy cost accounting behind proxies (see §6 — cost is marked untrusted, not fixed).

## 3. Storage model (decided)

A single gitignored file under `FLEET_HOME`, `providers.json`:

```json
{
  "longcat": {
    "base_url": "https://api.longcat.chat/anthropic",
    "model": "LongCat-2.0",
    "token_env": "LONGCAT_API_KEY",
    "small_fast_model": "LongCat-2.0"
  }
}
```

- `base_url` (required) → `ANTHROPIC_BASE_URL`
- `model` (required) → `ANTHROPIC_MODEL` + `ANTHROPIC_DEFAULT_OPUS_MODEL` + `ANTHROPIC_DEFAULT_SONNET_MODEL`
- `small_fast_model` (optional, defaults to `model`) → `ANTHROPIC_SMALL_FAST_MODEL`
- `token_env` (required) — the **name** of an env var holding the auth token. The token itself is **never** stored in fleet; it lives in the operator's shell/keychain. The token flows env → env at dispatch, never touching disk, logs, argv, events, or the registry.

**Why this over the stub's `providers.toml` + `state/secrets.toml`:** the stub's dedicated secret store existed to serve the old env-script delivery path (secrets had to be materialized to a sourced file). Native `--bg` injects env directly into the dispatch subprocess (§4), so a secret store is unnecessary weight — an env-var reference keeps the secret out of fleet entirely, which is strictly safer.

## 4. Delivery mechanism (env injection at dispatch)

**Primary approach — extend `_worker_env`.** `dispatch_bg` already launches `claude --bg` with `env=_worker_env(name)` (`fleet.py:6859`), and `_worker_env` copies `os.environ` (`fleet.py:1143`). We thread the resolved provider through to `_worker_env`, which — when a provider is active — overlays:

```
ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, ANTHROPIC_DEFAULT_OPUS_MODEL,
ANTHROPIC_DEFAULT_SONNET_MODEL, ANTHROPIC_SMALL_FAST_MODEL, ANTHROPIC_AUTH_TOKEN
```

When a provider is active, fleet **suppresses its own `--model` argv** (`fleet.py:6832`) — the provider's `ANTHROPIC_MODEL` governs, so a fleet model alias (e.g. `haiku` from integration tests) is never sent to an endpoint that has never heard of it. `--provider` and `--model` together is a refuse-early error (contradictory intent).

### 4.1 Task 0 — the `--bg` spike (HARD GATE before any further code)

`fleet.py:6823-6828` carries a standing admission that `--setting-sources`/env effects on a `--bg` worker are **"UNOBSERVED... never directly confirmed against a real daemon."** The whole feature rests on env reaching the worker turn, and the background daemon may be shared/long-lived (a daemon already booted under Anthropic could win). So the FIRST implementation task is an empirical spike, and its result is a gate:

1. Spawn one real `--bg` worker with `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL` set to LongCat via the dispatch env; a trivial prompt.
2. Confirm from the worker's transcript/outcome that it hit the **external** endpoint (LongCat model id present, or an Anthropic-model-not-found error is ABSENT).
3. Spawn an Anthropic worker **alongside** it; confirm no bleed (it stays on Anthropic). This is the per-worker-mixing test — the decisive one, since the user chose per-worker providers.

**Gate outcome:**
- **Pass** (env reaches worker, no bleed) → proceed with §4 as written.
- **Fail — env reaches worker but mixing bleeds** (daemon shares one env) → fall back to a per-worker `--settings` file carrying the routing in its `env` block, keeping the token in dispatch env only. Re-scope in the plan.
- **Fail — env does not reach worker at all** → stop; escalate to the operator. The feature is not deliverable on native `--bg` without a CLI change; document the finding in this doc and `providers.md`.

`log()` / report the spike result explicitly — no silent assumption that it passed.

### 4.2 SPIKE RESULT — 2026-07-21 — NEGATIVE (approach A dead)

Ran on the live machine (daemon already up from the operator's fleet ecosystem — the realistic case):

- Foreground `claude -p` with LongCat env → **`PONG`** (endpoint/token/model/thinking-off all good).
- `claude --bg` with the *identical* env on the dispatch process → worker **failed** with `model_not_found` + `401`, synthetic message *"There's an issue with the selected model (LongCat-2.0)..."* — byte-for-byte the original fleet+LongCat failure. Transcript: `~/.claude/projects/-private-tmp/492c326f-...jsonl`.

**Interpretation:** the model *name* propagated to the daemon, but **`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` did not** — a `--bg` worker resolves its endpoint + auth from the **daemon's own process env**, fixed at daemon-boot, not from the dispatch process's env. Because the daemon is shared and long-lived, **all workers on it share one backend**; per-worker provider mixing (the chosen model) is structurally impossible via env injection. This is a CLI/daemon-architecture limit, not a fleet defect.

**Consequence:** Approach A (§4) is not viable for the per-worker goal. Remaining paths, in order of likelihood:
1. **Per-worker `--settings` file with an `env` block** — untested; MAY work where process-env fails, because settings are per-session config the daemon applies per session. Cost: token would land on disk (violates §3's secret rule) unless the CLI resolves settings-`env` from the host environment (unverified). Needs its own spike.
2. **Dedicated daemon per backend** — run provider workers under a separate daemon booted with the provider env (e.g. a distinct `CLAUDE_CONFIG_DIR`/home). Heavier; changes fleet's single-daemon model.
3. **Upstream CLI change** — `claude --bg` learns to carry per-session base-url/auth. Out of fleet's control.

Do not implement §4 as written. Next step is a decision between (1)/(2)/park — see handoff.

## 5. Provenance & lifecycle

- `provider` (the profile name string, or `None`) becomes an **additive** field on the worker record via `new_worker_record` (invariant 6: single-writer `fleet.py` under `fleet.lock`; additive-schema rule, same pattern as `setting_sources`/`model`/`token_ceiling`).
- Immutable per worker like `cwd`/`model`: respawn and fork-steer read the persisted `provider` and re-inject it, so a worker never silently changes backend across turns. Respawn with a different `--provider` is allowed (provenance stays honest — the record updates).
- `fleet status` surfaces the provider name (non-secret) so the operator can see which backend each worker runs.

## 6. Validation, errors, cost

- **Undefined provider:** `--provider foo` with no `foo` in `providers.json` → refuse before any registry mutation, listing known names.
- **Missing secret:** `token_env` names a var absent from the environment at spawn → refuse before dispatch (never boot a half-configured worker that silently falls back to Anthropic on the operator's own account — the exact failure the stub's F10 warned about).
- **Malformed `providers.json`:** clear parse error; never crash the CLI.
- **No `providers.json`:** `--provider` given but file absent → actionable error ("create FLEET_HOME/providers.json"). Absence is fine for non-provider spawns (zero behavior change).
- **Cost accounting:** `result`-event `cost_usd` is Anthropic-priced and wrong/absent behind a proxy. A provider worker's `cost_usd` is marked **untrusted** in the registry/status (carry the stub's OQ3); token counts stay valid. `--max-budget-usd` is already refused under native dispatch (contract G3); `--token-ceiling` remains the real spend bound (stub F14).
- **Doctor:** a secret-presence check per referenced `token_env` — reports resolves/absent **without printing the value**; warns when a profile would shadow `ANTHROPIC_*` the operator already has set in the manager env.

## 7. Carried-forward open questions (from providers.md, still binding v1)

- OQ2 (model mapping): resolved for v1 — provider `model` overrides; `--provider` + `--model` is an error, not a merge.
- OQ4 (session compat across respawn --provider): transcript is local; verify no backend identity ties to session state during the spike/plan.
- OQ6 (auth path): `ANTHROPIC_AUTH_TOKEN` presence flips the CLI auth path — verify the worker uses API-key auth while the manager's interactive OAuth is untouched (it is, since env is per-dispatch).

## 8. Testing

- Unit: `load_providers()` validation (undefined name, missing `token_env`, malformed JSON, absent file); `_worker_env` env assembly for a provider (correct vars, token from `token_env`, `small_fast_model` default); `--model`+`--provider` refusal; `provider` record persistence + respawn/fork-steer re-injection; doctor secret-presence check (present/absent, no value printed).
- Non-regression: a spawn with **no** `--provider` produces byte-identical dispatch argv/env behavior to today (guard the existing suite).
- Integration/spike: §4.1, gated, run against real LongCat + a real daemon. Not part of the default pytest run (needs live creds); marked/skipped like the existing haiku integration tests.

## 9. Invariants touched

- **6 — single-writer registry:** `provider` is an additive provenance field; only `fleet.py` under `fleet.lock` writes `fleet.json`. Preserved.
- **8 — platform-adapter-only OS branching:** env injection is pure `dict` assembly in `_worker_env` — no OS branching introduced (the stub's adapter-permission concern died with the env-script mechanism). Preserved.
- **1 — daemonless views:** unchanged; status only reads the new field.

## 10. Done criteria

`fleet spawn w --provider longcat` completes a real task end-to-end through LongCat — spawn, mid-turn send, respawn — with the provider name visible in `fleet status`, an Anthropic worker running alongside unaffected, `--token-ceiling` demonstrably bounding the provider worker, and no secret ever in git, logs, argv, or events. Gated by the §4.1 spike passing first.
