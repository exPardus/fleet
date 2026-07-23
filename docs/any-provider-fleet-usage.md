# Running fleet workers on any model / provider

**TL;DR:** A worker's backend is fixed by the **daemon** that launches it, and a
daemon's backend is fixed at *its* boot. One `CLAUDE_CONFIG_DIR` = one daemon =
one backend. So: give each provider its own config dir, and you can run
Anthropic, LongCat, or any other Anthropic-compatible endpoint — **including
several at once**, in one `fleet status`.

This generalises [`longcat-fleet-usage.md`](longcat-fleet-usage.md) (LongCat is
just the worked example) and **corrects one claim in it** — see
[Mixing providers](#mixing-providers-verified) below.

---

## What actually works

| Capability | Supported? | How |
|---|---|---|
| Whole fleet on a non-Anthropic provider | **Yes** | Isolated `CLAUDE_CONFIG_DIR` + `ANTHROPIC_*` env |
| Different **model** per worker, same provider | **Yes** | `fleet spawn --model <name>` (name must exist on that provider) |
| Different **providers** running **concurrently** | **Yes** | One config dir per provider — see below |
| Mixing providers **inside one** config dir | **No** | One daemon, one backend. Not fixable without an upstream CLI change |
| `fleet spawn --provider <x>` | **No** | Designed then shelved (`specs/providers.md`) — use config dirs instead |

### Why the daemon is the unit

Foreground `claude` reads `ANTHROPIC_BASE_URL` / `_AUTH_TOKEN` / `_MODEL` from
its **own** process env, so a plain shell wrapper Just Works. Fleet workers are
launched with `claude --bg`, which hands the session to a **shared background
daemon**; the worker inherits the endpoint + auth from **the daemon's env, fixed
at daemon-boot** — not from the env at spawn time. Change the spawn-time env all
you like: if an existing daemon owns the namespace, the worker goes to *its*
backend.

That is the whole model. Everything below follows from it.

---

## Recipe: point a fleet at any Anthropic-compatible provider

Anything exposing an Anthropic-compatible `/v1/messages` works — LongCat, z.ai,
Moonshot/Kimi, DeepSeek behind a shim, OpenRouter's Anthropic-compat endpoint, a
local LiteLLM/vLLM proxy, etc.

```sh
# 1. A config dir DEDICATED to this provider (this is what forks the daemon)
export CLAUDE_CONFIG_DIR="$HOME/.claude-<provider>"

# 2. Point at the provider
export ANTHROPIC_BASE_URL="https://<provider-host>/anthropic"
export ANTHROPIC_AUTH_TOKEN="<token>"

# 3. Name the model in EVERY slot claude might reach for. Anthropic aliases
#    (haiku/sonnet/opus) do NOT exist on a foreign provider; if any slot still
#    resolves to one, that request 404s with model_not_found.
export ANTHROPIC_MODEL="<provider-model-id>"
export ANTHROPIC_SMALL_FAST_MODEL="<provider-model-id>"
export ANTHROPIC_DEFAULT_OPUS_MODEL="<provider-model-id>"
export ANTHROPIC_DEFAULT_SONNET_MODEL="<provider-model-id>"

# 4. Spawn WITHOUT --model, so the env governs
fleet spawn w1 --dir <path> --task @task.md --token-ceiling 30000
```

The **first** `--bg` spawn in a fresh config dir boots that namespace's daemon
under this env (`Starting background service…` in its `daemon.log`). Every later
worker in the namespace inherits it.

> **Do not pass `--model haiku` / `opus` / `sonnet` to a foreign provider.** Those
> are Anthropic aliases. `--model` is only for selecting a model the *current
> backend* actually serves. On a foreign provider, prefer the env vars.

### Non-negotiable: turn extended thinking off

Non-Anthropic models cannot emit valid Anthropic `thinking` blocks. With thinking
on, every turn **after the first** dies with:

```
400 ... each thinking block must contain non-whitespace thinking
```

Set it in the namespace's `settings.json` (workers inherit it):

```jsonc
// $CLAUDE_CONFIG_DIR/settings.json
{ "alwaysThinkingEnabled": false }
```

If workers specifically still wedge, also add `"alwaysThinkingEnabled": false` to
`worker-settings.template.json` and re-run `fleet init` to re-render.

---

## Mixing providers (verified)

`longcat-fleet-usage.md` says mixing is *"Impossible without a CLI change."* That
is true **only inside one config dir**. Across config dirs it works today,
because fleet's **registry is shared** while the **daemons are not**:

- `fleet home` is `~/fleet` regardless of `CLAUDE_CONFIG_DIR` → one registry, one
  `fleet status`, one set of worker names.
- Each `CLAUDE_CONFIG_DIR` boots its **own** daemon → its own backend.
- A worker is pinned to whichever daemon launched it, for its whole life.

So: **spawn each worker from the namespace whose provider you want.**

```sh
# LongCat worker
CLAUDE_CONFIG_DIR=~/.claude-longcat ANTHROPIC_BASE_URL=... ANTHROPIC_MODEL=LongCat-2.0 \
  fleet spawn w-lc --dir /tmp/x --task @task.md --mode dontask

# Anthropic worker (default namespace) — same registry, different backend
fleet spawn w-an --dir /tmp/x --task @task.md --mode dontask --model haiku
```

Both appear in one `fleet status`; each ran on its own backend:

```
$ fleet status
mix-an              idle           1  ...  tokens:in=10 out=103
mix-lc              idle           1  ...  tokens:in=253 out=5

$ fleet result mix-lc     # spawned from ~/.claude-longcat
-- tokens in=253 out=5 model=LongCat-2.0

$ fleet result mix-an     # spawned from the default namespace
-- tokens in=10 out=103 model=claude-haiku-4-5-20251001
```

*(Observed 2026-07-23, two daemons alive concurrently: one on
`~/.claude-longcat/daemon.json`, one on `~/.claude/daemon.json`.)*

**Caveats of mixing**

- **Names are global.** The registry is shared, so `w1` in one namespace collides
  with `w1` in another. Prefix by provider (`lc-…`, `an-…`).
- **You must remember which namespace a worker came from.** The registry does not
  record the provider. `fleet result` printing `model=` is the ground truth.
- Management commands (`status`, `result`, `peek`) work from any namespace since
  the registry is shared. `send`/`kill` are also registry-driven, but re-dispatch
  paths (fork-steer, `resume-limited`) relaunch through a daemon — run those from
  the worker's **own** namespace so it re-lands on the right backend.

---

## Verify a worker's backend

Do not assume. `fleet result` prints the model the turn actually ran on:

```sh
fleet result <name> | head -1
# -- tokens in=253 out=5 model=LongCat-2.0        <- foreign provider, good
# -- tokens in=10 out=103 model=claude-haiku-...  <- Anthropic
```

If it shows an Anthropic model when you wanted a foreign one, the worker landed
on the wrong daemon — you spawned from the wrong namespace, or a daemon for that
namespace was already up under different env.

> The older recipe of grepping `~/.claude/projects/**/*.jsonl` for
> `model_not_found` is unreliable: with an isolated namespace the transcripts
> live under `$CLAUDE_CONFIG_DIR/projects/`, not `~/.claude/projects/`. Use
> `fleet result`.

---

## Cost and budget

`fleet status` cost is **Anthropic-priced** and meaningless behind another
provider. Bound spend with `--token-ceiling`; **never** `--max-budget-usd`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `model_not_found` / "issue with the selected model" | Worker landed on a daemon whose backend doesn't serve that model name — usually an Anthropic daemon, or an Anthropic alias passed via `--model` | Spawn from the provider's own `CLAUDE_CONFIG_DIR`; drop `--model`; set all four model env vars |
| Turn 1 fine, every later turn `400 … thinking block must contain non-whitespace thinking` | Extended thinking on | `alwaysThinkingEnabled: false` in the namespace `settings.json` (and `worker-settings.template.json` for workers) |
| Worker replies as if it never got your `fleet send` | Fork-steer used to drop the manager message | Fixed by `_dispatch_argv_prompt` (branch `fix/fork-steer-dropped-steer`). Weak models may still ignore a delivered steer — check the transcript to tell *dropped* from *ignored* |
| `fleet result` shows the wrong provider's model | Spawned from the wrong namespace | Kill and respawn from the right `CLAUDE_CONFIG_DIR` |
| Costs look absurd | Anthropic pricing applied to a foreign provider | Ignore cost; use `--token-ceiling` |
| Killing the daemon doesn't help — an Anthropic one returns instantly | In the **default** namespace the daemon is owned and auto-respawned by a persistent `claude` monarch | Don't fight it. Use a separate `CLAUDE_CONFIG_DIR` (that's the whole point) |

---

## Why not `--provider`?

A first-class `fleet spawn --provider <x>` was designed
(`specs/providers.md`) and **shelved**: with one shared daemon per namespace, a
per-worker provider flag can't be honoured without an upstream CLI change or a
per-backend-daemon rewrite. The config-dir approach above gets the same result
today, at the cost of remembering which namespace you spawned from.
