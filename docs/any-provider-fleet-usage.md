# Run Claude workers through another provider

Fleet does not choose a provider for an ordinary Claude worker. The Claude Code
background daemon does. A daemon reads its endpoint, credentials, and model
defaults when it starts; workers later launched through that daemon inherit the
same backend.

The practical namespace rule is:

> One `CLAUDE_CONFIG_DIR` namespace has one Claude background daemon and one
> backend. Use a separate config directory for each provider.

This page describes that generic route for an Anthropic-compatible endpoint. It
is separate from Fleet's first-class [`openrouter:<slug>` route](#shipped-provider-routes)
and from [native Codex lanes](codex-lanes.md).

## Configure one provider namespace

An endpoint must implement the Anthropic-compatible Messages API expected by
Claude Code. Use a config directory dedicated to that endpoint, and set its
environment before the first `fleet spawn` in that namespace:

```sh
export CLAUDE_CONFIG_DIR="$HOME/.claude-provider-a"
export ANTHROPIC_BASE_URL="https://provider.example/v1"
export ANTHROPIC_AUTH_TOKEN="<token>"

# Use the provider's exact model id in every model slot it may receive.
# If the provider accepts only one model, using the same id in each slot is
# the least surprising setup.
export ANTHROPIC_MODEL="<provider-model-id>"
export ANTHROPIC_SMALL_FAST_MODEL="<provider-model-id>"
export ANTHROPIC_DEFAULT_OPUS_MODEL="<provider-model-id>"
export ANTHROPIC_DEFAULT_SONNET_MODEL="<provider-model-id>"

fleet spawn provider-worker --dir <path> --mode dontask \
  --task @task.md --token-ceiling 30000
```

Use the authentication variable required by the endpoint (`ANTHROPIC_AUTH_TOKEN`
or `ANTHROPIC_API_KEY`); do not set a secret in a task, brief, registry field,
or checked-in settings file. The exact base URL path and model ids are provider
configuration, not Fleet configuration.

The first `claude --bg` dispatch in a fresh namespace starts that namespace's
daemon. Later workers inherit the daemon's environment, not a newly changed
environment from an already-running daemon. If you change the endpoint or
credentials, start a fresh namespace/daemon before dispatching more workers.
Fleet itself only passes through the environment; it does not read or manage
`CLAUDE_CONFIG_DIR` or provider profiles.

### Model aliases are not universal

`haiku`, `sonnet`, and `opus` are Claude tier aliases. A compatible endpoint may
not serve those names. Either omit `--model` and let the namespace's model
environment choose an exact id, or pass `--model <provider-model-id>` only when
that backend documents the id. Passing an Anthropic alias to a backend that does
not map it commonly ends in `model_not_found`.

### Disable extended thinking when the backend cannot represent it

Many non-Anthropic models cannot return valid Anthropic `thinking` blocks. A
first turn may succeed and a later turn may fail with a 400 mentioning a
non-whitespace thinking block. Set the provider namespace's Claude settings:

```json
{
  "alwaysThinkingEnabled": false
}
```

For example, save that setting in
`$CLAUDE_CONFIG_DIR/settings.json` before dispatching workers. Whether a
provider supports thinking is its contract; do not enable it merely because a
Claude tier alias was accepted.

## Run providers concurrently

Separate namespaces can run at the same time while sharing one Fleet home and
registry:

```sh
# Provider A: this command boots or uses ~/.claude-provider-a's daemon.
CLAUDE_CONFIG_DIR="$HOME/.claude-provider-a" \
ANTHROPIC_BASE_URL="https://provider-a.example/v1" \
ANTHROPIC_AUTH_TOKEN="<token-a>" \
ANTHROPIC_MODEL="provider-a-model" \
fleet spawn pa-worker --dir <path> --task @task.md --mode dontask

# Provider B: a different daemon, but the same Fleet home and registry.
CLAUDE_CONFIG_DIR="$HOME/.claude-provider-b" \
ANTHROPIC_BASE_URL="https://provider-b.example/v1" \
ANTHROPIC_AUTH_TOKEN="<token-b>" \
ANTHROPIC_MODEL="provider-b-model" \
fleet spawn pb-worker --dir <path> --task @task.md --mode dontask

fleet status
```

The registry is keyed by worker name, not by config directory. Names are global
within a Fleet home, so use provider prefixes (`pa-…`, `pb-…`) and do not reuse
the same name in two namespaces. The registry and completed outcome store are
shared, so both names are visible from that Fleet home and `fleet result` can
read a completed result. A worker remains associated with the daemon that
launched its turn.

Live Claude views are different: `fleet status` obtains a roster from the daemon
in the current environment. Run authoritative live status and any daemon-facing
operation from the worker's original namespace; a different namespace can show a
foreign live row as unknown or stale even though the registry is shared. A
completed `fleet result` is file-backed, but using the original namespace for
`peek` keeps transcript discovery unambiguous.

Redispatch is the important caveat. An idle `fleet send`, `fleet respawn`, or
`fleet resume-limited` can launch a new turn through a daemon. Run those commands
with the worker's original `CLAUDE_CONFIG_DIR` and provider environment, or the
new turn can land on a different backend. Verify the result after any such
operation. If you intentionally need another backend, use a new worker name.

## Verify the backend that actually ran

Do not infer routing from the shell environment or from a transcript path. After
the turn completes, run:

```sh
fleet result pa-worker
```

The result text is printed on standard output. The final metadata line is printed
on standard error and includes the model, for example:

```text
-- tokens in=253 out=5 model=provider-a-model
```

That `model=` value is the authoritative witness for the completed turn. If it is
an Anthropic model when a provider model was expected, the worker used the wrong
daemon—usually because it was spawned from the wrong namespace or because that
namespace's daemon was already running with older environment. Stop the worker,
correct the namespace/daemon environment, and dispatch again; do not silently
continue under an unverified backend.

## Limits and cost semantics

Native Claude dispatch has no sanctioned USD cost signal. `fleet status` renders
a dash for its cost column and may show token counts from the latest outcome;
it does not promise provider pricing. The fleet-side spend bound is cumulative
tokens (input plus output) from completed outcome records:

```sh
fleet spawn provider-worker --dir <path> --task @task.md \
  --token-ceiling 30000
```

When the ceiling is reached, Fleet marks the worker `over_ceiling` and refuses a
new turn until an operator chooses an approved new ceiling or stops the worker.
`--max-budget-usd` is refused for native dispatch because the CLI cannot provide
a trustworthy USD figure; use `--token-ceiling` instead. A provider's own billing
and rate limits remain outside Fleet's token accounting.

## Shipped provider routes

The generic namespace recipe above is not a Fleet provider adapter. Two shipped
routes are explicit and have different provenance:

- **OpenRouter:** `fleet spawn NAME --dir PATH --model openrouter:<slug> --task
  "..."` uses Fleet's OpenRouter settings/key-file path (the local
  `~/.config/openrouter/env` file supplies `OPENROUTER_API_KEY`) and records a
  `substrate` such as `openrouter/<slug>`. See the implementation's public
  command surface in [the CLI reference](cli-reference.md#fleet-spawn).
- **Native Codex:** `--model codex:<model>` selects the Codex route, whose
  native app-server adapter is the default; `--codex-adapter mcx` is the legacy
  compatibility route. Both are described in [Codex lanes](codex-lanes.md), and
  neither uses the Claude daemon or `CLAUDE_CONFIG_DIR`.

There is no shipped `fleet spawn --provider` option. The parked
[provider-profile design](specs/providers.md) is historical and must not be used
as a command recipe.

## Quick diagnosis

| Symptom | Likely cause | Action |
|---|---|---|
| `model_not_found` | Wrong daemon or an Anthropic alias on a foreign backend | Use the provider namespace, omit `--model` or pass its exact id, and set the model slots. |
| First turn works; later turn fails with a thinking-block 400 | Extended thinking is enabled | Set `alwaysThinkingEnabled` to `false` in the namespace settings. |
| `fleet result` shows the wrong model | The turn ran through another namespace's daemon | Re-dispatch from the worker's original namespace and verify its metadata line. |
| A redispatched turn changes provider | `send`, `respawn`, or `resume-limited` was run without the original namespace environment | Repeat the management command from the original namespace; use a provider-prefixed worker name. |
| USD totals are absent or surprising | Native Fleet accounting is token-based, not provider-priced | Use `--token-ceiling`; consult the provider for billing. |
