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

---

## Fix-wave 1 disposition (spec-portability, 2026-07-10)

Applied against `docs/specs/portability.md`. Every CRITICAL/HIGH is FIXED — none disputed. WSL
Ubuntu (`wsl -d Ubuntu`) was used to independently re-verify `getconf CLK_TCK`/`os.sysconf`
agreement, `python3 --version` (3.12.3), and `/proc/stat`'s `btime` field, rather than only
reusing the reviewer's own transcript.

| ID | Severity | Status | Where fixed |
|---|---|---|---|
| F1 | CRITICAL | **FIXED** | D2 rewritten: Linux ctime is now a synthetic-epoch `datetime` built from boot-relative `starttime` ticks (`starttime_ticks / sysconf(SC_CLK_TCK)`), never recomputed from `time.time()`/`/proc/uptime`. Immune to NTP steps by construction (ticks are a kernel-immutable per-PID field). Failure behavior stated for (a) NTP step — immune, (b) reboot — correctly classifies gone (ticks reset near-zero), (c) PID reuse after reboot — same tick-mismatch discrimination, one accepted vanishingly-unlikely residual (no boot-id field added; reasoned why). No schema change to `turn_pid_ctime` needed — explicitly stated why (round-trips through existing `ctime_to_iso`/`_parse_iso` unchanged). D2 also states explicitly that macOS/D3 is NOT vulnerable to this bug (once-captured `p_starttime`, structurally like Windows `StartTime`). |
| F2 | HIGH | **FIXED** | D4 + `## Platform adapter interface`: `image_name` contract stated explicitly — must satisfy `_ALIVE_IMAGE_NAMES` (`fleet.py:604,628`); Linux reads `comm` (TASK_COMM_LEN truncation to 15 chars noted, "claude"/"node" fit); macOS reads `ps`'s `comm` column (full-path form noted, still substring-matches). |
| F3 | HIGH | **FIXED** | D4 + `## Platform adapter interface`: on any alive-unknown probe-read failure, the adapter returns the sentinel `("claude", None)` — a name that passes core's `_ALIVE_IMAGE_NAMES` check (`fleet.py:628`) before the ctime-is-None branch (`:630`) is reached, making the alive-unknown branch reachable from its own trigger case. |
| F4 | HIGH | **FIXED** | `## Platform adapter interface` + D6: `kill_process_tree(self, pid, killpg=None)` resolves `killpg = killpg or os.killpg` inside the method body, never as a default argument — `import fleet` no longer raises `AttributeError` on Windows. General rule stated inline for future adapter methods. |
| F5 | HIGH | **FIXED** | `## Platform adapter interface` + D2/D3: `ctime` contract stated as MUST-be tz-aware-UTC on every branch. Linux satisfies it via the F1 synthetic-epoch fix (already UTC-aware by construction). macOS: `ps -o lstart=` (naive local) is localized via `time.mktime` then converted to UTC — stdlib-only, no third-party tz dependency; DST-boundary exactness flagged `[UNSETTLED — needs port-posix-smoke]` (no macOS box to verify against). |
| F6 | HIGH | **FIXED (this spec's write set only)** | D4 rewritten: null/unparseable **stored** `turn_pid`/`turn_pid_ctime` is now correctly `definitely-gone` (matches shipped `bin/fleet.py:620-621,635-636`), not alive-unknown; alive-unknown is reserved strictly for probe-READ failures. The spec explicitly does NOT propose changing shipped `probe_liveness` (core, Windows-shared). **SPEC.md:382's independent prose drift is filed as a pointer only, per the reviewer's own instruction that it is out of this spec's write set — NOT fixed here, and not silently fixed by editing core.** Flagging for the manager/next SPEC.md-owning task. |
| F7 | HIGH | **FIXED** | D8 rewritten: corrected from "new file" to "already exists, `0d09c25`, review/extend only." Confirmed independently this fix-wave: `git log --oneline -1 -- .gitattributes` → `0d09c25`; `git ls-files --eol \| grep -c 'i/crlf'` → `0` (renormalize is a verified no-op). The blanket `* text=auto eol=lf` proposal is dropped entirely (would have deleted the load-bearing invariant-2 comment and existing targeted rules); done-criterion 7 (the renormalize step) removed. |
| F8 | HIGH | **FIXED** | `## Platform adapter interface` consumer-side note + D5: the `None`-branch state transition is now specified — `cmd_attach` checks for `None` AFTER the `attached` pre-claim (`fleet.py:3296-3301`) and BEFORE `popen`, prints the resume command + an explicit `fleet release`-required instruction, and does NOT enter the existing rollback-to-idle exception handler. Chosen direction (keep `attached`) justified against the double-launch risk of the alternative. |
| F9 | MED | **FIXED** | New `## Platform adapter interface` subsection "POSIX attach argv, pinned": exact argv for all 4 branches (`$TERMINAL` via `sh -c`, `gnome-terminal` via `--`, `tmux new-window` gated on `$TMUX`, headless `None`), with the shell-mediation question answered explicitly (one branch is shell-mediated by an explicit `sh` argv element; the others are not; `Popen(..., shell=True)` is never used). |
| F10 | MED | **FIXED** | Test port plan + Findings-against-PLAN.md #2: corrected to 13 tests (`test_steering.py:857-962`, `pytest -k Boundary -q` → `13 passed`, independently re-confirmed this fix-wave), breakdown corrected to 2 source-scan + 9 Windows-hardcoded + 2 unsupported-behavior (previously miscounted out of the "9" entirely). |
| F11 | MED | **FIXED** | Test port plan: `test_posix_platform_raises_unsupported` is now specified as DELETED outright on all OSes (not `skipif`'d, not "inverted in place") since it constructs `_PosixPlatform()` directly and would fail on every OS once implemented, not just POSIX. `test_unsupported_platform_error_is_not_implemented_error` is now correctly described as untouched forever (no `pytest.raises`, OS-independent) — the earlier self-contradiction removed. |
| F12 | MED | **FIXED** | D3/D4/probe matrix: zombie/dead check now compares `state[0]` only, with a corrected per-OS alphabet (`Linux {Z,X,x}`, `Darwin {Z}` only — `X`/`x` dropped for macOS). Darwin `Z+`/`S+`-style suffixes explicitly accounted for. `[UNSETTLED — needs port-posix-smoke]` retained for the exact Darwin zombie state string (no macOS box). |
| F13 | MED | **FIXED** | D4/probe matrix: `hidepid=1` (EACCES→alive-unknown) vs `hidepid=2` (ENOENT→definitely-gone) mapping corrected — the earlier example was exactly backwards. The load-bearing same-user-PID-only assumption is now stated explicitly as the reason this never becomes a live double-launch in fleet's supported single-user configuration. |
| F14 | MED | **FIXED (contract honesty); lifecycle spec ACCEPTED-AS-RESIDUAL, deferred to Phase 2.5 `providers` per the review's own note that this half is legitimately deferred** | D5: withdraws the false "shape doesn't need to change" guarantee — states plainly that `build_attach_argv`'s signature WILL need to change (or a new method added) for Phase 2.5 env delivery. The env-script creator/permission-mechanism/deletion-on-every-terminal-path specification is explicitly out of this spec's scope, owned by Phase 2.5 `providers`. |
| F15 | MED | **FIXED** | D10: explicit reconciliation added — `macos-latest` CI DOES exercise D3's probe via `TestPosixPlatformBehavior`, converting D3 from "wholly unverified" to "CI-verified for the common path, unverified only against a real operator workflow and DST-boundary edge cases." D3's and the probe matrix's residual cells cross-reference this reconciliation so `port-ci`/`port-test-suite` can't read them as contradictory. |
| F16 | LOW | **FIXED** | D2: the `comm`-may-contain-`)`/spaces claim is now attributed to reasoning, not a verbatim man-page quote. D3: the Darwin `etimes`-absence claim is downgraded from "confirmed absent" to `[UNVERIFIED — no macOS box]`, and the Leopard-era third-party mirror is explicitly flagged as an era-specific secondary source. |
| F17 | LOW | **FIXED** | D9: adds the missing fact that PEP 604 `X \| None` unions appear throughout and are neutralized only by `from __future__ import annotations` (`bin/fleet.py:20`), which is now flagged as load-bearing and must not be removed. Grep list also extended per the review's suggested additions. |
| F18 | LOW | **FIXED** | Probe matrix Windows row: elevation-mismatch re-tagged from "owned by C2 hardening kernel item 9" to "unowned residual, C2 closed, out of portability scope." Scope section: "shims per OS" re-scoped to "review of the existing shims" (all three already shipped in `0d09c25`). D8: "future shell-script file" wording dropped (`run_py.sh` already exists). |
| F19 | LOW | **FIXED** | D7: Owner cell corrected from "none (already shipped)" to `port-adapter-b`. The doctor exec-check residual is now explicitly `DEFERRED (demand-gated)` with a stated re-vet trigger (first real venv-move/distro-upgrade breakage), rather than the ambiguous "recommended, not required." `## Done criteria` gained an explicit "not a done criterion" note pointing at this so it isn't silently absent. |

**Not disputed:** none of F1–F19. Every finding's suggested disposition was independently verified against the cited code (`bin/fleet.py:604,620-637,875-885,182-187,218-269,3280-3314`, `.gitattributes`, `git log`/`git ls-files --eol`) and, where the review's own repro authority (WSL) applied, re-confirmed independently rather than taken on faith alone (see the WSL commands run this fix-wave, above the table).

**Newly verified via WSL this fix-wave (independent of the reviewer's own transcript):** `getconf CLK_TCK` → `100`; `python3 -c "import os; print(os.sysconf('SC_CLK_TCK'))"` → `100`; `python3 --version` → `3.12.3`; `/proc/stat` contains `btime 1783626278`. Four independent confirmations, feeding D2's evidence cell.

---

## Re-review — fix wave 1 (spec-portability-review-2, 2026-07-10)
**Verdict:** needs-fixes

Scope: verify commit `adfacab` against the 19 findings above; hunt regressions only in the sections it
touched (D2, D3, D4, D6, D8, the probe matrix, and — because the fix wave rewrote them — the
`## Platform adapter interface` block and `## Test port plan (B3)`). Everything else in the spec is out
of scope and was not re-reviewed.

Repro authority used: `py -3.13` with `sys.path.insert(0,"bin"); import fleet` (read-only, against the
real `ctime_to_iso`/`_parse_iso`/`probe_liveness`); `git show adfacab`; `git log`/`git ls-files --eol`;
grep; `py -3.13 -m pytest tests/test_steering.py -k Boundary -q` (13 passed).
**WSL Ubuntu was used** and is cited explicitly at each Linux claim below: `man 5 proc_pid_stat`,
`os.sysconf('SC_CLK_TCK')`, a live scan of every `/proc/<pid>/stat` `starttime`, and a `time.mktime`
TZ/DST experiment.

The author disputed nothing. **I found no spurious fix** — every one of the 19 findings was really
broken (F16's man-page absence and F11's direct `_PosixPlatform()` construction were both independently
re-derived from primary sources this session, not taken from the review's transcript). The problem is the
opposite: two of the fixes are themselves defective, and one HIGH was only half-applied.

| Finding | Verdict | Evidence |
|---|---|---|
| F1 | **REGRESSED** | The named CRITICAL is genuinely dead: D2's formula reads neither `time.time()` nor `/proc/uptime`, so an NTP step of any size cannot move it, and an independent consumer audit confirms `turn_pid_ctime` is *only* ever differenced (`bin/fleet.py:637`) — the synthetic epoch's core premise holds. **But the fix introduces a new HIGH defect (R1): boot-relative ticks have no cross-boot identity, making a post-reboot false-`alive` reachable, which then fires `killpg` on a live unrelated process group.** |
| F2 | **NOT-FIXED** | Only 1 of the 3 demands landed. The interface now *asserts* `image_name` must satisfy `_ALIVE_IMAGE_NAMES` and notes the 15-char/full-path forms. It still does **not** require `port-adapter-a` to record the real `comm` of a live POSIX `claude` turn, does **not** pre-authorize the cross-boundary edit to core's `_ALIVE_IMAGE_NAMES` (`bin/fleet.py:604`) that a mismatch would force, and does **not** drop or justify `"cmd"`. Surviving failure below the table. |
| F3 | FIXED | D4 + interface: "the adapter returns the sentinel `("claude", None)` … so core's name check (`fleet.py:628`) passes BEFORE it ever reaches the ctime-is-None branch (`fleet.py:630`)." Traced against real code: `"claude" in "claude"` → passes `:628`; `ctime is None` → `"unknown"` at `:630-632`. The branch is now reachable from its own trigger. |
| F4 | FIXED | Interface: `def kill_process_tree(self, pid, killpg=None)` with `killpg = killpg or os.killpg` resolved in the body, plus a module-top `import signal  # F4: never bind a POSIX-only stdlib name in a default argument or class body`. The general rule is stated, as F4 demanded. |
| F5 | FIXED | Interface: "`ctime` MUST be tz-aware UTC on every branch (F5)." Linux satisfies it by construction. The macOS *mechanism* chosen to satisfy it is itself defective — filed as R2, not as an F5 failure. |
| F6 | FIXED | D4: "**(F6 correction) the STORED `turn_pid`/`turn_pid_ctime` itself is null or fails to parse** — `probe_liveness` returns `"gone"` … on every OS today (`bin/fleet.py:620-621,635-636`), not alive-unknown." Matches shipped code exactly (re-read). All three probe-matrix rows updated. SPEC.md:382's drift filed as a pointer only, with the "must not be silently fixed by a builder editing core" clause. |
| F7 | FIXED | D8: "`.gitattributes` **already exists**, committed in `0d09c25`". Re-verified: real content is `*.sh text eol=lf` + `bin/fleet text eol=lf` + the invariant-2 comment; `git ls-files --eol \| grep -c 'i/crlf'` → `0`. Blanket `* text=auto eol=lf` dropped; done-criterion 7 (renormalize) removed; criterion 2 now says "review". |
| F8 | FIXED | Consumer-side note: "the `None`-check sits after the pre-claim and before the `popen` call; on `None`, `cmd_attach` prints … and returns WITHOUT calling `popen` and WITHOUT rolling the status back — the worker stays `attached`." The `fleet release`-required instruction is mandated in the printed output; done-criterion 6 checks both. |
| F9 | FIXED | New "POSIX attach argv, pinned" subsection gives literal argv for all four branches and answers the shell-mediation question ("`sh` is a visible, explicit child argv element, never `Popen(..., shell=True)`"). One loose end recorded as R4. |
| F10 | FIXED | "13 tests, not 11 … 2 pure source-scans … 9 Windows-hardcoded … 2 unsupported-behavior". Range corrected to `857-962`. Re-ran `pytest -k Boundary -q` → `13 passed`. `## Findings against PLAN.md` #2 corrected to match. |
| F11 | FIXED | "**Fix: DELETE `test_posix_platform_raises_unsupported` outright, on all OSes**". Confirmed at `tests/test_steering.py:950-951` that it does `posix = fleet._PosixPlatform()` directly, so the reviewer's "fails on every OS" claim is right. The neighbouring test is now "stays untouched, forever"; the L97/L127 contradiction is gone. |
| F12 | FIXED | D3: "compare `state[0]` only … Per-OS alphabet: **Linux `{Z, X, x}`** … **Darwin `{Z}` only**". D4 and both probe-matrix rows agree. The Darwin zombie string keeps its `[UNSETTLED — needs port-posix-smoke]` tag. The discriminator needed to *pick* the alphabet is unnamed — R5. |
| F13 | FIXED | D4: "`hidepid=1` … **EACCES/`PermissionError`** → alive-unknown … `hidepid=2` … **ENOENT/`FileNotFoundError`** → **definitely-gone**". The load-bearing clause is now explicit: "**fleet only ever probes its own same-user worker PIDs**". |
| F14 | FIXED | D5: "Delivering env in Phase 2.5 WILL require either changing the returned shape … or adding a new adapter method — this is a real, expected Phase-2.5 interface change, not a settled contract." The lifecycle half is deferred **with a named owner** (Phase 2.5 `providers`), which is what makes the residual acceptable rather than hand-waving. |
| F15 | FIXED | D10: "**`macos-latest` CI DOES exercise D3's probe**"; D3's residual narrowed to "unverified against a *real operator workflow*"; the D3 cell and the macOS probe-matrix row both cross-reference the reconciliation, so `port-ci` and `port-test-suite` cannot read them as contradictory. |
| F16 | FIXED | **Independently re-settled on WSL**, because a spurious fix here would bake a reviewer error into the contract. `man 5 proc_pid_stat \| col -b` gives, for field 2, only: *"The filename of the executable, in parentheses. Strings longer than TASK_COMM_LEN (16) characters … are silently truncated."* The sentence the first draft quoted is **not on that page**. The reviewer was right; D2 now attributes the last-`)` rule to reasoning. (Serendipity: WSL `/proc/324/stat` reads `324 ((sd-pam)) S …` — a real `comm` containing parentheses. The reasoning is not merely sound, it is observed.) `etimes` downgraded to `[UNVERIFIED — no macOS box]`; the Leopard mirror flagged era-specific. |
| F17 | FIXED | D9 now names the load-bearing fact: PEP 604 unions "do not force a 3.10 floor **only because** `bin/fleet.py:20` is `from __future__ import annotations` … **must not be removed**." Confirmed `bin/fleet.py:20` is exactly that import. Grep list extended. |
| F18 | FIXED | Probe-matrix Windows row: "C2 is merged and closed (`48a50e0`) … Re-tagged: **unowned Windows-only residual, out of portability scope**." Scope §: "**review of the existing per-OS shims**". Confirmed all three (`bin/fleet`, `bin/fleet.cmd`, `bin/hooks/run_py.sh`) are tracked. D8's "future" wording dropped. |
| F19 | FIXED | D7's Owner cell is now `port-adapter-b`; the residual reads `DEFERRED (demand-gated — F19 disposition)` with an explicit re-vet trigger; `## Done criteria` gained a "**Not a done criterion (F19 — explicit, not silently dropped)**" line. |

**Spurious fixes: none.** F16 and F11 — the two findings most likely to have been reviewer errors, and
the two whose "fixes" would have been most costly to bake in — were each re-derived from primary sources
this session. Both hold.

### F2's surviving failure

The interface block now asserts a contract without giving the builder any way to satisfy or falsify it:

> `image_name` MUST satisfy core's `_ALIVE_IMAGE_NAMES` substring test (fleet.py:604,628) or
> `probe_liveness` returns "gone" regardless of ctime (F2) — Linux returns `/proc/<pid>/stat`'s `comm`
> (TASK_COMM_LEN-truncated to 15 chars — "claude"/"node" fit with room to spare)

"Fit with room to spare" answers the *truncation-length* question. It presumes the answer to the
question F2 actually asked: **is a live POSIX `claude --print` turn's direct `Popen` child named
`claude` or `node` at all?** Core's own comment (`bin/fleet.py:597-603`) explains that `"cmd"`/`"node"`
are there because a *Windows* `claude.cmd` npm install re-parents through `cmd.exe`. Nothing in that
reasoning transfers. If the POSIX child is a `sh` wrapper, a venv shim, or a renamed launcher, every
probe of every worker returns `"gone"` on the first `fleet status`, deterministically → mass false-dead
→ `respawn` double-launch. Done criterion 7 records `python3 --version` and `SC_CLK_TCK`; it does not
record `comm`. So `port-adapter-a` still cannot discover this before `port-posix-smoke`, which runs after
the adapter merges — F2's stated failure, verbatim, unchanged.

Worse, the F3 sentinel makes the wrong workaround look sanctioned: a builder told both "`image_name` MUST
satisfy `_ALIVE_IMAGE_NAMES`" and "on a probe-read failure return the literal `"claude"`" will reasonably
hardcode `"claude"` whenever the real `comm` misses — silently disabling the PID-reuse image guard on
POSIX. The spec must forbid that in the same breath as it mandates the sentinel.

**Required:** (1) `port-adapter-a` MUST record the observed `comm` of a live POSIX `claude` turn as
evidence; (2) the spec MUST pre-authorize extending core's `_ALIVE_IMAGE_NAMES` in that same change,
since the set is core and the adapter cannot reach it; (3) `"cmd"` MUST be dropped from the POSIX
reasoning or justified; (4) the sentinel MUST be stated as legal *only* on the alive-unknown probe-read
path, never as a fallback for a real-but-unmatched `comm`.

### Regressions introduced by the fix wave

#### R1 — HIGH — The synthetic epoch trades an NTP-step false-`gone` for a cross-reboot false-`alive`, and `_interrupt_worker` then `killpg`s a live unrelated process group

**Claim under review:** D2 — "(b) **Reboot** — … a `turn_pid_ctime` stored pre-reboot differs from any
freshly-probed post-reboot process's ticks by (order of magnitude = pre-reboot uptime-at-launch) seconds,
far outside ±2 s … (c) **PID reuse after reboot** — … the one narrow accepted residual is a coincidental
post-reboot tick-value collision … the same *class* of vanishingly-unlikely accepted residual this
codebase already documents."

**Why it is wrong:** Both sentences are load-bearing and both fail in the deployment the ROADMAP already
plans for.

1. **"Order of magnitude = pre-reboot uptime-at-launch" is only large if the worker launched long after
   boot.** ROADMAP Phase 2's service-install starts the fleet manager from a logon-triggered task. A
   manager that starts at logon spawns its workers *inside the boot burst*, so uptime-at-launch is
   single-digit seconds and the stored synthetic ctime is `1970-01-01T00:00:3xZ`. A process launched at a
   similar boot offset on the *next* boot matches it within ±2 s.

2. **"Same class of vanishingly-unlikely residual" is a false equivalence.** The existing residual
   (`bin/fleet.py:597-603`) is *"a reused pid landing on an unrelated cmd/node/claude process within 2 s
   of the recorded ctime"* — where ctime is an **absolute wall-clock instant**. To collide, an unrelated
   process must have started inside a 4-second window of real time that lies in the past and can never
   recur. Under the synthetic epoch the collision condition becomes *"started within 2 s of the same
   **boot offset**"* — a condition that **recurs on every boot**, and that boot itself makes dense. One is
   a measure-zero coincidence; the other is a structural property of the representation.

3. **The two required coincidences are positively correlated, not independent.** Linux allocates PIDs
   sequentially from a counter that also resets at boot, advanced by the same deterministic boot+logon
   sequence that sets the tick offset. The "vanishingly unlikely" estimate silently multiplies two
   probabilities that are not independent.

4. **The ±2 s window was retained even though D2's own text says it now bounds only sub-second
   serialization truncation.** Measured against the real functions: the `ctime_to_iso`→`_parse_iso`
   round-trip has a supremum error of `0.999999 s` (truncated-stored vs untruncated-probed), so `±1 s` —
   or, per F1's original disposition, an exact-tick compare — would suffice. Keeping `±2 s` leaves a
   400-tick-wide window at `SC_CLK_TCK=100` where ~1 tick would do.

**WSL evidence (run this session, real `/proc`):** `SC_CLK_TCK=100`, so the compare window is `±200
ticks`, `400 ticks` (4 s) wide. Scanning every live `/proc/<pid>/stat` `starttime`:

```
    3343     33.43s  pid=1       systemd
    3347     33.47s  pid=2       init-systemd(Ub
    3376     33.76s  pid=40      systemd-journal
    ...
    3486     34.86s  pid=346     bash
densest +/-2s tick window contains 19 of 26 live processes
```

The entire userspace boot — PID 1 through the login shell — spans **1.43 s**, i.e. it fits inside a
*single* ±2 s window with room left over. Boot is precisely where the tick axis has no resolving power.

**Concrete failure:**
1. Manager auto-starts at logon (ROADMAP Phase 2). Worker `beta` is `working`; `turn_pid = P`;
   `turn_pid_ctime = 1970-01-01T00:00:37Z` (37 s of ticks).
2. Power loss / reboot. `state/registry.json` persists `beta` as `working` with `turn_pid = P`. Nothing
   invalidates `turn_pid` on boot — the spec explicitly declined a boot-id field.
3. Boot #2, same logon path, same deterministic sequence. The manager spawns worker `alpha`; its
   `claude`/`node` child gets PID `P` (sequential allocator, reset at boot) at ~36.2 s of ticks.
4. `fleet status`/`send`/`kill` on `beta` → `probe_liveness`: PID exists; `comm` is `node` → passes
   `_ALIVE_IMAGE_NAMES`; `|3620 − 3700| ticks = 0.8 s ≤ 2 s` → **`"alive"`**. `beta` is pinned `working`
   forever with no live process of its own (SPEC §11's reboot row says it should read gone).
5. The operator runs `fleet kill beta`. `_interrupt_worker` gates the kill on the ctime probe —
   `if not pid_alive(pid, ctime_iso, ...): return "not_running"` (`bin/fleet.py:3116`) — the gate
   **passes**, and `kill_process_tree(pid)` (`:3118`) fires: `killpg(P, SIGKILL)`.
   **Fleet SIGKILLs worker `alpha`'s process group while trying to kill `beta`.**

This falsifies the original review's own Pass-3 item (d) — *"`killpg` never fires on a reused pgid — every
kill path gates on the ctime probe first"* — which was true of the wall-clock representation and is not
true of this one. The failure *direction* is `alive`, not `gone`: it does **not** double-launch (invariants
5 and 7 hold), which is why this is HIGH and not CRITICAL. It wedges the state machine and it kills a live
process. Pre-fix D2 could not produce this: a recomputed wall-clock ctime for a post-reboot process is
always "now", never within 2 s of a pre-reboot launch instant. The defect is strictly new.

Fairness note: the review's own suggested disposition ("compare for exact equality, ±1 tick") has the same
hole, one 400th as wide. The author chose the wider of the two and then reasoned the residual away by
citing a comment about a structurally different residual.

**Suggested disposition:** D2 must stop calling this "the same class" of residual, must quantify it for the
boot-started-manager case, and must then pick one of these explicitly — this is exactly the cross-cutting
decision F1's disposition said the spec must make rather than leave to `port-adapter-a`:
- **(a) cheapest, no schema change:** on every `fleet` invocation compare `/proc/sys/kernel/random/boot_id`
  against a value cached in `state/`; on mismatch, null out every record's `turn_pid`/`turn_pid_ctime`
  before any probe runs. A null stored ctime is already `definitely-gone` (F6/D4) — the correct post-reboot
  verdict — and this needs no per-probe change.
- **(b) closes it completely:** add a `turn_pid_boot_id` companion field. That *is* a schema change; say so,
  rather than declaring one unnecessary.
- **(c) narrows it ~400×, does not close it:** tighten the Linux compare to exact tick equality. The ±2 s
  constant is **core** (`bin/fleet.py:637`), so this is a cross-boundary edit the spec must pre-authorize.

Whichever is chosen, D2 must state that `starttime` ticks carry **no cross-boot identity**, so `±2 s` on
this axis is not the same guarantee it is on the Windows/macOS wall-clock axis.

---

#### R2 — MED — D3's new `time.mktime` local→UTC conversion re-introduces F1's failure class on macOS: it makes a differenced-only quantity depend on the process's timezone environment

**Claim under review:** D3 (the F5 fix) — "`epoch = time.mktime(naive.timetuple()); ctime =
datetime.fromtimestamp(epoch, tz=timezone.utc)` … `[UNSETTLED — needs port-posix-smoke]` whether this
local→UTC round-trip is exact across a DST boundary on real Darwin."

**Why it is wrong:** The `[UNSETTLED]` tag guards the harmless half of the hazard, and the spec never names
the harmful half.

*The harmless half.* `naive.timetuple()` yields `tm_isdst = -1`, so `mktime` must guess on the repeated
local hour. That guess is **deterministic for a given input and timezone** — WSL, this session:

```
repeated mktime on ambiguous   2026-11-01 01:30 -> [1793511000.0, 1793511000.0, 1793511000.0]  deterministic: True
repeated mktime on nonexistent 2026-03-08 02:30 -> [1772955000.0, 1772955000.0, 1772955000.0]  deterministic: True
```

Store and probe both run the same function on the same immutable `lstart` string, so a wrong-but-consistent
guess **cancels in the difference**. DST ambiguity alone cannot break the ±2 s compare.

*The harmful half.* `time.mktime` reads the process's effective local timezone. Same naive input, same
session, three environments:

```
UTC                  epoch=1783606981  utc=2026-07-09T14:23:01+00:00
America/New_York     epoch=1783621381  utc=2026-07-09T18:23:01+00:00
Asia/Tokyo           epoch=1783574581  utc=2026-07-09T05:23:01+00:00
```

A 4-hour and a 9-hour shift. The stored value is written by whichever process ran `fleet spawn`/`send`
(`launch_turn` → `ctime_to_iso`, `bin/fleet.py:1348`); the probed value by whichever process ran
`fleet status`/`kill` (`recompute_status` → `probe_liveness`). If the effective timezone differs between
those two processes — an explicit `TZ=` in a launchd/cron/CI environment, or an operator changing the system
timezone mid-turn — the compare sees hours of difference, returns `"gone"`, takes `working→dead`, and
`fleet respawn` starts a second live `claude` in the same cwd. **That is F1's failure class, on macOS,
introduced by F1's sibling fix.**

The conversion buys nothing. An audit of every `turn_pid_ctime` consumer at HEAD (`bin/fleet.py`,
`bin/fleet_statusline.py`, `bin/hooks/*`, `commands/*`, `status_snapshot()`, `append_event`, every `--json`
path, `doctor`) confirms the field is never rendered, sorted, aged, or wall-clock-compared — the only
arithmetic on it anywhere is `abs((ctime - recorded).total_seconds()) <= 2.0` at `bin/fleet.py:637`. D2
relies on exactly that property to justify its synthetic epoch. D3 then pays a real correctness cost for an
absolute meaning nothing consumes.

**Concrete failure:** `fleet spawn` from an interactive shell (`TZ` unset → `/etc/localtime`). A
launchd-managed watchtower (Phase 2) later runs `fleet status` with `TZ=UTC` in its plist. Every macOS
worker probes `gone` → `dead` → the documented recovery lever `fleet respawn` double-launches. Invariants
5 and 7.

**Suggested disposition:** Apply D2's own trick, for which D3 already has every precondition: `lstart` is a
once-captured, immutable string for the life of the PID, so label it without converting —
`ctime = naive.replace(tzinfo=timezone.utc)`. This satisfies F5's tz-aware-UTC contract, is exact, is
timezone-environment-independent, needs no `time` import, and is consistent with the difference-only
contract D2 already depends on. Then delete the `[UNSETTLED — DST]` tag: with no conversion there is no DST
question. If the author instead keeps `mktime`, D3 must state that `turn_pid_ctime` on macOS is valid only
within a fixed-`TZ` process family, and name who guarantees that.

---

#### R3 — MED — The pinned `get_process_info` signature has no injection point, but the `TestPosixPlatformBehavior` class the same fix wave mandates requires one. This is F9's deadlock, relocated

**Claim under review:** Interface — `def get_process_info(self, pid):` (no further parameters). Test port
plan (F11's replacement class) — "returns the `("claude", None)` alive-unknown sentinel shape (F3) when a
fake `/proc` read is monkeypatched to raise `PermissionError` (Linux) — **via an injectable read-function
parameter** mirroring `get_process_info=None`'s injection pattern elsewhere in this file."

**Why it is wrong:** The `get_process_info=None` pattern the test plan points at is **core's**
(`probe_liveness(pid, ctime_iso, get_process_info=None)`, `bin/fleet.py:607`), not the adapter's. Neither
`_WindowsPlatform.get_process_info(self, pid)` (`:218`) nor the pinned `_PosixPlatform` signature has any
injection parameter. `kill_process_tree` got one (`killpg=None`, F4) and `build_attach_argv` has `which=`;
`get_process_info` has none — and the fix wave's own new test class demands one.

**Concrete failure:** identical in kind to F9, the finding this fix wave was supposed to close.
`port-adapter-a` implements the pinned two-argument signature. `port-test-suite` cannot write the mandated
sentinel test without either changing the adapter signature (a different task, a different wave) or
monkeypatching `builtins.open` — which the test plan did not ask for and which does not reach the macOS `ps`
branch at all. The two tasks deadlock, or the test author invents the contract.

**Suggested disposition:** Pin it. Add `read=None` (Linux: the `/proc/<pid>/stat` reader) and `run=None`
(macOS: the `ps` runner) to `get_process_info`'s specified signature, resolved inside the body per the F4
rule, and say in the interface block that they exist solely as test injection points and that no core call
site passes them. Then state which of the two the macOS branch of the sentinel test uses.

---

#### R4 — LOW — The pinned `$TERMINAL` argv calls `shlex.quote`, and the interface block's own import note lists only `signal`

**Claim under review:** "POSIX attach argv, pinned" — `[$TERMINAL, "-e", "sh", "-c", f"cd
{shlex.quote(cwd)} && claude --resume {shlex.quote(sid)}"]`; interface block — `import signal  # module
top-level -- F4: never bind a POSIX-only stdlib name in a default argument or class body`.

**Why it is wrong:** `bin/fleet.py` imports neither `shlex` nor `signal` today (`grep -n "^import
\(time\|shlex\|signal\)" bin/fleet.py` → only `32:import time`). F4's fix correctly added the `signal` note;
F9's new argv introduced a second missing import in the same commit and did not add one. Cosmetic —
`import shlex` is unconditional and portable — but the interface block is the copy-me artifact, and it is
one import short of running.

**Suggested disposition:** `import shlex` alongside `import signal` in the interface block's header.

---

#### R5 — LOW — F12's per-OS state alphabet needs a Linux-vs-Darwin discriminator the spec never names, and invariant 8's lint constrains where it may live

**Claim under review:** D3 — "Per-OS alphabet: **Linux `{Z, X, x}`** … **Darwin `{Z}` only**".

**Why it is wrong:** A single `_PosixPlatform` serves both OSes. D2 (`/proc`) vs D3 (`ps`) already implies an
internal discriminator, and F12 adds a third site that needs one, but the spec never says what it is
(`sys.platform == "darwin"`? `platform.system()`?) or where it may appear, given that
`TestPlatformAdapterBoundary.test_no_os_branches_outside_adapter_block` is the mechanical enforcement of
invariant 8. The fix wave sharpened the need without answering it.

**Suggested disposition:** One sentence in the interface block: name the discriminator, state that it lives
inside the adapter block, and confirm the source-scan lint's block boundaries cover it.

### CRITICAL-fix attack log

What I threw at the synthetic epoch, and what happened.

1. **"Is the difference-only claim true?"** — *survived.* Grepped `turn_pid_ctime` across the whole repo,
   not just `bin/fleet.py`: `bin/fleet_statusline.py`, `bin/hooks/*`, `commands/*`, `status_snapshot()`,
   every `append_event` call, both `--json` branches of `cmd_status`, `cmd_peek`, `cmd_result`, and all four
   `_doctor_check_*`. The field is stored (`:1348,1354,2346,2898,2993,3733`), cleared (`:3829`), or passed
   straight through to `pid_alive`/`probe_liveness` (`:1622,2619,3113,4210,4227`). It is decoded to a
   `datetime` in exactly one place — `probe_liveness` — and the only arithmetic is
   `abs((ctime - recorded).total_seconds()) <= 2.0`. It is **not** in `status_snapshot()`'s returned dict
   (so no view can render it), **never** printed by any CLI command, **never** written to `events.jsonl`,
   and **no** doctor check computes `now - turn_pid_ctime` (all staleness math uses `last_activity`,
   `attached_since`, or `limit_reset_at`). No statusline will print a 1970 date. The author's central
   premise holds, and the manager's grep is independently confirmed.

2. **`_parse_iso` round-trip** — *survived.* Driven against the real functions via
   `sys.path.insert(0,"bin"); import fleet`. `ctime_to_iso` truncates (`strftime("%Y-%m-%dT%H:%M:%SZ")`, no
   `%f`), so `probe_liveness` compares a truncated stored value against an untruncated probed one; the error
   is exactly the discarded fractional part, supremum `0.999999 s`, never reaching `1.0`. Well inside ±2 s
   for every `SC_CLK_TCK ∈ {100, 250, 1000}` and every uptime from 1 tick to 10 years. No overflow: at
   `SC_CLK_TCK=1000` a 100-year uptime lands at `2069-12-07`, and `datetime.max` would need ~8000 years of
   uptime. No year-<1000 zero-padding case exists (the base is 1970).

3. **The tz-aware/naive knife-edge** — *survived, but the margin is thinner than the spec admits.* On this
   UTC+5 box, `naive(1970,1,1,0,0,0).astimezone(timezone.utc)` raises `OSError(22, 'Invalid argument')` — a
   pre-epoch UTC instant the Windows CRT rejects. `ctime_to_iso` calls exactly that method
   (`bin/fleet.py:187`). D2's `datetime(1970,1,1,tzinfo=timezone.utc)` is aware, so `astimezone` is a no-op
   relabel and the path is safe **only because** the spec spells out `tzinfo=timezone.utc`. The near-epoch
   synthetic value puts the F5 tz-awareness contract on the critical path for a *crash*, not merely a wrong
   offset. No change required; worth one clause in D2 so that no builder "simplifies" it to
   `datetime(1970,1,1)`.

4. **Cross-OS registry mixing** — *not reachable, and here is precisely why.* A record's ctime is real-epoch
   (Windows/macOS) or boot-relative (Linux), and both are compared by the same core ±2 s constant, so a mixed
   registry would compare incommensurable quantities. But `probe_liveness` calls `PLATFORM.get_process_info`,
   and `PLATFORM` is selected from the **running** OS (`bin/fleet.py:340`). A Linux fleet reading a
   Windows-written record therefore probes a Linux PID and compares a boot-relative probe against a
   real-epoch stored value — off by decades → `"gone"`. Since a null or stale stored ctime is *also* `"gone"`
   (F6/D4), the mixed-registry outcome is the same fail-safe verdict a moved registry already produces; there
   is no path to a false `alive`. Note this is **not** guaranteed by any invariant: a worker's `cwd` is
   immutable (invariant 5) but `FLEET_HOME`/`state/` is not pinned to an OS by any invariant or doctor check,
   so a synced or shared `state/` is *possible*. It is safe by consequence, not by construction. **Not a
   fix-wave defect and I raise no finding** — but D2 asserts the fix is safe "with zero core changes" without
   naming this reasoning, and should state it in one sentence rather than leave a reader to reconstruct it.

5. **The reboot argument, attacked in the direction the author did not test** — *broke it.* The author tested
   stale-pre-reboot-ctime vs fresh-post-reboot-process (large tick delta → `gone`, the safe direction). The
   other direction — a worker launched `T` seconds after boot #1 vs an unrelated process launched `T ± 2`
   seconds after boot #2 — is admitted by the ±2 s window, and it is *dense* rather than rare: boot compresses
   the whole userspace startup into a sub-2-second tick band (WSL: 19 of 26 live processes inside one ±2 s
   window; PID 1 → login shell spans 1.43 s), and PID allocation resets at boot and advances through the same
   deterministic sequence, making the PID coincidence and the tick coincidence **correlated**, not
   independent. ROADMAP Phase 2's logon-triggered manager puts fleet's own workers squarely in that band. The
   consequence is a false `"alive"` — no double-launch, but a record pinned `working` forever, and
   `_interrupt_worker`'s ctime gate (`bin/fleet.py:3116`) passes, firing `killpg` on a live unrelated process
   group at `:3118`. Filed as **R1**.

**Verdict on the CRITICAL fix:** the NTP-step failure is genuinely and correctly eliminated, and the
difference-only premise it rests on is true for this codebase at HEAD — attacks 1 through 4 all failed to
break it. But the representation the fix chose carries **no cross-boot identity**, and the spec reasons that
gap away by equating it with an unrelated residual. The CRITICAL does not survive as a CRITICAL. It survives
as a HIGH pointing the other way.

**Gate.** One HIGH `NOT-FIXED` (F2) and one HIGH `REGRESSED` (R1). `docs/specs/portability.md`'s
`**Status:**` line therefore stays `drafting`. Nothing in this re-review bears on the C4 **build** waves in
any case — they remain gated on Altai's `SOAK GATE 1 SIGNED` line in `knowledge/lessons.md`, which still does
not exist.

---

## Fix-wave 2 disposition (spec-portability, 2026-07-10)

Applied against `docs/specs/portability.md`. WSL Ubuntu used again this fix-wave, independently: `cat
/proc/sys/kernel/random/boot_id` (twice, same value both reads — `8905ea2b-8244-46e7-b121-ca6770eb4749`),
`ls -la` on that path (`-r--r--r--`), and `whoami`/`id -u` confirming an unprivileged (UID 1000) read
succeeds. `grep -n "^import \(time\|shlex\|signal\)" bin/fleet.py`, `grep -n "def probe_liveness\|def
pid_alive\|def recompute_status\|def _interrupt_worker\|pid_alive(\|probe_liveness(" bin/fleet.py`, and
`grep -n "test_no_os_branches_outside_adapter_block" tests/test_steering.py` re-run directly against HEAD
to ground every line citation and the R5 lint-scan claim in current code, not the re-review's own numbers.

| ID | Status | Where fixed |
|---|---|---|
| R1 | **FIXED** | D2 rewritten (c): the "same class of vanishingly-unlikely residual" equivalence is withdrawn and replaced with the density/correlation argument the re-review made, plus an independent WSL re-scan this fix-wave (`getconf CLK_TCK`→100, boot-to-login-shell span 1.43 s, 19/26 live processes inside one ±2 s window). Closes the gap with boot identity rather than reasoning around it: a new additive registry field `turn_pid_boot_id` (nullable, Linux-only in practice, `null` on Windows/macOS always), compared inside the Linux branch of `get_process_info` (which gains a real `stored_boot_id` parameter) *before* the tick compare — mismatch → `None` (definitely-gone, reusing the existing wire contract, zero change to `probe_liveness`'s verdict logic); unresolvable (legacy `null` record or a failed current-boot-id read) → the F3 alive-unknown sentinel, never a bare "alive". D4, the probe matrix, the interface's `get_process_info` signature/docstring, and invariant 7's writeup were all updated to match. The core-side plumbing this requires (registry write in `launch_turn`; `stored_boot_id` threaded through `probe_liveness:607`, `pid_alive:640`, `recompute_status:870,881`, `_interrupt_worker:3115,3120`, the doctor check at `:4210`) is named explicitly, not hidden — `## Findings against SPEC.md` #1, owner `port-adapter-a`. The tolerance question is answered, not dodged: ±2 s is kept (not narrowed) because once the boot gate closes the cross-boot collision outright, the residual left is the ordinary same-boot PID-reuse case already accepted elsewhere; narrowing further is filed as an explicitly optional `## Findings against SPEC.md` #2, not applied. |
| F2 | **FIXED (3 of 3 remaining demands)** | `## Platform adapter interface`'s `get_process_info` comment gained an explicit "F2 REQUIRED" block: (1) `port-posix-smoke` (re-owned from `port-adapter-a` — no live POSIX box exists before that task runs) must record the observed `comm` of a real live POSIX `claude --print` turn, gated — build stops if it doesn't substring-match `_ALIVE_IMAGE_NAMES` — also added to `## Done criteria` #7; (2) extending `_ALIVE_IMAGE_NAMES` (`fleet.py:604`) on a gate failure is pre-authorized as part of `port-posix-smoke`'s own scope, named as such; (3) `"cmd"` is neither dropped from the shared core set nor relied on by the POSIX branch — justified (Windows-only `claude.cmd`→`cmd.exe` re-parenting quirk, no POSIX analogue) rather than silently carried or removed. A fourth guard was added beyond the three demands: the F3 sentinel is explicitly forbidden as a fallback for a real-but-unmatched `comm`, closing the "wrong workaround looks sanctioned" trap the re-review flagged. |
| R2 | **FIXED** | D3 rewritten: `time.mktime(naive.timetuple())` → `datetime.fromtimestamp(epoch, tz=timezone.utc)` replaced with `naive.replace(tzinfo=timezone.utc)` — a label, not a conversion, so it carries no dependency on the calling process's `TZ`. The three-`TZ` epoch spread the re-review measured (UTC/America-New_York/Asia-Tokyo, up to 9 h) is cited as the reason, re-derived this fix-wave against the same reasoning (not a macOS repro — no macOS box exists). The DST-boundary `[UNSETTLED]` tag is retired outright (no conversion, no DST question), including in the probe matrix's macOS row and D10's CI-coverage note, both of which still referenced it and were corrected in the same pass. `.replace(tzinfo=timezone.utc)` keeps the F5 tz-awareness contract intact — same mechanism D2 already uses for the synthetic epoch. |
| R3 | **FIXED** | `get_process_info`'s pinned signature gained `read=None`/`run=None` test-only injection points (mirroring `killpg=None`/`which=`), explicitly distinguished in the interface comment from the new `stored_boot_id` parameter (R1), which IS a real production call-site parameter, not a test seam. The Test port plan's `TestPosixPlatformBehavior` bullet, which pointed at the wrong injection pattern (`get_process_info=None`, which is `probe_liveness`'s, not the adapter method's), is corrected to reference the real parameters and extended to cover the R1 sentinel cases. |
| R4 | **FIXED** | `import shlex` added alongside `import signal` at the interface block's header, with the same "not imported by `bin/fleet.py` today" note F4's `signal` import already carried — re-verified this fix-wave: `grep -n "^import \(time\|shlex\|signal\)" bin/fleet.py` still matches only `import time`. |
| R5 | **FIXED** | One paragraph added to `_PosixPlatform`'s class docstring naming the discriminator (`sys.platform == "darwin"`) and confirming, against the lint's actual slicing logic (`test_no_os_branches_outside_adapter_block`, re-read directly this fix-wave at `test_steering.py:858-870`, not assumed) rather than the test's mere existence, that everything between the `# === PLATFORM ADAPTER START/END` markers — including the existing `PLATFORM = ... os.name == "nt" ...` selector line — is outside the lint's scan region. |

**Not disputed:** none of F2/R1–R5. Every fix was checked against the cited code this fix-wave, not only against the re-review's own transcript — the boot_id file, the shlex/signal import grep, the probe_liveness/pid_alive/recompute_status/_interrupt_worker call-site line numbers, and the lint's exact slice boundaries were all re-read directly at current HEAD.

**Newly verified via WSL this fix-wave:** `/proc/sys/kernel/random/boot_id` read twice (stable, same UUID both times); `ls -la` on that path (world-readable, `-r--r--r--`); `whoami`/`id -u` confirming an unprivileged read (UID 1000, not root). Three confirmations, feeding R1's mechanism directly (distinct from fix-wave 1's four WSL confirmations, which fed D2's tick-representation evidence cell).

**Not applied, named instead (per the write-set restriction: no `bin/fleet.py`, no `docs/SPEC.md` edits from this task):** two entries under the new `## Findings against SPEC.md` section — (1) the `turn_pid_boot_id` additive registry field and its core-side read/write/thread plumbing (R1's mechanism), owner `port-adapter-a`; (2) an optional, explicitly-deferred `tolerance_seconds` parameter on `probe_liveness`/`get_process_info` that would let the Linux branch use a ~1 s bound instead of the shared ±2 s constant, owner `port-adapter-a` if ever promoted, not required by any done criterion.

**Status left at `drafting`**, per instruction — this fix-wave does not self-promote.

---

## Re-review — fix wave 2 (loop 2)
**Verdict:** needs-fixes — **escalate rather than run a third fix wave**

Scope: commit `45851da` against R1/F2/R2/R3/R4/R5, plus regressions in the sections it touched
(D2, D3, D4, the probe matrix, `## Platform adapter interface`, `## Test port plan (B3)`, and the
new `## Findings against SPEC.md`). Everything else is out of scope and was not re-reviewed.

Repro authority: `git show 45851da`; grep and direct reads of `bin/fleet.py` / `tests/`;
`py -3.13` read-only. **WSL Ubuntu** used and cited per claim below.

**Headline.** The boot-identity *design* is right — I attacked it five ways and the design survived
all five, including the two the author was most exposed on (the `None`-means-gone reuse, and the
un-narrowed tolerance, which is now a **correct** argument where fix wave 1's version of it was
false). What does not survive is the *specification* of it. R1's read half is specified; **R1's write
half is not specified at all**, and the one production call site the author did not re-check —
`launch_turn` — turns the new case-3 rule into a CRITICAL: as written, every Linux worker stores a
null `turn_pid_ctime` at launch and reads `"gone"` on its first poll.

| Item | Verdict | Evidence |
|---|---|---|
| R1 | **NOT-FIXED** | The gate's read path is fully specified and correct. Its **write** path is one prose clause — "reading it from a new Linux-only adapter accessor at the same moment `get_process_info` is first called" — and the word `accessor` appears **exactly once in the entire spec** (`grep -c "accessor"` → `1`). No name, no signature, no return contract, no Windows/macOS counterpart, no test. Meanwhile `## Platform adapter interface` still specifies exactly **4** methods, line 53 still declares the duck-typed contract to be "same 4 method names, same call sites in core," and done criterion 1 still reads "**all 4 methods** per `## Platform adapter interface`". `port-adapter-a` cannot build the writer. With no writer, `turn_pid_boot_id` is `null` on every record forever, so **every** Linux probe takes case 3 (alive-unknown) — the gate never engages. This is F9's class (a mandated mechanism with no pinned contract), and it is why R1 is NOT-FIXED rather than merely regressed. See FW2-R2. |
| F2 | **FIXED** | All four demands landed, in the interface block's `F2 REQUIRED` numbered list plus done criterion 7. (1) "port-posix-smoke (NOT port-adapter-a …) MUST record the observed `comm` … with a build-stopping gate: if the observed name does not substring-match `_ALIVE_IMAGE_NAMES`, the build stops rather than shipping silently-broken liveness." (2) "extending `_ALIVE_IMAGE_NAMES` (fleet.py:604, core, outside the adapter block) … is **PRE-AUTHORIZED** as part of port-posix-smoke's own fix-forward scope." (3) `"cmd"` is justified, not dropped: "it exists solely for Windows' claude.cmd → cmd.exe re-parenting quirk … a POSIX install execs a shebang script or a real binary directly." (4) the trap I flagged is closed: "The sentinel … MUST NOT become the fallback whenever a real-but-unmatched `comm` is read. A builder who hardcodes "claude" to silence a requirement-1 gate failure … that is a defect, not a valid implementation." Done criterion 7 carries the gate. Nothing left to ask for. |
| R2 | **FIXED** | D3 and the interface both replace the conversion with a label: "macOS labels `ps -o lstart=` as UTC via `.replace(tzinfo=timezone.utc)`, never converted through `time.mktime` (D3, R2 — mktime reads the calling process's TZ and was itself a fix-wave-1 regression)"; D3 adds "it is a **label, not a conversion** (no timezone database consulted, no `time` module call)". Every remaining `mktime` mention in the spec is a negation. TZ-environment dependence is gone. |
| R3 | **FIXED** | `def get_process_info(self, pid, stored_boot_id=None, read=None, run=None)`, with `read`/`run` documented as "TEST-ONLY injection points … `read` stands in for the Linux `/proc/<pid>/stat` file read; `run` stands in for the macOS `ps` subprocess call. No core call site passes either one." The `TestPosixPlatformBehavior` sentinel test is now writable. (The *other* new parameter, `stored_boot_id`, is a production parameter and is where the damage is — FW2-R3.) |
| R4 | **FIXED** | `import shlex    # R4 fix-wave-2 -- the pinned $TERMINAL argv below calls shlex.quote(); neither this nor `signal` is imported by bin/fleet.py today`. Re-verified: `grep -n "^import \(time\|shlex\|signal\)" bin/fleet.py` → only `32:import time`. |
| R5 | **FIXED** | The discriminator is named and its lint-safety is *verified*, not assumed: "`sys.platform == "darwin"` … inside a `_PosixPlatform` method body is therefore lint-clean," justified by reading the lint's actual scan. I re-read it: `tests/test_steering.py:858-870` does `outside = source[:start] + source[end:]` and asserts the needles (`os.name`, `sys.platform`, `platform.system`, …) are absent from `outside` only. `_PosixPlatform` (`bin/fleet.py:313`) sits between the markers. Correct. |

**R2..R5: 4/4.** **F2: closed.** **R1: not closed.**

### Regressions introduced by fix wave 2

#### FW2-R1 — CRITICAL — D2's case 3 fires at launch time, so every Linux worker stores a null `turn_pid_ctime` and reads `"gone"` on its first poll

**Claim under review:** D2 — "3. **Stored boot_id is `null`** (a legacy record written before this field
existed, or the launch-time read failed) → **cannot verify either direction**, so the adapter returns the
F3 alive-unknown sentinel `(name, None)` rather than trusting the tick compare." Restated in the interface
block and in the Linux probe-matrix row. The rule is stated **unconditionally on the adapter method**, and
the parameter that carries it defaults to `None`.

**Why it is wrong:** `launch_turn` — core, unchanged by this spec, and the *only* place `turn_pid_ctime`
is ever produced — calls the adapter with no `stored_boot_id`:

```
bin/fleet.py:1343   get_process_info = get_process_info or PLATFORM.get_process_info
bin/fleet.py:1344   ctime_iso = None
bin/fleet.py:1345   try:
bin/fleet.py:1346       info = get_process_info(proc.pid)
bin/fleet.py:1347       if info is not None:
bin/fleet.py:1348           ctime_iso = ctime_to_iso(info[1])
bin/fleet.py:1349   except Exception:
bin/fleet.py:1350       ctime_iso = None
```

At stamp time there is no stored boot_id — by definition, the record is being created. So
`stored_boot_id` is `None`, case 3 applies verbatim, and the Linux adapter returns the sentinel
`("claude", None)`. Then: `info is not None` → `ctime_to_iso(None)` → `AttributeError` inside
`ctime_to_iso`'s `dt.astimezone(...)` → swallowed by the bare `except Exception` at `:1349` →
**`ctime_iso = None`**. The record is committed with `turn_pid` set and `turn_pid_ctime = null`.

`probe_liveness` maps a null **stored** ctime to `"gone"` unconditionally, at its very first branch —
this is F6's own finding, which this same spec correctly documents:

```
bin/fleet.py:620   if pid is None or ctime_iso is None:
bin/fleet.py:621       return "gone"
```

**Concrete failure:** `fleet spawn` on Linux → turn launches, `claude` is alive → registry records
`turn_pid_ctime: null`. The very next `fleet status` → `recompute_status` → `probe_liveness` → `"gone"`
→ retry-once (`:881`) → `"gone"` → **`working` → `dead`**, while the `claude` process is running. This is
mass false-dead on **every worker, on the first poll, deterministically** — and `fleet respawn`, the
documented dead-recovery lever, then calls `launch_turn` in the same immutable cwd: **two live `claude`
processes in one cwd.** Invariants 5 and 7. It is F2's original concrete failure and F1's original
concrete failure, arriving together through a third door.

Note the mechanism is silent: the `except Exception` at `:1349` is exactly the broad swallow that
`cmd_kill`/`cmd_respawn`/`cmd_clean`'s own comments already lean on ("`get_process_info` returns `None`
on ANY exception," `bin/fleet.py:3350,3764,3887`). Nothing logs, nothing raises, nothing lints.

**Suggested disposition:** The boot compare does not belong inside `get_process_info` at all. It is a
string equality on a field the adapter merely *supplies*; putting it inside the probe method is what
forced (a) an unspecified writer, (b) a production parameter on a method whose entire existing contract
is "answer a question about this pid", and (c) this launch-time collision. Instead:

- Add a **fifth adapter method on both adapters**: `boot_identity(self) -> str | None`. Linux reads
  `/proc/sys/kernel/random/boot_id`; Windows and macOS `return None`. It is a pure accessor with no pid
  argument — trivially testable, symmetric, and it satisfies the duck-typed 4-→5-method contract openly
  instead of smuggling a "Linux-only accessor" past it.
- `launch_turn` stamps `turn_pid_boot_id = PLATFORM.boot_identity()` next to `turn_pid_ctime`. No OS
  branch enters core; the value is opaque.
- `probe_liveness` gains `stored_boot_id=None` and does the compare **in core, before it calls
  `get_process_info` at all**: `current = PLATFORM.boot_identity()`; if `stored` and `current` are both
  non-null and differ → `"gone"`; if `stored` is null **and** `current` is non-null → `"unknown"`
  (the case-3 safe middle ground, now unreachable from `launch_turn` because `launch_turn` never calls
  `probe_liveness`); otherwise fall through to today's logic unchanged.

This keeps `get_process_info(pid, read=None, run=None)` at its R3 shape, leaves every existing test
double working, needs no change to `_WindowsPlatform`, and makes case 3 mean what the author wants it
to mean without it firing at stamp time. If the author prefers to keep the compare in the adapter, D2
must state explicitly that **`launch_turn`'s call passes a distinguishable `_UNSET` sentinel, not
`None`**, and that case 3 is skipped for it — see FW2-R5.

---

#### FW2-R2 — HIGH — The boot_id *writer* is one unspecified prose clause, and it contradicts the spec's own 4-method contract and done criterion 1

**Claim under review:** `## Findings against SPEC.md` #1 — "**Write path:** `launch_turn` stamps
`turn_pid_boot_id` alongside `turn_pid`/`turn_pid_ctime` at every launch (spawn, resume, respawn),
reading it from **a new Linux-only adapter accessor** at the same moment `get_process_info` is first
called on the freshly-`Popen`'d pid."

**Why it is wrong:** That clause is the entire specification of the writer. `grep -c "accessor"` over
`docs/specs/portability.md` → `1`. The interface block — the copy-me artifact — specifies four methods
and `get_process_info`'s return shape is explicitly *unchanged*: `None` / `(image_name, ctime)` /
`(image_name, None)`. **There is no return channel through which `launch_turn` could learn the current
boot_id.** So a fifth method is mandatory, and it is:

- unnamed, unsigned, un-return-typed, untested, and absent from `## Test port plan (B3)`;
- described as "Linux-only", which means `_WindowsPlatform` would not have it — so `launch_turn`
  (core) calling `PLATFORM.<accessor>()` raises `AttributeError` on Windows, and the only way to avoid
  that is a `hasattr`/`getattr` capability sniff, which is an OS branch in core in all but name (it
  passes the `test_no_os_branches_outside_adapter_block` needle list precisely the way F4's `os.killpg`
  did — green lint, dead Windows);
- in direct contradiction with `## Platform adapter interface` line 53 ("the contract is *same 4 method
  names, same call sites in core*") and with done criterion 1 ("`_PosixPlatform` fully implemented …
  **all 4 methods** per `## Platform adapter interface`"), neither of which fix wave 2 updated.

**Concrete failure:** `port-adapter-a` implements the four specified methods and stops, because done
criterion 1 says four. `turn_pid_boot_id` is never written. Every Linux record has it `null`, so every
probe takes case 3 → alive-unknown → every worker is pinned `working` forever, `pid_alive` is always
`False` so `_interrupt_worker` returns `"not_running"` and `fleet kill`/`interrupt` cannot reach the
turn, and the "self-healing per worker: the next successful launch/respawn populates
`turn_pid_boot_id`" clause never fires, because nothing ever populates it. R1's gate is inert and the
cross-reboot collision it was written to close is still open.

**Suggested disposition:** Pin the accessor in the interface block, on **both** adapter classes, with a
name, signature, return contract, and the `None`-on-Windows/macOS rule (see FW2-R1's `boot_identity()`
proposal). Update line 53 and done criterion 1 from "4 methods" to "5". Add its four branches to
`## Test port plan (B3)`.

---

#### FW2-R3 — HIGH — `_WindowsPlatform.get_process_info` never grows the parameter core is told to forward, and every existing test double is a one-argument lambda

**Claim under review:** `## Findings against SPEC.md` #1 — "`probe_liveness` (`:607`) and `pid_alive`
(`:640`) both gain a `stored_boot_id=None` parameter whose only job is forwarding to
`get_process_info`." Interface block — "Windows/macOS ignore it (always `None` on those OSes)."

**Why it is wrong:** macOS is fine — it runs `_PosixPlatform`, the class this spec is rewriting.
**Windows runs `_WindowsPlatform`**, and its signature is `def get_process_info(self, pid):`
(`bin/fleet.py:218`). This spec's write set is `_PosixPlatform`; the interface section is titled "Exact
method signatures `_PosixPlatform` … must implement"; done criterion 1 names only `_PosixPlatform`.
Nothing in fix wave 2 tells anyone to widen the Windows adapter. Once `probe_liveness` forwards
`stored_boot_id`, `PLATFORM.get_process_info(pid, stored_boot_id=...)` raises **`TypeError` on every
Windows probe** — every `fleet status`, `send`, `kill`, `clean`, `doctor`.

Second blast radius, equally concrete: core resolves `get_process_info = get_process_info or
PLATFORM.get_process_info` (`:622`, `:1343`), i.e. the forwarded parameter also reaches every **injected
test double**. Those are one-argument lambdas throughout — `get_process_info=lambda pid: None`
(`tests/test_cli.py:282,294,407,418,432,442,450`), `lambda pid: ("claude.exe", ctime)` (`:394`), and the
same shape across `test_core.py`, `test_steering.py`, `test_resilience.py`. Every one raises `TypeError`
the moment core forwards a second argument. `## Test port plan (B3)` does not mention them.

**Concrete failure:** `port-adapter-a` lands the core plumbing exactly as `## Findings against SPEC.md`
specifies. The `windows-latest` job of done criterion 4 goes red before the first assertion — this is
F4's failure mode ("green lint, dead Windows") reproduced by the very fix wave that closed F4.

**Suggested disposition:** Adopt FW2-R1's core-side compare, which removes the parameter from
`get_process_info` entirely and makes this finding moot. If the adapter-side compare is kept: state
explicitly that `_WindowsPlatform.get_process_info` gains `stored_boot_id=None` (ignored), name it in
done criterion 1, and add a `## Test port plan (B3)` item covering the arity change to every injected
`get_process_info` double across the four test files.

---

#### FW2-R4 — MED — The thread-through call-site list omits `_doctor_check_unreadable_starttime`, so `fleet doctor` flags every live Linux worker

**Claim under review:** `## Findings against SPEC.md` #1 — "every current call site that already pulls
`turn_pid_ctime` out of a record to call `probe_liveness`/`pid_alive` must also pull `turn_pid_boot_id`
and pass it through: `recompute_status` (`bin/fleet.py:870,881`), `_interrupt_worker`'s pre- and
post-kill checks (`:3115,3120`), **the doctor check at `:4210`**."

**Why it is wrong:** There are **two** doctor checks that pull those fields out of a record, not one.
`_doctor_check_stale_pids` (`:4206-4210`) is the one named. `_doctor_check_unreadable_starttime`
(`:4218-4228`) is not:

```
bin/fleet.py:4227   and probe_liveness(rec.get("turn_pid"), rec.get("turn_pid_ctime"),
bin/fleet.py:4228                      get_process_info=get_process_info) == "unknown"
```

It reads `turn_pid` and `turn_pid_ctime` straight off the record, exactly like the check one function
above it. Left un-threaded, it calls `probe_liveness` with `stored_boot_id` defaulting to `None` → D2
case 3 → alive-unknown sentinel → verdict `"unknown"` → **true for every live Linux worker**.

**Concrete failure:** `fleet doctor` on the exercise box prints "*N* working worker(s) with an unreadable
process StartTime" for **all** of them. The check is note-only (always PASS), so done criterion 5
(`fleet init && fleet doctor` clean) technically survives — which is what keeps this MED and not HIGH —
but the operator's one signal that the probe could not confirm a worker becomes noise on day one.

**Suggested disposition:** Add `_doctor_check_unreadable_starttime` (`bin/fleet.py:4218-4228`) to the
thread-through list. Then re-derive the list mechanically (`grep -n 'turn_pid_ctime' bin/fleet.py`)
rather than by inspection — the omission of a call site four lines below one that *was* listed is the
signature of a hand-built list.

---

#### FW2-R5 — MED — `stored_boot_id=None` uses one value for "the caller omitted it" and "this record's field is null", so every missed call site silently degrades to alive-unknown instead of failing loudly

**Claim under review:** D2 case 3 and the pinned signature
`get_process_info(self, pid, stored_boot_id=None, read=None, run=None)`.

**Why it is wrong:** The parameter's default and its legacy-record value are the same object. The adapter
therefore cannot distinguish *"core did not thread this through"* from *"core threaded through a genuine
`null`"*, and the spec assigns the second meaning to both. Every omission — `launch_turn` (FW2-R1),
`_doctor_check_unreadable_starttime` (FW2-R4), any future call site, any un-updated test — lands in the
alive-unknown branch, which by design is never demoted and never raises. The two most damaging findings
in this re-review are both instances of this one root cause, which is why it is filed separately rather
than folded into either.

Alive-unknown is the correct *verdict* for a genuinely-null stored field. It is the worst possible
*failure mode* for a plumbing bug, because it is indistinguishable from correct operation until a worker
wedges.

**Suggested disposition:** Preferred — FW2-R1's core-side compare, where the field is read from the
record at the one place that already reads `turn_pid_ctime`, so there is no parameter to forget. If the
parameter is kept, use a module-level `_UNSET = object()` default and specify that the adapter raises on
`_UNSET` rather than degrading, so a missed call site fails at the first test instead of the first
reboot.

### Boot-identity gate attack log

Five attacks. The **design** survived all five. The **specification** did not survive attacks 1 and 5's
follow-through, which is FW2-R1/R2/R3 above.

1. **The `None`-means-gone reuse.** *Survived.* `get_process_info(pid) is None` is mapped to `"gone"` at
   exactly one place — `bin/fleet.py:624-625` — and every consumer reaches it through
   `probe_liveness`/`pid_alive`: `recompute_status` (`:870,881`), `_interrupt_worker`'s pre- and post-kill
   gates (`:3115,3120`), `_doctor_check_stale_pids` (`:4210`), `_doctor_check_unreadable_starttime`
   (`:4227`), and `recompute_worker` (`:1623`) via `recompute_status`. **No caller calls
   `PLATFORM.get_process_info` directly and branches on `None` itself** except `launch_turn` (`:1346`),
   which only asks "is there a tuple to read a ctime out of." So the wire shape carries no second meaning
   any consumer can observe. Two further points in the author's favour, both of which I expected to break
   and did not: (a) `None` is *already* overloaded in shipped code — `_WindowsPlatform.get_process_info`
   ends `except Exception: return None` (`:268-269`), and `cmd_kill`/`cmd_respawn`/`cmd_clean`'s own
   comments say so ("`get_process_info` returns `None` on ANY exception," `:3350,3764,3887`) — so adding a
   third producer of `None` adds no ambiguity that was not already tolerated; (b) unlike those transient
   producers, a boot-id mismatch is *deterministic*, so the retry-once at `:881` cannot flap on it. The
   author's "positive proof beats absent evidence" framing (mismatch → gone; unresolvable → unknown) is
   the right way round, and it is the only place in this spec where a `"gone"` verdict is justified by
   proof rather than by absence.

2. **The launch-time race.** *Survived on the axis asked about; broke on an axis nobody was looking at.*
   A reboot between `Popen` and the stamp is not a hazard — a reboot kills the pid, so the record is born
   pointing at a dead process and the ordinary probe returns `"gone"`. The two-lock stamping sequence
   (`cmd_send`'s "re-acquire the lock once to stamp `turn_pid`/`turn_pid_ctime`", `bin/fleet.py:2722`) is
   also safe: `launch_turn` builds the whole dict — `turn_pid`, `turn_pid_ctime`, and (per the proposal)
   `turn_pid_boot_id` — *before* the lock is re-acquired, and all three are committed in one write
   (`:2346`, `:2898`, `:2993`, `:3733`, all four launch paths funnel through `launch_turn`'s return dict).
   So no record can exist with a ctime and a null boot_id **by way of the lock sequence**. It can exist
   for a different reason entirely: case 3 fires *inside* `launch_turn`'s own probe. That is FW2-R1, and
   it produces the opposite record — boot_id null *and ctime null* — which reads `"gone"`, not
   alive-unknown. The author's "legacy, self-healing" characterisation of a null boot_id is therefore
   correct for the case they considered and irrelevant to the case that actually occurs, since with no
   writer specified (FW2-R2) *every* record is a null-boot_id record and nothing ever heals.

3. **WSL-vs-real-Linux.** *Partially settled.* **WSL Ubuntu, this session:**
   `stat -c "%a %U" /proc/sys/kernel/random/boot_id` → `444 root`; `cat` → a stable UUID. It is
   world-readable and, being under `/proc/sys/` rather than `/proc/<pid>/`, **`hidepid` cannot affect it** —
   `hidepid` protects per-process directories only (`man 5 proc`). That much is settled, and it retires
   the spec's case-4 ("current boot_id read fails") as anything but paranoia on a stock kernel.
   **Not settled, and the spec should say so:** (a) whether a stock non-WSL systemd kernel guarantees the
   file (it is `CONFIG_PROC_SYSCTL` + the random driver; universally present in practice, but this is a
   documentation claim, not an experiment I ran); (b) **containers.** `/proc/sys` is not PID-namespaced,
   so a containerised fleet reads the **host's** boot_id — a container restart without a host reboot
   leaves the boot_id unchanged while the container's PID namespace resets to 1. The gate would not fire.
   Fleet is *probably* saved by a second accident — `/proc/<pid>/stat`'s `starttime` remains host-boot
   relative in a plain PID namespace, so post-restart processes carry large tick values that cannot
   collide with a stale record's — but a `CLONE_NEWTIME` time namespace virtualises `CLOCK_BOOTTIME` and
   would defeat that too. Tag `[UNSETTLED — needs port-posix-smoke]` and have the smoke test record:
   `cat /proc/sys/kernel/random/boot_id` on the exercise box; whether the box runs fleet in a container;
   and if so, whether `/proc/<pid>/stat` field 22 for a fresh process is host-uptime-scale or near-zero.
   Fleet does not currently claim container support, so this gates nothing — but the spec asserts the
   gate closes the reboot class outright, and a container restart is a reboot from the registry's point
   of view.

4. **The declined macOS analogue.** *Survived, with one honest gap the author already labelled.* The
   author's core claim — `kp_proc.p_starttime` is captured once at fork and not re-derived on read — is
   the same claim F1 rested on, and it is load-bearing again here. I cannot settle it without a Mac, and
   neither could the author; it stays `[UNSETTLED — needs port-posix-smoke]`, correctly tagged. But the
   argument does not actually depend on it: `probe_liveness` compares the **stored** `lstart` against a
   **re-read** `lstart` of the same pid, so even if the kernel re-derived the value, both sides would move
   together and the difference would still be zero. An NTP correction after the worker launched changes
   neither side of a self-consistent comparison. The only way a macOS record could false-`alive` across a
   reboot is if a *new* process's `lstart` landed within ±2 s of a *pre-reboot* stored `lstart` — which
   requires the box to boot to a wall clock within two seconds of the earlier launch instant, i.e. a
   machine with no working RTC. That is not a Mac. **`kern.boottime` is correctly declined.**

5. **The un-narrowed tolerance.** *Survived — and this is the finding I most expected to sustain and
   could not.* Fix wave 1 claimed the cross-boot collision was "the same class" as the existing accepted
   PID-reuse residual; that was false, and R1 proved it with boot-burst density. The author now makes the
   same-class claim about the **intra-boot** residual, and there it is **correct**. Once case 2 returns
   `None` before the tick compare, the surviving collision needs one boot to contain: a pid allocated to
   the worker, that pid *freed*, the allocator *wrapping the whole pid space* (WSL:
   `/proc/sys/kernel/pid_max` → `4194304`; `32768` on many distros), and the reused pid's `starttime`
   landing within ±2 s of the original's. But the tick value grows monotonically with the boot, and a
   wraparound takes far longer than 2 s of ticks to consume — so the reused pid's ticks are necessarily
   *far* from the original's. Boot-burst density does not bite here, because boot-burst pids are never
   the *reused* ones. The residual is genuinely the same class as `bin/fleet.py:597-603`'s. **The
   `tolerance_seconds` deferral is correct, its `## Findings against SPEC.md` #2 framing is honest, and
   the decision not to narrow ±2 s is right.** No finding.

**Verdict on the gate:** the mechanism is the right mechanism, chosen for the right reason, and the
author's two contested judgement calls (mismatch→gone before the tick compare; don't narrow the
tolerance) both hold up under attack. The gate fails only on plumbing — but it fails on plumbing in three
places, one of which is a CRITICAL that bricks Linux on the first `fleet status` and one of which reddens
`windows-latest`.

### Schema proposal

**Judged against SPEC.md:107's additive rule** ("`fleet.json` grows by ADDING fields, never
renaming/removing. Readers default any missing field …; writers preserve unknown fields"):

- **Additive rule: respected.** `turn_pid_boot_id` adds a field, renames nothing, removes nothing. The
  proposal states nullability ("string, nullable"), the legacy-record behavior ("readers default the
  missing field to `null`; writers preserve it on round-trip"), and cites the right precedents
  (`spawned_by`, SPEC.md:157; `limit_reset_at`/`limit_kind`, SPEC.md:126-129) — all three genuinely are
  additive-nullable fields under the same rule. No migration step, no format-version gate. Correct.
- **Invariant 8: not violated.** The core edits thread an *opaque string* through; no `os.name` /
  `sys.platform` / `platform.system` needle enters core, so
  `test_no_os_branches_outside_adapter_block` still passes for the right reason, not by accident. The
  OS-specific act (reading `/proc/sys/kernel/random/boot_id`) stays inside the adapter. The manager's
  worry that a schema change owned by the adapter task would breach the invariant-8 boundary is
  **unfounded** — invariant 8 governs where OS branches live, not which task edits which line, and the
  spec explicitly pre-authorizes the core edits, which is precisely what F1's disposition demanded.
- **Owner: defensible.** `port-adapter-a` owning five core call sites is fine *because it is written
  down*. The problem is not who owns the edits; it is that the edit list is wrong.
- **Enumeration: incomplete, in three places, and that is the finding.** The list omits `launch_turn`'s
  own `get_process_info` call (`:1346` — FW2-R1, CRITICAL), `_WindowsPlatform.get_process_info`'s
  signature (`:218` — FW2-R3, reddens `windows-latest`), `_doctor_check_unreadable_starttime`
  (`:4218-4228` — FW2-R4), and every injected `get_process_info` test double across four test files. It
  also relies on a fifth adapter method it never specifies (FW2-R2).

**SCHEMA-PROPOSAL-SOUND: no** — the additive rule and invariant 8 are both respected, but the core-edit
enumeration is incomplete in three places, one of which bricks Linux and one of which bricks Windows.

### Gate

`R1` is `NOT-FIXED`; five new regressions, one CRITICAL and two HIGH. `docs/specs/portability.md`'s
`**Status:**` line stays `drafting`. (Had the only defects been LOW-severity dispositions, promotion
would have been allowed under the manager's rule; that is not the case here.)

**Escalate.** Fix waves 1 and 2 each closed the finding they were aimed at and each introduced a new
defect in the same neighbourhood, in the same direction: a correct mechanism, specified with an
incomplete call-site enumeration, verified by inspection rather than by grep. A third wave against a
list I hand it would very likely produce a fourth. The structural problem is that D2 now specifies a
core plumbing change from inside an adapter spec, and the plumbing keeps growing. My recommendation to
the human: adopt FW2-R1's `boot_identity()` restructuring — it moves the compare into `probe_liveness`,
removes the production parameter from `get_process_info`, and reduces the core-edit list from "five call
sites, two adapter classes, and every test double" to "one new adapter method, one stamp in
`launch_turn`, one compare in `probe_liveness`" — and re-scope the whole boot-identity mechanism into a
short SPEC.md-owned decision rather than a residual clause inside a portability row.

Nothing in this re-review bears on the C4 **build** waves. They remain gated on Altai's
`SOAK GATE 1 SIGNED` line in `knowledge/lessons.md`, which does not exist.

---

## Fix-wave 3 disposition (`spec-boot-identity`, 2026-07-10) — escalation resolved

Author: `spec-boot-identity`, acting on Altai's ratified re-scope (`docs/PLAN.md` Campaign 4, added
2026-07-10). **Docs only**; `bin/fleet.py`, `bin/hooks/*`, `tests/*` untouched. Repro authority used:
`git log/show`, `grep`, read-only `py -3.13` import, read-only `pytest`, WSL Ubuntu.

**The rule this wave was given, and obeyed:** both prior waves specified a correct mechanism against a
call-site list built by **inspection**. Every enumeration below was produced by `grep`, and the grep is
pasted with it — in `docs/SPEC.md` appendix F33 (core), and in `docs/specs/portability.md`
`## Test port plan (B3)` (tests). Commit/date stamped: `9b5954d`, 2026-07-10.

**Structural fix.** The boot-identity mechanism no longer lives in `docs/specs/portability.md` D2. It is
`docs/SPEC.md` appendix **F33** + a §4 schema row + a §12 regression (`boot_identity_gates_tick_compare`),
tagged `[UNBUILT — owned by C4 port-adapter-a]`. D2 shrank from **16,922 characters to 4,809** and now
cites F33. `portability.md` keeps only what a portability spec owns: the adapter method. Its `**Status:**`
stays `drafting` — `spec-boot-identity-review` owns the promotion call for both specs.

| Finding | Verdict | Where / why |
|---|---|---|
| **FW2-R1** (CRITICAL) | **FIXED** (SPEC.md F33; portability.md D2, D4, probe matrix, interface) | The compare moved into `probe_liveness` (core), before `get_process_info` is called. `get_process_info` grows **no** boot-id parameter, so the `(name, None)` → `ctime_to_iso(None)` → swallowed `AttributeError` → `turn_pid_ctime=null` → `"gone"` chain is **structurally unreachable**: `launch_turn` never calls `probe_liveness`, and the receipt is pasted in F33 (`grep -n "probe_liveness(\|pid_alive(" bin/fleet.py` — `launch_turn:1241-1357` appears nowhere in the output). The deeper defect — an overloaded wire shape — is named in F33 and not repeated: `boot_identity()`'s `None` means *only* "this OS defines no boot identity"; a Linux read failure raises `OSError`, and is never encoded as `None`. |
| **FW2-R2** (HIGH) | **FIXED, and EXTENDED — see DISPUTED below** | `boot_identity(self) -> str \| None` is pinned in `## Platform adapter interface` on **both** adapter classes, with signature, return contract, the `None`-on-Windows/macOS rule *and why* each returns `None`, and its lint-safety verified rather than assumed. Interface line 53 and done criterion 1 now say **five** methods. `## Test port plan (B3)` gains `test_boot_identity_*`. Confirmed: the return channel FW2-R2 said was missing is exactly what a fifth method supplies; a fifth method is mandatory. |
| **FW2-R3** (HIGH) | **FIXED BY REMOVAL** | `_WindowsPlatform.get_process_info` (`bin/fleet.py:218`) is untouched, because core no longer forwards anything to it. The injected one-argument `get_process_info=lambda pid: ...` doubles across four test files keep working unchanged. There is no arity change to widen and no `windows-latest` breakage to fix. |
| **FW2-R4** (MED) | **CONFIRMED, FIXED, and EXTENDED** | The count is right. Re-derived mechanically, not by reading: `grep -c "def _doctor_check_" bin/fleet.py` → `18`; `grep -n "turn_pid" bin/fleet.py \| awk -F: '$1>=4043'` → hits only at `:4209,4210,4214,4215,4226,4227`, i.e. exactly **two** functions, `_doctor_check_stale_pids` (`:4206`) and `_doctor_check_unreadable_starttime` (`:4218`). Both are row 11 of F33's core-edit list. The finding's closing instruction — *"re-derive the list mechanically rather than by inspection"* — is the whole method of this wave, and executing it found two more sites the finding itself did not name. |
| **FW2-R5** (MED) | **FIXED BY REMOVAL** | The `_UNSET` sentinel is unnecessary because the parameter it was meant to protect no longer exists on the adapter. On core, `stored_boot_id` is a **required keyword-only parameter** on `probe_liveness` / `pid_alive` / `recompute_status` — omission is a `TypeError` at the call site, not a value. `None` therefore means exactly one thing (the record's field is null), and what *that* implies is decided by the fresh `boot_identity()` read, not by the null. No third overload is added; §12 pins the `TypeError`. |

**FW2-R1..R5: 5/5 disposed. 0 accepted as residual.**

### DISPUTED — 1

**The re-review's own suggested disposition, ratified verbatim into `docs/PLAN.md`, is short by three call
sites. "One stamp in `launch_turn`" is not sufficient, and would have reproduced FW2-R2's exact
"no writer" failure.** This is not a preference; it is a grep.

`launch_turn` does not write the registry. It **returns a dict** (`bin/fleet.py:1352-1357`), and four
separate commit sites copy the keys out of it under `fleet.lock`:

```
$ grep -n "turn_pid_ctime" bin/fleet.py          # (prose lines elided)
1354:        "turn_pid_ctime": ctime_iso,                                 <- launch_turn's RETURN dict
2346:                rec["turn_pid_ctime"] = info["turn_pid_ctime"]       <- cmd_spawn
2898:                r["turn_pid_ctime"] = info["turn_pid_ctime"]         <- cmd_send
2993:                r["turn_pid_ctime"] = info["turn_pid_ctime"]         <- _resume_one_limited
3733:                r["turn_pid_ctime"] = info["turn_pid_ctime"]         <- cmd_respawn
2619:                rec.get("turn_pid"), rec.get("turn_pid_ctime"), log_path,   <- cmd_wait
1622:        record.get("turn_pid"), record.get("turn_pid_ctime"), log_path,     <- recompute_worker
```

Consequences, all named in F33's eleven-row core-edit table:

1. **The four commit sites (`:2346`, `:2898`, `:2993`, `:3733`) must each copy `info["turn_pid_boot_id"]`.**
   Without them the field is never persisted, every Linux record reads `null` forever, every probe returns
   alive-unknown, and the gate is inert — precisely the concrete failure FW2-R2 described for the
   *un*-fixed spec, arriving through the fix that was supposed to close it.
2. **`cmd_wait` (`:2618-2622`) reads `turn_pid`/`turn_pid_ctime` straight off the record and calls
   `recompute_status`.** It is named by neither fix wave 2's list nor FW2-R4's correction of it. Left
   un-threaded, `fleet wait` takes the `stored_boot_id`-omitted path. (Under this wave's required-keyword-only
   design that is a loud `TypeError`, not a silent alive-unknown — which is the point of the design, and is
   why FW2-R5's disease had to be cured by construction rather than by a longer list.)
3. `recompute_worker` (`:1621-1624`) is the other record-reader behind `recompute_status`. The prior list
   named the forwarding function (`:870,881`) but neither of the two sites that actually read the record.

The reviewer was right about the mechanism and right to escalate. The *suggested disposition* was written
the same way the two fix waves it criticized were written. **The invariant is not "trust the reviewer's
list"; it is "re-derive the list with `grep` before every core change, and paste the grep."** F33 says so
in those words.

### Newly verified this wave (WSL Ubuntu; `wsl --list --quiet` → `Ubuntu`)

Attack 3 left three things unsettled. Two are now settled by command; one is not.

- **`boot_id` is kernel-global, not namespaced.** `[VERIFIED — WSL Ubuntu, unshare -r --fork --pid --mount-proc cat /proc/sys/kernel/random/boot_id → the same UUID, exit 0]`. Stronger than the reviewer's inference from `/proc/sys` not being PID-namespaced.
- **The boot-relative premise, which the whole design rests on and which no prior wave measured directly.** `[VERIFIED — WSL Ubuntu, awk '{print $22}' /proc/self/stat → 16469; getconf CLK_TCK → 100; cat /proc/uptime → 164.70 2582.76]` — field 22 ÷ CLK_TCK = 164.69 s ≈ uptime, so field 22 encodes ticks-since-boot and **no absolute instant**. A freshly spawned `sleep` read `16470` ticks.
- **Permissions and `hidepid`.** `[VERIFIED — WSL Ubuntu, ls -l → -r--r--r-- 1 root root; cat as uid 1000 → 53b5856e-50a5-4cdf-b283-944c2f619d7d; wc -c → 37; three reads across separate invocations, byte-identical]`. `[VERIFIED — cat /proc/mounts | grep ' /proc ' → rw,nosuid,nodev,noexec,noatime]`, no `hidepid`, and the path is under `/proc/sys/`, not `/proc/<pid>/`.
- **Containers remain `[UNSETTLED]`.** `which docker` → exit 1; no runtime in WSL. The host-boot_id-sharing claim follows from the namespace result above but was not demonstrated end-to-end. `port-posix-smoke` records it (F33 residual 1).
- **New, incidental:** `ps -o lstart=` on **Linux** is `btime + starttime/CLK_TCK`, and `btime` (`/proc/stat`; own read: `btime 1783631745`) is `wall_now − uptime` — so Linux `ps lstart` is NTP-step sensitive. This does **not** touch D3, where macOS renders a once-captured `p_starttime`. Recorded because a builder reaching for `ps` on Linux would silently inherit the step.
- `[UNVERIFIED — no macOS host]` macOS' `p_starttime`-captured-once premise. `[UNVERIFIED — would require `wsl --shutdown`]` that `boot_id` changes across a real reboot. `[UNVERIFIED — sudo -n true → "a password is required"]` a `hidepid=2` remount. All three carried and tagged; none asserted.

Lint re-verified read-only, not assumed: `py -3.13 -m pytest tests/test_steering.py -k Boundary -q` →
`13 passed, 42 deselected`. The scan is positional (`source[:start] + source[end:]` around the two marker
comments, `tests/test_steering.py:858-870`), so a `sys.platform == "darwin"` inside a `_PosixPlatform`
method is excised and never seen. R5's fix-wave-2 reasoning holds; `boot_identity()` inherits it.

### Carried forward, NOT silently fixed

D4 flags a genuine **SPEC.md drift**: `SPEC.md:115` and F20 (`:382`) both describe "the stored
`turn_pid`/`turn_pid_ctime` is null/corrupt" as **alive-unknown**, while shipped code returns `"gone"`
(`bin/fleet.py:620-621`, `:635-636`). D4 declined to fix it because SPEC.md was outside its write set.
SPEC.md **is** inside this wave's write set — and it is still not fixed here, deliberately: it is a separate
descriptive-drift finding, not an edit F33 requires, and "a builder silently fixing core to match a spec
sentence" is the exact hazard D4 raised. **F33's text does not depend on it** — F33 places its gate *after*
the `:620` branch, and says so, precisely so the two questions stay independent. Owner: a follow-up doc
task, or `spec-boot-identity-review`'s call.

### Two new residuals introduced by this wave, named rather than left to be discovered

1. **The `ubuntu-latest` unit-test trap.** On Linux `PLATFORM.boot_identity()` returns a real UUID, so the
   thirteen existing direct callers of `probe_liveness`/`pid_alive` change behavior: with `stored_boot_id=None`
   the gate fires and returns `"unknown"` where they assert `"alive"`. Green on Windows, red on Ubuntu — the
   mirror of FW2-R3, arriving from the test side. Receipt: `grep -rn "probe_liveness(\|pid_alive(" tests/ --include=*.py`
   → `test_core.py:371,377,383,387,391,396,408,413,418,427` and `test_resilience.py:2079,2082,2086`
   (the four other hits are test names / prose). Spec'd in `## Test port plan (B3)` with a recommended
   autouse `fleet.PLATFORM.boot_identity` stub. Owner: `port-test-suite`.
2. **`boot_identity` is deliberately not threaded** through `recompute_status` or the doctor checks; it is
   resolved once inside `probe_liveness`, with a test-only injection point there and on `pid_alive`.
   Rationale: `get_process_info`'s keyword fan-out across a dozen entrypoints is the disease this finding
   cures, and reproducing it for `boot_identity` would re-import it. The cost, stated: tests that reach
   `probe_liveness` indirectly must monkeypatch `fleet.PLATFORM.boot_identity` (precedent:
   `tests/test_terminal_surface.py:149,175,404`). A decision, with its price named.

### Gate

`docs/specs/portability.md` `**Status:**` remains **`drafting`**. This wave's author does not promote its own
spec, and does not promote the spec it amended (`87a85de`; PROCESS CHANGE #1,
`knowledge/lessons.md#2026-07-10-c4-spec-portability`). `spec-boot-identity-review` owns the
`ready-for-build` call for **both** `docs/specs/portability.md` and the F33 amendment to `docs/SPEC.md`.

**What the reviewer should attack first:** the eleven-row core-edit table in F33. Rows 8 and 9 exist because
a `grep` contradicted a list that two reviews and one ratified PLAN bullet had agreed on. Run the greps
again. If a twelfth site exists, this wave failed exactly the way its two predecessors did.

---

## Review — spec-boot-identity (F33)

**Reviewer:** `spec-boot-identity-review` (adversarial, third spec artifact of the C4 spec wave).
**Under review:** `28d5d81` (`docs/SPEC.md` → v2.2, appendix F33; `docs/specs/portability.md` D2 → citation).
**Verdict: `needs-fixes`.** CRITICAL=0 **HIGH=1** MED=0 LOW=2. `portability.md` **stays `drafting`.**
Nothing in this review unblocks the C4 build waves — they remain gated on Altai's `SOAK GATE 1 SIGNED`
line in `knowledge/lessons.md`, which does not exist.

**Write set obeyed.** `git diff --stat 9b5954d..HEAD -- bin/ tests/` → empty. No code or test was touched.

The design is right. The F33 null-discrimination idea survives every attack in the brief: it kills FW2-R1,
it kills FW2-R5, it keeps `OSError` out of every read-only view, its intra-boot residual claim is correct
**on the evidence** (not by analogy), and its receipts are honest — I re-ran all of them. The single HIGH is
not in the mechanism. It is in the one place the mechanism is invoked *outside* `probe_liveness`, and it
exists **because** of the FW2-R1 fix. That is the fourth consecutive occurrence of this campaign's signature
failure mode, and it is the reason this artifact cannot be promoted as written.

### The signature failure mode, stated once

Fix wave 1 closed F1 and broke the cross-boot case. Fix wave 2 closed R1 and broke `launch_turn`. F33 closes
FW2-R1 by **routing `launch_turn` around `probe_liveness`** — and `probe_liveness` is where F33 puts the only
`except OSError` in the entire design. So the fix that removed `launch_turn` from the danger path also removed
`launch_turn`'s only exception handler, and then F33's prose asserts a safety property that the specified code
cannot have. Each wave's fix is correct; each wave's fix relocates the defect one call site outward.

---

### HIGH — F33-R1: `launch_turn`'s boot-id read is specified unwrapped, but its stated behavior needs a wrapper. Built to the letter, an `OSError` orphans a live, billable `claude`.

F33's core-edit table, row 6:

> | 6 | `launch_turn`, `:1343-1357` | read `PLATFORM.boot_identity()` **before** the `:1345` `try`; add `"turn_pid_boot_id"` to the returned dict |

F33's prose, two paragraphs earlier:

> The boot-id read at launch is a separate, pid-free call whose exception is **not** swallowed by the bare
> `except Exception` at `:1349` — it sits before the `try` at `:1345`, so an `OSError` stamps `null`
> deliberately (a Linux worker with an unreadable boot_id probes alive-unknown, never `"gone"`).

The `so` is a non-sequitur. Placing an unguarded call *before* a `try` does not make its exception become a
`null`; it makes the exception propagate. The actual code (`bin/fleet.py:1343-1357`, read this session):

```
1343      get_process_info = get_process_info or PLATFORM.get_process_info
1344      ctime_iso = None
1345      try:
1346          info = get_process_info(proc.pid)
1347          if info is not None:
1348              ctime_iso = ctime_to_iso(info[1])
1349      except Exception:
1350          ctime_iso = None
1351
1352      return {
1353          "turn_pid": proc.pid,
1354          "turn_pid_ctime": ctime_iso,
```

The `try` at `:1345` is the only guard in the region. F33 correctly wants the boot-id read *outside* it (so
`except Exception` cannot swallow an `OSError` into a corrupt `turn_pid_ctime`) — but it never gives the read
a guard of its own, and then claims the behavior a guard would produce.

**Consequence, traced.** By `:1343` `Popen` has already run: the healthy-launch deadline loop at `:1339` has
elapsed and `proc.pid` is consumed at `:1346`. An `OSError` raised at `:1344` therefore escapes `launch_turn`
*after* a real `claude` is live. Every one of the four callers wraps `launch_turn` in `except BaseException`
and **pops the record**:

```
$ grep -n "launch_turn(" bin/fleet.py
1241:def launch_turn(name: str, cwd, sid: str, prompt: str, mode: str, first: bool = False,
2311:        info = launch_turn(          # cmd_spawn
2860:        info = launch_turn(          # cmd_send
2967:        info = launch_turn(          # _resume_one_limited
3692:        info = launch_turn(          # cmd_respawn
```

`cmd_spawn`, `bin/fleet.py:2310-2329`:

```
2310      try:
2311          info = launch_turn(
   ...
2320          finalize_mailbox_claim(claim)
2321      except BaseException as exc:
   ...
2325          restore_mailbox_claim(claim)
2326          with fleet_lock():
2327              data = load_registry()
2328              data["workers"].pop(args.name, None)
2329              save_registry(data)
```

So the outcome is not a ghost pre-claim. It is **worse**: a live `claude` process with *no registry record at
all* — no `turn_pid`, so `interrupt` and `kill` cannot reach it; no name, so `doctor` cannot see it; billing
until it exits on its own. `bin/fleet.py:1959` names this exact hazard in a comment: *"launch_turn() has
ALREADY succeeded -- a real, billable, running"* claude. Fires on all four launch paths (spawn, send, respawn,
resume-limited).

**§12 does not catch it.** The `boot_identity_gates_tick_compare` pin's launch companion reads:

> a launch commits a **non-null** `turn_pid_boot_id` on a platform whose `boot_identity()` is non-null, and its
> first `probe_liveness` returns `"alive"` — no worker is born `"gone"` (FW2-R1)

That pins the happy path only. No pin exercises `boot_identity()` *raising* at launch. The one behavior F33's
prose promises for that path is the one behavior nothing tests.

**Why HIGH and not CRITICAL.** The trigger is an `OSError` on `/proc/sys/kernel/random/boot_id`, and F33's own
evidence — which I reproduced (below) — shows that file is `0444`, world-readable, and outside `hidepid`'s
reach. It never mis-decides liveness. Unlike FW2-R1 it does not fire on every Linux worker. It requires a
`/proc`-less or hardened environment. **Why not LOW:** it is a stated-mechanism contradiction in a
**PRESCRIPTIVE** spec, on the sole code path where `boot_identity()` is called outside `probe_liveness`, with
no test pinning it, in a campaign whose thesis is that the call site one step from the fix is where the defect
lands.

**Fix — one sentence and one pin.**

1. Row 6 → *"give the read its own guard: `try: boot_id = PLATFORM.boot_identity()` / `except OSError: boot_id = None`,
   placed before the `:1345` `try` (so the bare `except Exception` at `:1349` cannot swallow it into a corrupt
   `turn_pid_ctime`, and an unreadable boot_id stamps `null` rather than raising past a live `Popen`)."*
   Delete the false causal clause from the prose paragraph.
2. §12 companion pin: *`boot_identity()` raising `OSError` at launch commits `turn_pid_boot_id = null` and the
   record still receives `turn_pid` — `launch_turn` does not propagate.*

With that, case (v) carries it the rest of the way: stored `null` + fresh non-`None` → `"unknown"` → alive-unknown,
never demoted, never `killpg`'d, self-healing on next launch. The design was already right; only the placement
text is wrong.

---

### LOW — F33-R2: the §4 example-record JSON carries `turn_pid_boot_id` with no `[UNBUILT]` marker

`docs/SPEC.md:89` shows `"turn_pid_boot_id": null,` inside §4's example record. The `[UNBUILT — owned by C4
port-adapter-a]` tag is 30 lines below, at `:119`. This matches the existing convention — `limit_reset_at` and
`limit_kind` (UL1, also prescriptive, also unbuilt) sit untagged in the same JSON — so it is not *new* drift,
and I do not hold the author to a standard the file does not already set. But the F20 mirror-image (an unbuilt
thing read as shipped) is precisely what the tag convention exists to prevent, and a builder scanning the schema
block sees three unbuilt fields presented as current. **Recommend** one line under the JSON naming the
prescriptive fields. Not blocking.

### LOW — F33-R3: `pid_max` is a sysctl, and the wraparound argument is quantitatively sensitive to it

F33 residual (2) argues the intra-boot residual is negligible because a pid-space wrap "consumes far more than
2 s" of ticks, citing `/proc/sys/kernel/pid_max` → `4194304 on WSL`. I confirm `4194304` on WSL Ubuntu
(below). But `pid_max` is a tunable whose *stock kernel* default is `32768`; `systemd` is what raises it. At
`32768` the wrap costs ≥16k forks/s to fit inside the ±2 s window — absurd for fleet, but not the ~128×-safer
number the spec quotes. The **class** claim is unaffected (see below). **Recommend** `port-posix-smoke` record
`pid_max` alongside `boot_id`. Not blocking.

---

## The dispute: **UPHELD. `docs/PLAN.md` is wrong and needs a second amendment.**

`docs/PLAN.md:185` ratified, verbatim:

> (b) adopt the reviewer's `boot_identity()` restructuring — the compare moves into `probe_liveness`,
> `get_process_info` grows **no** production parameter, cutting the core-edit list from "five call sites, two
> adapter classes, and every test double" to **"one new adapter method, one stamp in `launch_turn`, one compare
> in `probe_liveness`"**

That is three edits. The truth is eleven rows. The same PLAN bullet, four sentences later, mandates *"Every
call-site enumeration must be produced by `grep` and pasted as evidence."* The author obeyed the mandate and
thereby falsified the list the same bullet ratified. **PLAN.md contradicts itself, and the author is on the
right side of the contradiction.** I do not edit PLAN.md; the manager should amend `:185` (b) to cite F33's
eleven-row table rather than the three-edit reduction.

**All six of the author's anchors confirmed from primary source.** `launch_turn` does **not** write the
registry — it returns a dict at `:1352-1357`, whose keys four commit sites copy under `fleet.lock`
(`:2346`, `:2898`, `:2993`, `:3733`), and `cmd_wait` (`:2618-2622`) reads the fields straight off the record.

## CALL-SITE-LIST-COMPLETE: **yes.** The corrected list is not short.

The brief asked the question neither the manager nor the author had answered: *is the corrected list complete,
or is it short too?* I enumerated independently, by grep, and then checked every hit against F33's table.

```
$ grep -n "turn_pid" bin/fleet.py        # superset; the ctime footprint is the structural twin
547:        "turn_pid": None,
548:        "turn_pid_ctime": None,
1353:        "turn_pid": proc.pid,
1354:        "turn_pid_ctime": ctime_iso,
1622:        record.get("turn_pid"), record.get("turn_pid_ctime"), log_path,
2345:                rec["turn_pid"] = info["turn_pid"]
2346:                rec["turn_pid_ctime"] = info["turn_pid_ctime"]
2619:                rec.get("turn_pid"), rec.get("turn_pid_ctime"), log_path,
2805:            after["turn_pid"] = None
2897:                r["turn_pid"] = info["turn_pid"]
2898:                r["turn_pid_ctime"] = info["turn_pid_ctime"]
2950:        rec["turn_pid"] = None
2992:                r["turn_pid"] = info["turn_pid"]
2993:                r["turn_pid_ctime"] = info["turn_pid_ctime"]
3112:        pid = rec.get("turn_pid")
3113:        ctime_iso = rec.get("turn_pid_ctime")
3732:                r["turn_pid"] = info["turn_pid"]
3733:                r["turn_pid_ctime"] = info["turn_pid_ctime"]
3828:            rec["turn_pid"] = None
3829:            rec["turn_pid_ctime"] = None
4209:        if rec.get("status") == "working" and rec.get("turn_pid") is not None
4210:        and not pid_alive(rec.get("turn_pid"), rec.get("turn_pid_ctime"), get_process_info=get_process_info)
4226:        if rec.get("status") == "working" and rec.get("turn_pid") is not None
4227:        and probe_liveness(rec.get("turn_pid"), rec.get("turn_pid_ctime"),
(prose/docstring lines 184,185,754,766,790,793,1253,1256,1264,1957,1962,1974,2011,2014,2019,2023,2278,2324,
 2350,2712,2722,2728,2853,2874,2882,2902,2928,2930,2934,2976,2981,2997,3089,3130,3136,3164,3173,3184,3231,
 3233,3279,3448,3458,3462,3469,3558,3587,3620,3674,3710,3737,3776,3783,3804,4214,4215 elided — pre-claim
 `turn_pid is None` guards, `append_event` kwargs, and comments; none carries or forwards the field.)
```

Every mutating/reading site maps to an F33 row:

| line | F33 row | line | F33 row |
|---|---|---|---|
| `:548` | 2 (`new_worker_record`) | `:2993` | 9 (commit site) |
| `:1354` | 6 (`launch_turn`) | `:3113` | 10 (`_interrupt_worker`) |
| `:1622` | 7 (`recompute_worker`) | `:3733` | 9 (commit site) |
| `:2346` | 9 (commit site) | `:4210` | 11 (doctor stale-pids) |
| `:2619` | 8 (`cmd_wait`) | `:4227` | 11 (doctor unreadable-starttime) |
| `:2898` | 9 (commit site) | `:607/:640/:782` | 3, 4, 5 (signatures) |

The three residual `turn_pid = None` clears (`:2805`, `:2950`, `:3828`) are **named and dispositioned** in F33,
not omitted: *"the three sites that clear `turn_pid` on a rollback or a kill … leave a stale `turn_pid_boot_id`
behind, and `:620`'s `pid is None` short-circuit means the gate never sees it. Those sites therefore need **no**
boot-id edit."* I verified `:3828` sets `turn_pid = None` on the line above `:3829`, so the short-circuit does
hold, and `cmd_kill:3829`'s optional hygiene null is correctly labelled a decision rather than an omission.

**Signature blast radius, verified.** Required kw-only `stored_boot_id` on `probe_liveness`/`pid_alive`/
`recompute_status` makes every existing caller a `TypeError`. Production callers: `:646` (row 4), `:870`,`:881`
(row 5), `:1621` (row 7), `:2618` (row 8), `:3115`,`:3120` (row 10), `:4210`,`:4227` (row 11) — **all nine are
in the table.** Test callers: 13, enumerated by the author's own grep and assigned to `port-test-suite`; I
re-ran it and got 10 `pid_alive` + 3 `probe_liveness` = 13. **The list is complete.**

One subagent leg reported the list "still short by six" (`:548`, `:1622`, `:3113`, `:3829`, `:4210`, `:4227`).
That leg compared against the **commit message's six anchors** rather than against F33's eleven-row table. All
six are in the table (rows 2, 7, 10, dispositioned, 11, 11). Re-aimed at primary source, the finding evaporates.
Recording it because a future reviewer will make the same mistake: the commit message is not the spec.

## Attacks on the null-discrimination design

**FW2-R1 — DEAD.** `launch_turn` cannot reach the gate. `get_process_info` grows no production parameter, so the
`(name, None)` sentinel never carries boot-id meaning; and `launch_turn` never calls `probe_liveness`:

```
$ grep -n "probe_liveness(\|pid_alive(" bin/fleet.py   # code lines only
607:def probe_liveness(...)   640:def pid_alive(...)   646:  return probe_liveness(...)
870, 881: recompute_status   3115, 3120: _interrupt_worker   4210, 4227: doctor
```

`launch_turn` spans `:1241-1357` and appears nowhere. The FW2-R1 chain `get_process_info → (name, None) →
ctime_to_iso(None) → AttributeError → swallowed → turn_pid_ctime=null → "gone"` is structurally unreachable.
The §12 pin does pin it: a launch on a boot-identity platform commits non-null `turn_pid_boot_id`, and its first
`probe_liveness` sees fresh non-`None` + stored non-`null` + **equal** → falls through to the tick compare →
`"alive"`. No worker born `"gone"`.

**FW2-R5 — DEAD.** The two-meanings default is gone by *removal*, not by sentinel. Omission is a `TypeError` at
the call site. It is expressible: all nine production callers are enumerated above and every one is an edit row,
so the breaking change is a change the spec already schedules. The 13 test callers are named with a pasted grep
and assigned to `port-test-suite` with a concrete mechanism (autouse `fleet.PLATFORM.boot_identity` stub, on the
`get_process_info` monkeypatch precedent at `tests/test_terminal_surface.py:149,175,404`). §12 pins the omission
directly (`raises TypeError rather than silently degrading`), and any production site that forgets the kwarg goes
red through the existing suite, which already exercises `cmd_wait`, `doctor`, and `_interrupt_worker`.

**`OSError` into read-only views — NOT a finding.** I traced it and the spec is **not silent**; the answer is
correct on both counts. (1) The views never probe. `status_snapshot` (`bin/fleet.py:1742`) reads
`rec.get("status")` and routes through `_read_registry_readonly` (`:1722`, *"Never writes, never quarantines,
never raises"*); it calls neither `probe_liveness` nor `pid_alive`. The statusline
(`bin/fleet_statusline.py:236`), the SessionStart hook (`bin/hooks/sessionstart_fleet.py:101`), and
`cmd_status --stale-ok` (`:2419-2425`) all stop there. An `OSError` inside `probe_liveness` is structurally
unreachable from every surface `CLAUDE.md` names as a view. (2) For the commands that *do* probe — `cmd_status`
default (which takes `fleet_lock` and writes, so it is not a view), `cmd_doctor`, `wait`/`send`/`attach`/
`respawn`/`clean`/`interrupt`/`kill` — F33 catches it explicitly: `SPEC.md:467` *"`probe_liveness` catches that
`OSError` and returns `"unknown"` — the fail-safe verdict"*, with matching pseudocode, and `portability.md:269`
*"core catches it and returns `"unknown"`."* Correct, and correctly placed. **This is exactly why F33-R1 is a
finding: `probe_liveness` is the only place that catch exists, and `launch_turn` was deliberately routed around
it.**

**The equal-boot_id fall-through — the "same class" claim is CORRECT here, on the evidence.** Fix wave 1 made
this claim about the cross-boot case and was wrong, so I checked the structure rather than the analogy. Cross-boot
was wrong because a reboot **recreates every offset**: collision probability approaches 1, and is *densest at
boot* where fleet spawns. Intra-boot is structurally different: within one boot `starttime` increases
monotonically and is never revisited, so two processes sharing a pid must be separated by a **full pid-space
wrap**. A false `alive` needs that wrap to complete inside ±2 s (≤200 ticks at `CLK_TCK=100`). That is the same
guard shape as the accepted Windows/macOS residual at `bin/fleet.py:597-603` — *"a reused pid landing on an
unrelated cmd/node/claude process within 2s of the recorded ctime"*. Both reduce to "reuse must occur within 2 s
of the original's start." **Same class, and for a structural reason, not by analogy.** (Magnitude caveat: LOW
F33-R3.)

**Container / namespace — half settled here, half correctly left `[UNSETTLED]`.** I confirmed on WSL Ubuntu that
`boot_id` is kernel-global (a container therefore reads the *host's*, and a container restart without a host
reboot leaves it unchanged), and I settled the half the author deferred: **field 22 remains host-boot-relative
inside a PID namespace**, so a fresh container process's ticks are host-uptime-scale, not near-zero, and cannot
collide with a stale record's. Evidence (my run, this session):

```
$ wsl -d Ubuntu -- bash -c 'cut -d" " -f1 /proc/uptime;
    unshare -r --fork --pid --mount-proc bash -c "cut -d\" \" -f1 /proc/self/stat; cut -d\" \" -f22 /proc/self/stat"'
4.33                 # host uptime, seconds
2                    # namespace-local pid
434                  # field 22 = 434 ticks = 4.34 s  -> HOST boot, not namespace start
```

So the PID-namespace shape does **not** reintroduce the collision. What remains genuinely unsettled, and what
`port-posix-smoke` must check: (a) whether fleet ever runs under a container runtime at all (none available in
WSL to test); (b) `CLONE_NEWTIME` / `unshare --time`, which offsets `boottime` and *would* defeat the
host-relative property — the author names this defeater correctly; (c) the box's `pid_max` (LOW F33-R3).
The author's `[UNSETTLED]` tag is conservative and its named checks are the right ones.

## RECEIPTS-HONEST: **yes. FABRICATION: none.** Re-ran all seven at the stated commit (`9b5954d`).

| # | Receipt | Re-run verdict |
|---|---|---|
| R1 | `grep -rn "boot_id" bin/ tests/ --include=*.py` → `(no matches)` | **EXACT** |
| R2 | WSL: field 22 `16469` / `CLK_TCK 100` = `164.69` vs uptime `164.70` | **PREMISE INDEPENDENTLY REPRODUCED** — see below |
| R3 | `grep -n "get_process_info("` → `623`,`1346`; `grep -n "probe_liveness(\|pid_alive("` → 9 code lines | **EXACT**; the "comment/docstring lines elided" annotation names `:235,3073,3168,3237,3763,3779,3886` — correct to the digit |
| R4 | `grep -n "turn_pid_ctime"` (18 lines) + `grep -n "recompute_status("` (4 lines) | **EXACT** |
| R5 | `grep -c "def _doctor_check_"` → `18`; `awk -F: '$1>=4043'` → 6 lines | **EXACT**; `4043` really is the first `_doctor_check_` def |
| R6 | `grep -rn "probe_liveness(\|pid_alive(" tests/` → 10 + 3 = 13 | **ABRIDGED, self-declared, accurate** — reformatted to comma-lists; every line number and every code-vs-prose call correct |
| R7 | `git log --oneline -1 -- .gitattributes` → `0d09c25`; `git ls-files --eol \| grep -c 'i/crlf'` → `0` | **EXACT** |

Plus the runtime receipt `py -3.13 -m pytest tests/test_steering.py -k Boundary -q` → claimed `13 passed, 42
deselected`; I ran it: `13 passed, 42 deselected`. **EXACT.**

**On R2, which is the load-bearing premise of the entire finding.** It is the one receipt not reproducible from
the repo, so I re-derived it from scratch on WSL Ubuntu, twice, two seconds apart:

```
$ wsl -d Ubuntu -- bash -c 'cat /proc/uptime; cut -d" " -f22 /proc/self/stat;
                            sleep 2; cat /proc/uptime; cut -d" " -f22 /proc/self/stat'
54.30 839.09         5430        # 5430 ticks / 100 = 54.30 s  == uptime
56.30 871.18         5630        # 5630 ticks / 100 = 56.30 s  == uptime
```

Field 22 is boot-relative. **Confirmed.** No absolute instant is encoded, and F33's premise stands. (A first
attempt using the author's `awk '{print $22}'` form returned `2` — an argv-mangling artifact of the
Windows→`wsl`→`bash -c` quoting path, not a discrepancy in the author's number. Recording it so the next
reviewer does not raise the false alarm I briefly did: use `cut -d" " -f22` when crossing that boundary.)

Also independently confirmed on WSL Ubuntu: `ls -l /proc/sys/kernel/random/boot_id` → `-r--r--r-- 1 root root`
(`0444`, unprivileged-readable, and under `/proc/sys/` where `hidepid` does not reach); `getconf CLK_TCK` → `100`;
`pid_max` → `4194304`; and `unshare -r --fork --pid --mount-proc cat /proc/sys/kernel/random/boot_id` returns the
**same UUID** as the host — `boot_id` is kernel-global, not namespaced, exactly as claimed.

**Five workers, zero fabrications. The record holds.**

## `[UNBUILT]` tag coverage

Present on **4 of the 5** brief-named surfaces, and effectively on the fifth:

| surface | line | tag |
|---|---|---|
| Status header (v2.2 line) | `SPEC.md:3` | **yes** — and it adds the F20-mirror instruction: *"do not leave the tag on after `port-adapter-a` lands it"* |
| §4 PID-liveness paragraph | `SPEC.md:119` | **yes** — *"PRESCRIPTIVE, no part of this paragraph ships today"* |
| §4 schema row / field bullet | `SPEC.md:89`, `:121` | **inside** the `:119` paragraph, whose tag says "no part of this paragraph"; the JSON at `:89` is bare → LOW F33-R2 |
| §12 pin | `SPEC.md:340` | **yes** |
| appendix F33 | `SPEC.md:438` | **yes** |

Bonus: §14's adapter-surface line (`SPEC.md:357`) is tagged too. `portability.md` carries no inline tag on D2 /
`## Boot identity` / the adapter row, but all three explicitly defer (*"SPECIFIED ELSEWHERE, DO NOT RE-SPECIFY
HERE … decided in `docs/SPEC.md` appendix F33 + §4"*), which is the correct disposition for a doc that no longer
owns the decision. **No F20-style drift.**

## Scope: did shrinking D2 lose anything? **No.**

D2 went 16,922 → 4,809 chars. Everything load-bearing survived, in D2 or in its owning section:

- **Kept in D2:** the `comm` last-`)` parse and field indices; **F1 CRITICAL** — *"never recompute wall-clock via
  `time.time() − /proc/uptime`"*; the synthetic-epoch representation; `±2 s` unchanged; `sysconf` never
  hardcoded; NTP-step immunity; the intra-boot residual and its `:597-603` class; **`sysctl kern.boottime`
  explicitly declined** so macOS does not grow a boot id for false symmetry.
- **Moved, not lost:** the `tolerance_seconds` optional hardening finding. D2's prose referenced it; it *lives*
  in `## Findings against SPEC.md` #2, and it is intact there (`portability.md:389-392`) — default `2.0`, Linux
  requesting `1.0`, owner `port-adapter-a` if ever promoted, the measured `0.999999 s` round-trip supremum, and
  the "not required by any done criterion" gating all still present.
- **Heading diff `9b5954d`→`HEAD`:** every section preserved; exactly one added (`## Boot identity (SPEC §4 F33)`).

**Out of scope, and not drifted into:** every section `28d5d81` did not touch (D1, D3–D8, the per-OS probe
matrix rows other than Linux, the done criteria, `## Findings against PLAN.md`).

## Disposition

- `docs/SPEC.md` — v2.2 Status header left exactly as the author wrote it (an amendment, not a gate). **F33 is
  not yet ratified**: it is correct in mechanism and one sentence short in `launch_turn`. Fix F33-R1 (row 6 +
  one §12 companion pin) and it ratifies.
- `docs/specs/portability.md` — **`drafting`.** Not promoted. The `ready-for-build` line the reviewer was
  authorized to write is withheld solely on F33-R1; nothing in the portability spec itself is defective.
- `docs/PLAN.md:185` (b) — **wrong, needs a second amendment.** Manager's edit, not the reviewer's.

**Neither promotion would have unblocked anything.** The C4 build waves are gated on Altai's `SOAK GATE 1 SIGNED`
line in `knowledge/lessons.md`, which does not exist.

**For the next fix wave — the one-line brief:** F33-R1 is not a design flaw. It is the fix's own shadow. When you
route a call site *around* the function that owns the exception handler, you have moved that call site out of the
handler's scope. Grep for the handler, not just for the field.

---

## Fix-wave 4 disposition â€” `spec-boot-identity` (F33-R1..R3)

**Author:** `spec-boot-identity` (respawned; context reset, journal intact). **Append-only.**
**Under fix:** `2f1021a`'s `## Review â€” spec-boot-identity (F33)`. Write set: `docs/SPEC.md` (F33 only) +
this file (append only). **No code, no tests, no `docs/PLAN.md`, no `docs/specs/portability.md`.**
Receipts below are at `efa64be`; `git diff --stat 9b5954d..efa64be -- bin/ tests/` â†’ **empty**, so every
line number the reviewer and I both cite holds unchanged at either commit.

**No dispute. F33-R1 is correct, and the reviewer's trace is correct.** I built the fix one step past the
recommendation, for a reason given below.

---

### F33-R1 (HIGH) â€” **FIXED**, and with a second property the recommendation did not require.

The reviewer's minimum was *"give the read its own guard, placed before the `:1345` `try`."* That is
necessary and I adopted it. It is **not sufficient**, and the gap is the same one this campaign keeps
finding: it closes the exception class you named and leaves the ones you did not.

`except OSError` around the read makes an unreadable `/proc/sys/kernel/random/boot_id` stamp `null`. It
does nothing about an adapter bug â€” a `TypeError`, an `AttributeError`, a `ValueError` out of a UUID
parse. Placed at `:1344`, any of those still escapes `launch_turn` **after** `Popen` (`:1288`), and all
four callers `except BaseException` â†’ `data["workers"].pop(name, None)`. The orphan survives the fix at
one exception class' remove. Widening to `except Exception` would close it, but at the cost the narrow
catch exists to avoid: an adapter bug becomes a silent `null` and a permanently alive-unknown worker.

**So the specified read is guarded *and* hoisted above the `Popen`.** `boot_identity()` is pid-free and
side-effect-free; nothing forces it below `:1288`. Above it, *every* exception class raises before a child
exists, and the caller's `except BaseException` restores the mailbox claim and pops a record that never
had a live process behind it. The wrapper supplies the promised semantics; the hoist supplies the
impossibility. Neither alone does both.

This is not a new contract. It is `launch_turn`'s own, stated in its own comment:

```
$ sed -n '1270,1274p' bin/fleet.py            # at efa64be
    # funnels through here, so one guard covers them all -- and raising
    # BEFORE the Popen keeps the launch-sequence contract intact (the caller
    # restores the mailbox claim on any raise, same as a resolve/argv error).
    if not os.path.isdir(cwd):
        raise TurnLaunchError(f"registered cwd no longer exists, refusing to launch {name!r}: {cwd}")
```

```
$ grep -n "launch_turn(" bin/fleet.py         # at efa64be
1241:def launch_turn(...)   2311:cmd_spawn   2860:cmd_send   2967:_resume_one_limited   3692:cmd_respawn
(:236, :1959, :2280 prose/comments)

$ sed -n '1284,1298p' bin/fleet.py            # the Popen and its own OSError guard
1284:    out_f = open(log_path, "ab")
1288:            proc = popen(
1297:        except OSError as exc:
1298:            raise TurnLaunchError(f"failed to launch claude turn for {name!r}: {exc}") from exc
```

**Why not inside the `:1345` `try`** (the brief asked me to pick and justify): that block's
`except Exception` at `:1349` has exactly one purpose, `ctime_iso = None`. A boot-id read nested inside it
is swallowed by that handler and nulls `turn_pid_ctime` as collateral. `probe_liveness:620`
(`pid is None or ctime_iso is None â†’ "gone"`) then returns `"gone"` on the worker's **first** poll. That is
FW2-R1's exact failure, rebuilt out of FW2-R1's own fix. **Conflating the two handlers is how FW2-R1
happened.** They stay separate because their purposes are, and Â§12's new pin asserts the returned dict
still carries a non-null `turn_pid_ctime` so a builder cannot make that mistake silently.

**What the `null` means at probe time â€” walked through Â§4's table, not asserted.** The reviewer wrote
*"case (v) carries it the rest of the way"*. Case (v) as written covered only the branch where the file
became readable again. Both branches now exist and both are `"unknown"`:

- `boot_identity()` raising at all implies **Linux**: `_WindowsPlatform` and the macOS branch return `None`
  as a static property of the OS and have no failure mode. A Linux `boot_identity()` returns `str` or
  raises, never `None`. The two probe-time outcomes are therefore exhaustive.
- The record carries `turn_pid` and (because the handlers stayed separate) a non-null `turn_pid_ctime`, so
  `:620` does not short-circuit and the fresh read runs.
- **Still unreadable** â†’ fresh read raises â†’ `probe_liveness`'s `except OSError` â†’ **`"unknown"`**. This is
  **new case (vi)** in Â§4's table; the old five-case table had no row for a probe-time raise.
- **Readable again** â†’ fresh non-`None` + stored `null` â†’ **case (v)** â†’ **`"unknown"`**.

Never `"gone"`, on either. Case (v)'s consequence column then applies unchanged: never demoted to `dead`
(no `respawn` double-launch), `pid_alive` `False` (`_interrupt_worker` â†’ `"not_running"`, no `killpg`),
self-heals on the next launch. **Confirmed by walking it, and the walk found the missing row.**

**The Â§12 pin.** Added as a third companion to `boot_identity_gates_tick_compare`, with three assertions
rather than one, because each catches a different way to build row 6 wrong:

> a `boot_identity()` that raises `OSError` during launch yields a committed record with `turn_pid` set and
> `turn_pid_boot_id = null`; `launch_turn` returns normally and propagates nothing, and that worker's first
> `probe_liveness` returns `"unknown"` â€” never `"gone"`, and never an orphaned child.

(a) `launch_turn` does not raise â†’ catches the unguarded read (orphan). (b) the returned dict carries
`turn_pid` **and** non-null `turn_pid_ctime` â†’ catches the read nested in the `:1345` `try` (FW2-R1
rebuilt). (c) the verdict is `"unknown"` for **both** a recovered and a still-failing fresh read â†’ exercises
`probe_liveness`'s own `except OSError`, whose deletion is the next foreseeable regression.

### The same class of defect, everywhere else `boot_identity()` is called â€” **there is nowhere else.**

Two call sites, both now guarded. Row 1 defines the method; row 3 calls it in `probe_liveness` under
`except OSError`; row 6 calls it in `launch_turn` under `except OSError`, above the `Popen`. Nothing else
calls it, and that is a design property, not an accident: F33 deliberately does not thread `boot_identity`
through `recompute_status` or the doctor checks (*Test obligations*), which is what holds the count at two.

### Read-only views â€” **answered here, not left to `port-adapter-a`.**

```
$ grep -rn "probe_liveness(\|pid_alive(" bin/fleet.py bin/fleet_statusline.py bin/hooks/ --include=*.py
bin/fleet.py:607,640,646,870,881,3115,3120,4210,4227      # code
bin/fleet.py:3073,3168,3237,3763,3779,3886                # prose
bin/fleet_statusline.py: (no matches)
bin/hooks/: (no matches)
```

The reviewer is right that the statusline, the SessionStart hook, and `status_snapshot` never probe â€” so an
`OSError` is structurally unreachable from them. **But the reviewer's conclusion ("NOT a finding") rests on
`probe_liveness` catching it, and nothing states what happens if a builder decides that catch is
redundant.** It is not redundant; it is the only thing there is:

- `/fleet:doctor` is an inline read-only surface (`docs/specs/terminal-surface.md:54,148`) and `fleet doctor`
  **does** probe (`:4210`, `:4227`).
- `cmd_doctor` (`bin/fleet.py:4493`) builds `checks = [...]` **eagerly, with no `try`** â€” every check runs
  during list construction and any exception propagates out of `cmd_doctor`.
- `main()` catches `RegistryCorruptError`, then
  `(FleetCliError, ClaudeNotFoundError, TurnLaunchError, ValueError, FleetLockTimeout, UnsupportedPlatformError)`.
  **`OSError` is not in that tuple.** An escaping `OSError` is an unhandled traceback out of a read-only view.

So: `probe_liveness`'s `except OSError` is the **sole** containment for every probing surface. F33 now says
that, in the appendix, in the pseudocode comment, and in case (vi)'s consequence column, with the
instruction that `port-adapter-a` must not remove it in favour of a caller-side guard that does not exist.

---

### F33-R2 (LOW) â€” **FIXED**, and the fix names UL1's fields too.

The reviewer's own recommendation was *"one line under the JSON naming the prescriptive fields"* (plural).
Tagging `turn_pid_boot_id` alone would have fixed my field and left `limit_reset_at` / `limit_kind` in the
inconsistent state that made the convention ambiguous in the first place â€” the outcome the brief names as
the one indefensible option. The added line at `docs/SPEC.md:102` names **all three**, points at each
field's owning `[UNBUILT]` paragraph, and states why the JSON block cannot carry the tags itself. UL1's
semantics are untouched; this is an annotation, not an amendment, and it stays inside my write set.

### F33-R3 (LOW) â€” **BOUNDED**, and partly verified.

`[VERIFIED â€” WSL Ubuntu, cat /proc/sys/kernel/pid_max â†’ 4194304; uname -r â†’ 6.18.33.2-microsoft-standard-WSL2]`
â€” the reviewer's `4194304` reproduces. That settles the value on this box and settles nothing about any
other, which is the reviewer's point.

The old text ("a wraparound consumes far more than 2 s of ticks") is not a fact about ticks; it is a fact
about `pid_max`, smuggled in as one. Replaced with the bound it actually is. Every one of `pid_max`
allocations must occur between the original's start and the reused pid's, and a false `alive` requires that
interval to be â‰¤ 2 s, so reuse inside the window requires a **sustained fork rate â‰¥ `pid_max` / 2 s**:

| `pid_max` | required sustained fork rate | provenance |
|---|---|---|
| `4194304` | 2,097,152 /s | `[VERIFIED â€” WSL Ubuntu]` |
| `32768` | 16,384 /s | conservative floor `[UNVERIFIED â€” kernel default; verify in port-posix-smoke]` |

128Ã— apart. The **class** claim is unaffected â€” the reused pid must additionally pass the
`_ALIVE_IMAGE_NAMES` filter, and the residual is the same shape as `bin/fleet.py:597-603`'s accepted one â€”
but the spec now quotes the formula rather than one box's constant, and `port-posix-smoke` records `pid_max`
alongside `boot_id`. I did not assert a probability, because I cannot measure the fork-rate ceiling of a
machine I have not seen.

---

### Changes to `docs/SPEC.md`

| # | Surface | Change |
|---|---|---|
| 1 | `:102` (under Â§4's example JSON) | **new line** naming the three PRESCRIPTIVE-unbuilt fields (F33-R2) |
| 2 | Â§4 `turn_pid_boot_id` field bullet | **Writer** clause now says the read is guarded and hoisted above the `Popen` |
| 3 | Â§12 `boot_identity_gates_tick_compare` | two companion pins â†’ **three**; the launch-path failure pin, with its three assertions (F33-R1) |
| 4 | F33 appendix header | cites `F33-R1..R3`; states `bin/` is unchanged `9b5954d..efa64be` |
| 5 | F33 pseudocode | `except OSError` annotated **SOLE containment â€” do not delete** |
| 6 | F33, new *"The launch-path read"* section | replaces the retracted non-sequitur; wrapper + hoist, both justified; the two-call-site audit; the read-only-views paragraph |
| 7 | F33 case table | **five cases â†’ six**; (v) broadened to cover an `OSError`-stamped `null`; **(vi)** added for a probe-time raise |
| 8 | F33 core-edit table, **row 6** | rewritten: own `try/except OSError`, hoisted above `:1288`, explicitly not inside the `:1345` `try`, with the FW2-R1-rebuilt consequence spelled out |
| 9 | F33 *Accepted residuals* (2) | tick-consumption assertion â†’ the `pid_max`/2 s fork-rate bound (F33-R3) |

**Retracted, in writing:** *"it sits before the `try` at `:1345`, so an `OSError` stamps `null`
deliberately."* The `so` was a non-sequitur. It is gone from the appendix, not softened.

### New receipts: 7 (all at `efa64be`; `bin/`+`tests/` byte-identical to `9b5954d`)

1. `git diff --stat 9b5954d..efa64be -- bin/ tests/` â†’ empty
2. `grep -n "launch_turn(" bin/fleet.py` â†’ def `:1241`, callers `:2311,:2860,:2967,:3692`
3. `sed -n '1284,1298p' bin/fleet.py` â†’ `out_f = open` `:1284`, `proc = popen(` **`:1288`**, `except OSError` â†’ `TurnLaunchError` `:1297-1298`
4. `sed -n '1270,1274p' bin/fleet.py` â†’ the pre-`Popen` launch-sequence contract comment
5. `grep -rn "probe_liveness(\|pid_alive(" bin/fleet.py bin/fleet_statusline.py bin/hooks/ --include=*.py` â†’ **0 hits in `fleet_statusline.py` and `bin/hooks/`**
6. `cmd_doctor` `:4493` builds `checks = [...]` with no `try`; `main()`'s except tuple = `RegistryCorruptError` | `(FleetCliError, ClaudeNotFoundError, TurnLaunchError, ValueError, FleetLockTimeout, UnsupportedPlatformError)` â€” **no `OSError`**
7. `wsl -d Ubuntu -- bash -c 'cat /proc/sys/kernel/pid_max; uname -r'` â†’ `4194304` / `6.18.33.2-microsoft-standard-WSL2`

**Nothing fabricated.** Every command above was run this session, on this box, at `efa64be`.

### Residuals I am leaving, named

1. **`SPEC.md:115` and F20 (`:382`) still call a null/corrupt *stored* ctime alive-unknown; shipped code
   returns `"gone"` (`bin/fleet.py:620-621,635-636`).** Carried forward from fix wave 3, unchanged. F33 does
   not depend on it (the gate sits after `:620`), and folding it silently is the hazard D4 raised. Owner:
   a follow-up doc task, or `spec-boot-identity-review`'s call.
2. **`32768` as the stock `pid_max` default is `[UNVERIFIED]`.** I have one Linux box and it reports
   `4194304`. The bound is stated as a formula so the claim does not depend on which is right.
3. The `ubuntu-latest` unit-test trap and the `boot_identity` non-threading cost, both from fix wave 3,
   stand as spec'd. Owner `port-test-suite`.

### Disposition

- **F33-R1 â€” FIXED.** Row 6 respecified (guard + hoist above `:1288`), the false causal clause retracted,
  the launch-path failure pin added to Â§12 with three assertions, case (vi) added, the read-only-views
  containment stated where the decision lives.
- **F33-R2 â€” FIXED** (one line, all three prescriptive fields).
- **F33-R3 â€” BOUNDED** (fork-rate formula; `pid_max` verified on WSL; `port-posix-smoke` records it).
- **Disputed: none.** The reviewer's trace was right, its recommendation was one exception-class short, and
  I said so above rather than quietly building past it.
- **Promotion: not mine.** `docs/specs/portability.md` untouched, `Status: drafting`. `spec-boot-identity-review`
  owns the `ready-for-build` call for both specs.

**For the reviewer â€” the one-line brief:** re-check **row 6's hoist** before anything else. The wrapper is
the reviewer's fix and it is in; the hoist is mine and it is the load-bearing half. If `boot_identity()` is
read anywhere below `bin/fleet.py:1288`, an adapter bug raising a non-`OSError` still orphans a live,
billable `claude`, and `except OSError` will not see it. Grep for the `Popen`, not just for the handler.

---

## Re-verify — F33 fix wave

**Reviewer:** `spec-boot-identity-review`. **Under review:** `2f56bb3` (fix wave 4), against my
`## Review — spec-boot-identity (F33)` above.
**Verdict: `needs-fixes`.** CRITICAL=0 **HIGH=1** MED=1 LOW=1. `portability.md` **stays `drafting`**;
SPEC.md F33 **not ratified**. `FABRICATION: none` — all seven new receipts re-run and exact.

**Write set obeyed.** `git diff --stat 9b5954d..HEAD -- bin/ tests/` → empty. Docs only, both commits.

**F33-R1 — the HIGH I raised — is genuinely FIXED, and fixed better than I asked.** The new HIGH is not
in it. It is in the fix for `F33-R2`, the LOW. And the false premise `F33-R2`'s fix encodes is **mine**:
I wrote it into my own review, the author implemented it without grepping it, and it is now a false
statement about shipped code sitting in §4. Both of us skipped the one command that would have caught it.
That is the finding.

---

### F33-R1 — **FIXED. ORPHAN-IMPOSSIBLE: yes.**

Row 6 now reads (`docs/SPEC.md`):

> give the read its own guard and hoist it **above the `Popen` at `:1288`**: `try: boot_id = PLATFORM.boot_identity()` /
> `except OSError: boot_id = None`. **Not** inside the `try` at `:1345` …

Traced, not taken on trust. `Popen` is at `bin/fleet.py:1288`:

```
$ sed -n '1284,1290p' bin/fleet.py
1284      out_f = open(log_path, "ab")
1285      err_f = open(err_path, "ab")
1286      try:
1287          try:
1288              proc = popen(
```

The hoist target the row names (`:1276`, beside the `argv` build) sits above every one of those lines.
**If `boot_identity()` raises anywhere in `:1276-1287`, no child process exists yet** — `popen` has not been
called. The caller's `except BaseException` then pops a record that never had a live process behind it, and
`restore_mailbox_claim` runs. The orphan is impossible **by construction, for every exception class**, not
just for `OSError`. The author is right that this is stronger than the wrapper I asked for, and right about
why: the wrapper alone would have left `TypeError`/`AttributeError` from an adapter bug escaping *past* a
live `Popen`.

It is also right that this is not a new contract. `launch_turn` already states it, and the receipt is exact:

```
$ sed -n '1270,1274p' bin/fleet.py
    # funnels through here, so one guard covers them all -- and raising
    # BEFORE the Popen keeps the launch-sequence contract intact (the caller
    # restores the mailbox claim on any raise, same as a resolve/argv error).
    if not os.path.isdir(cwd):
        raise TurnLaunchError(f"registered cwd no longer exists, refusing to launch {name!r}: {cwd}")
```

**Is there any other path between the hoisted read and the record-commit that can raise and strand a live
child?** Three sites raise after `:1288`: `TurnLaunchError` at `:1298` (the `Popen` call's own `except OSError`),
`:1309` (writer saw the read end closed — *child exited during init*), and `:1317` (`poll()` returned nonzero —
*child already exited*). Each fires only when the child is dead or never started. `ctime_to_iso` failures are
swallowed at `:1349`. So `launch_turn`'s post-`Popen` region raises only on a dead child, which is the existing
launch-sequence contract, and F33 does not add a raise to it. **No stranding path exists.**

**The `except OSError` width — what escapes, named.** `PermissionError`, `FileNotFoundError`, `IsADirectoryError`
are `OSError` subclasses and are caught. `UnicodeDecodeError` on a corrupt `boot_id` is not — but it is a
`ValueError` subclass (`py -3.13 -c "print([c.__name__ for c in UnicodeDecodeError.__mro__])"` →
`['UnicodeDecodeError', 'UnicodeError', 'ValueError', 'Exception', 'BaseException', 'object']`), and `main()`'s
except tuple **does** list `ValueError`. So at launch it escapes the wrapper, raises above the `Popen` (no
orphan), and `main()` turns it into `fleet: <msg>` / exit 1. Loud, clean, no traceback. At probe time it escapes
`probe_liveness`'s `except OSError` and lands in the same `ValueError` arm. **See LOW F33-R6** — this is a
correct outcome that the spec never states, and the class that *would* traceback (`TypeError`, `AttributeError`
— absent from `main()`'s tuple) is exactly the class the spec deliberately wants loud. Say so.

### VIEWS-CANNOT-CRASH: **yes.** The author answered, and the answer is real.

The structural half, re-run:

```
$ grep -rn "probe_liveness(\|pid_alive(" bin/fleet.py bin/fleet_statusline.py bin/hooks/ --include=*.py
  16 matches in bin/fleet.py
  (bin/fleet_statusline.py: no matches. bin/hooks/: no matches.)
```

The statusline and the SessionStart hook never reach a probe; they read `status_snapshot` (`:1742`) through
`_read_registry_readonly` (`:1722` — *"Never writes, never quarantines, never raises"*). An `OSError` inside
`probe_liveness` is unreachable from them.

The author then found the surface I had waved past: **`/fleet:doctor` is a read-only inline view *and* it probes.**
Verified — `docs/specs/terminal-surface.md:54` lists it under *"Inline `` !` `` (read-only)"*, and `:148` maps it
to `` !`fleet doctor` ``. Its containment claim is verified exact:

- `cmd_doctor` (`bin/fleet.py:4493`) builds `checks = [...]` **eagerly, with no `try`** (`:4508-4526`), and
  `_doctor_check_stale_pids` (`:4210`) / `_doctor_check_unreadable_starttime` (`:4227`) are entries in that list.
- `main()` catches exactly `RegistryCorruptError` and
  `(FleetCliError, ClaudeNotFoundError, TurnLaunchError, ValueError, FleetLockTimeout, UnsupportedPlatformError)`.
  **`OSError` is not in the tuple.** I read every `except` in `main()`; there are two.

So `probe_liveness`'s `except OSError` really is the **sole** containment for every probing surface, and deleting
it as "unreachable" really would traceback out of a read-only view. The spec now says this, in the doc that owns
the decision, with a `# Do not delete` marker in the pseudocode. That is the right place and the right words.

### PIN-CATCHES-THE-BUG: **yes** — but it does not pin the hoist. **MED F33-R5.**

The new §12 clause makes three assertions, and against an injected `OSError`-raising `boot_identity` each one
fails on a distinct wrong build:

- (a) `launch_turn` does not raise → **fails on the unguarded read** (the original F33-R1 orphan). The pin *can*
  fail on the bug it exists to catch. This was the manager's question, and the answer is yes.
- (b) the dict still carries `turn_pid` **and non-null** `turn_pid_ctime` → fails on a read nested in the `:1345`
  `try`, whose `except Exception` would null the ctime and let `:620` return `"gone"` (FW2-R1 rebuilt).
- (c) the verdict is `"unknown"` for both a recovered and a still-failing fresh read → exercises
  `probe_liveness`'s own `except OSError`.

**The gap:** a builder who writes the wrapper but skips the hoist passes all three. Under an `OSError` injection
the wrapper alone is sufficient — nothing raises, so nothing orphans. The hoist only matters for the classes
`except OSError` does *not* catch, and no assertion injects one. The appendix says, correctly, *"The hoist, not
the width of the catch, is what makes an orphan impossible"* — and then pins the catch, not the hoist. The one
property the prose calls load-bearing is the one property untested.

**Fix (MED, cheap):** a fourth assertion — inject a `boot_identity` raising a **non-`OSError`** (e.g. `RuntimeError`),
assert `launch_turn` raises **and** that the injected `popen` was never called. `popen` is already an injected
parameter on all four launch paths, so "no child was created" is directly observable; "does not raise" is not the
same assertion and the manager was right to press on it.

---

### HIGH — F33-R4 (NEW REGRESSION, introduced by `2f56bb3`): §4's new pointer line declares two **shipped** registry fields `[UNBUILT]`.

`docs/SPEC.md:102`, added by this commit as the fix for my LOW `F33-R2`:

> **Three fields in the block above are PRESCRIPTIVE, not shipped** (F33-R2): `turn_pid_boot_id` (v2.2, F33,
> `[UNBUILT — owned by C4 port-adapter-a]`) and `limit_reset_at` / `limit_kind` (v2.1, UL1/F31, `[UNBUILT]`).
> … the `[UNBUILT]` tags live with each field's owning paragraph (`:121` for F33, appendix F31 for UL1).

Both clauses are false for UL1. **`limit_reset_at` and `limit_kind` are shipped, and tested.**

```
$ grep -n "limit_reset_at\|limit_kind" bin/fleet.py
557:        "limit_reset_at": None,          # new_worker_record default -- WRITTEN TODAY
558:        "limit_kind": None,
1582:    reset = record.get("limit_reset_at")          # _limit_reset_passed
1646:            updated["status"] = "limited"         # classifier sets the park
1647:            updated["limit_reset_at"] = reset_at
1648:            updated["limit_kind"] = kind
1782:            "limit_reset_at": rec.get("limit_reset_at"),   # status_snapshot forwards
1783:            "limit_kind": rec.get("limit_kind"),
3040:        reset = rec.get("limit_reset_at")         # cmd_resume_limited
4272:        weekly = ... r.get("limit_kind") == "weekly"       # doctor check
4273:        null_h = ... r.get("limit_reset_at") is None
(13 hits; :550-556, :859, :1579, :1701-1703, :3011-3014, :4264 are comments/docstrings)

$ grep -n "resume-limited" bin/fleet.py
4630:    p_resume = sub.add_parser("resume-limited",     # real subcommand
4680:        if args.command == "resume-limited":        # real dispatch

$ grep -n '"limited"' bin/fleet.py
860:    if current_status == "limited":     # sticky-until-reset, shipped
861:        return "limited"

$ py -3.13 -m pytest tests/ -k "limited or limit_reset" -q
29 passed, 691 deselected in 1.05s
```

And the cross-reference points at a tag that does not exist:

```
$ sed -n '416,424p' docs/SPEC.md | grep -c "UNBUILT"      # appendix F31
0
$ sed -n '130,141p' docs/SPEC.md | grep -c "UNBUILT"      # §4's UL1 park paragraph
0
```

There is no `[UNBUILT]` tag in appendix F31 or in UL1's owning §4 paragraph — **because there is nothing to tag.**
UL1 shipped. The line invents a tag, attributes it to a paragraph that has none, and tells a builder that
`new_worker_record:557-558` is unbuilt.

**Why HIGH.** This is the **F20 drift**, freshly minted, in §4 — the schema section a builder reads first. F20 was
a shipped kernel left tagged `[UNBUILT]`, and the campaign's own record is that it *"nearly made a builder rewrite
working code."* A C2 builder taking up *"hardening kernel item 11"* now reads §4:102, concludes `limit_reset_at` is
unbuilt, and re-implements a field that `new_worker_record` already writes and 29 tests already cover. The
convention exists to prevent exactly this, and the line written to honor the convention violates it. It is docs-only
and cannot corrupt runtime — that is why it is HIGH and not CRITICAL — but it misdescribes shipped code in the one
place that must not.

**This is my error before it is the author's.** My `F33-R2` said *"a builder scanning the schema block sees three
unbuilt fields presented as current"* and recommended *"one line under the JSON naming the prescriptive fields."*
There were never three. I asserted it from the JSON block's shape without grepping `bin/fleet.py`, in a review whose
own thesis is that inspection lists are wrong and grep lists are right. The author then implemented my premise
faithfully, pasted seven receipts for everything it already believed, and ran no receipt against the one claim that
was new. `grep -n limit_reset_at bin/fleet.py` — thirteen hits — refutes it in one command. **The receipt discipline
was applied to the argument and not to the assertion.** That is the lesson to carry, and it is worth more than the
finding.

**Fix.** Rewrite `:102` to name **one** prescriptive field, and answer the manager's actual question — *why* do
UL1's fields keep the untagged form? Because they are **shipped**, and a shipped field takes no tag. Suggested:

> **One field in the block above is PRESCRIPTIVE, not shipped** (F33-R2): `turn_pid_boot_id` (v2.2, F33,
> `[UNBUILT — owned by C4 port-adapter-a]`; the tag lives with its owning paragraph at `:121`). Every other field
> here, including `limit_reset_at` / `limit_kind` (v2.1, UL1/F31), is **written by `bin/fleet.py` today** and
> correctly carries no tag. This line exists because a builder scanning only the JSON cannot see the one tag that
> is there — the F20 mirror-image drift the convention prevents.

**Adjacent, PRE-EXISTING, and not introduced by `2f56bb3` — the manager should open it separately.** The same stale
premise is already in two older places, which is where the author picked it up: the Status header (`:3`,
*"UL1 park+resume (F31) are prescriptive"*) and §12's two UL1 pins (`:338`, `:341`, tagged
`[UNBUILT — C2 hardening kernel item 11]`). `limited_sticky_exempt_from_dead` is shipped at `:860-861`;
`resume_limited_gated_on_reset` is shipped at `:3040`/`:4630`. **That is a live F20 drift of real size**, larger
than this finding, and outside both this commit's diff and my scope. I am not touching it. It wants its own task
with `grep -n` receipts against `bin/fleet.py`, the way F20's own correction was done on 2026-07-09.

---

### LOW — F33-R6: the `except OSError` width is a decision; state it and its escape

The appendix says the narrow catch is deliberate — *"a bug in the adapter must go loud, not become a silent `null`"*
— which I agree with. It does not say what "loud" means, and the answer is not uniform:

- `UnicodeDecodeError` (a corrupt `boot_id`) escapes the catch but **is** a `ValueError`, which `main()`'s tuple
  lists → `fleet: <msg>`, exit 1, no traceback. `/fleet:doctor` degrades cleanly.
- `TypeError` / `AttributeError` (an adapter bug) are in neither `except OSError` nor `main()`'s tuple → a traceback
  out of `/fleet:doctor`. That *is* the intended loudness, but it is the one place the spec's own
  "views never crash" paragraph and its "adapter bugs go loud" paragraph pull against each other.

Neither is a defect. **Recommend** one sentence in *"The launch-path read"* naming both, and one in
`portability.md`'s adapter body pinning the read to a shape that cannot produce `UnicodeDecodeError`
(read bytes, `.decode("ascii", "strict")` inside the adapter's own guard, or `.strip()` on a byte read). Not blocking.

### F33-R2: **bad** — see HIGH F33-R4 above. F33-R3: **ok.**

R3 is properly bounded now, and bounded the way a spec should be — by the formula, not by one box's constant:

> reuse inside the window requires a **sustained fork rate ≥ `pid_max` / 2 s** … At the measured value that is
> **2,097,152 forks/s** `[VERIFIED — WSL Ubuntu, cat /proc/sys/kernel/pid_max → 4194304; uname -r → 6.18.33.2-microsoft-standard-WSL2]`.
> At the conservative `32768` floor … it is **16,384 forks/s** … the reason this spec quotes the formula rather than
> one box's constant.

Arithmetic checks (`4194304/2 = 2,097,152`; `32768/2 = 16,384`). Both WSL claims re-run by me this session:
`cat /proc/sys/kernel/pid_max` → `4194304`; `uname -r` → `6.18.33.2-microsoft-standard-WSL2`. **Exact.** The `32768`
floor is correctly marked `[UNVERIFIED — verify in port-posix-smoke]` rather than asserted, and the spec now requires
`port-posix-smoke` to record the box's `pid_max` alongside its `boot_id` — which is precisely what F33-R3 asked for.
The structural argument (ticks increase monotonically within a boot, so a pid recurs only after a full wrap) is
stated separately from the quantitative one, so the residual no longer rests on a number that varies per machine.

---

### Receipts — **all seven re-run at their stated commits. FABRICATION: none.**

| # | Receipt | Verdict |
|---|---|---|
| 1 | `sed -n '1270,1274p' bin/fleet.py` (the launch-sequence contract comment) | **EXACT**, to the line |
| 2 | `grep -n "launch_turn(" bin/fleet.py` → `1241, 2311, 2860, 2967, 3692`; prose `236, 1959, 2280` | **EXACT**, including the prose classification |
| 3 | `sed -n '1284,1298p'` (the `Popen` at `:1288` and its own `except OSError`) | **EXACT** |
| 4 | `grep -rn "probe_liveness(\|pid_alive(" bin/fleet.py bin/fleet_statusline.py bin/hooks/` → statusline & hooks: no matches | **EXACT** |
| 5 | `cmd_doctor:4493` has no `try`; `main()`'s except tuple omits `OSError` | **EXACT** — I read both |
| 6 | `git diff --stat 9b5954d..efa64be -- bin/ tests/` → empty | **EXACT** |
| 7 | WSL: `pid_max` → `4194304`; `uname -r` → `6.18.33.2-microsoft-standard-WSL2` | **EXACT**, re-run by me |

Five spec artifacts, zero fabrications. The record holds. **F33-R4 is not a fabrication** and must not be read as
one: no receipt was falsified, abridged, or transcribed from memory. A claim was made *without* a receipt, in a
document whose rule is that claims come with receipts. That is a different failure, and a smaller one — but it is
the failure that produced the only HIGH in this pass, and it produced it in the one paragraph nobody thought needed
a grep.

---

### Disposition

- `docs/specs/portability.md` — **`drafting`.** Not promoted. Withheld solely on F33-R4. **Nothing in
  `portability.md` is defective**; `2f56bb3` did not touch it, and its Status line is untouched by me.
- `docs/SPEC.md` — **F33 not ratified.** F33-R1 is fixed and the fix is correct and well-argued; the blocking
  defect is `:102`, F33's own disposition of F33-R2. One rewritten line and one added §12 assertion clear both the
  HIGH and the MED, and F33 ratifies.
- **The C4 build waves remain gated on Altai's `SOAK GATE 1 SIGNED` line in `knowledge/lessons.md`, which does not
  exist.** Nothing in this review, and nothing a promotion would have done, changes that.

**For fix wave 5 — the one-line brief:** F33-R1 was fixed properly, and then the LOW's fix asserted, without a grep,
that two shipped fields were unbuilt — because *my* review asserted it first. The rule this campaign keeps
rediscovering is not "grep the call sites." It is **grep the claim.** Every claim. Including the ones that arrive
already believed, and especially the ones a reviewer hands you.

---

## Final verification

Worker `spec-final-verify`, 2026-07-10. Scope: (1) certify the manager's correction `92e8a44` — the
manager authored it, so the manager cannot certify it; (2) confirm the F33-R1 fix at `2f56bb3` still
stands; (3) rule on promoting `docs/specs/portability.md`. Nothing here re-reviews settled findings.

**Verdict: needs-fixes. One HIGH. `docs/specs/portability.md` stays `drafting`; SPEC.md F33 is NOT
ratified.** Nothing in this document unblocks the C4 build waves — they are gated on Altai's
`SOAK GATE 1 SIGNED` line in `knowledge/lessons.md`, which does not exist (`grep -rn "SOAK GATE 1"
knowledge/lessons.md` → no matches), and no finding, fix, or promotion here changes that.

### 1. The manager's receipt is honest, and the claim is true

The two greps pasted inline in `92e8a44` were re-run at `2f56bb3` (via `git show`) and at HEAD. They
reproduce **exactly**:

```
$ git show 2f56bb3:bin/fleet.py | grep -c "limit_reset_at\|limit_kind"
18
$ for f in $(git ls-tree --name-only 2f56bb3 tests/); do ... done
tests/test_core.py:1
tests/test_destructive_guard.py:1
tests/test_resilience.py:26
tests/test_terminal_surface.py:13          # 1+1+26+13 = 41, as the commit message states
```

Identical at HEAD (the only delta is four `tests/__pycache__/*.pyc` byte-matches, which are build
artifacts, not source; the manager's paste correctly excluded them). **No fabrication.** The record
stands at six workers, zero fabrications.

The claim is true, and stronger than "the fields exist" — they are written, read, and regression-pinned:

- **Written:** `new_worker_record` seeds both (`bin/fleet.py:557-558`); the turn-end classifier stamps
  them and emits `limited_suspected` (`bin/fleet.py:1647-1649`).
- **Read:** `_limit_reset_passed` (`bin/fleet.py:1579-1587`), `cmd_resume_limited`'s sweep
  (`:3040`), the status snapshot (`:1782-1783`), doctor's park summary (`:4272-4273`).
- **Pinned:** `tests/test_resilience.py:2252-2564` (26 refs — park, sticky, reset-gating, `--force-now`,
  weekly vs `session_5h`, launch-failure rollback), `tests/test_terminal_surface.py:118-137, 275-284`
  (13 refs — snapshot never raises, `resume_eligible` flag, statusline rendering),
  `tests/test_core.py:122` (schema), `tests/test_destructive_guard.py:43`.

UL1 landed as **C2 Wave 2B link 5/5**, commit `784a73f` (`harden: fleet.py UL1 usage-limit resilience
kernel`), re-landed at HEAD via `710e3d3` (`git merge-base --is-ancestor 710e3d3 HEAD` → yes).

**`turn_pid_boot_id` is genuinely `[UNBUILT]`.** `grep -rn "boot_id" bin/ tests/ --include=*.py` → **no
matches**, at HEAD. No mirror defect. `92e8a44` is correct as written.

### 2. HIGH — the correction fixed one line and left seven false `[UNBUILT]` tags standing

`92e8a44` corrected `docs/SPEC.md:102`. It did not sweep the file. Enumeration built **by grep**, not by
inspection — `grep -on ".\{0,80\}\[UNBUILT[^]]*\]" docs/SPEC.md`, **23 occurrences**, every one checked
against `bin/fleet.py` and `tests/`:

| # | Line | Tag / claim | Verdict |
|---|------|-------------|---------|
| 1 | 3 | `[UNBUILT — owned by <kernel>]` (naming the convention) | n/a — convention, not a claim |
| 2 | 3 | F33 `[UNBUILT — owned by C4 port-adapter-a]` | **TRUE** — `boot_id` grep: no matches |
| 3 | 102 | `turn_pid_boot_id` `[UNBUILT — owned by C4 port-adapter-a]` | **TRUE** |
| 4 | 102 | "Its `[UNBUILT]` tag lives at `:121`" | **TRUE** — back-reference |
| 5 | 104 | "an earlier revision also declared … `[UNBUILT]`" | **TRUE** — recorded history |
| 6 | 116 | "F20: a shipped kernel left tagged `[UNBUILT]`" | **TRUE** — history |
| 7 | 116 | "any claim … that a field is `[UNBUILT]` must be verifiable by grep" | **TRUE** — the rule |
| 8 | 128 | doctor elevation-mismatch `[UNBUILT — C2 hardening kernel item 9]` | **TRUE** — no impl (below) |
| 9 | 135 | F33 boot-identity paragraph `[UNBUILT — C4 port-adapter-a]` | **TRUE** |
| 10 | 176 | doctor elevation check `[UNBUILT — C2 item 9]` | **TRUE** |
| 11 | 352 | `budget_persistence_repassed_every_launch` `[UNBUILT — item 7]` | **FALSE — SHIPPED** |
| 12 | 353 | `rotation_retry_unrotate_rollback` `[UNBUILT — B2 half]` | **FALSE — SHIPPED** |
| 13 | 354 | (UL1) `limited_sticky_exempt_from_dead` `[UNBUILT — item 11]` | **FALSE — SHIPPED** |
| 14 | 355 | (UL1) `resume_limited_gated_on_reset` `[UNBUILT — item 11]` | **FALSE — SHIPPED** |
| 15 | 356 | (F33) `boot_identity_gates_tick_compare` `[UNBUILT — C4]` | **TRUE** |
| 16 | 357 | (UL1) `limited_distinct_from_budget_trip` `[UNBUILT — item 11]` | **FALSE — SHIPPED** |
| 17 | 373 | port-adapter `boot_identity` `[UNBUILT — C4 port-adapter-a]` | **TRUE** |
| 18 | 400 | "F20's three-way probe is PRESCRIPTIVE/`[UNBUILT]`" | **TRUE** — history, self-corrected |
| 19 | 408 | "the spec carried `[UNBUILT]` long after the kernel landed" | **TRUE** — history |
| 20 | 412 | F22 `[UNBUILT — C2 harden-fleet-b / item 7]` | **FALSE — SHIPPED** |
| 21 | 414 | F23 provider-side token ceiling `[UNBUILT — item 10]` | **MISLEADING** (LOW, below) |
| 22 | 416 | F24 `[UNBUILT — C2 harden-fleet-d / B2 half]` | **FALSE — SHIPPED** |
| 23 | 454 | F33 appendix `[UNBUILT — C4 port-adapter-a]` | **TRUE** |

**23 audited. 7 false. 1 misleading. 15 correct.**

**Receipts for each false tag.** All three kernels landed in **C2 Wave 2B** and are in HEAD's ancestry
via `710e3d3` (`Revert "Revert "merge: Campaign 2 … (11 kernels, UL1, 506 tests)""`):

- **Item 7 / F22** (`:352`, `:412`) — landed `f8c9513` (`harden: fleet.py budget/setting-sources
  persistence (C2 Wave 2B link 2/5)`). `max_budget_usd`/`setting_sources` are re-passed on **every**
  launch path: spawn `:2298`, send-when-idle `:2315-2316`, respawn `:3539-3541`/`:3592`/`:3641`/`:3696`,
  resume-limited `:2961-2969`. The worker-level ceiling refuses + flags `over_budget` at `:2766-2777`
  (`append_event("budget_exceeded", …)`). Pinned: `tests/test_steering.py:226`
  (`test_idle_resume_refuses_and_flags_when_cumulative_over_budget`), `:252` (sticky across recompute),
  `tests/test_resilience.py:532`, `:556`, `:2412` (`test_resume_repasses_budget_and_setting_sources`).
  `bin/fleet.py:515` names it in-code: *"Phase1 kernel item 7 (F13/M5)"*.
- **B2 half / F24** (`:353`, `:416`) — landed `0a6de4b`. The spec's parenthetical asserts *"the
  rotation-retry-on-`PermissionError` wrapper is what is unbuilt."* It is at `bin/fleet.py:3397`
  (`except PermissionError as exc:` inside the `_ROTATE_RETRY_ATTEMPTS` loop), raising `LogRotationError`
  on exhaustion (`:3403`), with `_unrotate_worker_log` (`:3409`) called from respawn's clean-fail paths
  (`:3669`, `:3717`). Pinned: `tests/test_resilience.py:143-160` (retry succeeds, injected `sleep`),
  `:173-178` (exhaustion raises), `:185-233` (clean-fail → registry snapshot restored + log un-rotated),
  `:677` (`test_launch_failure_rollback_unrotates_log_and_preserves_transcript`).
- **Item 11 / UL1** (`:354`, `:355`, `:357`) — landed `784a73f`. Sticky exemption:
  `bin/fleet.py:853-858`, pinned `tests/test_resilience.py:2326`
  (`test_limited_never_demoted_to_dead_on_gone_probe`) and `:2336`
  (`test_recompute_status_returns_limited_sticky`). Reset-gated resume: `cmd_resume_limited`
  (`:3004-3043`), `_limit_reset_passed` (`:1579`), `--force-now` (`:4633`), CLI dispatch (`:4680`);
  pinned `tests/test_resilience.py:2352` (past), `:2367` (future), `:2379` (null horizon), `:2403`
  (weekly), `:2444` (launch-failure rollback → `limited`), `:2506`, and `tests/test_cli.py:354`.
  Limited-vs-budget-trip: classifier at `:1644-1649` parks on a limit-shaped stderr signal and
  *falls through* to crash-dead otherwise; pinned `tests/test_resilience.py:2277`
  (`test_errored_no_result_with_limit_stderr_parks_limited`), with the budget trip pinned separately
  as `over_budget` (`tests/test_steering.py:226`).

**Why this is HIGH, not LOW.** All five false §12 entries sit under the bucket header at
`docs/SPEC.md:351`: ***"(b) Pins unbuilt fixes — FAILS until the named C2 kernel lands. … a builder
writes them as `xfail`/gated until the kernel ships, then flips them green."*** A builder who follows
that instruction takes five behaviors that **pass today** and marks them `xfail` — and, reading the F22
and F24 appendix tags at `:412`/`:416`, rebuilds three kernels that already exist. That is precisely the
harm the tag convention exists to prevent, and precisely the harm `92e8a44`'s own commit message names:
*"a shipped feature tagged `[UNBUILT]`, which would have a builder rewrite working code."*

Independent confirmation that these pins are green, not gated: `py -3.13 -m pytest tests/ -q` →
**708 passed, 12 skipped** (the 12 are the `FLEET_LIVE=1` tier-3 haiku harness), and
`grep -rn "xfail\|@pytest.mark.skip" tests/*.py` → **zero matches**. Bucket (b) describes a state of the
test suite that does not exist.

**Collateral, same class, no `[UNBUILT` token — so a grep for the tag alone will miss it.** `docs/SPEC.md:3`
(the `**Status:**` line) still reads: *"budget/`setting_sources` persistence (F22), the rotation-retry
wrapper (F24), and UL1 park+resume (F31) are prescriptive."* All three ship. Any fix wave must correct
`:3` as well; a sweep driven only by `grep "\[UNBUILT"` will leave it standing. This is the fifth
enumeration in this campaign to be built by inspection, and the mechanism is now visible: **the tag is
not the claim. The claim is the claim, and it also appears untagged.**

**LOW (`:414`, F23 token ceiling — imprecise, not false).** The tag reads
`[UNBUILT — owned by C2 providers token-ceiling kernel / item 10]`. Item 10's **fleet-side** half shipped
in `0a6de4b` (*"token-ceiling fleet-side"*): the `token_ceiling` field (`:538`), resume refusal +
sticky `over_ceiling` (`:2785-2802`), `_write_ceiling_file` (`:2307`), the Stop-hook allow-boundary
(`>=`, `:2789-2791`); pinned `tests/test_resilience.py:2159`, `:2196`, `tests/test_hooks.py:616`, `:693`,
`tests/test_cli.py:224-237`. What remains genuinely unbuilt is the **provider-side** half — untrusted-cost
marking under a non-default profile, owned by `stub-inject-providers` — which is what F23's caveat
actually needs. The sentence is defensible as written but reads as "item 10 is unbuilt," which is half
wrong. Fix wave should scope the tag to the provider-side half. Not a promotion blocker on its own.

**Not a finding — verified correct.** `:128`/`:176` claim only the doctor **elevation-mismatch** check
remains unbuilt from item 9. Confirmed: a case-insensitive grep for `elevation|elevated|integrity level|
IsInRole|Administrator` over `bin/fleet.py` returns a single match — a *comment* at `:224` describing the
Access-Denied case — and zero matches in `tests/`. `_doctor_check_unreadable_starttime` exists (`:4218`,
wired at `:4518`), which is the part `:408` says shipped. Both tags are accurate.

### 3. F33-R1 stands, and the §12 pin can fail on the defect it exists to catch

**The fix stands.** Spot-checked in the spec text at `2f56bb3` and HEAD, not re-derived:

- `docs/SPEC.md:529` — heading: *"The launch-path read: guarded, and hoisted above the `Popen` (F33-R1)."*
- `:531` — the earlier draft's non-sequitur (that a call placed before the `:1345` `try` would "stamp
  `null`") is **explicitly retracted**: *"An unguarded call before a `try` propagates."*
- `:545` — *"The specified read is therefore both wrapped and hoisted."*
- `:564` — *"It is the read's **own** `try/except OSError` — explicitly **not** the existing block at
  `:1345`,"* whose `except Exception` at `:1349` exists solely to null `ctime_iso`.
- `:650` (the call-site table) — `except OSError: boot_id = None`, **"Not** inside the `try` at `:1345`",
  marked *"placement corrected by F33-R1."*
- `:137` (§4 field) — *"guarded and hoisted above the `Popen`… a launch may never fail, and may never
  orphan a live `claude`, because a boot id was unreadable."*

The anchor is real: `bin/fleet.py:1288` is `proc = popen(` — so a read hoisted above it runs when no
child exists yet, and no exception class can orphan one. Consistent across all six sites.

**The pin catches the bug.** `docs/SPEC.md:356` specifies three assertions for the F33-R1 launch-path
row, and assertion **(a)** is *"`launch_turn` does not raise"* — not merely "a committed record has
`turn_pid_boot_id = null`." Fault-injected against every wrong build:

- read left **unguarded below the `Popen`** (the real defect) → `OSError` escapes → callers'
  `except BaseException` pops the record, child orphaned → `launch_turn` **raises** → **(a) fails.**
- read **nested inside the `:1345` `try`** → `except Exception` at `:1349` nulls `turn_pid_ctime` too,
  and `:620`'s `ctime_iso is None` short-circuit returns `"gone"` → **(b) fails** (it requires a non-null
  `turn_pid_ctime` alongside `turn_pid`).
- read guarded but placed **below** the `Popen` → no raise, no orphan, `boot_id = null` → all three pass,
  and correctly so: nothing is orphaned. (No orphaning build passes.)

A pin asserting only `turn_pid_boot_id = null` would pass on the first case and be theater. This one does
not. **PIN-CATCHES-THE-BUG: yes.**

*Observation (not a finding, no fix required).* Assertion (a) establishes orphan-freedom **by inference** —
"`launch_turn` returned normally, therefore nothing was left running" — while the prose at `:137` and
`:356` promises "never an orphaned child" directly. The inference is sound here (the only orphan path is
an escaping exception), so the pin cannot pass on the defect. A builder who wants the prose asserted
literally can have the injected `popen` record its spawns and assert none survive an
`OSError`-raising `boot_identity()`. Strengthening, not correcting.

### 4. Ruling on promotion

A HIGH survives §1. Per the promotion gate, **`docs/specs/portability.md` remains `drafting`** — the
`**Status:**` line is untouched by this review — and **SPEC.md F33 is not ratified.**

To be precise about what is and is not wrong, because the next fix wave should not overshoot: **F33's own
content is clean.** Every F33 tag (`:3`, `:102`, `:135`, `:356`, `:373`, `:454`) is true, its `boot_id`
grep receipt reproduces, F33-R1's fix is correctly specified at six sites, and its §12 pin fault-injects
against the real defect. **The manager's correction `92e8a44` is also clean** — honest receipt, true
claim, correctly scoped to the line it fixed.

What blocks ratification is the seven stale tags F33 inherited and the campaign never swept: five §12
entries that would have a builder `xfail` passing tests, two appendix tags that would have him rebuild
`f8c9513` and `0a6de4b`, and the untagged sentence at `:3` that repeats the claim where no grep for
`[UNBUILT` will find it. **Ratifying F33 while `docs/SPEC.md:351-357` instructs a builder to gate five
green tests is ratifying the F20 drift a third time.**

**To unblock:** correct `:3`, `:352`, `:353`, `:354`, `:355`, `:357`, `:412`, `:416` — moving the five §12
entries from bucket (b) to bucket (a) with commit anchors (`f8c9513`, `0a6de4b`, `784a73f`) — scope
`:414` to the provider-side half, then re-verify with the same grep. Estimated: one fix wave, eight edits,
no code change.

**Build waves remain gated on the `SOAK GATE 1 SIGNED` signature in `knowledge/lessons.md` regardless of
this verdict.** Promotion of `portability.md`, whenever it is earned, would not have unblocked them either.

### Receipts index

Every claim above is reproducible read-only from this commit:

```
grep -rn "boot_id" bin/ tests/ --include=*.py                  # -> no matches (turn_pid_boot_id UNBUILT)
grep -on ".\{0,80\}\[UNBUILT[^]]*\]" docs/SPEC.md              # -> 23 occurrences (the table above)
grep -rn "xfail\|@pytest.mark.skip" tests/*.py                 # -> no matches (bucket (b) is fiction)
py -3.13 -m pytest tests/ -q                                   # -> 708 passed, 12 skipped
git merge-base --is-ancestor 710e3d3 HEAD                      # -> yes (Campaign 2 kernels are in HEAD)
grep -rn "SOAK GATE 1" knowledge/lessons.md                    # -> no matches (build waves gated)
```

**For the record:** the manager's receipt reproduced. Six workers, zero fabrications.
