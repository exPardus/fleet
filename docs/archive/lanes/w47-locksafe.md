# `w47-locksafe` — `fleet_lock` drops the Windows delete-pending race

| | |
|---|---|
| Branch | `w47/locksafe` |
| Base | `e0bdd97` (`docs(gates): open the init --home question before slice (b) builds it`) |
| Fix commit | `cc1246b` |
| Fence | `bin/fleet.py` — `fleet_lock` only — and `tests/test_core.py`. Held; see §8. |
| Diff | `bin/fleet.py` +36, `tests/test_core.py` +125. No deletions, no moved code. |

Every line below is tagged **MEASURED** (I ran it, output pasted or summarised from a run in this
lane) or **BELIEVED** (reasoning I did not execute). The gate should read §1 first.

---

## 1. WHERE THIS BRIEF WAS WRONG

The brief invited me to check its Windows claim from the errno and the semantics rather than from
its sentence. I did. **The claim is correct; the mechanism it gives for reaching the state is
not sufficient**, and that turns out to explain the brief's own second observation better than the
brief does.

### 1a. `path.unlink()` alone does NOT usually produce delete-pending on this machine — MEASURED

The brief says: *"The holder releases the lock with `path.unlink()`; a contender polling at
`LOCK_RETRY_INTERVAL_SECONDS` can land exactly inside that window."*

My first probe did exactly that — held a file open with `FILE_SHARE_READ|WRITE|DELETE`, called
`os.remove()`, then attempted the acquisition open — and the open **succeeded**:

```
python: 3.10.1
--- while DELETE-PENDING (handle still open) ---
Q1 open        -> SUCCEEDED (no exception)
```

Identical on 3.13.12. The reason is that on Windows 10 1809+ `DeleteFileW` prefers **POSIX-semantics
delete** (`FILE_DISPOSITION_POSIX_SEMANTICS`), which unlinks the *name* immediately; the file data
lingers for the open handle but the directory entry is gone, so `O_CREAT|O_EXCL` simply creates a
new file. There is no window at all on that path.

**So the delete-pending window is not a property of `unlink()` racing a poll.** It exists only when
`DeleteFileW` is forced off its POSIX fast path onto the legacy disposition — which happens when
some other handle on the file was opened *without* `FILE_SHARE_DELETE`. On a developer Windows box
that third party is a virus scanner, the search indexer, or a backup agent transiently opening the
file it just saw appear.

**This matters for the gate's reading of the brief**, because the brief attributes the flake's
rarity to load: *"Load-dependent, not deterministic. 12/12 green re-running that test alone… It
fired once, under two concurrent suites plus a working lane."* — MEASURED-adjacent, and I do not
dispute the observation. But the better explanation is that the failure needs a **third-party handle
to coincide** with the release, not merely concurrency. Load raises the coincidence rate (more file
activity → more scanner attention, more polls per unlink) without being the mechanism. **BELIEVED**,
from the measured fact in 1a plus the Windows semantics; I did not instrument an AV handle in the
wild to prove it. The practical consequence is the same either way and is the one the brief already
drew: you cannot make this deterministic by adding load, which is why the pins inject it.

### 1b. The exception carries `winerror=None`, so `winerror == 5` is not available — MEASURED

Forcing the legacy disposition with `SetFileInformationByHandle(h, FileDispositionInfo, {1})` and
re-probing gives, identically on `py -3.10` (3.10.1) and `py -3.13` (3.13.12):

```
Q1 os.open     -> PermissionError errno=13 winerror=None
                  str: [Errno 13] Permission denied: '...\fleet.lock'
   isinstance FileExistsError: False
   isinstance PermissionError: True
```

The brief's claim — `ERROR_ACCESS_DENIED` → `PermissionError` (errno 13), not `EEXIST` — is
**confirmed exactly**. The detail the brief does not give, and which rules out an otherwise obvious
fix, is `winerror=None`: the exception comes out of the CRT `_wopen` path, not `CreateFileW`, so the
Win32 code is not carried on the exception. **A fix keyed on `e.winerror == 5` would never fire.**
`errno`/`PermissionError` is the only discriminator on offer.

### 1c. There is a second escape of the same shape, three statements away — MEASURED

The same probe, still delete-pending:

```
Q3 unlink      -> PermissionError errno=13 [WinError 5] Access is denied: '...\fleet.lock'
```

`unlink()` on a delete-pending name raises too. The stale-break arm does `path.unlink()` catching
only `FileNotFoundError`. So a lock file that is *both* older than `LOCK_STALE_SECONDS` *and*
delete-pending escapes there instead. Reported, not fixed — see §7.

### 1d. "adds a syscall and a branch to the hot path of the lock" overstates the cost — MEASURED

The brief frames the design tension as *"adds a syscall and a branch to the hot path of the lock, on
the failure side."* The parenthetical is the accurate half. The `path.exists()` call lives inside
`except PermissionError:`, which **cannot execute on an uncontended acquire** — the uncontended path
is one `os.open` that succeeds and never enters any handler. Measured cost on the hot path: zero
added syscalls, zero added branches. The real cost is one `stat` per *denied* open, on the platform
where denied opens happen at all. That is what made the design call easy rather than close, and the
gate should not credit me with resolving a tension that was smaller than stated.

### 1e. The tension the brief refused to pre-decide is real, and I measured it — MEASURED

*"a genuine permissions problem (unwritable `state/`) then spins until the deadline and surfaces as
`FleetLockTimeout`, converting a fast, accurate error into a slow, misleading one."* Confirmed by
planting it as mutant **M3** (§4): the run took 6.27s waiting out a 5s deadline and raised
`fleet.FleetLockTimeout: timed out waiting for lock: …\state\fleet.lock`, naming lock contention for
a fault that was not contention. Not hypothetical.

### 1f. Baseline number superseded — MEASURED

The brief's `4037 passed, 14 skipped, 1 xfailed = 4052 collected` is at `74a5abf`. At my base
`e0bdd97` it is **`4136 passed, 14 skipped, 1 xfailed` = 4151 collected**, on both interpreters. The
brief anticipated this and told me to re-derive; recorded here only so the gate uses the right
number. See §5.

---

## 2. The RED, reproduced deterministically — MEASURED

The pins inject the shape rather than racing for it (§1a is why racing for it is not available).
`TestLockContention._delete_pending_open` replaces `os.open` so that opens *of the lock path* fail
the first N times with the exact exception Windows produces —
`PermissionError(13, "Permission denied", path)` — while the lock file's **name is on disk**, which
is the state §1b measured. Run against the shipped function, with `bin/fleet.py` untouched at
`e0bdd97`:

```
$ py -3.10 -m pytest tests/test_core.py::TestLockContention -q

C:\Program Files\Python310\lib\contextlib.py:135: in __enter__
    return next(self.gen)
bin\fleet.py:602: in fleet_lock
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
...
E               PermissionError: [Errno 13] Permission denied:
    'C:\Users\Techn\AppData\Local\Temp\pytest-of-Techn\pytest-5955\test_delete_pending_that_never0\state\fleet.lock'

=========================== short test summary info ===========================
FAILED tests/test_core.py::TestLockContention::test_delete_pending_lock_is_retried_until_the_name_clears
FAILED tests/test_core.py::TestLockContention::test_delete_pending_that_never_clears_still_times_out
2 failed, 7 passed in 1.30s
```

**This is the production traceback.** Same frame (`fleet_lock`), same statement
(`fd = os.open(str(path), …)`), same line (`bin/fleet.py:602`), same exception and errno as the
verbatim `74a5abf` capture in the brief. The difference is that this one is reproducible on demand:
9/9 identical across the runs in this lane, on both interpreters.

The third pin, `test_permission_error_with_no_lock_file_is_raised_immediately`, **passes against the
shipped function**. That is deliberate and I want the gate to see me say it rather than discover it:
its RED is against the *rejected design alternative*, not against `e0bdd97`. It is planted and shown
RED as mutant M3 in §4. A pin whose RED I never exhibited would be exactly the "docstring claim
nobody executes" this repo has measured to be worth nothing.

---

## 3. The design call, and why I rejected the alternative

**Chosen: discriminate on the lock file, and do it without a platform branch.**

```python
        except PermissionError:
            # …reason, in the code, where a future reader can check it…
            if not path.exists():
                raise
            if time.monotonic() >= deadline:
                raise FleetLockTimeout(f"timed out waiting for lock: {path}")
            time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
```

- **name present** → the denial is about *that file*: contention. Poll on, under the *same* deadline
  as the `EEXIST` arm.
- **name absent** → the denial is about the *directory* (an unwritable `state/`). Retrying cannot
  help, so re-raise immediately and keep the fast, true error.

**Why this discriminator and not `os.name`.** `bin/fleet.py` permits exactly one platform branch and
it is spent on `PLATFORM`; a source-scan in `tests/test_steering.py` enforces it. MEASURED: my first
draft of the comment merely *contained the literal string* `os.name` in prose and
`TestPlatformAdapterBoundary::test_no_os_branches_outside_adapter_block` went RED —
`found 'os.name' outside the platform adapter block`. Reworded to "platform branch"; green. The
scan is textual, and a lane touching this file should expect that.

**Why it is a genuine no-op on POSIX.** BELIEVED, from the standard rather than from a Linux run
(none available in this lane): POSIX specifies that `open()` with `O_CREAT|O_EXCL` **fails with
`EEXIST` if the file exists**, and that check precedes the permission check. So on POSIX an `EACCES`
from this call always means the directory case, `path.exists()` is false, and the exception is
re-raised — byte-for-byte today's behaviour. The change is a no-op there *by construction of the
discriminator*, not by a platform test, which is what `origin/posix-port` needs.
The one behaviour I did change on POSIX is pathological and I will not hide it: if a POSIX kernel
ever returned `EACCES` for a call where the file exists (sticky-bit/LSM corner cases), the new arm
polls to the deadline instead of raising at once. I judged that acceptable because it is not
reachable through the specified semantics; the gate may disagree.

**Why the arm does not fall through to the stale-break.** Because of §1c: `unlink()` on a
delete-pending name raises `PermissionError` too, so routing through the stale-break would re-open
the identical escape one statement further down. A name that is *genuinely* stale still gets broken —
on a later poll, once the denial resolves into a plain `EEXIST` and the existing arm handles it.
Cost: up to one extra poll interval (50ms) before a stale delete-pending lock is broken.

**The alternative I rejected: blanket-retry every `PermissionError`.** One line shorter, and it does
make the Windows race disappear. I rejected it because it silently re-classifies a whole category of
real fault. Every caller of `fleet_lock` is a CLI verb whose error text an operator reads; an
unwritable `state/` would print `timed out waiting for lock: …\state\fleet.lock` after a 5-second
stall, sending that operator to look for a phantom lock holder. Trading a correct instant error for
an incorrect slow one is a bad trade even once, and this fleet's own history — three lane reports
lost to a path nobody re-derived — is a history of exactly that shape of misdirection.
**And the decisive part: the claim is testable, so I tested it.** `M3` in §4 is that alternative,
planted, run, and shown RED, with the 6.27s stall and the wrong exception type in the output.

**What is deliberately untouched:** the stale-break, the deadline, the `FileNotFoundError`
continue-immediately arm, the ENOSPC token-write rollback, the compare-and-delete release. The diff
is purely additive — one new `except` arm appended after the existing one. No existing line of
`fleet_lock` is modified or moved. MEASURED: `git diff --stat` reports `36 insertions(+)`, zero
deletions, for `bin/fleet.py`.

---

## 4. Mutants planted against my own pin — MEASURED

Pristine `bin/fleet.py` at `cc1246b`: sha256 `C8E2E11196346B737D13A64D9636388B323D3C7D5E08480539A7F81A9BAF18B4`.
Each mutant was applied to the working tree, run, then reverted with `git checkout -- bin/fleet.py`
and the hash re-taken. **All three restores were byte-identical, and `git status --short` was empty
after each.**

### M1 — swallow the exception entirely (the whole arm body replaced by `pass`)

```
### M1 = swallow the exception entirely ###
tests/test_core.py:515: AssertionError: fleet_lock made 100 acquisition attempts without honouring its deadline
tests/test_core.py:515: AssertionError: fleet_lock made 100 acquisition attempts without honouring its deadline
FAILED tests/test_core.py::TestLockContention::test_permission_error_with_no_lock_file_is_raised_immediately
FAILED tests/test_core.py::TestLockContention::test_delete_pending_that_never_clears_still_times_out
2 failed, 7 passed in 0.79s
--- restored sha256 ---
C8E2E11196346B737D13A64D9636388B323D3C7D5E08480539A7F81A9BAF18B4
```

Caught by two pins. Note *which* two: the retry pin still passes under M1, because a swallow that
happens to terminate looks like a successful retry. A single "does it retry?" test would have
graded this mutant GREEN.

### M2 — retry without honouring the deadline (deadline check dropped from the arm)

```
### M2 = retry without honouring the deadline ###
tests/test_core.py:515: AssertionError: fleet_lock made 100 acquisition attempts without honouring its deadline
FAILED tests/test_core.py::TestLockContention::test_delete_pending_that_never_clears_still_times_out
1 failed, 8 passed in 7.10s
--- restored sha256 ---
C8E2E11196346B737D13A64D9636388B323D3C7D5E08480539A7F81A9BAF18B4
```

Caught. The 100-attempt trip-wire inside `_delete_pending_open` is load-bearing: without it this
mutant does not fail, it **hangs**, and a hanging pin in a 4000-test floor is worse evidence than a
failing one. 7.10s, bounded, legible.

### M3 — the rejected alternative: blanket-retry every `PermissionError` (discriminator dropped)

```
### M3 = the rejected alternative: blanket-retry every PermissionError ###
bin\fleet.py:649: fleet.FleetLockTimeout: timed out waiting for lock:
  C:\Users\Techn\AppData\Local\Temp\pytest-of-Techn\pytest-5965\test_permission_error_with_no_0\state\fleet.lock
FAILED tests/test_core.py::TestLockContention::test_permission_error_with_no_lock_file_is_raised_immediately
1 failed, 8 passed in 6.27s
--- restored sha256 ---
C8E2E11196346B737D13A64D9636388B323D3C7D5E08480539A7F81A9BAF18B4
```

Caught, and this is the receipt for §3's design argument rather than for the code: the alternative
does not fail loudly, it fails *plausibly*, with a well-formed `FleetLockTimeout` about a lock that
was never held, 6.27s late.

The brief asked for two mutants. M3 is the third because the design call was mine to defend, and an
undefended rejection is a claim nobody executed.

---

## 5. Floors — predicted, then measured

**Collection**, derived with `--collect-only`, never by counting `def test_`:

| | base `e0bdd97` | predicted | measured |
|---|---|---|---|
| `py -3.13` | 4151 | 4151 + 3 = **4154** | **4154** |
| `py -3.10` | 4151 | 4151 + 3 = **4154** | 4154 (see §5 note) |

**Full floors.** Baseline was run at `e0bdd97` before any file was touched, sequentially (not
concurrently — a concurrent baseline is the load that produced the flake, and an unreliable baseline
is worse than a slow one):

| | base: passed / skipped / xfailed | predicted after | measured after |
|---|---|---|---|
| `py -3.13` | 4136 / 14 / 1 (376.69s) | 4133 / 14 / 1 + **6 failed** | **4131 / 14 / 1 + 8 failed** (374.97s) |
| `py -3.10` | 4136 / 14 / 1 (346.90s) | 4133 / 14 / 1 + **6 failed** | **4131 / 14 / 1 + 8 failed** (339.27s) |

**I predicted this wrong and the gate should weigh it.** I predicted 6 failures; there are **8**.
The arithmetic that failed was not the arithmetic — 4131 + 8 + 14 + 1 = 4154 reconciles exactly with
the collected count, and the two interpreters agree failure-for-failure, so nothing here is flaky.
What failed was my **scoping**: when I measured the citation rot I ran `tests/test_self_citations.py`
because the brief named it, and I did not go looking for *other* tests that resolve line numbers into
`bin/fleet.py`. There is a second such family — `tests/test_retired_sid_citations.py` — and it rots
the same way, for the same reason, by the same +36. Both are folded into §6 now. The lesson I would
want a later lane to take: the brief named one out-of-fence test that would notice a line shift, and
naming one is not the same as there being one; ask the floor, not the brief.

Everything else landed as predicted: collection 4154 on both, no test outside the two citation
families changed state, and the 3 new pins pass on both interpreters. **The floor is green except
for the citation rot §6 owes a landing edit for.**

**Instrument warning for the gate and for anyone resuming this lane — MEASURED.** During the
baseline I used a `Monitor` until-loop to watch the output files and it reported
`4151 passed, 14 skipped, 1 xfailed in 249.62s` for a run that had not finished; PowerShell showed
the same file still growing and it finished `4136 passed … in 376.69s`. The reported line was
self-inconsistent on its face (4151 + 14 + 1 = 4166 ≠ 4151 collected), which is how I caught it. The
`Bash` tool's filesystem view in this session disagreed repeatedly with PowerShell's — `ls` denied
the existence of files PowerShell could read and hash. **Every number in this report was read back
through PowerShell after the producing job reported completion.** Any floor figure sourced from a
mid-run `grep` should be treated as unverified.

---

## 6. OWED LANDING EDIT — citation rot in `bin/fleet.py` — MEASURED

The fix inserts **36 lines** near the top of `bin/fleet.py`, so every line-number citation below the
insertion point is short by exactly 36. **Two** test families resolve such citations, and both rot:
`tests/test_self_citations.py` goes `17 passed` → `6 failed, 11 passed`, and
`tests/test_retired_sid_citations.py` goes `4 passed` → `2 failed, 2 passed`. Both files, and every
citing site (all far below `fleet_lock`), are outside this lane's fence, so per the brief this is
reported, not repaired.

The edit is mechanical and uniform: **+36 to 21 citation numbers across 7 sites (17 distinct
targets).**

Family A — `tests/test_self_citations.py`:

| Citing site | cites | should cite |
|---|---|---|
| `bin/fleet.py:911` — quarantine-artifact readers | 3109, 4023, 6843, 10694, 11802, 12340, 16033, 16312, 16469 | 3145, 4059, 6879, 10730, 11838, 12376, 16069, 16348, 16505 |
| `bin/fleet.py:932` — `_identity_abstention_note` | 16033 | 16069 |
| `bin/fleet.py:3114` — load_registry RENAMES (identity resolver) | 1027 | 1063 |
| `bin/fleet.py:8813` — `cmd_kill:8668` | 8668 | 8704 |
| `bin/fleet.py:14946` | 2855 | 2891 |

Failing: `test_no_citation_points_at_a_blank_line`, `test_every_cited_line_carries_its_anchor`,
`test_every_cited_line_is_a_member_of_its_derived_set`,
`test_every_cited_line_is_inside_the_function_it_names`,
`test_every_function_qualified_citation_lands_in_that_function`,
`test_every_enumeration_matches_the_derived_set`.

Family B — `tests/test_retired_sid_citations.py` (the one I failed to predict, §5). The same four
`retired_sids`-writer line numbers are spelled out at two separate citing sites:

| Citing site | cites | should cite |
|---|---|---|
| `bin/fleet.py:14962-14963` — "writer appends that record's OWN prior sid alone" | 7768, 8241, 12684, 17983 | 7804, 8277, 12720, 18019 |
| `bin/fleet.py:15653-15654` — same sentence, restated as a comment | 7768, 8241, 12684, 17983 | 7804, 8277, 12720, 18019 |

Failing: `test_every_cited_line_is_a_retired_sids_write`, `test_every_retired_sids_writer_is_cited`.

**Do not apply the tables blind at merge time.** The `+36` is correct relative to `e0bdd97`; if any
other lane lands lines into `bin/fleet.py` before this merges — and slice a3 already put ~1000 lines
in this file this wave — the offsets change. Re-derive by running **both**
`tests/test_self_citations.py` and `tests/test_retired_sid_citations.py`, each of which prints every
stale number alongside its correct target. That the edit must be recomputed at merge time is itself
the argument for the brief's instruction not to repair it here: a repair made now would be stale by
the time it landed. And per §5, do not assume these two files are the whole set either — run the
floor and read the failures.

---

## 7. FINDING — a second escape of the same shape, NOT fixed

MEASURED (§1c): `path.unlink()` on a delete-pending name raises `PermissionError` errno 13.
The stale-break arm is:

```python
            if age > LOCK_STALE_SECONDS:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
```

A lock file that is both older than `LOCK_STALE_SECONDS` and delete-pending therefore escapes there
with the same uncaught `PermissionError` this lane exists to remove — reachable, for example, when
two contenders break the same falsely-stale lock and a scanner holds the name between them.

**Not fixed, deliberately.** Mandate 4 says a fix that *requires* changing the existing arms is a
finding to report rather than a liberty to take, and mine does not require it: the new arm never
reaches the stale-break. **It is also not a regression** — today that same state escapes one
statement *earlier*, at the `os.open`, so this lane strictly reduces the exposure and does not move
it. The obvious repair is widening that `except FileNotFoundError` to `except OSError` and letting
the loop `continue` (the deadline then bounds it), which is one token, but it is a change to a
guard that a previous fix-wave put there for its own reason and it belongs to whoever owns that arm.

---

## 8. Fence compliance and what I did not do

- Touched: `bin/fleet.py` (`fleet_lock` only — the diff is 36 added lines inside that function, no
  line outside it changed) and `tests/test_core.py` (125 added lines inside `TestLockContention`).
  Plus this report. **MEASURED** via `git diff --stat`: `2 files changed, 161 insertions(+)`.
- Did **not** repair `tests/test_self_citations.py` or any citing site (§6).
- Did **not** touch the stale-break, deadline, `FileNotFoundError` arm, ENOSPC rollback, or
  compare-and-delete release (§7).
- Did **not** change `fleet_lock`'s docstring. This repo has measured that an unexecuted docstring
  claim is worth nothing; the reasoning went into a comment next to the code it describes, and every
  claim in that comment is pinned by a test named in it.
- Probe scripts (`delete_pending_probe.py`, `delete_pending_probe2.py`) were written to the job's
  scratch directory, not the repo, and are not committed. Their output is transcribed in §1; they
  are throwaway instruments, not evidence the repo should carry.
- No background process outlives this lane.

## 9. For the gate

The three things most worth attacking:

1. **§1a** — I claim the delete-pending window needs a third-party non-`FILE_SHARE_DELETE` handle,
   from a measured negative (POSIX-semantics delete leaves no window) plus Windows semantics. I did
   not catch an AV handle in the act. If that reasoning is wrong, the *fix* still stands on the
   measured errno, but the brief's "load-dependent" story and my sharpening of it both need redoing.
2. **§3's POSIX claim** — argued from the `O_CREAT|O_EXCL` → `EEXIST` guarantee, not from a Linux
   run. No Linux is available in this lane. `origin/posix-port` should re-check it on real POSIX.
3. **§2's third pin** — it is GREEN against shipped code by construction. Its only RED is M3. If the
   gate thinks a pin that never went RED against `e0bdd97` does not belong in `TestLockContention`,
   that is a fair fight, and my answer is §4/M3.

And the one I got wrong on my own, recorded so the gate does not have to find it: **§5's floor
prediction was 6 failures and the measurement was 8.** I scoped the out-of-fence blast radius from
the file the brief named instead of from the floor. The fix and its pins are unaffected — the two
extra failures are the same citation rot, now in §6 — but a lane that mispredicts its own blast
radius by a third has not earned the gate's trust on the parts of §1 it could only reason about.

---

## 10. The citation re-pin, closed on this branch — MEASURED

§6 left this as an owed landing edit, correctly under the original fence and correctly reasoned:
the offsets were relative to `e0bdd97` and `bin/fleet.py` was moving. The manager reopened the lane
on the ground that it has stopped moving. **Verified before acting, not assumed:** `main` is
`f8c4b81`, the only commit since `e0bdd97` is `docs(w47): journal through the wave-47 close`
touching `supervisor/JOURNAL.md` (+53) and nothing else, so main's `bin/fleet.py` is byte-identical
to my base's and nothing shifts under this edit.

### 10a. §6 UNDERCOUNTED THE OWED EDIT BY MORE THAN HALF

**§6 said "+36 to 21 citation numbers across 7 sites". The real population is 43 number rewrites
across 25 lines and ~20 citing sites.** §6's tables were built from the *failing tests*, and a
failing-test list is a **lower bound, never a census** — several of those assertions stop at the
first bad number, so the rot behind them was never printed. §5 already recorded that I scoped the
blast radius from the brief instead of the floor; this is the same error one level in, and it is
the second time in this lane that reading a red test list as a census cost me a correct count. The
population used for the re-pin came from the pin's own classifier instead, which is the only thing
that enumerates *all* self-citations rather than the ones that happened to fail first.

The undercount also propagated: the manager's re-dispatch says "the 21 numbers across 7 sites"
because it is quoting §6. The number to carry forward is **43 across 25 lines**.

### 10b. Method — alignment and content, never a constant

`+36` was the right answer for every citation here, and it is still not how the edit was made. A
constant is a citation *generator*: it emits a number for every input, including inputs whose
target was deleted, edited, or never correct, so it cannot fail and therefore cannot tell you it
was wrong. The tool (`repin.py`, throwaway, not committed) instead:

1. **Aligns** base `e0bdd97` against the current file with
   `difflib.SequenceMatcher(..., autojunk=False)` and builds a base-lineno → current-lineno map
   from the `equal` opcodes only. `autojunk=False` is load-bearing: at 21k lines the default
   popularity heuristic treats the thousands of identical blank lines as junk and shreds the
   alignment. MEASURED: `21403 of 21403 base lines aligned`.
2. **Seed-tests its own scanner.** The classifier is a copy of the pin's, and a copy that drifts
   would re-pin a different population than the pin measures — so the tool imports
   `tests/test_self_citations.py` and asserts its population equals that module's `SELF_CITATIONS`
   on the current file. MEASURED: `seed test OK: 42 self-citations, identical to the pin's set`.
   Without this the tool is exactly the scanner-that-finds-nothing this repo built
   `tools/verify_receipts.py --self-test` to prevent.
3. **Content-verifies every single rewrite.** The base line's text must be byte-identical to the
   text now sitting at the mapped line, or the rewrite is REFUSED rather than guessed. MEASURED:
   `refused: 0`. The premise this rests on is measured, not assumed: at `e0bdd97` the floor was
   4136 passed / **0 failed**, so every citation was correct at base.

The targets confirm the mapping semantically, not just positionally — the nine
quarantine-artifact citations all land on `… = _quarantine_artifacts()` call lines, the thirteen
`_releaser_is_roster_live` citations all land on `_record_sids(…)` reads, and the four
`retired_sids` citations all land on `…["retired_sids"] = …` writes, which is independently what
`test_retired_sid_citations.py::_WRITE_RE` requires.

**Neither pin file was edited.** Both derive their expectations from `bin/fleet.py` at run time —
`test_self_citations.py` says so in its own docstring ("Change the number in `bin/fleet.py`;
nothing here moves") — so the entire repair is 25 prose lines in `bin/fleet.py`. MEASURED:
`git diff` on the re-pin is `25 insertions(+), 25 deletions(-)`, every changed line a docstring or
comment, no code line touched, and the `three-tier-command.md` ranges deliberately untouched.

### 10c. A CRLF hazard the tool would have caused, caught before applying — MEASURED

The working tree is **21438 CRLF, 0 bare LF** (`core.autocrlf=true`), while `git show` returns the
blob with LF. The first draft of the tool read with `read_text()` (which normalises CRLF → LF) and
wrote with `newline=""`, which would have **rewritten all 21438 line endings** and buried a
25-line repair inside a whole-file diff. Fixed by reading and writing with `newline=""` and
asserting, before the write lands, that the CRLF count and the line count are both unchanged. Any
later lane doing a mechanical edit to this file on Windows should assume this hazard rather than
discover it.

### 10d. The ranged form — the manager's warning was live, and there is exactly one

The homes lane's warning applies here. `_NUMBER_RE` is `:(\d+)`, so in `` `name:START-END` `` the
END carries no colon and **no test has ever seen it**. Swept explicitly:

```
fleet.py:8879:  `cmd_respawn:8434-8436`   ->  `cmd_respawn:8470-8472`
```

Verified by the citation's *own quoted text*, which is the strongest content check available
anywhere in this repair: the sentence quotes *"resolve under the lock so a corrupt registry
surfaces through load_registry's quarantine"*, and lines 8470-8472 are exactly that three-line
comment, sitting inside `cmd_respawn` — the function the citation names.

An independent sweep for `:\d+[-–—]\d+` across the whole file found **11** ranged forms. One is the
self-citation above; the other ten are other-document (`SPEC:1196-1198`, `SPEC:1175-1179`,
`SPEC:1224-1229`, `CN:1671-1675`, `SPAWN:461-471`, and four `three-tier-command.md` ranges) and are
correctly excluded by the classifier and correctly absent from the diff. **A `+36` sweep over
ranged numbers would have corrupted all ten of those**, which is the concrete form of the harm the
"never add a constant" rule prevents.

### 10e. Fixpoint

Pin files green on pass 1 and re-run to confirm stability: `21 passed` on `py -3.13` (twice) and
`21 passed` on `py -3.10`. Pass 1 was already clean because the whole population was repaired at
once rather than only the reported failures — repairing only the failures is precisely what makes
a landing here need six passes.

One caveat for anyone re-running the tool: it maps *base* numbers to *current* ones, so it is not
idempotent by design. Running it again after a successful apply would shift the now-correct numbers
a second time. The fixpoint oracle is the pin files and the floor, not a second run of the tool.

### 10f. Floors after the re-pin — predicted, then measured

Predicted before running, and I agreed with the manager's prediction: collected **4154**, and
**4139 passed / 14 skipped / 1 xfailed / 0 failed** — the eight citation failures were the only red
in §5, and changing digits inside comments can neither add nor remove a test.

| | collected | passed | skipped | xfailed | failed |
|---|---|---|---|---|---|
| `py -3.13` | **4154** | **4139** | 14 | 1 | **0** (373.27s) |
| `py -3.10` | **4154** | **4139** | 14 | 1 | **0** (339.25s) |

**Prediction met exactly, on both interpreters, on every field.** Collection re-derived with
`--collect-only` rather than inferred from the run: `4154 tests collected` on both. The branch is
green — the lane no longer owes a landing edit, and the merge lands green instead of landing red
and being repaired in place.

For the record against §5's baseline: base was 4136 passed / 0 failed at 4151 collected; the branch
is 4139 passed / 0 failed at 4154 collected. **+3 collected, +3 passed, no test changed state in
any other direction.**

---

## 11. Conclusion

The lane's fix is three lines of behaviour behind twenty-nine of explanation: an
`except PermissionError` arm that treats a denied open as contention **only when the lock file is
actually there**, and re-raises immediately when it is not. It removes a real production crash path
— a raw `OSError` escaping `fleet_lock`'s "acquire, or raise `FleetLockTimeout`" contract and
taking `clean`/`kill`/`archive`/`spawn`/`send`/`respawn`/`resume-limited` and the `sup-*` family
with it — without a platform branch, without touching any existing arm, and without converting a
genuine permissions fault into a slow lie. Both floors are green on both interpreters, and the
citation re-pin that this work owed is closed on this branch rather than left for the merge.

**The one thing a reader should carry out of this report is not the fix. It is §7.**

`unlink()` on a delete-pending name raises `PermissionError` too — MEASURED, errno 13 / WinError 5,
on both interpreters. The stale-break arm still does:

```python
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
```

so a lock file that is **both** older than `LOCK_STALE_SECONDS` **and** delete-pending escapes
`fleet_lock` exactly the way this lane's defect did, three statements further down. It is
**not a regression** — today that state escapes one statement *earlier*, at the `os.open`, so this
lane strictly reduces the exposure — and it was left alone deliberately under mandate 4, because
the fix did not require touching it and that arm belongs to whoever owns it. But the same shape is
still in the function, it is now the *only* uncaught `PermissionError` left on the acquisition
path, and the next reader should not have to find it in a numbered appendix. The repair is small
(widen that `except` and let the loop `continue`, which the deadline already bounds); the reason it
is not in this diff is fence discipline, not doubt about whether it is real.

Second thing to carry: **twice in this lane I read a red test list as a census and got the count
wrong** — §5 (predicted 6 failures, measured 8) and §10a (reported 21 owed rewrites, actual 43).
Both times the fix was to ask the tool that enumerates the whole population instead of the one that
reports the first failure. That generalises past this lane.
