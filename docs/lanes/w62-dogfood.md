# Lane `w62-dogfood` — the second fleet home, proven end to end, and the append withheld

**Branch** `w62/dogfood`, based at `294315d`. **Worktree** `/home/altai/proga/fleet-w62-dogfood`.
**Date** 2026-09-10. Every line below is marked MEASURED or BELIEVED.

---

## 0. Verdict, before the evidence

**MEASURED.** All six proofs in §3 of the brief were driven. Five passed, one (the keeper) came
back NEGATIVE — the keeper cannot be pointed at a second home at all.

**MEASURED.** `/home/altai/proga/fleet-dogfood` exists, is a git repo with a README, **is** an
initialized fleet home (`state/fleet.json` exists and parses), and has one real Sonnet worker in
its registry that ran a turn, wrote its file, and left an outcome record. It is left in place per §6.

**MEASURED, AND IT IS THE FINDING THAT MATTERS.** `~/.claude/fleet-homes.list` **is still absent.
The one destructive act this lane was licensed to perform was NOT performed.** Brief §5 named the
condition under which that is the correct outcome — *"if the append does something broader than
register one home … that is a gate, not a step. File the draft text and STOP"* — and the condition
is met: **the first append to that file arms `docs/specs/multi-fleet.md` §5's wrong-home guard
machine-wide, and the session it breaks is the server interface tier.** §1 below is the receipt.

Everything in §3 was therefore driven with `HOME` redirected to a scratch directory, so the append
landed in a sandbox list. §5 enumerates every invocation and which home it actually touched. The
sandboxed/real split is stated per command and never mixed.

**BELIEVED (a judgement, not a measurement):** stopping was the right call. The append is
irreversible (§4 of the spec: append-only forever; only `homes --retire` folds it out, and §6 of the
brief forbids retiring). The cost of stopping wrongly is a lane that delivers sandboxed evidence
instead of live evidence. The cost of proceeding wrongly is a production supervisor loop that
starts refusing its own revival verb, with no undo. The asymmetry is not close.

---

## 1. THE GATE — draft text for the supervisor to file

I file no gates myself (`sup-decision` is single-occupancy). This is the draft.

> **G-?? — The first append to `~/.claude/fleet-homes.list` arms §5's wrong-home guard for the
> whole machine, and the interface tier is what it breaks. Rule before the append is made.**
>
> *(Raised 2026-09-10 by lane `w62-dogfood`, which was licensed by the DOGFOOD ruling to make that
> append and declined to, under brief §5's own stop condition. Report: `docs/lanes/w62-dogfood.md`.
> The second home at `/home/altai/proga/fleet-dogfood` is built, proven and waiting; the append is
> the only step not taken, and it is one command.)*
>
> **What was measured, in a sealed sandbox — scratch `HOME` *and* a copied install root, so both
> homes in the population were throwaways and no live home was read or written:**
>
> ```text
> $ fleet archive no-such-worker-xyz          # ONE home in the population
> fleet: unknown worker: 'no-such-worker-xyz'
>
> $ fleet init --home <second>                # ...then, verbatim the same command:
> $ fleet archive no-such-worker-xyz
> fleet: `archive` destroys evidence or sessions and nothing recovers it, this machine runs 2
> fleets, and no `--fleet-home` and no session membership chose this home: […]
> Name the home you mean with `--fleet-home <PATH>`.
> ```
>
> `multi_fleet_arming` moves `population_below_two` → `population_at_least_two`;
> `_apply_wrong_home_guard` then refuses every DESTRUCTIVE verb resolved at §5 step 3 (env) or
> step 4 (legacy). That tuple is `clean`, `archive`, `autoclean`, `doctor --repair`, `sup-boot`,
> `sup-spawn`, `sup-checkpoint`, `sup-release`, `sup-handoff-{begin,complete,abort}`,
> `sup-decision --clear`, `homes --add/--retire`, `init --home`.
>
> **Only one of the brief's two clauses fires, and the distinction should survive into the ruling.**
> `fleet home` printed the legacy install root before *and* after the append — what a bare `fleet`
> **resolves to** is unchanged. What changes is whether the verb is **allowed to run**.
>
> **Who is hit.** Not workers: a fleet-spawned worker's sid is in the registry, so §5 step 2 answers
> and *"lookup-hit resolutions are exempt"*. Not the keeper: its systemd unit passes
> `--fleet-home /home/altai/proga/fleet` and the only verb it shells out to is `sup-status`, which
> is ORDINARY. **The INTERFACE tier is hit.** `bin/fleet_keeper.py:704` launches it as a bare
> `claude --permission-mode bypassPermissions "Read <profile> …"` — never through `fleet spawn` — so
> it holds no registry membership, step 2 cannot exempt it, and it lands on step 4. Its own profile
> has it run `fleet autoclean` as startup ritual step 1
> (`docs/operator/server-interface-profile.md:9`) and `fleet sup-spawn` on every `supervisor-dead`
> page (`:31`, `:45`, `:51`). **Both are DESTRUCTIVE. Post-append, both refuse.** Given G-K6, the
> supervisor-revival path is the one thing on this host that most needs to keep working.
>
> **And the append is not merely a cost — it is also the containment mechanism.** Measured with a
> real worker in the second home: a bare `fleet` call carrying that worker's sid resolves to the
> **live** home while the second home is unlisted (step 2 misses, because the population is
> `listed ∪ legacy`), and to its **own** home once listed. So *not* appending leaves the second
> home's own sessions leaking into the live fleet on any bare call. The two effects are one
> ruling, not two.
>
> **Readings.**
> - **A — append, and fix the interface.** Add `--fleet-home /home/altai/proga/fleet` to the
>   interface profile's `autoclean` and `sup-spawn` lines (step 1 exempts both the terminus and the
>   guard). Cost: an edit to a live operator surface, and every future surface that types a bare
>   destructive verb inherits the same trap. This is the reading the design intends — §5's arming
>   paragraph exists precisely to make a two-fleet machine demand an explicit home.
> - **B — append, and give the interface membership.** Make the keeper launch the interface through
>   a path that registers it, so step 2 exempts it the way it exempts workers. Cost: new mechanism;
>   the interface is deliberately not a worker.
> - **C — do not append; reach the second home by `--fleet-home` only.** Cost: measured above —
>   the second home's own workers are not contained, and `fleet homes` never lists it.
> - **D — append, and narrow the arming rule** so a home with no live workers does not count.
>   Cost: an edit to a ratified section of `docs/specs/multi-fleet.md`, and it re-opens
>   *"indeterminacy never selects the permissive branch"*. Recommended by nobody here.
>
> **The lane's recommendation: A**, with the interface-profile edit landed *before* the append, not
> after — the window between them is exactly when a `supervisor-dead` page would fail to revive.

**BELIEVED:** the ordering sentence at the end is the part most worth keeping. Whichever reading is
taken, the edit and the append are not commutative.

---

## 2. What is on disk right now

**MEASURED.**

```text
# volatile: host state — measured 2026-09-10
$ ls -la /home/altai/.claude/fleet-homes.list
ls: cannot access '/home/altai/.claude/fleet-homes.list': No such file or directory

$ git -C /home/altai/proga/fleet-dogfood log --oneline
79a4b74 the throwaway second fleet home, created by lane w62-dogfood

$ find /home/altai/proga/fleet-dogfood -not -path '*/.git/*' -not -name '.git' | sort
/home/altai/proga/fleet-dogfood
/home/altai/proga/fleet-dogfood/.claude/worktrees/linear-hatching-leaf/hello.txt      (+ README.md, .gitignore)
/home/altai/proga/fleet-dogfood/.gitignore
/home/altai/proga/fleet-dogfood/README.md
/home/altai/proga/fleet-dogfood/state/briefs/df-hello.md
/home/altai/proga/fleet-dogfood/state/events.jsonl
/home/altai/proga/fleet-dogfood/state/fleet.json
/home/altai/proga/fleet-dogfood/state/journals
/home/altai/proga/fleet-dogfood/state/outcomes/df-hello.jsonl
/home/altai/proga/fleet-dogfood/state/tasks/df-hello.md
/home/altai/proga/fleet-dogfood/state/tasks/hello.md
/home/altai/proga/fleet-dogfood/state/worker-settings.json
```

**MEASURED.** The new home's hooks are wired to the **durable** install, not to this lane's
worktree — all four hook commands in its `state/worker-settings.json` read
`/home/altai/proga/fleet/bin/hooks/…`, and each carries
`--fleet-home "/home/altai/proga/fleet-dogfood"`. That was not luck: `INSTALL_ROOT` is
`Path(__file__).resolve().parent.parent` (`bin/fleet.py:114`), so running the lane worktree's own
`bin/fleet.py` would have stamped a temporary path into a home the operator is meant to keep. Every
real invocation in this lane used `/home/altai/proga/fleet/bin/fleet` for that reason.

**MEASURED, unexpected, not a fleet defect:** the worker wrote its file into a git worktree it
created for itself at `.claude/worktrees/linear-hatching-leaf/`, not at the repo root. That is the
harness's worktree isolation, unrelated to multi-fleet. Recorded so the next reader does not chase
a missing `hello.txt`.

---

## 3. The six proofs

Driver for every `fleet` call in this section, verbatim:

```sh
HOME=$CLAUDE_JOB_DIR/tmp/sbx env -u CLAUDE_CODE_SESSION_ID -u FLEET_HOME \
  /home/altai/proga/fleet/bin/fleet "$@"
```

REAL install, REAL target home, **sandbox `HOME`** so the machine-global list is not the operator's.
`-u CLAUDE_CODE_SESSION_ID` is mandatory and §6.2 says why.

### P1 — `init --home` creates the home and appends. **PASS (append sandboxed).**

**MEASURED.**

```text
# volatile: host state — measured 2026-09-10, real home + SANDBOX homes list
$ ls -la <sandbox>/.claude/fleet-homes.list
ls: cannot access '…/sbx/.claude/fleet-homes.list': No such file or directory

$ fleet init --home /home/altai/proga/fleet-dogfood
fleet init: initialized home /home/altai/proga/fleet-dogfood
  registry:    /home/altai/proga/fleet-dogfood/state/fleet.json
  settings:    /home/altai/proga/fleet-dogfood/state/worker-settings.json
  python:      /usr/bin/python3.12
  homes list:  …/sbx/.claude/fleet-homes.list (appended: /home/altai/proga/fleet-dogfood)
  note:        that append is permanent -- the list is append-only and only `fleet homes --retire` folds it out.

$ cat <sandbox>/.claude/fleet-homes.list
/home/altai/proga/fleet-dogfood

$ ls -la /home/altai/.claude/fleet-homes.list        # the REAL one, after
ls: cannot access '/home/altai/.claude/fleet-homes.list': No such file or directory
```

**MEASURED.** The before/after the brief asked for is shown; the file that changed is the sandbox's.
The verb's own creation half ran against the real target and is what §2 shows on disk.

**MEASURED.** There is **no CLI path to an initialized home that skips the append.**
`_init_named_home` writes the home state and then appends, with no `--no-list` flag; bare
`fleet init` writes only `worker-settings.json` and no registry; `homes --add` and `--fleet-home`
both refuse an uninitialized home. So "create the home but withhold the membership" is only
reachable by redirecting `HOME`, which is what this lane did.

### P2 — spawn one SONNET worker there. **PASS.**

**MEASURED.**

```text
# volatile: host state — measured 2026-09-10
$ fleet --fleet-home /home/altai/proga/fleet-dogfood spawn df-hello \
    --dir /home/altai/proga/fleet-dogfood \
    --task /home/altai/proga/fleet-dogfood/state/tasks/hello.md \
    --model sonnet --mode bypass
fleet: df-hello: native spawn failed -- --bg dispatch exited 1: --bg with bypassPermissions requires accepting the disclaimer first. Run `claude --dangerously-skip-permissions` once interactively.

$ cat /home/altai/proga/fleet-dogfood/state/fleet.json      # registry NOT polluted by the failure
{
  "workers": {}
}

$ fleet --fleet-home … spawn df-hello … --model sonnet --mode accept
model: sonnet
df-hello bf25f0f2-c34a-43d8-9e10-4cf27e5f9e3f (native bg, short id bf25f0f2)
```

**MEASURED.** Sonnet, not Haiku, per three-tier §3.4 — confirmed downstream by the result line's
`model=claude-sonnet-5`, which is the harness's own word rather than the flag echoed back.

**MEASURED, and it is a usable operational fact for the next lane:** `--mode bypass` is unusable for
`--bg` on this host without a one-time interactive disclaimer. `--mode accept` works. The shipped
`spawn` default is `dontask`, which is what killed three workers in the S-2 incident recorded in
`docs/operator/keeper-soak-2026-09.md`; this worker recorded `permission_denials: 0`.

### P3 — `fleet status --fleet-home <dogfood>` shows that worker. **PASS.**

**MEASURED.**

```text
# volatile: host state — measured 2026-09-10
$ fleet --fleet-home /home/altai/proga/fleet-dogfood status
NAME                STATUS     TURNS     COST  MIN-AGO  MAIL   ATTACH  FLAGS
df-hello            idle           1        -        2     0        -  tokens:in=2 out=329

$ fleet --fleet-home /home/altai/proga/fleet-dogfood result df-hello
-- tokens in=2 out=329 model=claude-sonnet-5
changed: hello.txt; verified: wrote it; blocked: none
```

**MEASURED.** The Stop hook fired into the **dogfood** home:
`state/outcomes/df-hello.jsonl` carries `session_id: bf25f0f2-…`, `permission_denials: 0`. That is
the strongest single isolation receipt in this lane — see §4.

### P4 — the statusline across two homes. **MEASURED, and the brief's premise is half wrong.**

The brief says G-K5 build item (1), *"the statusline must differ per fleet home"*, is UNBUILT, and
asked me to measure rather than build. I built nothing. `bin/` is untouched on this branch.

**MEASURED**, four runs of `bin/fleet_statusline.py`, blob = `{"session_id":"<sid>"}`:

```text
# volatile: host state — measured 2026-09-10 (ANSI stripped)
--- REAL machine HOME (homes list ABSENT) ---
dogfood worker's sid   : [fleet]  sup held  4 bodies  work 3  idle 9 5h
live-home worker's sid : [fleet]  sup held  4 bodies  work 3  idle 9 5h

--- SANDBOX HOME (dogfood IS listed) ---
dogfood worker's sid   : [fleet]  work 1
live-home worker's sid : [fleet]  sup held  4 bodies  work 3  idle 9 5h
```

**MEASURED.** Item (1) is two claims and only one is unbuilt:

1. *Per-home resolution* is **BUILT and works.** `fleet_statusline.py:555` runs the blob's sid
   through `fleet.resolve_home()` (multi-fleet slice d) and reassigns `fleet.FLEET_HOME` before
   reading. Two sessions on one machine render two different rows. Nothing needs building here.
2. *The row carrying the home's identity* — G-K5's own words, *"the row must carry the home's
   identity so two fleets are never confused in the bar"* — is **NOT built.** Both rows say
   `[fleet]`. An operator with two windows sees two different counts and no label saying which
   fleet each belongs to. That is the whole of the remaining work, and it is a renderer change.
3. **MEASURED.** On the machine as it stands *today*, it cannot differ at all: with the second home
   unlisted the population has one member, the lookup misses, and both sids render the live home's
   row — the two real-HOME lines above are identical. So the building lane cannot see its own
   feature work until the P1 append (or an equivalent) exists. **That dependency is worth telling
   them**, because a lane that measures on today's machine will conclude slice d is broken.

### P5 — the keeper with `--fleet-home`. **NEGATIVE. It refuses.**

The brief said *"show it reads the dogfood home when pointed there."* **MEASURED: pointing it there
with `--fleet-home` does the opposite.** No live keeper was armed; every run is `--once --dry-run`,
which *"touch[es] neither tmux nor state"*.

```text
# volatile: host state — measured 2026-09-10
$ python3 bin/fleet_keeper.py --once --dry-run --fleet-home /home/altai/proga/fleet-dogfood
keeper: --fleet-home /home/altai/proga/fleet-dogfood does not match the imported fleet home /home/altai/proga/fleet; refusing        (exit 1)

$ FLEET_HOME=/home/altai/proga/fleet-dogfood python3 bin/fleet_keeper.py --once --dry-run
keeper: --fleet-home /home/altai/proga/fleet does not match the imported fleet home /home/altai/proga/fleet-dogfood; refusing        (exit 1)

$ FLEET_HOME=/home/altai/proga/fleet-dogfood python3 bin/fleet_keeper.py --once --dry-run \
      --fleet-home /home/altai/proga/fleet-dogfood
keeper: git unpushed check unavailable (no remote-tracking ref to compare against)                                                   (exit 0)

$ python3 bin/fleet_keeper.py --once --dry-run --fleet-home /home/altai/proga/fleet      # control
                                                                                                                                     (exit 0, silent)
```

**MEASURED — the mechanism, which is the useful half.** `--fleet-home` on the keeper is **an
assertion, not a selector.** `fleet_keeper.py:697` compares it against `fleet.FLEET_HOME` *frozen at
import* and refuses a mismatch, with its own reason stated in the source: *"a mismatch means half
the observation is about one home and half about another, which is worse than no tick at all."* And
`:678` defaults the flag to `_INSTALL_ROOT`, **not** to `fleet.FLEET_HOME` — which is why the env
alone also refuses. Both must be set, consistently, and only the env actually moves the home.

**MEASURED — that the third run really read the dogfood home**, rather than silently reading the
live one: the dogfood repo has no remote-tracking ref and the live fleet repo does, and only the
dogfood run emitted the unpushed-check line. A negative result needs a positive discriminator or it
is indistinguishable from a no-op.

**BELIEVED, for the building lane:** this is a second surface where "which home" has its own
spelling, which is the fourth-spelling hazard G-K5's Reading-B note already warns about. The keeper
reaching a home through §5 step 3 (env) also means that **once the guard is armed, a keeper pointed
at a second home is on the guarded path**, not the exempt one.

### P6 — isolation, both directions. **PASS.**

**MEASURED.**

```text
# volatile: host state — measured 2026-09-10
$ fleet --fleet-home /home/altai/proga/fleet-dogfood status     # 1 row
df-hello            idle           1        -        2     0        -  tokens:in=2 out=329

$ fleet status                                                  # live home: 16 rows, none of them df-hello
sup|…bootidle / w57-bootdoc / w58-docs / w58-notify / w59-* / w60-homeseam / w61-* / w62-codex / w62-dogfood / w62-keeperc

$ for d in state logs mailbox; do grep -rl "df-hello\|bf25f0f2" /home/altai/proga/fleet/$d | wc -l; done
0
0
0
$ for w in w62-codex w62-keeperc w61-keeperblind; do grep -rl "$w" /home/altai/proga/fleet-dogfood/state | wc -l; done
0
0
0
$ live registry: 26 workers        dogfood registry: 1 worker
```

Zero bleed, measured by grep over all three runtime trees in both directions, not by reading a table.

---

## 4. WHY it is contained — the mechanism, per brief §4

The brief warns that a wave-48 containment audit came back clean *for the wrong reason*, and that
`resolution_population()` makes the population **never empty**. Confirmed: `bin/fleet.py:4681-4683`
appends `home_identity(install)` unconditionally, so the population here was `['/home/altai/proga/fleet']`
even with the list absent. "Nothing showed up" would therefore have been worthless. Three distinct
mechanisms are doing the work, and they are not the same mechanism.

**M1 — a worker view is structurally incapable of reading a second home. MEASURED by AST, not by
reading prose.** `read_registry_at` is the only function that reads a home other than `FLEET_HOME`.
It has exactly nine call sites and **none of them is a view of workers**:

| caller | what it does with the foreign home |
|---|---|
| `home_is_initialized` | predicate: does `state/fleet.json` parse |
| `validate_named_home` | §5 step 1 validation |
| `lookup_home_for_sid` | §5 step 2 sid→home |
| `homes_population`, `homes_population_states` | per-home **counts** |
| `multi_fleet_arming` | the count, for the guard |
| `cmd_homes` | the `fleet homes` view — counts, never names |
| `_write_new_home_state`, `_init_named_home` | creation |

`cmd_status` reaches `load_registry` → `registry_path` → `state_dir()` → `FLEET_HOME`. One file.
`status_snapshot` reaches `_read_registry_readonly`, likewise. **There is no union anywhere in the
module**, so the population is consulted only to choose *which single home to read* and never to
merge rosters. `fleet homes` is the sole multi-home surface and it renders `<path> ok (N workers)` —
a number, not a name. That is why the live `fleet status` could not have shown `df-hello` even if
the dogfood home had been listed.

**M2 — the dogfood worker's hooks were contained by an explicit flag, not by membership. MEASURED.**
`fleet init --home` renders `--fleet-home "/home/altai/proga/fleet-dogfood"` into all four hook
commands in the new home's `state/worker-settings.json` (multi-fleet slice c). So each hook answers
at §5 **step 1** and never falls through. That is verifiable in the outcome record: the Stop hook
wrote `state/outcomes/df-hello.jsonl` **into the dogfood home** while
`lookup_home_for_sid("bf25f0f2-…")` on the real machine returns `state: miss, home: None`. The hook
was contained by argv while the resolver could not see its home at all.

**M3 — and a bare `fleet` call from that same worker is NOT contained. MEASURED.**

```text
# volatile: host state — measured 2026-09-10; sid is df-hello's, a live worker in the dogfood home
$ CLAUDE_CODE_SESSION_ID=bf25f0f2-… fleet home        # real HOME, list absent
/home/altai/proga/fleet
$ CLAUDE_CODE_SESSION_ID=bf25f0f2-… fleet home        # sandbox HOME, dogfood listed
/home/altai/proga/fleet-dogfood
```

In-process, under the real machine state:
`resolution_population() → ['/home/altai/proga/fleet']`,
`lookup_home_for_sid(bf25f0f2) → state:miss`,
`resolve_home(flag=None) → step:legacy, home:/home/altai/proga/fleet`.

So a second home's own worker, typing a bare `fleet` verb, acts on the **live** fleet — until the
home is listed. **The machine list is load-bearing for containment, not a registry of convenience.**
This is the finding that turns the gate in §1 from "an inconvenience" into a genuine two-sided
ruling, and it is the answer to *why*, not *whether*.

**BELIEVED:** M2 is why the isolation looked clean in this lane, and M1 is why it would have looked
clean regardless. Had I only run P6, I would have reported a pass produced almost entirely by M1 —
a mechanism that has nothing to do with the homes list — and the operator would have concluded that
two fleets are isolated by design, when in fact one of the three mechanisms is missing on this
machine right now.

---

## 5. Every `fleet` command, and which home it touched

**MEASURED.** SANDBOXED = `HOME` redirected to `$CLAUDE_JOB_DIR/tmp/…`. The real machine list was
never written; §2's `ls` is the receipt, taken after everything below.

| # | command | HOME | home it acted on | wrote? |
|---|---|---|---|---|
| 1 | `fleet home` | sandbox | live (`/home/altai/proga/fleet`), via step 4 | no |
| 2 | `fleet init --home /home/altai/proga/fleet-dogfood` | **sandbox** | **dogfood** (created it) | **yes — dogfood `state/`; append to the SANDBOX list** |
| 3 | `fleet --fleet-home <dogfood> home` | sandbox | dogfood, via step 1 | no |
| 4 | `fleet --fleet-home <dogfood> home`, sid **not** stripped | sandbox | none — refused | no |
| 5 | `fleet --fleet-home <dogfood> spawn df-hello … --mode bypass` | sandbox | dogfood — dispatch failed | no (registry verified `{"workers": {}}`) |
| 6 | `fleet --fleet-home <dogfood> spawn df-hello … --mode accept` | sandbox | **dogfood** | **yes — dogfood registry, briefs, tasks, events** |
| 7 | `fleet --fleet-home <dogfood> status` | sandbox | dogfood | registry refresh, dogfood only |
| 8 | `fleet status` (no flag) | sandbox | **live**, via step 4 | registry refresh, live only — see note |
| 9 | `fleet --fleet-home <dogfood> result df-hello` | sandbox | dogfood | no |
| 10 | `fleet home`, `CLAUDE_CODE_SESSION_ID=bf25f0f2-…` | **real** | live, via step 4 | no |
| 11 | `fleet home`, same sid | sandbox | dogfood, via step 2 | no |
| 12 | `bin/fleet_statusline.py` × 4 | 2 real, 2 sandbox | live ×3, dogfood ×1 | no (D4: views never write) |
| 13 | `bin/fleet_keeper.py --once --dry-run` × 4 | real | live ×2 (1 refused), dogfood ×2 (1 refused) | no (`--dry-run`) |
| 14 | sealed rehearsal: `init --home` ×3, `archive no-such-worker-xyz` ×2 | sandbox | **throwaway homes only**, under a COPIED install root | yes, inside `$CLAUDE_JOB_DIR/tmp` |
| 15 | in-process `import fleet` measurements | both | reads only | no |

**Note on #8, disclosed because the brief asked which home was *touched* and not merely read:**
`cmd_status` reaches `save_registry` (AST-confirmed), so `fleet status` can refresh the live
registry. That is the ordinary behaviour of an operator typing `fleet status`, it is a lock-holding
verb rather than one of D4's views, and it is the live home's own single writer doing its job — but
it is a write, and calling it a pure read would be wrong.

**MEASURED — the machine fence held.** Nothing under `/home/altai/proga/` was created, written or
spawned into except `fleet-dogfood` (new), this worktree, and the live `fleet` home via #7/#8. The
sibling lane worktrees `fleet-w62-codex` and `fleet-w62-keeperc` were not touched. **Correction to
brief §0:** its enumeration of the operator's projects omits `/home/altai/proga/fleet-wt`, which
exists on disk. I did not touch it either, but a fence that enumerates is a fence that can be
incomplete, and this one is.

---

## 6. Suite: the prediction, then the measurement

**MEASURED.** The prediction was written into
`$FLEET_HOME/state/journals/w62-dogfood.md` **before** any pytest process started, from a separate
`git clone --no-local` of `w62/dogfood`. It read: *4965 collected on 3.10 and on 3.12, identical;
6 failed on each, the known host-assumption six; no new failure attributable to this lane* — with
the stated reasoning that this lane's diff is docs-only and that `docs/lanes/` is exempt by
construction (`tests/test_doc_claims.py:447`, pinned at `:761-763`), with no per-file sweep over it.

```text
# volatile: host state — measured 2026-09-10, from `git clone --no-local` of w62/dogfood at 294315d
$ uv run --no-project --python 3.12 --with pytest python -m pytest -q
6 failed, 4942 passed, 16 skipped, 1 xfailed in 502.54s (0:08:22)

$ uv run --no-project --python 3.10 --with pytest python -m pytest -q
6 failed, 4942 passed, 16 skipped, 1 xfailed in 440.77s (0:07:20)

both floors, the same six:
  test_fleet_index.py::TestPathContainment  ×3   (drive-qualified rel)
  test_fleet_q.py::TestOutlinePathContainment ×1 (absolute path outside root)
  test_terminal_surface.py::TestCollaboratorInstall ×2 (venv-shim re-exec)
```

**MEASURED.** 4942 + 16 + 1 + 6 = **4965 collected, identical on both floors.** Prediction confirmed
exactly, including the identity of the six. Nothing in this lane moved the floor, which is what a
docs-only diff owes.

**MEASURED.** No `verify_receipts.py` run is owed. The receipts in this lane live in
`docs/lanes/w62-dogfood.md` and `docs/operator/keeper-soak-2026-09.md`, and
`tests/test_receipts.py:172` globs `SPEC_DIR.glob("*.md")` — i.e. `docs/specs/*.md` only. Neither
file is in scope. **That is a deliberate choice and not an evasion:** most of the blocks above are
*refusals* whose exact text is pinned to a host state the gate in §1 is about to change, and a
receipt harness re-executing them would go red the moment the operator rules. Nothing under
`docs/specs/` was edited.

**MEASURED — soak file chosen, per §6.** `grep -rl soak docs/` returns 22 files; exactly one is a
log of host receipts rather than a document that mentions the word:
`docs/operator/keeper-soak-2026-09.md`. Its own header declares *"Every block here is
`# volatile: host state` — evidence lives on kz-work, not in the tree"*, which is precisely the
class these blocks belong to. Appended as `## Multi-fleet dogfood — a SECOND home on this host`.

---

## 7. WHERE THIS BRIEF WAS WRONG

The brief predicted it would be wrong *"in §2's idiom or §3's step 4"*. It was wrong in both, and in
three other places.

**W1 — §2's idiom is incomplete, and the missing half is the one that bites. MEASURED.**
The brief says *"once the home exists, `--fleet-home /home/altai/proga/fleet-dogfood` resolves and
is the idiom for every later call."* It does not — not from a fleet-launched session:

```text
$ fleet --fleet-home /home/altai/proga/fleet-dogfood home     # sid NOT stripped
fleet: [fleet] WITNESS: --fleet-home names /home/altai/proga/fleet-dogfood, but this session is a member of /home/altai/proga/fleet.
Refusing to act on a home the flag and the registry disagree about. Drop `--fleet-home` to act on the home this session belongs to.
```

That is §5 step 1's disagreement guard, and it fires on `fleet home` — an **ordinary read verb**.
The brief supplied the sid-stripping fix (*"removing `CLAUDE_CODE_SESSION_ID` from the child
environment is what makes the fence hold"*) but scoped it to `FLEET_HOME`, and stated `--fleet-home`
as unconditionally sufficient. It is not: **`env -u CLAUDE_CODE_SESSION_ID` is required for
`--fleet-home` too**, on every verb, from any fleet-launched session. Worse for a dogfooder, the
refusal's remedy is *"drop `--fleet-home`"* — the exact opposite of what is wanted — because
`_disagreement_remedy` only offers `--yes` on the three verbs that have it, and `home` is not one.
Every lane brief on this machine that hands out `--fleet-home <other home>` as the idiom inherits
this, so the correction belongs in `docs/lanes/BRIEF-TEMPLATE.md`, not just here.

**W2 — §2's gate is unsatisfiable for the one call §2 tells you to make. MEASURED.**
*"Gate every step on `fleet home` invoked the same way: if it does not print the path you intend,
run nothing else."* For the **creating** call, `fleet home` cannot print the intended path: the home
does not exist yet, `--fleet-home` is refused alongside `init --home`, and there is no third
spelling. I ran the gate anyway and it printed `/home/altai/proga/fleet` — the live home — which by
the brief's own rule means *run nothing else*, and would have stopped the lane at step one. The gate
is sound for every call **after** P1 and vacuous for P1 itself; that is worth stating rather than
letting the next lane discover it by ignoring its own instruction.

**W3 — §3 step 4's premise. MEASURED.** *"The statusline must differ per fleet home is G-K5 build
item (1) and is UNBUILT."* Per-home resolution is **built and working** (slice d, measured in §3-P4:
two homes, two different rows). What is unbuilt is item (1)'s *other* half — the row carrying the
home's identity. A lane told "it is unbuilt" would build the half that already exists.

**W4 — §2's "name check" is wrong on its stated evidence, right on its conclusion. MEASURED.**
*"The only `glob` on a state path is `fleet.json.corrupt.*` at `bin/fleet.py:982`."* There are
**nine** globs in the module, and several are on state paths: `mailbox_dir().glob(…)` (`:10439`,
`:12435`, `:12442`), `outcomes_dir().glob("*.jsonl")` (`:13951`), `state_dir().glob(
"supervisor-handoff-*.md")` (`:15318`, `:20056`), `archive_root().glob("*/*")` (`:11545`), and
`Path.home().glob(".claude/projects/*/<sid>.jsonl")` (`:2600`). The **conclusion** survives: every
one of them is rooted at `FLEET_HOME` or at `~/.claude`, none sweeps sibling directories, and there
is no `fleet-*` sweep that could mistake `fleet-dogfood` for a worktree. So the name is safe — but
the brief said "confirm this yourself before relying on it", and confirming it falsifies the
sentence that was offered as the confirmation.

**W5 — §1's framing of the append as a step. MEASURED.** *"This is the destructive act — show it
landed."* The append is not one act; it is two, and the second is invisible from the verb's output.
The brief's own §5 anticipated this and it is why the append was withheld. See §1.

**Confirmed, not wrong:** §1's claim that `~/.claude/fleet-homes.list` does not exist (re-measured at
lane start and again at lane end). §2's claim that `--fleet-home` is refused alongside `init --home`
(confirmed in source at `bin/fleet.py:5426-5448` and by `TERMINUS_EXEMPT_FLAGS`, and it carries a
purpose-built refusal message). §2's claim that `--fleet-home` cannot name a home about to be
created (`validate_named_home`'s third check). §4's claim that the population is never empty
(`bin/fleet.py:4681-4683`).

---

## 8. What this lane did NOT do

- **MEASURED.** No append to `~/.claude/fleet-homes.list`. No write to `~/.claude/settings.json`.
  No `fleet init` against the live home. No second live keeper armed — every keeper run was
  `--once --dry-run`.
- **MEASURED.** `bin/` is untouched on this branch (`git diff --stat` covers `docs/` only). §3-P4
  explicitly forbade editing `bin/` to make the statusline proof pass, and it was not edited to make
  P5's negative go away either.
- **MEASURED.** No push, no merge, no other ref moved. One branch, `w62/dogfood`.
- **MEASURED.** The second home is left in place, un-retired, with its worker in the registry.
- **BELIEVED.** No gate filed by me. §1 is draft text for the supervisor.

## 9. Residuals I could not close

- **BELIEVED.** Whether the interface tier is the *only* unregistered session that types a bare
  destructive verb. I found it by reading `fleet_keeper.py:704` and the interface profile; I did not
  enumerate every surface on the machine that shells out to `fleet`. A ruling on §1 should assume
  there may be others.
- **MEASURED but not driven to conclusion.** With the guard armed, `fleet homes` and `init --home`
  are themselves DESTRUCTIVE *and* terminus-exempt. The exemption stops the resolver refusing; the
  tier still stops a read-only `/fleet:*` grant reaching them. I did not test that pairing under a
  restricted grant.
- **NOT MEASURED.** Whether a *third* home changes anything. Arming is a `>= 2` predicate, so I
  believe it does not, but two is the only population this lane drove.
- **NOT MEASURED.** The dogfood home has no `logs/` or `mailbox/` directory yet — the worker's one
  turn did not create them. Whether a second home needs them pre-created for `fleet peek`/`send` is
  untested.
