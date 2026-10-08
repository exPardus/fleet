# fleet CLI reference

<!-- Generated from bin/fleet.py build_parser() by tools/gen_cli_reference.py.
     Do not edit by hand. Regenerate with: python tools/gen_cli_reference.py -->

Every verb and option below is printed by the parser itself. For the workflow
behind the verbs, read [getting-started.md](getting-started.md); for the
behavioural contract, read [SPEC.md](SPEC.md).

Verbs marked hidden in the parser are not listed here or in top-level
`fleet --help` output.

## Global options

```text
usage: fleet <verb> [options]

claude-fleet manager CLI

global: --fleet-home <PATH> selects which fleet home to act on (accepted in any position; see docs/specs/multi-fleet.md §5)
```

## Verbs

- [`fleet home`](#fleet-home) — print the resolved FLEET_HOME path
- [`fleet knowledge`](#fleet-knowledge) — print knowledge/INDEX.md
- [`fleet homes`](#fleet-homes) — list, add or retire fleet homes
- [`fleet init`](#fleet-init) — create a fleet home in cwd without registering it; --home also registers a named home
- [`fleet spawn`](#fleet-spawn) — spawn a new worker session
- [`fleet status`](#fleet-status) — show worker status table
- [`fleet peek`](#fleet-peek) — digest of recent stream events
- [`fleet result`](#fleet-result) — final result text of last completed turn
- [`fleet pr-poll`](#fleet-pr-poll) — read a GitHub PR head SHA and report changes from a recorded SHA
- [`fleet address`](#fleet-address) — exact native session name for SendMessage `to`
- [`fleet wait`](#fleet-wait) — block until turn(s) end
- [`fleet send`](#fleet-send) — send a message to a worker (mailbox or resume)
- [`fleet mail`](#fleet-mail) — read-only verification of authenticated Interface mail
  - [`fleet mail verify`](#fleet-mail-verify) — verify one Interface-mail receipt and print its canonical body
- [`fleet codex-respond`](#fleet-codex-respond) — answer one current native Codex approval/input request exactly once
- [`fleet interrupt`](#fleet-interrupt) — kill a worker's running turn
- [`fleet release`](#fleet-release) — release an attached worker back to idle
- [`fleet respawn`](#fleet-respawn) — fresh session for a worker (context-reset lever)
- [`fleet resume-limited`](#fleet-resume-limited) — relaunch limited workers whose reset horizon has passed
- [`fleet kill`](#fleet-kill) — interrupt (if running) and mark a worker dead
- [`fleet clean`](#fleet-clean) — remove dead workers and their logs/mailboxes/journals
- [`fleet archive`](#fleet-archive) — auto-archive terminal-state native workers past a TTL
- [`fleet autoclean`](#fleet-autoclean) — staleness sweep: archive TTL pass + fleet-owned daemon-husk rm (docs/specs/autoclean.md)
- [`fleet index`](#fleet-index) — per-project symbol index (opt-in)
  - [`fleet index init`](#fleet-index-init) — opt in: create .fleet-index/ and run the first build
  - [`fleet index build`](#fleet-index-build) — rebuild an existing index
  - [`fleet index update`](#fleet-index-update) — refresh named files only
  - [`fleet index status`](#fleet-index-status) — counts and stale shards
- [`fleet land`](#fleet-land) — stage a lane result, rebase its branch, and run its checks
- [`fleet brief`](#fleet-brief) — render a validated brief from a task file
- [`fleet q`](#fleet-q) — query this project's symbol index (M2)
- [`fleet doctor`](#fleet-doctor) — run fleet health checks
- [`fleet sup-boot`](#fleet-sup-boot) — supervisor boot ritual: epoch check, claim decision, boot bundle (spec §4)
- [`fleet sup-spawn`](#fleet-sup-spawn) — dispatch the gen-0 supervisor body under sup|<launch-id>|boot (three-tier §10.1); its first act is `fleet sup-boot`
- [`fleet sup-checkpoint`](#fleet-sup-checkpoint) — append a supervisor journal checkpoint (claim holder only) + refresh heartbeat
- [`fleet journal-roll`](#fleet-journal-roll) — roll older supervisor journal entries into history
- [`fleet interface-register`](#fleet-interface-register) — register this tmux pane or Claude session as the interface
- [`fleet watch`](#fleet-watch) — wait for mail, lane, mcx, memory, or disk events
- [`fleet relay-ack`](#fleet-relay-ack) — append an interface relay and acknowledge one mail file
- [`fleet wave-close`](#fleet-wave-close) — reap, floor, account, land, push, and notify one wave boundary
- [`fleet sup-heartbeat`](#fleet-sup-heartbeat) — refresh the supervisor claim heartbeat (no journal write)
- [`fleet sup-release`](#fleet-sup-release) — release the supervisor claim cleanly (claim holder only); the next sup-boot claims fresh with no seizure
- [`fleet sup-status`](#fleet-sup-status) — read-only supervisor claim/handshake status
- [`fleet sup-guard`](#fleet-sup-guard) — one-line two-live-body verdict before supervisor revival
- [`fleet sup-reconcile`](#fleet-sup-reconcile) — explicitly reconcile a native Codex supervisor after host restart; never creates a thread or turn
- [`fleet sup-context`](#fleet-sup-context) — read this session's own context occupancy vs its tier's context band -- supervisor 350-400k, worker 250-300k (§11.2)
- [`fleet sup-decision`](#fleet-sup-decision) — operator-gate routing (§8): --raise (supervisor parks a decision), --answer (interface answers), --clear, or show
- [`fleet sup-notify`](#fleet-sup-notify) — type one `SUPERVISOR: <text>` line into the interface tmux window (claim holder only): the graceful-end announcement the interface acts on
- [`fleet sup-handoff-begin`](#fleet-sup-handoff-begin) — dispatch a handoff successor (claim holder only)
- [`fleet sup-handoff-complete`](#fleet-sup-handoff-complete) — verify HANDSHAKE and transfer the claim
- [`fleet sup-handoff-abort`](#fleet-sup-handoff-abort) — abort a handoff: stop the limbo successor, resume duty

### fleet home

```text
usage: fleet home [-h] [--tag]

options:
  -h, --help  show this help message and exit
  --tag       print the home's statusline tag instead of its path -- the tag
              the bar shows in `[fleet:<tag>]`)
```

### fleet knowledge

```text
usage: fleet knowledge [-h]

options:
  -h, --help  show this help message and exit
```

### fleet homes

```text
usage: fleet homes [-h] [--add PATH | --retire PATH]

options:
  -h, --help     show this help message and exit
  --add PATH     append <PATH> to ~/.claude/fleet-homes.list (must be an
                 initialized fleet home)
  --retire PATH  append a retirement record for <PATH> (the home need not
                 still exist)
```

### fleet init

```text
usage: fleet init [-h] [--nonce NONCE] [--home PATH] [--statusline] [--chain]
                  [--force]

options:
  -h, --help     show this help message and exit
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
  --home PATH    initialise a fleet home at PATH (creates its
                 state/fleet.json) and record it in ~/.claude/fleet-homes.list
                 -- DESTRUCTIVE: the append is irreversible, only the fold
                 reverses it
  --statusline   also install fleet's statusline into ~/.claude/settings.json
  --chain        with --statusline: keep an existing foreign statusline and
                 print fleet's row beneath it
  --force        with --statusline: overwrite a foreign statusline
```

### fleet spawn

```text
usage: fleet spawn [-h] --dir DIR --task TASK
                   [--mode {bypass,accept,dontask,plan,omit}] [--model MODEL]
                   [--effort {low,medium,high,xhigh}]
                   [--codex-adapter {native,mcx}]
                   [--max-budget-usd MAX_BUDGET_USD]
                   [--setting-sources SETTING_SOURCES] [--nonce NONCE]
                   [--force-band] [--token-ceiling TOKEN_CEILING]
                   [--category CATEGORY] [--context CONTEXT]
                   name

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --dir DIR
  --task TASK
  --mode {bypass,accept,dontask,plan,omit}
  --model MODEL
  --effort {low,medium,high,xhigh}
                        legacy mcx reasoning effort; ignored by the native
                        Codex adapter
  --codex-adapter {native,mcx}
                        Codex transport for codex:<model> (default: native;
                        use mcx for the legacy compatibility adapter)
  --max-budget-usd MAX_BUDGET_USD
  --setting-sources SETTING_SOURCES
  --nonce NONCE         the current supervisor generation (claim-nonce §5.3):
                        clears §7's claim gate for a mutating verb while a
                        fresh claim is held, and proves the lineage that owns
                        a rotated body's workers (§6.2)
  --force-band          override the supervisor soft context-band refusal;
                        never the hard ceiling
  --token-ceiling TOKEN_CEILING
  --category CATEGORY
  --context CONTEXT     comma-separated source paths under --dir whose fleet-
                        index digests are injected into the prompt (§7);
                        ignored when the project has no index
```

### fleet status

```text
usage: fleet status [-h] [--json] [--stale-ok] [--all] [name]

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      print the status snapshot as JSON
  --stale-ok  read-only fast path: no PID probe, no lock, no write (last-
              committed state; used by the statusline)
  --all       include archived (tombstoned) workers, flagged 'archived'
```

### fleet peek

```text
usage: fleet peek [-h] [-n LINES] name

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  -n LINES, --lines LINES
```

### fleet result

```text
usage: fleet result [-h] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
```

### fleet pr-poll

```text
usage: fleet pr-poll [-h] (--since SINCE | --since-file PATH) [--repo REPO]
                     [--json]
                     pr

positional arguments:
  pr                    pull request number, URL, or gh PR selector

options:
  -h, --help            show this help message and exit
  --since SINCE, --recorded-sha SINCE
                        recorded commit SHA to compare (never updated)
  --since-file PATH     read the recorded SHA from a small local file
  --repo REPO           OWNER/REPO passed to gh (otherwise gh resolves it)
  --json                print the bounded result as JSON
```

### fleet address

```text
usage: fleet address [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json
```

### fleet wait

```text
usage: fleet wait [-h] [--any | --all] [--timeout TIMEOUT] names [names ...]

positional arguments:
  names

options:
  -h, --help         show this help message and exit
  --any
  --all
  --timeout TIMEOUT
```

### fleet send

```text
usage: fleet send [-h] [--nonce NONCE] [--force-band] name message

positional arguments:
  name
  message

options:
  -h, --help     show this help message and exit
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
  --force-band   override the supervisor soft context-band refusal; never the
                 hard ceiling
```

### fleet mail

```text
usage: fleet mail [-h] {verify} ...

positional arguments:
  {verify}
    verify    verify one Interface-mail receipt and print its canonical body

options:
  -h, --help  show this help message and exit
```

#### fleet mail verify

```text
usage: fleet mail verify [-h] mail_id

positional arguments:
  mail_id

options:
  -h, --help  show this help message and exit
```

### fleet codex-respond

```text
usage: fleet codex-respond [-h] [--nonce NONCE] name request_id decision

positional arguments:
  name
  request_id
  decision       literal offered choice, JSON object, or @file

options:
  -h, --help     show this help message and exit
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
```

### fleet interrupt

```text
usage: fleet interrupt [-h] [--nonce NONCE] name

positional arguments:
  name

options:
  -h, --help     show this help message and exit
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
```

### fleet release

```text
usage: fleet release [-h] [--nonce NONCE] name

positional arguments:
  name

options:
  -h, --help     show this help message and exit
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
```

### fleet respawn

```text
usage: fleet respawn [-h] [--task TASK] [--force] [--force-band] [--yes]
                     [--nonce NONCE] [--max-budget-usd MAX_BUDGET_USD]
                     [--setting-sources SETTING_SOURCES]
                     [--token-ceiling TOKEN_CEILING]
                     name

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --task TASK
  --force
  --force-band          with --task: override the supervisor soft context-band
                        refusal; never the hard ceiling
  --yes                 confirm respawning a worker this session did not spawn
  --nonce NONCE         the current supervisor generation (claim-nonce §5.3):
                        clears §7's claim gate for a mutating verb while a
                        fresh claim is held, and proves the lineage that owns
                        a rotated body's workers (§6.2)
  --max-budget-usd MAX_BUDGET_USD
  --setting-sources SETTING_SOURCES
  --token-ceiling TOKEN_CEILING
```

### fleet resume-limited

```text
usage: fleet resume-limited [-h] [--force-now] [--nonce NONCE] [name]

positional arguments:
  name

options:
  -h, --help     show this help message and exit
  --force-now    resume a named worker even before its horizon / with an
                 unknown horizon
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
```

### fleet kill

```text
usage: fleet kill [-h] [--yes] [--nonce NONCE] name

positional arguments:
  name

options:
  -h, --help     show this help message and exit
  --yes          confirm killing a worker this session did not spawn
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
```

### fleet clean

```text
usage: fleet clean [-h] [--yes] [--nonce NONCE] [--dead-only | --tombstones]

options:
  -h, --help     show this help message and exit
  --yes          confirm deleting workers this session did not spawn
  --nonce NONCE  the current supervisor generation (claim-nonce §5.3): clears
                 §7's claim gate for a mutating verb while a fresh claim is
                 held, and proves the lineage that owns a rotated body's
                 workers (§6.2)
  --dead-only    sweep only confirmed-dead workers; spare archived tombstones
  --tombstones   sweep only archived tombstones; touch nothing else
```

### fleet archive

```text
usage: fleet archive [-h] [--ttl-hours TTL_HOURS] [--dry-run] [--nonce NONCE]
                     [name]

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --ttl-hours TTL_HOURS
  --dry-run
  --nonce NONCE         the current supervisor generation (claim-nonce §5.3):
                        clears §7's claim gate for a mutating verb while a
                        fresh claim is held, and proves the lineage that owns
                        a rotated body's workers (§6.2)
```

### fleet autoclean

```text
usage: fleet autoclean [-h] [--ttl-hours TTL_HOURS]
                       [--expire-tombstones-hours EXPIRE_TOMBSTONES_HOURS]
                       [--dry-run] [--fleet-home FLEET_HOME]

options:
  -h, --help            show this help message and exit
  --ttl-hours TTL_HOURS
                        tier-1 archive TTL (default 24)
  --expire-tombstones-hours EXPIRE_TOMBSTONES_HOURS
                        tier 3 (default OFF): drop registry tombstones older
                        than this; files in logs/archive/ are never deleted
  --dry-run
  --fleet-home FLEET_HOME
                        explicit FLEET_HOME override for a caller whose
                        environment does not carry one
```

### fleet index

```text
usage: fleet index [-h] {init,build,update,status} ...

positional arguments:
  {init,build,update,status}
    init                opt in: create .fleet-index/ and run the first build
    build               rebuild an existing index
    update              refresh named files only
    status              counts and stale shards

options:
  -h, --help            show this help message and exit
```

#### fleet index init

```text
usage: fleet index init [-h] [--path PATH]

options:
  -h, --help   show this help message and exit
  --path PATH  index root (default: the current directory)
```

#### fleet index build

```text
usage: fleet index build [-h] [--force] [--path PATH]

options:
  -h, --help   show this help message and exit
  --force      re-parse every file, not just the changed ones
  --path PATH  index root (default: the current directory)
```

#### fleet index update

```text
usage: fleet index update [-h] --files FILES [--path PATH]

options:
  -h, --help     show this help message and exit
  --files FILES  comma-separated source paths, relative to the index root
  --path PATH    index root (default: the current directory)
```

#### fleet index status

```text
usage: fleet index status [-h] [--path PATH]

options:
  -h, --help   show this help message and exit
  --path PATH  index root (default: the current directory)
```

### fleet land

```text
usage: fleet land [-h] lane

positional arguments:
  lane        lane name, such as w78

options:
  -h, --help  show this help message and exit
```

### fleet brief

```text
usage: fleet brief [-h] item

positional arguments:
  item        task file path or task item name

options:
  -h, --help  show this help message and exit
```

### fleet q

```text
usage: fleet q [-h] [--outline PATH] [--src] [--path GLOB]
               [--kind {func,class,method,const,section}] [--limit N]
               [--no-refresh]
               [query]

positional arguments:
  query                 exact name, dotted name, or a `*`/`?` glob over names

options:
  -h, --help            show this help message and exit
  --outline PATH        print one file's digest instead of running a query;
                        takes only --no-refresh
  --src                 the query must resolve to exactly one symbol; print
                        its source, sliced from the file
  --path GLOB           restrict hits to source paths matching this glob (the
                        config.toml dialect: `**`-aware, case-sensitive)
  --kind {func,class,method,const,section}
                        restrict hits to one symbol kind
  --limit N             cap printed hits (default 20); a truncated list is
                        still exit 0
  --no-refresh          never write anything: stale and orphan hits are
                        withheld rather than repaired
```

### fleet doctor

```text
usage: fleet doctor [-h] [--repair]

options:
  -h, --help  show this help message and exit
  --repair    quarantine a corrupt state/fleet.json and reconcile legacy dead-
              suspected native Codex rows whose exact durable and live turn
              evidence both say completed. Without this flag `doctor` only
              reports
```

### fleet sup-boot

```text
usage: fleet sup-boot [-h] [--sid SID] [--nonce NONCE]
                      [--handoff-inc HANDOFF_INC]
                      [--handoff-token HANDOFF_TOKEN]

options:
  -h, --help            show this help message and exit
  --sid SID             override caller session id (default:
                        CLAUDE_CODE_SESSION_ID)
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
  --handoff-inc HANDOFF_INC
                        handoff-successor mode: write HANDSHAKE with this
                        incarnation id; no claim action
  --handoff-token HANDOFF_TOKEN
                        handoff-successor mode: the one-shot token from the
                        predecessor's task file; its hash is written into
                        HANDSHAKE so complete can verify this body without a
                        sid comparison (§6.4)
```

### fleet sup-spawn

```text
usage: fleet sup-spawn [-h] --task TASK [--model MODEL]
                       [--codex-adapter {native}]
                       [--permission-mode {bypass,accept,dontask,plan,omit}]
                       [--nonce NONCE] [--force-band]
                       [--setting-sources SETTING_SOURCES]

options:
  -h, --help            show this help message and exit
  --task TASK           campaign brief, text or @file -- delivered below the
                        boot ritual in the task file
  --model MODEL         tier alias for the supervisor session (default:
                        resolve_model_for_role('supervisor') from the GOALS
                        tier policy; unset policy omits --model, §3.3(d))
  --codex-adapter {native}
                        Codex supervisor transport (codex:<model> defaults to
                        native; omission with other models preserves the
                        Claude route)
  --permission-mode {bypass,accept,dontask,plan,omit}
                        fleet mode name (default: bypass, §10.2 earned-
                        privilege)
  --nonce NONCE         the current supervisor generation (claim-nonce §5.3):
                        clears §7's claim gate for a mutating verb while a
                        fresh claim is held, and proves the lineage that owns
                        a rotated body's workers (§6.2)
  --force-band          override the supervisor soft context-band refusal;
                        never the hard ceiling
  --setting-sources SETTING_SOURCES
```

### fleet sup-checkpoint

```text
usage: fleet sup-checkpoint [-h] [--kind {CHECKPOINT,PROPOSAL,PARKED}]
                            [--wake-when WAKE_CONDITION] [--sid SID]
                            [--nonce NONCE]
                            body

positional arguments:
  body                  checkpoint text, or @file

options:
  -h, --help            show this help message and exit
  --kind {CHECKPOINT,PROPOSAL,PARKED}
  --wake-when WAKE_CONDITION, --wake-condition WAKE_CONDITION
                        optional condition that ends a PARKED checkpoint
  --sid SID             override caller session id
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```

### fleet journal-roll

```text
usage: fleet journal-roll [-h]

options:
  -h, --help  show this help message and exit
```

### fleet interface-register

```text
usage: fleet interface-register [-h] [--session-id SESSION_ID]
                                [--codex-thread CODEX_THREAD]

options:
  -h, --help            show this help message and exit
  --session-id SESSION_ID
                        session id for registration when outside tmux
                        (default: environment)
  --codex-thread CODEX_THREAD
                        provider-minted current Codex thread; requires
                        explicit --fleet-home and matching public
                        caller/session/source evidence
```

### fleet watch

```text
usage: fleet watch [-h] [--fleet-home PATH] [--mcx-dir DIR]
                   [--mem-floor-mb MEM_FLOOR_MB]
                   [--disk-floor-gb DISK_FLOOR_GB] [--interval INTERVAL]
                   [--timeout TIMEOUT]

options:
  -h, --help            show this help message and exit
  --fleet-home PATH     home to watch; repeatable
  --mcx-dir DIR         mcx state directory; repeatable
  --mem-floor-mb MEM_FLOOR_MB
  --disk-floor-gb DISK_FLOOR_GB
  --interval INTERVAL
  --timeout TIMEOUT
```

### fleet relay-ack

```text
usage: fleet relay-ack [-h] --mail FILE --line TEXT [--mirror-log PATH]

options:
  -h, --help         show this help message and exit
  --mail FILE
  --line TEXT
  --mirror-log PATH  additional log to append; repeatable
```

### fleet wave-close

```text
usage: fleet wave-close [-h] [--base BASE] --changelog CHANGELOG
                        [--alias MERGE_LANE=WORKER] [--sid SID]
                        [--nonce NONCE]

options:
  -h, --help            show this help message and exit
  --base BASE           base commit SHA for the throughput diff (default:
                        previous wave-close commit)
  --changelog CHANGELOG
                        CHANGELOG sentences, or @file containing them
  --alias MERGE_LANE=WORKER
                        join a merge(<lane>) token to the registry worker it
                        landed from (renamed or re-dispatched lanes);
                        repeatable
  --sid SID             override caller session id
  --nonce NONCE         the current supervisor generation (claim-nonce §5.3):
                        clears §7's claim gate for a mutating verb while a
                        fresh claim is held, and proves the lineage that owns
                        a rotated body's workers (§6.2)
```

### fleet sup-heartbeat

```text
usage: fleet sup-heartbeat [-h] [--sid SID] [--nonce NONCE]

options:
  -h, --help     show this help message and exit
  --sid SID      override caller session id
  --nonce NONCE  the generation this body was last given (claim-nonce §5.3);
                 the ONLY presentation channel -- there is no env-var fallback
```

### fleet sup-release

```text
usage: fleet sup-release [-h] [--reason REASON] [--sid SID] [--nonce NONCE]

options:
  -h, --help       show this help message and exit
  --reason REASON  short note recorded in the journal and the claim
  --sid SID        override caller session id
  --nonce NONCE    the generation this body was last given (claim-nonce §5.3);
                   the ONLY presentation channel -- there is no env-var
                   fallback
```

### fleet sup-status

```text
usage: fleet sup-status [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json
```

### fleet sup-guard

```text
usage: fleet sup-guard [-h] [--do] [--json]

options:
  -h, --help  show this help message and exit
  --do        re-verify immediately, then send WAKE; OK does nothing;
              DISPATCH/PAGE remain interface verdicts
  --json      include read-only guard detail as one JSON line
```

### fleet sup-reconcile

```text
usage: fleet sup-reconcile [-h]

options:
  -h, --help  show this help message and exit
```

### fleet sup-context

```text
usage: fleet sup-context [-h] [--sid SID] [--json]

options:
  -h, --help  show this help message and exit
  --sid SID   override caller session id (out-of-band inspection)
  --json
```

### fleet sup-decision

```text
usage: fleet sup-decision [-h] [--raise QUESTION] [--context-ref CONTEXT_REF]
                          [--answer TEXT] [--clear] [--json] [--sid SID]
                          [--nonce NONCE]

options:
  -h, --help            show this help message and exit
  --raise QUESTION      supervisor routes an operator-only decision and parks
                        (claim holder only; one open at a time)
  --context-ref CONTEXT_REF
                        a pointer (file#L, journal ref) the interface reads
                        for context
  --answer TEXT         the interface tier writes the operator's decision
  --clear               remove the open decision (consumed)
  --json
  --sid SID             override caller session id (for --raise)
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```

### fleet sup-notify

```text
usage: fleet sup-notify [-h] [--tmux-session TMUX_SESSION] [--window WINDOW]
                        [--dry-run] [--sid SID] [--nonce NONCE]
                        text

positional arguments:
  text                  the line's text -- prefixed with `SUPERVISOR: ` and
                        sanitised to one printable line before it is typed

options:
  -h, --help            show this help message and exit
  --tmux-session TMUX_SESSION
                        tmux session holding the interface window (default:
                        work)
  --window WINDOW       tmux window name (default: fleet)
  --dry-run             print the exact bytes and stop: no lock, no claim
                        read, no write, no tmux
  --sid SID             override caller session id
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```

### fleet sup-handoff-begin

```text
usage: fleet sup-handoff-begin [-h] [--model MODEL]
                               [--permission-mode {bypass,accept,dontask,plan,omit}]
                               [--setting-sources SETTING_SOURCES] [--sid SID]
                               [--nonce NONCE]

options:
  -h, --help            show this help message and exit
  --model MODEL         model for the successor session (default: inherit the
                        validated predecessor; refuses if unavailable unless
                        explicitly supplied)
  --permission-mode {bypass,accept,dontask,plan,omit}
                        fleet mode name for the successor session (default:
                        inherit the predecessor; refuses if unavailable)
  --setting-sources SETTING_SOURCES
                        Claude setting-source selection for the successor
                        (default: inherit the validated predecessor; refuses
                        if unavailable unless explicitly supplied)
  --sid SID             override caller session id
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```

### fleet sup-handoff-complete

```text
usage: fleet sup-handoff-complete [-h] --expect-inc EXPECT_INC
                                  [--expect-sid EXPECT_SID] [--sid SID]
                                  [--nonce NONCE]

options:
  -h, --help            show this help message and exit
  --expect-inc EXPECT_INC
  --expect-sid EXPECT_SID
                        optional: warn (do not refuse) if the HANDSHAKE sid
                        differs
  --sid SID             override caller session id
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```

### fleet sup-handoff-abort

```text
usage: fleet sup-handoff-abort [-h] [--successor-sid SUCCESSOR_SID]
                               [--successor-inc SUCCESSOR_INC] [--retire-all]
                               [--force] [--sid SID] [--nonce NONCE]

options:
  -h, --help            show this help message and exit
  --successor-sid SUCCESSOR_SID
                        sid of the limbo successor to stop
  --successor-inc SUCCESSOR_INC
                        incarnation id of the pending successor; retires a
                        stale entry that never recorded a sid
  --retire-all          retire EVERY pending entry that names no session
                        (resolvable-stale, superseded, unreadable); stops
                        nothing, reports what still stands
  --force               also retire an entry that records no sid and cannot be
                        aged (unreadable minted_at), which no other verb would
                        ever retire; never stops a session, and is DECLINED on
                        an entry whose minted_at reads fine
  --sid SID             override caller session id
  --nonce NONCE         the generation this body was last given (claim-nonce
                        §5.3); the ONLY presentation channel -- there is no
                        env-var fallback
```
