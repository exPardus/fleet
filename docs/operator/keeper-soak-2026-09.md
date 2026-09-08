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

## S2/S3 — window, dry-run, timer

Host: this box, `/home/altai/proga/fleet`, branch `server/persistent-fleet` at `92cec0a`.
`fleet init` already ran (Task 9). Window created by hand, keeper run twice by hand (dry-run then
real), timer deploy attempted via Ansible.

### Step 1 — interface window by hand, ccgram binding

```text
# volatile: host state — 2026-09-08 20:41 UTC (host clock)
$ tmux list-windows -t work -F '#{window_name} #{pane_current_command}'   # before
zsh zsh
zsh zsh
repo claude
claude claude

$ tmux new-window -d -t work -n fleet -c /home/altai/proga/fleet \
  'claude --permission-mode bypassPermissions "Read /home/altai/proga/fleet/docs/operator/server-interface-profile.md and follow it exactly."'
new-window rc=0

$ sleep 20
$ tmux list-windows -t work -F '#{window_name} #{pane_current_command}'
zsh zsh
zsh zsh
fleet claude
repo claude
claude claude

$ python3 -c "import json;d=json.load(open('/home/altai/.ccgram/state.json'));print(d.get('window_display_names'));print([k for k in d.get('chat_thread_bindings',{})])"
{'@0': 'zsh', '@7': 'tap', '@8': 'repo', '@9': 'fwdeploy', '@10': 'claude', '@12': 'dep2', '@13': 'dep3', '@14': 'codexlogin', '@15': 'codexauth', '@16': 'zsh', '@17': 'chk', '@18': 'dep4', '@19': 'fleet'}
['1219110869:1219110869:511347', ... 14 opaque thread-binding keys, no readable names ...]

$ tail -n 5 ~/.ccgram/events.jsonl | cut -c1-200
... {"event":"SessionStart","window_key":"work:@19","session_id":"e9fc7d5e-6c18-4e7d-8a05-dd9bd4b101f1", ...}
... {"event":"Stop","window_key":"work:@19","session_id":"e9fc7d5e-6c18-4e7d-8a05-dd9bd4b101f1", ...} (arrived after the ~60s wait)
```

`@19` -> `fleet` in `window_display_names` confirms ccgram bound the new window; `SessionStart`/
`Stop` events for `work:@19` confirm the session ran. `chat_thread_bindings` keys are opaque
chat:chat:thread ids with no window name attached, so binding was read off `window_display_names` +
events, not that map. Could not see the phone from this session (no phone access) -- did not send
`status` from it; recording only what the host shows, per the controller's ruling. Waited ~60s
foreground (20s + 40s, no `&`) before the real tick in Step 3. `tmux capture-pane -p -t work:fleet`
after the wait showed the full startup ritual report (open gates G-K1/G-K2/G-K4, no supervisor
claim, GOALS active, fleet dead and not revived, 1 dead worker, git clean and 17 ahead of main, no
hook errors, keeper timer not yet installed) ending in "Waiting."

### Step 2 — keeper dry-run

```text
# volatile: host state — 2026-09-08 20:42 UTC
$ sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --dry-run --fleet-home "$PWD"
[dry-run] supervisor-dead: KEEPER: supervisor dead (claim none). Report state; await operator before sup-spawn.
dry-run rc=0

$ sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --dry-run --fleet-home "$PWD"   # again, same
[dry-run] supervisor-dead: KEEPER: supervisor dead (claim none). Report state; await operator before sup-spawn.
dry-run rc=0
```

Matches the controller's prior verification exactly; no `would create` line (window already
existed); nothing typed into the window.

### Step 3 — one real tick

```text
# volatile: host state — 2026-09-08 20:42 UTC
$ sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --fleet-home "$PWD"
keeper: paged supervisor-dead
real-tick rc=0

$ cat state/keeper/last-page.json
{
 "_hook_error_lines": 0,
 "supervisor-dead": {
  "at": 1788882140.5814927,
  "fingerprint": "none:claim none"
 }
}

$ sh bin/hooks/run_py.sh bin/fleet_keeper.py --once --fleet-home "$PWD"   # second run
second-tick rc=0
(no stdout -- dedup confirmed)
```

`tmux capture-pane -p -t work:fleet | tail -n 30` after the tick and a further ~15s wait:

```text
❯ KEEPER: supervisor dead (claim none). Report state; await operator before sup-spawn.

  Ran 1 shell command

● Keeper page confirmed.

  Keeper saw: supervisor dead, claim none.

  Confirmed: fleet sup-status = no claim, GOALS active. fleet doctor all PASS, no pending decision, no wedge, no hook errors. One worker canary-srv dead (70 min). One untracked
  claude session f83c8b56 (not fleet's). Git clean, 17 commits ahead of main, unpushed.

  Recommend: dispatch supervisor/briefs/server-standing.md via fleet sup-spawn --task @supervisor/briefs/server-standing.md --setting-sources project,local. Reply revive to do it. No
  action taken.

✻ Cooked for 11s · done 8:42 PM
```

The interface session read the `KEEPER:` line, investigated with read-only verbs only, posted one
message, took no mutating action -- exactly per `server-interface-profile.md`.

### Step 4 — Ansible timer deploy: BLOCKED at stage (a)

```text
# volatile: host state — 2026-09-08 20:43 UTC
$ cd /home/altai/china-infra && git status --short
 M inventory/group_vars/all/secrets.sops.yml
```
(pre-existing dirty file from another live session; not touched, not stashed.)

```text
$ ansible-playbook playbooks/work.yml --tags fleet_keeper --check --diff 2>&1 | tail -60
... (preflight plays skip) ...
PLAY [Configure kz-work (Headscale, DERP #1, devbox, monitoring)] **************
TASK [Gathering Facts] *********************************************************
ok: [kz-work]
TASK [golang : Install the pinned Go toolchain] ********************************
included: /home/altai/china-infra/roles/golang/tasks/install.yml for kz-work
TASK [golang : Look for an existing Go toolchain] ******************************
ok: [kz-work]
TASK [golang : Ask the installed toolchain which version it is] ****************
skipping: [kz-work]
TASK [golang : Decide whether the pinned toolchain has to be installed] ********
ok: [kz-work]
TASK [golang : Report that the pinned Go toolchain is already installed] *******
skipping: [kz-work]
TASK [golang : Fetch the go.dev release index] *********************************
skipping: [kz-work]
TASK [golang : Pick the linux-amd64 entry out of the index for go1.27.1.linux-amd64.tar.gz] ***
ok: [kz-work]
TASK [golang : Fail unless go.dev publishes the pinned digest for this release] ***
[ERROR]: Task failed: Action failed: go.dev publishes sha256 "" for go1.27.1.linux-amd64.tar.gz, but roles/golang/defaults/main.yml pins "63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445". An empty value means go1.27.1 is not in https://go.dev/dl/?mode=json&include=all at all -- check versions.go in inventory/group_vars/all/vars.yml. A DIFFERENT value means upstream re-cut the release under the same file name, or somebody is between this host and go.dev. Do not deploy either way.
Origin: /home/altai/china-infra/roles/golang/tasks/install.yml:71:3
fatal: [kz-work]: FAILED! => assertion: golang_published_sha256 | length == 64, changed: false, evaluated_to: false

PLAY RECAP *********************************************************************
kz-work                    : ok=5    changed=0    unreachable=0    failed=1    skipped=21   rescued=0    ignored=0
```

The `golang` role's preflight tasks ran despite `--tags fleet_keeper` (apparently tagged `always`
or otherwise unfiltered) and aborted the play on an unrelated, network-dependent digest assertion
(go.dev no longer serves a sha256 for the pinned `go1.27.1` release) *before* any `fleet_keeper`
task ran. `changed=0`, no diff was produced for any file. Per the controller's ruling ("Proceed to
(b) ONLY if every changed/created file is under `~/.config/systemd/user/fleet-keeper.*`... if the
check shows changes to any other host file... STOP... reply BLOCKED"): there is no diff to confirm
that condition against, so stage (b) (the real `ansible-playbook ... --tags fleet_keeper` without
`--check`) was **not run**. The timer is **not deployed**. `systemctl --user list-timers
fleet-keeper.timer` / `journalctl --user -u fleet-keeper.service` were not run (nothing to verify
yet). `china-infra` left untouched beyond this read-only check and two `git status` calls; still
only the pre-existing dirty `secrets.sops.yml`.

This is an existing, unrelated `china-infra` infra issue (an upstream Go release digest gone
missing) blocking every tagged play on this host, not something this task introduced. It needs a
decision from whoever owns `china-infra` before the fleet_keeper timer diff can even be evaluated.
