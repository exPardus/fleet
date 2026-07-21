# Using LongCat (and other proxy providers) with fleet

**TL;DR:** A single foreground `longcat` session works fine. Fleet **workers** are harder: every worker on a machine shares **one background daemon**, and that daemon's backend is fixed when it boots. You can run the *whole* fleet on LongCat by dedicating the daemon to it, but you **cannot mix** LongCat and Anthropic workers at the same time.

> Full investigation + evidence: `docs/superpowers/specs/2026-07-21-worker-providers-native-design.md` (§4.2 spike result). This file is the operator how-to; that one is the why.

---

## Why workers are different from a plain `longcat` session

- **Foreground `claude` / `longcat`** reads `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_MODEL` from its **own** process env. Your `longcat()` shell function sets them, so it Just Works.
- **Fleet workers** are launched with `claude --bg`, which hands the session to a **shared background daemon**. A worker resolves its **endpoint + auth from the daemon's env, fixed at daemon-boot** — *not* from the env at spawn time. Proven: a `--bg` worker spawned with correct LongCat env still failed `model_not_found` because a pre-existing Anthropic daemon owned it.

**Consequence:** one daemon = one backend. No per-worker mixing.

---

## What works

### 1. Single LongCat session (fully supported)

```sh
longcat            # your ~/.zshrc function; thinking is off via longcat-settings.json
```

Thinking **must** stay off for LongCat (non-Anthropic models can't emit valid Anthropic thinking blocks — otherwise every turn after the first dies with `400 ... thinking block must contain non-whitespace thinking`). This is already handled: `longcat()` passes `--settings ~/.claude/longcat-settings.json` which sets `alwaysThinkingEnabled: false`. Don't remove that.

### 2. Whole fleet on LongCat

> **Reality check (verified 2026-07-21):** the "just kill the daemon and reboot it under LongCat env" idea **does not work on a machine with a live Claude ecosystem.** The background daemon is *owned and auto-respawned by a persistent `claude` process* (the monarch, e.g. pid 51058) under **its** env — which is Anthropic. `pkill` the daemon and an Anthropic one reboots in under a second (watchdogs enforce this). You cannot win that race without tearing down the monarch and everything holding it, which breaks your normal Anthropic work. **Use the isolated-config approach below instead.**

#### 2a. Isolated daemon namespace (the path that actually works)

Give LongCat fleet work its **own** `CLAUDE_CONFIG_DIR` so it gets a **separate daemon** that never collides with your Anthropic monarch:

```sh
export CLAUDE_CONFIG_DIR="$HOME/.claude-longcat"   # separate namespace = separate daemon
export ANTHROPIC_AUTH_TOKEN="…" ANTHROPIC_BASE_URL="https://api.longcat.chat/anthropic"
export ANTHROPIC_MODEL="LongCat-2.0" ANTHROPIC_SMALL_FAST_MODEL="LongCat-2.0"
# first --bg spawn here boots a LongCat-env daemon isolated from the Anthropic one
fleet spawn w1 --dir <path> --task @task.md     # NO --model
```

Or just use the **`longcat-fleet`** launcher (added to `~/.zshrc`): it exports the isolated `CLAUDE_CONFIG_DIR` + LongCat env and starts a manager session; `fleet spawn` from inside it puts workers on LongCat.

**VERIFIED 2026-07-21:** a `--bg` worker in the `~/.claude-longcat` namespace booted its own daemon (`Starting background service…`) under LongCat env and replied `PONG` with **zero** `model_not_found` — the isolated daemon (env confirmed `ANTHROPIC_BASE_URL=…longcat…`, `CLAUDE_CONFIG_DIR=~/.claude-longcat`) never collides with the Anthropic monarch.

Trade-offs: a second config dir means its fleet/plugin state is separate; your Anthropic and LongCat daemons coexist without a shared-backend collision. **Worker thinking:** the namespace's `settings.json` sets `alwaysThinkingEnabled:false`, which workers inherit — keep it, or they wedge on the thinking-block 400.

#### 2b. Original single-daemon idea (blocked — kept for the record)

Because workers inherit the daemon's backend, boot the daemon **fresh under LongCat env** and every worker follows. Procedure:

1. **Stop every running agent + the daemon** so no Anthropic daemon lingers:
   ```sh
   claude agents          # see what's alive
   claude stop <id>       # stop each, or stop-all if your version has it
   ```
   Confirm `claude agents` lists nothing before continuing.
2. **Export LongCat env globally** for the shell you'll run fleet from — not just inside the `longcat()` function, so the daemon the first spawn boots inherits it:
   ```sh
   export ANTHROPIC_AUTH_TOKEN="…"                       # your LongCat token
   export ANTHROPIC_BASE_URL="https://api.longcat.chat/anthropic"
   export ANTHROPIC_MODEL="LongCat-2.0"
   export ANTHROPIC_SMALL_FAST_MODEL="LongCat-2.0"
   export ANTHROPIC_DEFAULT_OPUS_MODEL="LongCat-2.0"
   export ANTHROPIC_DEFAULT_SONNET_MODEL="LongCat-2.0"
   ```
3. **Spawn a worker without a fleet model alias.** Do **not** pass `--model haiku`/`opus` etc. — those names don't exist on LongCat. Let the env's `ANTHROPIC_MODEL` govern:
   ```sh
   fleet spawn w1 --dir <path> --task @task.md      # NO --model
   ```
4. **Verify routing before trusting it** (see next section). If the worker errors `model_not_found`, an Anthropic daemon is still up — go back to step 1.

**Caveats of this mode:**
- The daemon is now LongCat-only until you restart it. Your foreground Anthropic `claude` sessions still work (they read their own env), but any `--bg`/fleet worker goes to LongCat.
- **Thinking:** make workers inherit the same thinking-off setting. Fleet renders worker settings from `worker-settings.template.json`; if workers wedge on the `thinking block` 400, add `"alwaysThinkingEnabled": false` to that template (then `fleet init` re-renders) — see Troubleshooting.
- **Cost numbers are wrong.** `fleet status` cost is Anthropic-priced; behind LongCat it's meaningless. Bound spend with `--token-ceiling`, never `--max-budget-usd`.

---

## What does NOT work

- **Mixing** LongCat + Anthropic workers simultaneously — one daemon, one backend. Impossible without a CLI change.
- **Spawning LongCat workers while an Anthropic daemon is already up** — workers get the Anthropic backend and fail `model_not_found` on the LongCat model name. This is the original failure you hit.
- **Passing a fleet model alias** (`--model haiku`, plan-mode's default subagents, etc.) to LongCat — the alias isn't a real LongCat model. Plan-mode / built-in subagents that pick their own model tier will fail; stick to explicit fleet workers with no `--model`.

---

## Verify a worker is actually on LongCat

Spawn a trivial worker, then read its transcript (no extra `claude` calls needed):

```sh
# find the newest worker transcript and check for the failure signature
f=$(find ~/.claude/projects -name '*.jsonl' -newermt '-2 minutes' | head -1)
grep -c 'model_not_found\|selected model' "$f"    # 0 = good (on LongCat); >0 = wrong daemon
```

`0` means it ran clean on LongCat. Anything above `0` means it hit the Anthropic daemon — restart per step 1.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Worker: *"issue with the selected model (LongCat-2.0)… may not exist"* | Worker landed on an Anthropic daemon | Stop all agents + daemon, re-boot under LongCat env (§What works #2) |
| Every turn after the first: `400 … thinking block must contain non-whitespace thinking` | Extended thinking on; LongCat can't emit valid thinking blocks | `alwaysThinkingEnabled: false` — in `longcat-settings.json` for sessions, in `worker-settings.template.json` for workers |
| `claude.ai connectors are disabled…` warning | An API auth source overrides claude.ai login | Harmless; ignore |
| Costs look absurd in `fleet status` | Cost fields are Anthropic-priced | Ignore cost; use `--token-ceiling` for bounds |

---

## Status of first-class support

A `fleet spawn --provider longcat` flag was designed (`docs/specs/providers.md` + the 2026-07-21 design doc) but **shelved**: the shared-daemon architecture makes per-worker providers unshippable without an upstream CLI change or a per-backend-daemon rewrite. This document is the working alternative until that changes.
