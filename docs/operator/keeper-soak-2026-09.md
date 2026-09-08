# Keeper soak — September 2026

Host receipts for `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`.
Every block here is `# volatile: host state` — evidence lives on kz-work, not in the tree.

## Baseline (before Task 1)

```text
# volatile: host state — measured 2026-09-08, commit 09819e1
3.12: 6 failed, 4638 passed, 7 skipped, 1 xfailed in ~6 min
3.10: 6 failed, 4638 passed, 7 skipped, 1 xfailed in ~6 min
pre-existing failures (6, same set on both): tests/test_fleet_index.py::TestPathContainment x3, tests/test_fleet_q.py::TestOutlinePathContainment x1, tests/test_terminal_surface.py::TestCollaboratorInstall x2
```

**"~6 min" above is APPROXIMATE and UNMEASURED** — it is a wall-clock impression of the two runs,
not a timed figure, and pytest's own duration line was not captured. Read it as "minutes, not
seconds and not an hour"; do not cite it as a benchmark or use it to detect a slowdown. A real
figure would come from the `in <n>s` pytest prints, kept verbatim.

## Soak items — carried deliberately, no code until the soak says so

Each is a signal the design's §3.3 rule table names and the shipped keeper does NOT observe. They
are listed here rather than built because the soak is what decides whether they page usefully or
just add noise; a rule that fires falsely is worse than a rule that is absent, because it teaches
the operator to ignore the channel.

| # | Signal | Why it is deferred | What would close it |
|---|---|---|---|
| S-1 | The **outcomes half of `login-expired`** — the spec's rule reads "`claude agents --json` fails, **or the newest outcome in `state/outcomes/` is an auth error**". Only the first half is built. | The auth-error shape in an outcome record has never been measured on this host; a rule keyed on a guessed substring would page on any result text containing it. | One real expiry during the soak, with the outcome file kept, and a rule keyed on what it actually contains. |
| S-2 | The **permission-stall arm of `worker-anomaly`** — the spec's rule reads "`dead-suspected`, `limited`, `idle+mail`, **or permission-stall**". The first three are built. | A permission stall is not in `status_snapshot()` at all: the snapshot carries `status`/`mail`/`limit_kind`, and nothing distinguishes a worker waiting on a permission prompt from one working. Building it means either a new snapshot field or a second read path, and the keeper is deliberately a reader of one projection. | A measured stall on this host, then a decision about which layer should surface it — `status_snapshot` (where every view would get it) rather than the keeper. |

## Pages observed

| when (UTC) | rule | text | true/false page | action taken |
|---|---|---|---|---|

## S0 — install

Host: this box, `/home/altai/proga/fleet`, branch `server/persistent-fleet` at `62b5e96`.
`fleet init` had never been run here; `fleet doctor` showed four `[FAIL] … run fleet init` rows
before this section. Steps below follow `docs/operator/fleet-init-recipe.md` §2/§4 and Task 1's
`--setting-sources`.

### Step 1 — init and install the plugin

```text
# volatile: host state — 2026-09-08 14:32 UTC
$ export PATH="$PWD/bin:$PATH"
$ fleet home
/home/altai/proga/fleet

$ fleet doctor 2>&1 | grep -E '^\[FAIL\]' ; printf 'doctor rc=%s\n' $?
[FAIL] worker-settings-instance: /home/altai/proga/fleet/state/worker-settings.json missing -- run `fleet init`
[FAIL] instance-freshness: worker-settings.json instance missing -- run `fleet init`
[FAIL] instance-grants: /home/altai/proga/fleet/state/worker-settings.json missing -- run `fleet init`
[FAIL] hook-registration: /home/altai/proga/fleet/state/worker-settings.json missing -- run `fleet init`
rc=0

$ env -u CLAUDE_CODE_SESSION_ID fleet init
fleet init: wrote /home/altai/proga/fleet/state/worker-settings.json
  python:      /home/altai/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
  fleet home:  /home/altai/proga/fleet
init rc=0

$ fleet doctor 2>&1 | grep -E '^\[FAIL\]' ; printf 'doctor rc=%s\n' $?
doctor rc=1
# (grep matched nothing, so it printed no [FAIL] lines; rc=1 is grep's "no match" status)

$ claude plugin marketplace add /home/altai/proga/fleet
Adding marketplace…✔ Successfully added marketplace: claude-fleet (declared in user settings)
marketplace add rc=0

$ claude plugin install fleet@claude-fleet
Installing plugin "fleet@claude-fleet"...✔ Successfully installed plugin: fleet@claude-fleet (scope: user)
install rc=0
```

No fallback marketplace name was needed — `fleet@claude-fleet` installed on the first try.

### Step 2 — canary worker, spawned with `--setting-sources`

```text
# volatile: host state — 2026-09-08 14:32 UTC
$ fleet spawn canary-srv --dir /home/altai/proga/fleet --setting-sources project,local \
    --task "Print the current date and stop. Do not edit any file."
model: (claude default)
canary-srv 73da4fe2-a391-4bf9-8e71-f3309751e1bb (native bg, short id 73da4fe2)
spawn rc=0

# polled with `sleep 15` in a loop (no background &); outcome file appeared after 15s
$ tail -n 1 state/outcomes/canary-srv.jsonl
{"ts": "2026-09-08T14:32:22Z", "session_id": "73da4fe2-a391-4bf9-8e71-f3309751e1bb", "kind": "result", "result_text": "Tue Sep  8 07:32:16 PM +05 2026\n\n**Result:** changed — none (task explicitly forbids file edits, including the journal). verified — `date` executed in `/home/altai/proga/fleet`. blocked — none. No background processes started.", "input_tokens": 2, "output_tokens": 88, "cache_creation_input_tokens": 9187, "cache_read_input_tokens": 40120, "model": "claude-opus-5", "transcript_path": "/home/altai/.claude/projects/-home-altai-proga-fleet/73da4fe2-a391-4bf9-8e71-f3309751e1bb.jsonl"}

$ fleet result canary-srv
-- tokens in=2 out=88 model=claude-opus-5
Tue Sep  8 07:32:16 PM +05 2026

**Result:** changed — none (task explicitly forbids file edits, including the journal). verified — `date` executed in `/home/altai/proga/fleet`. blocked — none. No background processes started.
```

### Step 3 — the ccgram-events check

```text
# volatile: host state — 2026-09-08 14:32 UTC
$ SID=$(python3 - <<'EOF'
import json;print(json.load(open('state/fleet.json'))['workers']['canary-srv']['session_id'])
EOF
)
$ echo "$SID"
73da4fe2-a391-4bf9-8e71-f3309751e1bb

$ grep -c "$SID" /home/altai/.ccgram/events.jsonl || printf 'no ccgram events for %s\n' "$SID"
0
```

**Result: 0.** The canary's session id does not appear anywhere in `~/.ccgram/events.jsonl`.
`--setting-sources project,local` excluded the user-level ccgram hooks registered in
`~/.claude/settings.json` on this `claude` 2.1.263 install, as designed. Not blocked; proceeding
per the brief.

### Step 4 — dispose

```text
# volatile: host state — 2026-09-08 14:32 UTC
$ fleet kill canary-srv --yes
canary-srv: killed
kill rc=0
```
