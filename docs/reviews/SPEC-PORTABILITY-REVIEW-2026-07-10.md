# Adversarial review — docs/specs/portability.md (C4 spec wave)
**Reviewer:** spec-portability-review · **Date:** 2026-07-10 · **Verdict:** needs-fixes

19 findings: 1 CRITICAL, 7 HIGH, 7 MED, 4 LOW. The `**Status:**` line stays at `drafting`
(a reviewer may not declare `ready-for-build` over an open HIGH, let alone a CRITICAL).

Nothing in this review unblocks the C4 **build** waves. They are gated on Altai's
`SOAK GATE 1 SIGNED` line in `knowledge/lessons.md`, which does not exist yet.

Repro authority used: `py -3.13`, `git log`/`git show`/`git config`/`git ls-files --eol`,
grep, `py -3.13 -m pytest tests/test_steering.py -k Boundary -q` (13 passed).
**WSL Ubuntu exists on this box and was used** to settle POSIX claims: `/proc/1/stat`,
`/proc/uptime`, `/proc/stat` `btime`, `getconf CLK_TCK`, `os.sysconf('SC_CLK_TCK')`,
`man 5 proc` (hidepid), `man 5 proc_pid_stat`, a real `fork()`+zombie `kill(pid,0)` test,
and `TASK_COMM_LEN` truncation. No macOS box exists; every macOS-only claim that could not
be settled is marked `[UNSETTLED — needs port-posix-smoke]` below.

## Hostile passes run

| Pass | What it ruled out | Findings |
|---|---|---|
| 1 Fabrication audit | **No invented experimental result.** Every POSIX/macOS behavioral claim the author could not run was correctly tagged `[UNVERIFIED — verify in port-posix-smoke]`. WSL-verified as TRUE: D2's field-22-is-index-19-after-last-`)` arithmetic (against a real `/proc/1/stat`); the `proc_pid_stat(5)` clock-ticks quote; `/proc/uptime` first-field semantics; `os.sysconf('SC_CLK_TCK')` accepting that exact string; D4's zombie-answers-`kill(pid,0)` claim (reproduced with a real unwaited `fork()`); `ProcessLookupError`/`PermissionError` classes; D4's retry-once claim (`recompute_status`, fleet.py:875-885); D3's `strptime("%a %b %d %H:%M:%S %Y")` tolerating `ps`'s space-padded day. All D7/D10 line citations exact. SPEC.md:382 says what the spec says it says. | F6, F16, F17 |
| 2 Build from the spec alone | Ruled out as *determined by the spec*: `detached_popen_kwargs` composes cleanly with `launch_turn`'s `stdin=PIPE`/redirect Popen (fleet.py:1288-1296); D6's `pid == pgid` premise holds (`launch_turn` Popens an argv **list**, no `shell=True`, no wrapper, so `start_new_session=True` makes the recorded pid its own session+group leader); `signal.SIGKILL` inside a method **body** is call-time only and safe on Windows. Everything else about `_PosixPlatform` required a guess. | F2, F3, F4, F5, F8, F9, F10, F11 |
| 3 Invariant assault | Could **not** break: (c) zombie→definitely-gone is sound on POSIX — claude's launcher execs in place, so no wrapper can zombie while a live child continues, and the detached turn is reparented to init and auto-reaped; (d) `killpg` never fires on a reused pgid — every kill path gates on the ctime probe first (`_interrupt_worker`); (e) D8's `eol=lf` touches line endings only, so CLAUDE.md's forward-slash hook rule and `worker-settings.template.json` are untouched. The two source-scan lint tests do stay literally green and unmodified — **but green lint ≠ invariant 8 upheld** (F4, F6, F2 all pass the lint while being OS-coupling it structurally cannot see). Invariant 5/7 **did** break: F1. | F1, F4, F6, F13, F2 |
| 4 Stale-tag hunt | The one the author was ordered to fix **is fixed**: OQ2/L160 correctly calls the old `[UNBUILT — C2 hardening kernel item 9]` three-way-probe tag stale and cites SPEC.md:382. Verified. Four *new* stale tags found. Every `bin/fleet.py` anchor the spec cites (`:14`, `:204-206`, `:209-310`, `:313-334`, `:340`, `:1863`, `:2227-2253`, `:2242`, `:3156`, `:4122`, `:4254`) is exact, as are all twelve `tests/` line citations. | F7, F18 |
| 5 Decision completeness | **No silently-dropped OQ.** Stub OQ1-8 + OQ9 (`git show d2ade0a`) map 1:1 onto current OQ1-9 → D1-D12; none renumbered or substituted; every one ends `RESOLVED`. Every `Owner task` names a real Campaign-4 task per PLAN.md, except D7's. OQ9 (pytest tiers) was carried forward in substance. OQ3 was carried forward in *letter* but not in substance — see F14. | F14, F15, F19, F7 |

## Findings

### F1 — CRITICAL — D2's wall-clock ctime recomputation turns any CLOCK_REALTIME step into a false `definitely-gone`, and `respawn` then double-launches in the cwd

**Claim under review:** D2, L31 — "Convert `starttime` (clock ticks since boot) to wall-clock:
`abs_start ≈ (time.time() - float(open('/proc/uptime').read().split()[0])) + starttime_ticks / os.sysconf('SC_CLK_TCK')`. Tolerance: **±2 s**."

**Why it is wrong:** `starttime` (field 22) is boot-relative and *constant* for a live PID.
The spec converts it to wall-clock on **every read** using `time.time()` — CLOCK_REALTIME,
which NTP **steps** — minus `/proc/uptime`, which is monotonic. So the derived boot anchor is
`boot_wall = realtime − uptime`, and any REALTIME step of `S` seconds propagates verbatim:
`abs_start_probe = abs_start_launch + S`, while `starttime` never moved. The stored
`turn_pid_ctime` is itself produced by this same formula at launch (`launch_turn` calls
`get_process_info` right after `Popen`, fleet.py:1251). The ±2 s tolerance was calibrated —
by D2's own evidence cell — for two-syscall read jitter and tick rounding, both in the
millisecond range. It was never calibrated for a clock step.

Windows is immune: `$p.StartTime` is an absolute kernel-recorded creation time, not a
quantity recomputed from the current clock. This is a POSIX-only regression that D2
introduces; it is not a port of shipped behavior.

**Concrete failure:**
1. `fleet spawn` on Linux. Turn runs; `turn_pid_ctime` stored via the D2 formula. Status `working`.
2. CLOCK_REALTIME steps ≥ 3 s. Routine triggers: first `chrony`/`systemd-timesyncd` sync after
   boot (`makestep` is on by default), VM resume, laptop suspend + hwclock resync,
   `timedatectl set-time`. The named exercise box (dev server 192.168.1.202) is a VM.
3. Any `fleet status` / `send` / `clean` → `recompute_status` (fleet.py:870) → `probe_liveness`:
   image name matches, ctime present, `abs(ctime − recorded) = 3 s > 2 s` → **`"gone"`**.
4. Mid-turn there is no trailing result event, so the `working→dead` path is taken. The
   retry-once (fleet.py:880) re-probes — the step persists — still `"gone"` → **`"dead"`**.
5. The worker is now `dead` while its `claude` is still running. `fleet respawn` — the
   documented dead-recovery lever — calls `launch_turn` in the **same immutable cwd**:
   **two live `claude` processes in one cwd.** Invariant 5 and invariant 7, both broken.
   `fleet clean` on the same false-dead record additionally deletes the live worker's logs,
   mailbox, and journal.

This is the identical failure class C2's adversarial review already caught once on Windows
(HIGH double-launch), reintroduced on the new OS by the very decision that was supposed to
port the probe faithfully. The spec's own `## Invariants touched` section (L140) claims
invariant 7 is preserved "because the alive-unknown tier never demotes a live turn" — but
this path never reaches alive-unknown. It reaches `alive`→`gone` through the ctime compare.

**Suggested disposition:** D2 must compare in **boot-relative tick space** — store the raw
`starttime` ticks (field 22) and compare for exact equality (±1 tick). That quantity is
invariant under every wall-clock change and needs no tolerance at all. If a wall-clock
`datetime` is required to satisfy `get_process_info`'s return contract, anchor it to
`/proc/stat`'s `btime` (WSL-confirmed: `btime 1783625155`, `uptime 4.15`, `date +%s`
1783625159 → `btime + uptime ≈ now`) and state explicitly that `btime` is itself
REALTIME-derived and therefore moves under a step, so it may be used for display but **must
not** be the compared quantity. The ±2 s tolerance must not be reused for a value that
tracks CLOCK_REALTIME. Note that this changes the *stored registry field's meaning* on
POSIX, which is a cross-cutting decision the spec must make explicitly rather than leave to
`port-adapter-a`.

---

### F2 — HIGH — What `image_name` must contain on POSIX is never stated, and core rejects any name outside `_ALIVE_IMAGE_NAMES`

**Claim under review:** `## Platform adapter interface`, L72-74 — "`image_name` = the comm/parsed
process name (used by the caller, `probe_liveness`, for the same PID-reuse image-mismatch check
the Windows probe already performs)."

**Why it is wrong:** `probe_liveness` (fleet.py:628) substring-matches the returned name against
a **core** constant, `_ALIVE_IMAGE_NAMES = {"claude", "node", "cmd"}` (fleet.py:604), and returns
`"gone"` on any miss. The spec never connects `image_name` to that set, never says what a
`claude --print` turn's direct `Popen` child is actually named on POSIX, and never notes that the
two OSes return structurally different strings: Linux `comm` is **truncated to 15 characters**
(TASK_COMM_LEN; WSL-confirmed — a binary named `averyveryverylongprocessname` yields
`comm=averyveryverylo`), whereas macOS `ps -o comm=` prints a **full executable path**
(`/opt/homebrew/bin/node`). Substring matching happens to survive both for `node`/`claude`, but
that is luck, not specification. `"cmd"` is Windows-only dead weight in the set.

**Concrete failure:** `port-adapter-a` faithfully implements D2 and returns `comm`. If the real
POSIX child is named anything not containing `claude`/`node`/`cmd` — a venv shim, a `sh` wrapper,
a renamed launcher — then **every probe of every worker returns `"gone"` on the first poll**.
Mass false-dead → the F1 double-launch, but for all workers, deterministically, on the first
`fleet status`. The spec offers no way for the builder to discover this before
`port-posix-smoke`, which runs *after* the adapter merges.

**Suggested disposition:** State the contract explicitly: *the name returned by
`get_process_info` MUST substring-match `_ALIVE_IMAGE_NAMES` (fleet.py:604) or the probe is
`"gone"` regardless of ctime.* Require `port-adapter-a` to record the real `comm` of a live
POSIX `claude` turn and, if it does not match, extend the core set in the same change — that set
is core, not adapter, so extending it is a cross-boundary edit the spec must pre-authorize.
Note the 15-char Linux truncation and the macOS full-path form. Drop or justify `"cmd"`.

---

### F3 — HIGH — The alive-unknown wire shape is unbuildable in its own trigger case: core rejects the tuple before it ever looks at the `None` ctime

**Claim under review:** D4, L33 — "**alive-unknown** = `PermissionError`/`EPERM` reading
`/proc/<pid>/stat` … or an unparseable `ps`/`/proc` read … alive-unknown is never demoted to `dead`."
Interface, L69 — "`(image_name: str, None)` -- alive-unknown".

**Why it is wrong:** On Linux, `image_name` comes from `/proc/<pid>/stat` field 2 (D2) — the exact
file the adapter just failed to read. On macOS, it comes from the `ps` invocation that just errored
or emitted garbage. In both alive-unknown trigger cases **the adapter has no name to return.**
Now trace core: `probe_liveness` runs the name check at fleet.py:628 **before** the
`if ctime is None` alive-unknown branch at :630. A builder returning the only things available —
`("", None)` or `(None, None)` — gets `name_l == ""`, matches nothing in `_ALIVE_IMAGE_NAMES`, and
core returns **`"gone"`**. The alive-unknown branch is unreachable from its own trigger.

**Concrete failure:** EPERM or an unparseable read on a live turn → adapter returns `("", None)` →
`probe_liveness` `"gone"` → retry-once → `"dead"` → `fleet respawn` → second live `claude` in the
cwd. The spec's own D4 sentence "alive-unknown is never demoted to `dead`" is falsified by the wire
contract it specifies two sections later.

Reachability in the supported configuration is low — fleet probes its own same-user PIDs, and
`/proc/<pid>/stat` is world-readable — which is why this is HIGH and not CRITICAL. But the spec
*mandates* a branch the builder cannot implement, and the failure direction when they guess is
toward double-launch, not toward fail-safe.

**Suggested disposition:** State that on any name-unavailable failure the adapter classifies as
alive-unknown, it must return a **sentinel name that satisfies `_ALIVE_IMAGE_NAMES`** (e.g. the
literal `"claude"`) paired with `None`. Say so for both the Linux and macOS branches. Note that
`_ALIVE_IMAGE_NAMES` and the :628-before-:630 ordering live in core `probe_liveness` and cannot be
changed from inside the adapter.

---

### F4 — HIGH — The mandated signature `killpg=os.killpg` is evaluated at import and raises `AttributeError` on Windows

**Claim under review:** `## Platform adapter interface`, L77 (a copy-me code block) —
`def kill_process_tree(self, pid, killpg=os.killpg) -> bool:`; restated in D6, L35.

**Why it is wrong:** A default argument is evaluated when the `def` executes, i.e. during
`_PosixPlatform`'s class body at `import fleet`, on **every** OS — both adapter classes are always
*defined*, only conditionally *instantiated* (fleet.py:340). `os.killpg` does not exist on Windows.
Reproduced:

```
$ py -3.13 -c "import os,signal; print(hasattr(os,'killpg'), hasattr(signal,'SIGKILL'))"
False False
$ py -3.13 -c "import os
class X:
    def k(self, pid, killpg=os.killpg): ..."
AttributeError: module 'os' has no attribute 'killpg'
```

The shipped stub avoids this with `run=None` (fleet.py:330). The spec *introduces* the regression.
`signal.SIGKILL` inside the method **body** is fine — call-time only, never executed on Windows.
Only the default arg bites.

**Concrete failure:** `port-adapter-a` transcribes the signature → `import fleet` raises on Windows
→ **every test in every file errors at collection** → the `windows-latest` job of done-criterion 4
("3 green OS jobs") is red before a single test runs. Note this passes the invariant-8 source-scan
lint untouched: `os.killpg` is not in the forbidden-substring list. Green lint, dead Windows.

**Suggested disposition:** Never bind a POSIX-only name in a default argument or class body.
Specify `killpg=None`, resolved as `killpg = killpg or os.killpg` inside the body (which only runs
on POSIX). Add `import signal` at module top. Neither introduces an `os.name` branch, so invariant
8 is preserved. Add a line to the spec stating the general rule, because D6 and any future adapter
method are exposed to it.

---

### F5 — HIGH — `get_process_info`'s ctime timezone is never specified; the obvious implementation crashes `probe_liveness`

**Claim under review:** Interface, L68 — "`(image_name: str, ctime: datetime)   -- alive, ctime readable`".

**Why it is wrong:** "datetime" — no timezone stated, anywhere in the spec. D2 hands the builder a
**float** (`(time.time() − uptime) + ticks/HZ`); the natural conversion `datetime.fromtimestamp(x)`
returns a **naive local** datetime. The shipped Windows adapter returns tz-aware UTC
(fleet.py:266, `.replace(tzinfo=timezone.utc)`). `probe_liveness` does the subtraction *outside*
its `try` — the `try` at fleet.py:633-636 wraps only `_parse_iso` — so at :637:

```
py -3.13 -c "from datetime import datetime,timezone; datetime.now() - datetime.now(timezone.utc)"
TypeError: can't subtract offset-naive and offset-aware datetimes
```

Uncaught. It propagates out of `probe_liveness` → `pid_alive` / `recompute_status` → every status
poll raises on POSIX. The storage half fails quietly too: `ctime_to_iso` (fleet.py:187) does
`dt.astimezone(timezone.utc)`, which on a naive value assumes **local** tz and shifts it by the UTC
offset — so a builder who "fixes" the crash by storing a naive value gets a permanent ±N-hour ctime
mismatch → `"gone"` on every live turn.

**Concrete failure:** `port-adapter-a` ships; `fleet status` on Linux raises `TypeError` on the
first poll (crash), or, with the naive-storage variant, silently marks every worker dead (F1's
double-launch, permanently).

**Suggested disposition:** The interface block must say: *`ctime` MUST be a tz-aware UTC `datetime`,
matching `_WindowsPlatform.get_process_info` — `datetime.fromtimestamp(abs_start, tz=timezone.utc)`
on Linux; `strptime(...)` then attach/convert to UTC on macOS.* Note that `ps`'s `lstart` is
**local time** with no offset, so the macOS branch must localize before converting — a second
unstated hazard. `[UNSETTLED — needs port-posix-smoke]` whether Darwin `ps` can be made to emit UTC.

---

### F6 — HIGH — D4's "null/corrupt stored ctime → alive-unknown" is a false statement about shipped Windows behavior, and implementing it changes Windows

**Claim under review:** D4, L33 — "**alive-unknown** = … OR the stored `turn_pid`/`turn_pid_ctime`
is null/corrupt (**mirrors the shipped Windows null-ctime alive-unknown case**)." Repeated in the
probe matrix, L47 and L48-49 ("missing/corrupt stored `turn_pid_ctime`" listed under the
alive-unknown discriminator column, for all three OSes).

**Why it is wrong:** Shipped code does the opposite, twice:

```
bin/fleet.py:620   if pid is None or ctime_iso is None:
bin/fleet.py:621       return "gone"
...
bin/fleet.py:635   except (ValueError, TypeError):
bin/fleet.py:636       return "gone"
```

A null **stored** ctime is `"gone"`. An unparseable **stored** ctime is `"gone"`. The genuine
Windows alive-unknown case is a **probed** StartTime that is unreadable — `get_process_info`
returning `(name, None)` at fleet.py:630. The spec conflates stored-ctime-null with
probed-ctime-null. They are different quantities on different sides of the adapter boundary.
(The spec's prose does match SPEC.md:382's prose — which means SPEC.md carries the same drift —
but the spec's claim is about *shipped code*, and the code says `"gone"`.)

**Concrete failure:** `port-adapter-a` cannot implement this in the adapter at all — the stored
value never reaches `get_process_info`. So the builder edits `probe_liveness`, i.e. **core, shared
by Windows**. Result: a Windows worker with a corrupt registry entry flips from `"gone"` to
`"unknown"`, and because alive-unknown is never demoted, it is pinned `working` **forever** — no
`fleet kill`, no `clean`, no `respawn` path reaches it without `--force`. A silent Windows
regression shipped by a portability change. It also passes the invariant-8 lint, because
`probe_liveness` contains no `os.name`.

**Suggested disposition:** D4 and the probe matrix must state that null/unparseable **stored**
ctime is `definitely-gone` on all OSes (matching shipped `probe_liveness`), and reserve
alive-unknown strictly for **probe-read** failures (EACCES, unparseable `/proc`/`ps`). Separately,
file a note that SPEC.md:382's prose is drifted the same way — that is a SPEC.md fix, out of this
spec's write set, and must not be silently "fixed" by a builder editing core.

---

### F7 — HIGH — D8 calls `.gitattributes` a new file. It exists, its content differs, and a literal `Write` destroys the rules that keep hooks from dying silently

**Claim under review:** D8, L37 — "`.gitattributes`, added at repo root (**new file**, in C4 scope):
`* text=auto eol=lf`" … "the one-time `git add --renormalize .` to rewrite already-committed CRLF
blobs to LF is a **required companion step**". Done criterion 7, L152, mandates it as "a bulk
history-rewriting diff". Evidence cell: "Direct observed evidence this session."

**Why it is wrong:** Four separate errors, all settleable by a command the Windows-hosted author
could have run.

1. The file **already exists**, committed in `0d09c25` ("feat(terminal-surface): make the plugin
   actually installable") — a prior campaign, not C4.
2. Its content is not `* text=auto eol=lf`. It is surgical, and load-bearing:
   ```
   *.sh text eol=lf
   bin/fleet text eol=lf
   ```
   with a comment explaining that a CRLF `run_py.sh` on POSIX "dies with `\r: command not found`,
   and because a hook must exit 0 on every failure (**invariant 2**) it would die SILENTLY."
3. The renormalize step is a verified **no-op**: `git ls-files --eol | grep -c 'i/crlf'` → `0`.
   All 85 tracked files are already `i/lf` in the index. There are no committed CRLF blobs to
   rewrite. The residual paragraph describes work with no effect, and done criterion 7 mandates
   reviewing an empty diff.
4. What `* text=auto eol=lf` *would* actually do, on this box (`git config --get core.autocrlf`
   → `true`, working tree currently `w/crlf`), is flip the **working copy of all 85 files** from
   CRLF to LF on next checkout. That is a real consequence D8 presents as harmless additive polish.

D8 also internally contradicts done criterion 2 (L147), which says "`.gitattributes` **polish**" —
i.e. edit an existing file.

**Concrete failure:** `port-adapter-b` reads "new file" and `Write`s `.gitattributes` with the
single `* text=auto eol=lf` line, erasing `*.sh text eol=lf` and `bin/fleet text eol=lf`. The
global rule happens to cover them today, so nothing breaks visibly — until someone adds
`.gitattributes` scoping later, or a tool re-checkouts with a stale index. Meanwhile the deleted
comment was the only record of *why* those rules exist (invariant 2, silent hook death).
Independently, the builder spends a cycle producing and reviewing an empty renormalize diff.

**Suggested disposition:** D8 must say "**edit** the existing `.gitattributes` (added `0d09c25`),
preserving the existing `*.sh` / `bin/fleet` rules and their invariant-2 comment." State that the
index is already LF-normalized so `git add --renormalize .` is a no-op, and delete the
"rewrite already-committed CRLF blobs" residual and done criterion 7 — or re-scope criterion 7 to
the working-tree churn, which is the real effect. Justify `* text=auto eol=lf` on its own merits
(it is defensible) rather than on a false claim about repo state.

---

### F8 — HIGH — `cmd_attach`'s `None` branch: the spec never says whether the worker stays `attached`, and the rollback answer double-launches

**Claim under review:** Consumer-side note, L95 — "`cmd_attach` (`bin/fleet.py:3156`) must add a
`None`-check branch — 'if `build_attach_argv` returned `None`, print the `claude --resume <sid>`
command and the cwd instead of calling `Popen`.'"

**Why it is wrong:** The spec describes the branch as if `build_attach_argv` were the first thing
`cmd_attach` does. It is not. Read fleet.py:3296-3304: the registry write happens **first**, inside
the lock —

```
r["status"] = "attached"; r["attached_since"] = now_iso()
save_registry(data); append_event("attached", args.name)
...
argv = PLATFORM.build_attach_argv(cwd, sid, which=which)     # 3302
try:
    popen(argv, cwd=str(cwd), **PLATFORM.detached_popen_kwargs())
except BaseException:                                         # rolls attached -> idle, re-raises
```

So today the headless case does not print — it calls `popen(None, ...)`, raises, and the
`except BaseException` rolls `attached`→`idle`. A builder must decide whether the print path
**keeps** the pre-claimed `attached` status or **rolls it back**, and the spec picks neither. Both
are defensible; one is unsafe.

**Concrete failure (the rollback answer):** `fleet attach` on the headless dev server prints
`claude --resume <sid>`; `cmd_attach` rolls the record back to `idle`; the operator runs the
printed command by hand. Now a live interactive `claude` owns that session in that cwd while the
registry says `idle`. The next `fleet send` to that worker starts a turn — `launch_turn`, same cwd,
same session id. **Two live `claude` processes, one cwd.** Invariants 5 and 7.

**Concrete failure (the keep answer):** the record stays `attached` and `recompute_status` refuses
to demote `attached` (fleet.py:~789), so a worker whose operator never runs `fleet release` is
pinned `attached` forever with no live process. That is the safe failure, but it must be *chosen*,
and the operator must be told `fleet release` is mandatory.

**Suggested disposition:** Specify: the print path **keeps** `attached`, the printed output must
instruct the operator that `fleet release` is required when done, and the `None`-check sits
*before* the `popen` call but *after* the 3296 pre-claim (so `--force` takeover semantics are
unchanged). Say explicitly that `cmd_attach` must not roll back on the `None` path, and add a
`port-posix-smoke` observation for it — done criterion 6 already exercises this path.

---

### F9 — MED — Every POSIX attach argv is a builder guess, while the test plan demands tests that assert them

**Claim under review:** D5, L34 and interface L84-92 — "Priority chain: `$TERMINAL` env ->
`which("gnome-terminal")` -> `which("tmux")` (new-window-if-inside-tmux) -> `None`." Test plan,
L125 — "Add a **new** parallel set: `test_build_attach_argv_posix_prefers_terminal_env`,
`_falls_back_to_gnome_terminal`, `_falls_back_to_tmux`, `_returns_none_when_headless`."

**Why it is wrong:** The Windows side pins argv byte-for-byte
(`["wt","-d",cwd,"--","claude","--resume",sid]`) and its tests assert exact equality. The POSIX
side specifies a *priority order* and zero argv. Unspecified, each a guess: the `$TERMINAL`
invocation convention (`-e` vs `--` vs `--command`, which differ per terminal emulator);
`gnome-terminal`'s `--working-directory=` and `--` handling; how to detect "inside tmux" (`$TMUX`
env? unstated) and what the **not**-inside-tmux argv is (`new-session`? or fall through to `None`?).
Additionally D5's env-script mechanism requires the launched shell to run `source <script> &&
claude --resume`, which needs a shell string — contradicting L125's own reasoning that "Popen with
an argv list never goes through a shell."

**Concrete failure:** `port-test-suite` cannot write the four mandated tests: there is no expected
value to assert against. It blocks on `port-adapter-b`, which the PLAN runs in a *different* wave.
The two tasks deadlock or the test author invents the contract, which is exactly what a spec exists
to prevent.

**Suggested disposition:** Pin the exact argv for all four branches, including the `$TERMINAL`
convention chosen and the inside-vs-outside-tmux detection and argv. State whether the returned
list is ever shell-mediated.

---

### F10 — MED — `TestPlatformAdapterBoundary` has 13 tests, not 11; the "other 9" arithmetic silently drops two from the port plan

**Claim under review:** L112 — "`TestPlatformAdapterBoundary` (`test_steering.py:857-963`) has
**11 tests**. Two are pure source-scans … The other **9** call `fleet.PLATFORM.<method>(...)`
directly." Restated in `## Findings against PLAN.md` #2, L174 ("2 of its 11", "9 of the class's 11").

**Why it is wrong:** The class spans `test_steering.py:857-962` (not 963) and contains **13**
`def test_` methods — counted directly, and `py -3.13 -m pytest tests/test_steering.py -k Boundary -q`
reports `13 passed`. The breakdown is 2 source-scans + 9 Windows-hardcoded `PLATFORM` tests + **the
2 tests the spec itself plans to invert at L127** (`test_posix_platform_raises_unsupported` :950,
`test_unsupported_platform_error_is_not_implemented_error` :961). The spec counts out the very two
tests it elsewhere assigns work on. Also imprecise: those two currently **pass** on POSIX (they
assert the stub raises), so L174's "every one of them hard-fails on POSIX today" is wrong for them.

**Concrete failure:** `port-test-suite` ports 9 tests and never touches the other 2.
`test_posix_platform_raises_unsupported` then fails everywhere (see F11).

**Suggested disposition:** "13 tests: 2 source-scan (unmodified) + 9 Windows-hardcoded (fail on
POSIX today) + 2 unsupported-behavior tests (pass today on both OSes; removed by this build)."
Fix the range to `857-962` and correct L174 to match.

---

### F11 — MED — `test_posix_platform_raises_unsupported` fails on **every** OS once the adapter ships, not just POSIX — and the spec contradicts itself about the neighbouring test

**Claim under review:** L127 — "`test_posix_platform_raises_unsupported` (lines 950-959) and
`test_unsupported_platform_error_is_not_implemented_error` (961-962) — **inverted** … Once
`_PosixPlatform` is implemented, the four `pytest.raises(UnsupportedPlatformError)` assertions
become false **on POSIX**."

**Why it is wrong:** Two errors.

1. The test constructs `fleet._PosixPlatform()` **directly** (`posix = fleet._PosixPlatform()`),
   not `fleet.PLATFORM`. Once the class is implemented, the four `pytest.raises` fail on **Windows
   too** — the class body is defined on every OS. "on POSIX" is wrong.
2. The spec contradicts itself. L97: "`test_unsupported_platform_error_is_not_implemented_error`
   still needs the class to exist" — correct; it is a pure `issubclass(...)` check, OS-independent,
   stays green forever, needs no change. L127 lists that same test among those "**inverted**" whose
   "four `pytest.raises` become false." It contains no `pytest.raises`.

**Concrete failure:** `port-test-suite` reads "fails on POSIX," applies
`@pytest.mark.skipif(os.name == "nt")` or only writes the POSIX replacement. The original test still
runs on `windows-latest`; `pytest.raises(UnsupportedPlatformError)` does not raise; the Windows CI
job is red at done-criterion 4. Separately, the builder needlessly rewrites a correct
OS-independent test.

**Suggested disposition:** "Delete `test_posix_platform_raises_unsupported` outright on all OSes —
not OS-guard it. Leave `test_unsupported_platform_error_is_not_implemented_error` untouched
(OS-independent; it is why `UnsupportedPlatformError` stays defined)." Remove the L97/L127
contradiction.

---

### F12 — MED — macOS `ps -o state=` emits multi-character state strings, which defeat D4's `state in {Z,X,x}` membership test

**Claim under review:** D4, L33 — "state not in `{Z,X,x}` (zombie/dead)" … "OR the PID exists but
its state is `Z`/`X`/`x`". D3, L32 — `ps -o state=,lstart=,comm= -p <pid>`.

**Why it is wrong:** BSD/Darwin `ps` appends flag suffixes to the state field: `Ss`, `S+`, `R+`,
and for a zombie `Z+` or `Z`. D4's test is whole-token membership, so `"Z+"` is not in `{Z,X,x}`.
The spec never says to take `state[0]`. Additionally `X` and `x` are Linux-only state codes with no
Darwin analogue, so the set is half-wrong for the OS D3 applies it to.

**Concrete failure (fail-safe direction, hence MED not HIGH):** a macOS zombie reports `Z+`, is
classified alive-and-matching, and the worker is pinned `working` indefinitely rather than
transitioning to `dead`/`idle`. No double-launch, but the state machine wedges. Symmetrically,
`Ss`/`S+` pass the "not a zombie" test correctly, so the common path masks the bug.

`[UNSETTLED — needs port-posix-smoke]` on real Darwin: exact `ps -o state=` output for a zombie.
Linux `ps -o state=` emits a bare single char (WSL-confirmed), so the Linux branch is unaffected.

**Suggested disposition:** Compare `state[0]` (first character only), and give the per-OS state
alphabet: Linux `{Z, X, x}`; Darwin `{Z}`. Also state how the three space-separated `ps` columns
are split, given that `lstart` itself contains four spaces and `comm` may contain a path with
spaces — the spec's D3 says "parse `lstart`" without saying how to isolate it. That is a second,
unlisted guess.

---

### F13 — MED — D4's `hidepid=2` example is factually inverted: it yields ENOENT, which the spec's own rule maps to `definitely-gone`

**Claim under review:** D4, L33 — "**alive-unknown** = `PermissionError`/`EPERM` reading
`/proc/<pid>/stat` (e.g. a `hidepid=2` mount hiding other users' processes on Linux)". Probe matrix,
L48, repeats it as the Linux alive-unknown discriminator.

**Why it is wrong:** WSL-verified against `man 5 proc`. `hidepid=1` — `/proc/<pid>` directories
"remain visible" but their files are protected → `open("/proc/<pid>/stat")` on another user's PID
raises **EACCES / `PermissionError`**. `hidepid=2` — those directories "become **invisible**" → the
path does not exist → **ENOENT / `FileNotFoundError`**. D4 maps `FileNotFoundError` to
**definitely-gone**. So the spec's own named example maps a live-but-hidden process to
definitely-gone: the exact double-launch direction, cited as evidence for the safe direction.

**Concrete failure:** on a `hidepid=2` host, probing another user's live PID → `FileNotFoundError` →
`"gone"` → dead → respawn → second claude. Practically unreachable in the supported configuration
(fleet probes its own same-user PIDs, which remain visible to their owner under both hidepid
levels), which is why this is MED. But the *claim* is load-bearing in D4 and it is backwards.

**Suggested disposition:** Name `hidepid=1` as the EACCES→alive-unknown path. State that
`hidepid=2` produces ENOENT and *would* misclassify a cross-user live PID as gone, and that fleet's
same-user probe is immune to both — so this never becomes a double-launch in the single-user
configuration fleet supports. Say that last clause explicitly; it is the load-bearing assumption.

---

### F14 — MED — D5's "the contract is fixed now" is hollow: `build_attach_argv`'s specified signature has no channel for env delivery, and the env script has no lifecycle

**Claim under review:** D5 residual, L34 — "The **no-secrets-in-argv assertion** … is deferred in
*enforcement* to Phase 2.5 `providers` build … but the *contract* is fixed now so
`port-adapter-b`'s `build_attach_argv` shape doesn't need to change later."

**Why it is wrong:** Two gaps, and OQ3 was pre-resolved with instructions to carry it forward *in
substance*.

1. The specified signature is `build_attach_argv(self, cwd, sid: str, which=shutil.which)` →
   `list[str] | None`. There is **no parameter** through which an env-script path could be passed
   and **no return channel** through which one could be reported. Delivering env in Phase 2.5
   ("script sourced by the launched shell") therefore requires either changing the returned argv
   shape (to `sh -c "source SCRIPT && claude --resume …"`) or adding a new adapter method. The
   shape *will* have to change. The guarantee is false as stated.
2. The env script's lifecycle is specified only for the happy path: "deleted on `fleet release`."
   The spec never says **who creates it**, **when**, or what removes it when `fleet release` never
   runs — worker killed, turn crashed, manager died. `fleet clean` (`cmd_clean`, fleet.py:3876)
   sweeps dead workers' artifacts; the spec is silent on whether it removes env scripts. A `0600`
   file with a provider secret orphaned in `state/` after an abnormal exit is a secret-at-rest path.

This is not CRITICAL today only because no secret exists to leak until Phase 2.5 — but D5 claims
the contract is settled *now*, which is precisely what a Phase-2.5 builder would rely on.

**Suggested disposition:** Either put the env-script path into `build_attach_argv`'s specified
return contract (derive it from `sid`, and say so), or drop the "shape doesn't need to change"
guarantee and record an expected Phase-2.5 interface addition. Separately, specify the script's
creator, its permission mechanism on each OS, and its deletion on **every** terminal path
(`release`, `kill`, `respawn`, `clean`, crash sweep) — and add env-script removal to `fleet clean`'s
artifact list.

---

### F15 — MED — D3 says "no macOS box exists in C4"; D10 mandates a `macos-latest` CI runner that would exercise the very probe D3 calls unverifiable

**Claim under review:** D3, L32 and probe matrix L49 — "no macOS box exists in C4 (OQ3-scope
deferral) … its correctness on real hardware is unverified" / "cannot be *exercised* live this
campaign." D10, L39 and done criterion 4, L149 — matrix `os: [windows-latest, ubuntu-latest,
macos-latest]`; "3 green OS jobs … is the required status check."

**Why it is wrong:** `macos-latest` is a macOS box. The `TestPosixPlatformBehavior` class the spec
mandates at L127 calls `get_process_info(os.getpid())` under
`@pytest.mark.skipif(os.name == "nt")` — which runs on the macOS runner and exercises the real
Darwin `ps -o lstart=` probe, including the `strptime` format and (per F12) the `state` parse.
Either D3's "unverifiable this campaign" is overstated, or the macOS CI job does **not** actually
run that probe, in which case "3 green OS jobs" is a merge gate that gives false confidence for one
of its three platforms. The spec cannot be right both ways.

**Concrete failure (the builder decision that stalls):** `port-ci` reads D3 and treats macOS
failures as expected/deferred; `port-test-suite` reads L127 and writes tests that run there.
Whichever way the ambiguity resolves, one of the two tasks is doing the wrong thing, and the merge
gate's meaning is undefined.

**Suggested disposition:** Reconcile explicitly. Recommended: state that `macos-latest` CI **does**
exercise D3's probe (which is good news — it converts D3 from unverified to CI-verified for the
common path), downgrade D3's residual to "unverified against a *real operator workflow*; the probe
itself is exercised by the macos-latest job," and list the specific macOS behaviors CI cannot cover
(attach/osascript, notifications — genuinely deferred).

---

### F16 — LOW — Citation hygiene: one quote is not in the page it is attributed to, one absence is "confirmed" by an author who could not check, and a third-party mirror is cited as authoritative

**Claim under review:** D2, L31 — "`comm` 'may contain spaces... and can even contain closing
parentheses' **per the same man page**" (attributed to `proc_pid_stat(5)`). D3, L32 — "The Darwin
`ps` KEYWORDS list has **no `etimes` keyword** (**confirmed absent**, not merely undocumented)",
cited to `https://leopard-adc.pepas.com/documentation/Darwin/Reference/ManPages/man1/ps.1.html`.

**Why it is wrong:** WSL `man 5 proc_pid_stat | col -b | grep -i "space\|parenthes"` returns only
"The filename of the executable, in parentheses" and an unrelated "stack space" line. The quoted
sentence is not in that page. The last-`)` split technique is nonetheless **correct** and the
arithmetic is verified — this is the author's own sound reasoning dressed as a verbatim citation,
which is the failure mode the drafting brief was written to prevent. Separately, a Windows-hosted
worker with no macOS box and no `ps` source cannot *confirm an absence*; "confirmed absent, not
merely undocumented" is an overclaim that contradicts the same row's own `[UNVERIFIED]` residual.
(The fact happens to be true — `etimes` is a procps-ng extension — which makes the overclaim
harder, not easier, to catch.) `leopard-adc.pepas.com` is a third-party mirror of *Leopard-era
(10.5, 2007)* Darwin man pages, cited without qualification for current macOS behavior.

**Note for the record:** this is the closest the spec comes to fabrication, and it does **not**
cross the line. Pass 1 found **zero invented experimental results**. Every POSIX/macOS behavior the
author could not run is tagged `[UNVERIFIED — verify in port-posix-smoke]`, correctly. The
instruction was obeyed.

**Suggested disposition:** Attribute the last-`)` requirement to reasoning ("`comm` is unquoted and
may contain `)` or spaces; therefore the naive `split()` is unsafe — derived, not quoted"), or cite
a page that says it. Downgrade "confirmed absent" to `[UNVERIFIED — no macOS box; etimes is
documented only in procps-ng ps(1)]`. Mark the Leopard mirror as an era-specific secondary source.

---

### F17 — LOW — D9's "the only modern-Python feature actually used is the walrus operator" is false; the conclusion survives only via an uncited `from __future__ import annotations`

**Claim under review:** D9, L38 — "Grep of `bin/fleet.py` for 3.10+-only syntax … found **zero**
hits — the only modern-Python feature actually used is the walrus operator `:=`
(`bin/fleet.py:4254`), which is 3.8+."

**Why it is wrong:** The listed greps do all return zero (verified: no `match`, no `tomllib`, no
`datetime.UTC`, no `removeprefix`/`removesuffix`; also no `zip(strict=)`, `.bit_count`,
`slots=True`, `aclosing`), and the walrus is indeed the sole `:=`. But PEP 604 `X | None` union
annotations are used throughout — 7 occurrences, e.g. `bin/fleet.py:499, 713, 782, 1144-1145, 1410,
1458` (`def recompute_status(..., current_status: str | None = None, ...)`). Those are a 3.10
runtime feature. They do not force a 3.10 floor **only because** `bin/fleet.py:20` is
`from __future__ import annotations`, which makes annotations lazy strings. D9's *conclusion*
("the code itself does not require 3.10; the floor is a distro-availability choice") is TRUE, but
it is reached by an incomplete grep and rests on a load-bearing fact the evidence cell never names.

**Concrete failure:** a builder who removes the `__future__` import (a plausible cleanup, since
nothing in the spec says it is load-bearing) silently raises the real floor to 3.10, and D9's stated
rationale no longer holds.

**Suggested disposition:** Add: "PEP 604 unions appear throughout but are neutralized by
`from __future__ import annotations` (`bin/fleet.py:20`) — that import is load-bearing for the
sub-3.10 syntax claim and must not be removed."

---

### F18 — LOW — Stale ownership and stale scope: the elevation check is attributed to a closed campaign, and the "shims per OS" the spec scopes into C4 already ship

**Claim under review:** Probe matrix, Windows row, L47 — elevation-mismatch is "the one remaining
`[UNBUILT — C2 hardening kernel item 9]` piece of F20". Scope, L12 — "shims per OS" listed as C4
work. D8 evidence, L37 — "any **future** shell-script file (e.g. a `run_py.sh`-style shim)".

**Why it is wrong:** The elevation check is genuinely unbuilt (SPEC.md:382 agrees; `grep -i elevat`
finds only a comment at fleet.py:224), but **C2 is merged and closed** (`48a50e0` "merge: Campaign 2
… 11 kernels"; postmortem `c57b7ee`). Item 9 will not build it. It is now unowned Windows residual,
not "owned by C2" — the same class of stale tag the author was sent to fix on the three-way probe.
Separately, `bin/fleet` (extensionless POSIX `#!/bin/sh` shim), `bin/fleet.cmd`, and
`bin/hooks/run_py.sh` **all already exist** (shipped in `0d09c25`). `run_py.sh` is not "future,"
and the existing `.gitattributes` already protects it (F7).

**Concrete failure:** a C4 builder scoped on "shims per OS" builds a POSIX shim that exists, or
waits for a C2 task that will never run.

**Suggested disposition:** Re-tag the elevation check as "unowned residual (C2 closed without it);
Windows-only, out of portability scope — no POSIX analogue needed." Re-scope L12 to "review the
existing shims (`bin/fleet`, `bin/fleet.cmd`, `bin/hooks/run_py.sh`)," and drop "future" from D8.

---

### F19 — LOW — D7's `Owner` cell reads "none (already shipped)" while its residual assigns the only real deliverable, and no done criterion covers it

**Claim under review:** D7, L36 — Owner: "none (already shipped) — `port-adapter-b` owns only the
residual below". Residual: "`port-adapter-b` should add a doctor check … **Recommended, not
currently required** by any shipped test; flagged for the builder to add or explicitly decline."

**Why it is wrong:** The `Owner` column is what a build worker scans for their own task name.
`port-adapter-b` sees "none" and moves on. The one real deliverable — a doctor check that the
embedded `{{PYTHON}}` path still executes — is buried in prose, framed as optional, and appears in
**none** of done criteria 1-8. That is a deferral wearing a decision's clothes: the row resolves
OQ5 correctly (the mechanism is shipped, `bin/fleet.py:2242`, verified) but leaves its only
actionable residue unowned and ungated. The gap D7 describes is real — `instance_freshness_info`
(fleet.py:1863) is mtime-only and does not check the embedded path executes.

**Suggested disposition:** Put `port-adapter-b` in the Owner cell. Then either promote the doctor
exec-check to a done criterion, or record it as an explicit
`DEFERRED (demand-gated — no shipped test requires it; re-vetted when a venv-move breaks a worker)`
line. "Recommended, not required" is neither.

---

## Disposition appendix

| ID | Severity | Owner | Status |
|---|---|---|---|
| F1 | CRITICAL | spec author | open — blocks `port-adapter-a` |
| F2 | HIGH | spec author | open — blocks `port-adapter-a` |
| F3 | HIGH | spec author | open — blocks `port-adapter-a` |
| F4 | HIGH | spec author | open — blocks `port-adapter-a`, `port-ci` |
| F5 | HIGH | spec author | open — blocks `port-adapter-a` |
| F6 | HIGH | spec author | open — blocks `port-adapter-a`; SPEC.md:382 prose drift filed separately, **not** in this spec's write set |
| F7 | HIGH | spec author | open — blocks `port-adapter-b` |
| F8 | HIGH | spec author | open — blocks `port-adapter-b`, `port-posix-smoke` |
| F9 | MED | spec author | open — blocks `port-test-suite` on `port-adapter-b` |
| F10 | MED | spec author | open |
| F11 | MED | spec author | open — would redden `windows-latest` |
| F12 | MED | spec author | open; Darwin `ps -o state=` zombie output `[UNSETTLED — needs port-posix-smoke]` |
| F13 | MED | spec author | open |
| F14 | MED | spec author | open; enforcement half legitimately deferred to Phase 2.5 `providers` |
| F15 | MED | spec author | open |
| F16 | LOW | spec author | open |
| F17 | LOW | spec author | open |
| F18 | LOW | spec author | open |
| F19 | LOW | spec author | open |

**Not findings — checked and clean.** The F20 stale-tag correction the author was ordered to make
was made, correctly, and verified against SPEC.md:382. No OQ was silently dropped: stub OQ1-8 plus
the pre-resolved OQ9 map 1:1 onto current OQ1-9 → D1-D12, none renumbered or substituted, all
`RESOLVED`. OQ9's substance (unit+hooks in CI, `live` gated on `FLEET_LIVE=1`, SPEC §12 tier-3) is
carried forward faithfully. Every `Owner task` names a real Campaign-4 task per `docs/PLAN.md`
(except F19's). All eleven `bin/fleet.py` line anchors and all twelve `tests/` line anchors the spec
cites are exact — the author did re-grep. D2's `/proc` field arithmetic is right. D4's zombie
rationale and retry-once claim are right. D6's `pid == pgid` premise is right. D9's conclusion is
right (F17 is about its reasoning, not its answer). The two invariant-8 source-scan lint tests do
stay green and unmodified, as promised — though F2, F4, and F6 are all OS-coupling that passes that
lint, which is a limit of the lint, not a violation of the promise.

**Weakest pass:** Pass 5. Decision-completeness is the only pass with no repro authority — you
cannot execute a decision table. Its findings (F14, F15, F19) are arguments about what a *future*
builder will misread, not demonstrations. If one pass should be re-run harder before the spec author
starts fixing, it is Pass 5 against the *revised* decision table, once F1-F8 have rewritten it.

**Two independent errors point at one root cause.** F1 (recomputed wall-clock ctime) and F6
(stored-vs-probed ctime conflated) are both the author reasoning about `turn_pid_ctime` from
SPEC.md's *prose* rather than from `probe_liveness`'s *code*. SPEC.md:382 describes an alive-unknown
tier that `bin/fleet.py:620` does not implement. The spec author inherited that drift and built on
it. Fixing F6 in `portability.md` alone leaves SPEC.md still wrong; that is a separate task and it is
outside this review's write set.
