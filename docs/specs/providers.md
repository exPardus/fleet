# Spec: Provider profiles — proxies & alternate AI backends

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md principles. Independent of watchtower; can be specced/built any time after Phase 1.5 (needs `fleet init` machinery).

## Goal

Run any worker against a non-default backend: an API proxy (LiteLLM/self-hosted gateway exposing an Anthropic-compatible API), a different Anthropic account/region, Bedrock/Vertex, or any provider reachable through such a proxy — chosen per worker at spawn, without touching global machine config.

## Scope

In: named provider profiles, per-worker env injection at turn launch AND attach, registry/provenance, doctor checks, cost-accounting caveats. Out: non-Claude-Code worker CLIs (Codex etc. — that's Phase 6 "Reach"; this spec keeps the claude CLI and swaps what's behind it), automatic provider failover, load balancing.

## Mechanism (fixed)

- Profiles are named entries in git-tracked `providers.toml`: env-var map (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, model aliases/overrides, etc.) plus references to secrets — never secret values. Secrets live in gitignored `state/secrets.toml` (or env-var names resolved at launch).
- `fleet spawn <name> --provider <profile>` merges the profile's env over the inherited env for every turn process of that worker. Profile name recorded in registry; immutable per worker (like cwd) unless respawned with a different one — provenance must stay honest.
- `fleet attach` injects the same env into the launched terminal (otherwise the interactive session silently talks to the default backend — a correctness bug, not a nicety).
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

## Done criteria

A worker completes a real task through a LiteLLM (or equivalent) proxy profile end-to-end — spawn, mid-turn send, attach (env verified pointing at proxy), respawn — with provenance visible in `fleet status` and no secret ever landing in git or logs.
