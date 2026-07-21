# ME-UL review — hostile review of branch `me/ul` @ `4b8a88e`

**Reviewer:** fleet worker `me-ul-review` (`--bg`), worktree `C:/proga/fleet-me-ul-review`,
branch `me/ul-review` based on `fleet-impl @ 39ec4f8`.
**Under review:** `me/ul`, single commit `4b8a88e` on base `ac3e34d` (2 files, +188/−18).
**Date:** 2026-07-21. **Host:** Windows 10 Pro 19045, `py -3.13` = 3.13.12, `py -3.10` present.

## VERDICT: `fix-wave(C1, M1, M2; m1 same wave)`

Three blocking findings. The code changes themselves are, with one exception, correct — U1's
range guard is a real fix for a real bug and I reproduced the pre-fix wrong horizon myself. What
does not hold up is (**C1**) the one operator-facing deliverable of U3 is not pinned by any test
and can be deleted with the full 1145-test suite still green, (**M1**) the D3 DST paragraph makes
a categorical safety claim that its own subject matter contradicts — I have the repro — and
(**M2**) four of the nine new tests assert against an environment fact that is present only by
coincidence, including one that inverts on exactly the machine the new check exists to detect.

No CRITICAL *code* defect. No standing-goal-2 violation: no production path raises where it
previously parked (verified, §6.5). Scope is clean.

---

## 0. Receipt reproduction (mandatory method §1)

Every receipt the builder pasted in `state/journals/me-ul.md`, re-executed by me.

| Builder receipt | Reproduced? | My output |
|---|---|---|
| Baseline @ `ac3e34d`: `py -3.13 -m pytest tests/ -q` → 1136 passed, 6 skipped | ✅ exact | `1136 passed, 6 skipped in 55.68s` |
| After: 1145 passed, 6 skipped (+9) | ✅ exact | `1145 passed, 6 skipped in 56.84s` |
| 3.10 floor: `py -3.10 -m pytest tests/test_resilience.py -q` → 111 passed | ✅ exact | `111 passed in 1.68s` |
| Grep @ `ac3e34d`: 4 sites in `bin/fleet.py` (2 defs, 2 calls), 7 in `tests/` | ✅ exact | see below |
| `from __future__ import annotations` already present | ✅ | `bin/fleet.py:20` |
| Fault injections U1/U2/U3 go RED | ✅ superseded by my own 10-injection wave (§2) | — |

Grep receipt, re-run verbatim:

```
$ git -C C:/proga/fleet-me-ul grep -n "_parse_limit_signal(\|_next_local_reset_utc(" ac3e34d -- bin/fleet.py tests/
ac3e34d:bin/fleet.py:1110:def _next_local_reset_utc(hour: int, minute: int, tz_name: str, *, now: "datetime | None" = None):
ac3e34d:bin/fleet.py:1136:def _parse_limit_signal(text: str, *, now: "datetime | None" = None):
ac3e34d:bin/fleet.py:1179:            reset_at = _next_local_reset_utc(hour24, minute, tz_name, now=now)
ac3e34d:bin/fleet.py:1368:            reset_at, kind = _parse_limit_signal("\n".join(parts), now=_record_time(rec))
ac3e34d:tests/test_resilience.py:569,573,577,589,628,636,644   (7)
```

**Receipt scope gap, closed by me.** The builder's grep was scoped `-- bin/fleet.py tests/`. A
signature change to a required keyword must be checked repo-wide, not in the two files the author
happens to be editing. I ran the wider grep:

```
$ grep -rn "_parse_limit_signal\|_next_local_reset_utc\|_doctor_check_tzdata" \
    --include=*.py --include=*.md --include=*.json --include=*.sh --include=*.ps1 . | grep -v ^./docs/reviews/
```

Result: **no live call site outside the two files.** The only extra hit that looks like a call is
`docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md:1225`
(`reset_at, kind = _parse_limit_signal("\n".join(parts))`, no `now=`) — a frozen historical plan
document, not executed. **No missed twin.** The class of bug the brief warned about (fix at one
call site and not its twin) did **not** fire here.

**Nit on the journal's prose (not a code finding).** The journal reads *"Production call sites
(…; fleet.py:1368/1430 `_parse_limit_signal(..., now=_record_time(rec))`)"*, which parses as two
production call sites. There is exactly **one** — `1368` pre-edit / `1430` post-edit are the same
call. The underlying grep receipt is correct; only the prose is ambiguous.

---

## 1. Injection table (mandatory method §2) — 9 RED / 10 total, **1 GREEN**

Method: worktree `C:/proga/fleet-me-ul-review` with `bin/fleet.py` and `tests/test_resilience.py`
checked out from `4b8a88e` (`git checkout 4b8a88e -- …`). One injection at a time, full suite
(`py -3.13 -m pytest tests/ -q`), then `git checkout 4b8a88e -- …` to restore. Failing test names
captured on a second targeted pass (`pytest tests/test_resilience.py -q --color=no -rf`) because
the first pass's name regex was eaten by ANSI codes; **counts** below are from the full-suite runs.
Driver script: `$CLAUDE_JOB_DIR/tmp/inject.py`. All injections reverted; final `git status` clean
apart from this file (§8).

| # | Injection (in `bin/fleet.py`, at `4b8a88e` content) | Full-suite result | Verdict |
|---|---|---|---|
| I1 | drop the **lower** bound: `if not 1 <= hour <= 12` → `if not hour <= 12` | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I2 | drop the **upper** bound: → `if not 1 <= hour` | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I3 | delete the whole D2 guard (restore pre-fix `if ampm == "am":`) | 2 failed, 1143 passed, 6 skipped | 🔴 RED |
| I4 | restore `= None` default on `_parse_limit_signal`'s `now` | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I5 | restore `= None` default on `_next_local_reset_utc`'s `now` | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I6 | corrupt the doctor **remedy** string (`py -3.13 -m pip install tzdata` → `install some tz data somehow`) | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I7 | corrupt the doctor **pass** message (`"zoneinfo resolves named zones (tz data present)"` → `"tz ok"`) | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| **I8** | **delete `functools.partial(_doctor_check_tzdata),` from `cmd_doctor`'s `check_calls`** | **1145 passed, 6 skipped** | **🟢 GREEN — TEST THEATER** |
| I9 | doctor check FAILs instead of PASS-note (`("tzdata", True, …)` → `("tzdata", False, …)`) on the failure branch | 1 failed, 1144 passed, 6 skipped | 🔴 RED |
| I10 | adjacent-path probe: D2 branch also nukes `kind` (`return None, None`) | 2 failed, 1143 passed, 6 skipped | 🔴 RED |

Failing test names:

```
I1  TestParseLimitSignalHourValidation::test_out_of_range_hours_null_park_not_wrong_horizon[0pm]
I2  TestParseLimitSignalHourValidation::test_out_of_range_hours_null_park_not_wrong_horizon[13am]
I3  …[0pm] and …[13am]
I4  TestNowParameterRequired::test_parse_limit_signal_requires_now_kwarg
I5  TestNowParameterRequired::test_next_local_reset_utc_requires_now_kwarg
I6  TestDoctorTzdata::test_zoneinfo_lookup_failure_is_pass_note_not_fail
I7  TestDoctorTzdata::test_zoneinfo_resolves_passes_plain
I8  (none — GREEN on both tests/test_resilience.py and the full suite)
I9  TestDoctorTzdata::test_zoneinfo_lookup_failure_is_pass_note_not_fail
I10 …[0pm] and …[13am]
```

Reading: the **behavioral** work (U1, U2) is pinned tightly — both ends of the range bound are
independently pinned (I1/I2 fail *different* parametrizations), both removed defaults are
independently pinned, and the adjacent `kind` path is pinned (I10). The **wiring** of U3 is not
pinned at all. See C1.

---

## 2. C1 — CRITICAL: U3's registration in `fleet doctor` is unpinned, and the repo has a purpose-built test class for exactly this that was not extended

**Defect.** `_doctor_check_tzdata` is exercised only by direct calls
(`fleet._doctor_check_tzdata()` at `tests/test_resilience.py:180,192`). Nothing asserts it is
registered in `cmd_doctor`'s `check_calls`. The single line at `bin/fleet.py:6152` is the entire
deliverable of U3/D1 — D1's ask was verbatim *"add a `fleet doctor` check that reports tz-data
presence … converts a silent degradation into a visible one"*
(`MD-ULPARSER-REVIEW-2026-07-17.md:158`). Delete that line and the check still passes its unit
tests, still exists, and reports to nobody.

**Repro** (worktree content = `4b8a88e`, injection I8):

```
# bin/fleet.py, inside cmd_doctor's check_calls list:
-        functools.partial(_doctor_check_tzdata),

$ py -3.13 -m pytest tests/ -q
1145 passed, 6 skipped in 56.10s
$ py -3.13 -m pytest tests/test_resilience.py -q --color=no -rf
111 passed in ~1.7s      # zero FAILED lines
```

**Why this is CRITICAL and not MINOR.** This is not "a gap nobody thought about". The repo
already has a test class whose sole stated job is to pin new-doctor-check registration:

```python
# tests/test_native.py:4912
class TestCmdDoctorRegistersNewChecks:
    def test_new_checks_run_and_appear_in_output(self, native_home, capsys):
        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(args, which=lambda n: None, run=lambda *a, **k: _FakeVersionResult())
        out = capsys.readouterr().out
        assert "pin-version" in out
        assert "legacy-mix" in out
        assert "dead-suspected" in out
        # pin-version registered right after claude-on-path, per the T11 brief.
        assert out.index("claude-on-path") < out.index("pin-version") < out.index("worker-settings-instance")
```

A new doctor check landed and this class was not touched. The established convention was
available, named, and skipped.

**Exact fix.** Extend `TestCmdDoctorRegistersNewChecks::test_new_checks_run_and_appear_in_output`
(or add a sibling) with `assert "tzdata" in out`, plus a position assertion matching U3's stated
intent of being registered LAST:
`assert out.index("supervisor-handoff") < out.index("tzdata")`.
**Test that must pin it:** the assertion above must go RED when
`functools.partial(_doctor_check_tzdata),` is removed from `check_calls`. Re-run I8 to confirm.

**Positive evidence that the wiring is correct *today*** — `fleet doctor` read-only, run by **me**
(`me-ul-review`), worktree content `4b8a88e`, `py -3.13 bin/fleet.py doctor`, tail:

```
[PASS] supervisor-claim: SUPERVISOR: GOALS active, no claim -- boot one (`fleet sup-boot`; see skills/fleet/supervisor.md).
[PASS] supervisor-handoff: no handoff in flight, no aborted-handoff flag
[PASS] tzdata: zoneinfo resolves named zones (tz data present)
```

The check runs, runs last, PASSes on a host with tz data, and writes nothing. The FAILs above it
in the full output (`worker-settings-instance`, `instance-freshness`, `hook-registration`,
`fleet-home marker`) are artifacts of running doctor inside a non-`init`-ed review worktree, not
regressions from this branch. I did not read doctor's exit code (`$?` after a pipe reports
`tail`'s status, not doctor's) and I do not assert one.

---

## 3. M1 — MAJOR (comment lies about the code): the D3 DST paragraph's categorical claim is false in the fall-back direction

**The claim**, `bin/fleet.py:1147-1161`:

> ```
>       - an ambiguous fall-back local time resolves according to whichever
>         fold `now` (the anchor) itself carries, which is correct as long
>         as the anchor's fold reflects when the signal actually fired.
>     Both directions are bounded and late-erring, never early -- consistent
>     with this module's standing bias (a late resume beats an early one,
>     and either beats a fabricated horizon).
> ```

**Repro** (`py -3.13`, replicating `_next_local_reset_utc`'s exact body, America/New_York;
script `$CLAUDE_JOB_DIR/tmp/dst.py`, run at review time against `4b8a88e` semantics):

```
anchor local: 2025-11-02 00:00:00-04:00 fold= 0
ambiguous 1:30am -> 2025-11-02 01:30:00-04:00 fold= 0 -> 2025-11-02T05:30:00Z
  EDT-first  = 2025-11-02T05:30:00Z ; EST-second = 2025-11-02T06:30:00Z

anchor local: 2025-03-09 01:00:00-05:00 fold= 0
gap 2:30am -> 2025-03-09 02:30:00-05:00 fold= 0 -> 2025-03-09T07:30:00Z
  pre-transition(EST,-5) = 07:30Z ; post-transition(EDT,-4) = 06:30Z
```

- Spring-forward **gap**: resolves to `07:30Z`, the pre-transition offset, the **later** of the
  two readings. The docstring's first bullet is **correct**.
- Fall-back **ambiguity**: resolves to `05:30Z` — the **FIRST (EDT) occurrence**, i.e. the
  **EARLIER** of the two candidate instants, by one full DST delta. "**never early**" is **false**.

**And the mitigating clause is vacuous.** The docstring hangs correctness on *"as long as the
anchor's fold reflects when the signal actually fired"*. `moment = now.astimezone(tz)` carries
`fold=1` **only when the anchor itself lies inside the repeated hour** — a 1-hour window. For the
other 23 hours of the transition day, and every other day of the year, `fold` is 0 and the
ambiguous candidate resolves to the earlier occurrence unconditionally. Confirmed:

```
anchor 2025-11-02 05:10:00+00:00 -> local 01:10:00-04:00 fold=0 | candidate 01:30:00-04:00 fold=0 -> 2025-11-02T05:30:00Z
anchor 2025-11-02 06:10:00+00:00 -> local 01:10:00-05:00 fold=1 | candidate 01:30:00-05:00 fold=1 -> 2025-11-02T06:30:00Z
cross-day into ambiguous: 2025-11-01 06:00:00-04:00 -> 2025-11-02 01:30:00-04:00 fold=0 -> 2025-11-02T05:30:00Z
```

The last line is the realistic shape: an anchor a day earlier, nowhere near the fold, resolving
the ambiguous target to the earlier instant. The fold is not "tracking when the signal fired" —
it is pinned at 0 by construction.

**Why this matters at MAJOR.** An early horizon is precisely the harm the surrounding module is
built to avoid: `_limit_reset_passed` gates auto-resume on `now >= limit_reset_at`, so a horizon
1h early resumes a `limited` worker before the wall lifts and burns a second limit hit. The
paragraph tells the next maintainer this cannot happen. It can. U4 shipped as
"documentation only, no behavior change" — the behavior is indeed unchanged, but the
documentation added is wrong in the one direction that has a cost.

**Provenance note (not exculpatory).** The source review's D3 paragraph
(`MD-ULPARSER-REVIEW-2026-07-17.md:180-190`) already said *"error bounded at ≤1h and in the **late**
(safer) direction"* while pasting a repro showing `fold=0 → 2026-11-01T05:30:00Z` (the earlier
one). The builder did not merely copy that imprecision — they **strengthened** it into
"**Both directions** … **never early**", a categorical claim the source's own pasted data
refutes.

**Exact fix.** Replace the second bullet and the summary sentence with:

> - an ambiguous fall-back local time inherits `moment`'s fold, which is 0 unless the anchor
>   itself falls inside the repeated hour — so in practice it resolves to the **first (DST)**
>   occurrence, i.e. up to one DST delta **EARLY**. This is the one direction in which this
>   helper can err early; it is bounded by the DST delta (≤1h in every current tzdb zone) and is
>   dormant for the only zone observed in production (Asia/Qyzylorda, no DST).

and delete "Both directions are bounded and late-erring, never early". If the early direction is
judged unacceptable rather than merely documented, the code fix is one keyword —
`moment.replace(..., fold=1)` — which selects the later occurrence in the ambiguous case and
leaves the gap case unchanged; that is a behavior change and needs its own test.

**Test that must pin it (if the code is changed):** an `America/New_York` case with
`now = 2025-11-01T06:00:00Z` and text `"resets 1:30am (America/New_York)"`, asserting the chosen
instant explicitly. There is **no** DST test anywhere in the suite today — `grep` finds no
`America/New_York` in `tests/`. That absence is why an incorrect DST paragraph could ship.

---

## 4. M2 — MAJOR: four new tests depend on the `tzdata` pip package, and U3's pass-branch test inverts on exactly the machine U3 exists to detect

**Defect.** `TestDoctorTzdata::test_zoneinfo_resolves_passes_plain` asserts
`"resolves named zones" in msg` — i.e. it asserts that tz data **is present**. The check it tests
exists because, in the source review's own words
(`MD-ULPARSER-REVIEW-2026-07-17.md:143-152`), tz data on this host is present *"by coincidence of
an unrelated project's transitive dependency (`pandas`)"*, and `pip uninstall pandas`, a clean
Windows box, or a venv all remove it. The new check's docstring repeats that reasoning verbatim —
and then the new test asserts the coincidence holds.

**Repro** — simulate a box without the `tzdata` pip package by blocking its import (this is
faithful: `TZPATH: ()` on Windows, so `zoneinfo` resolves *entirely* through that package):

```
$ py -3.13 -c "
import sys, importlib.abc, pytest
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'tzdata' or name.startswith('tzdata.'):
            raise ImportError('blocked: simulating box without tzdata pip package')
sys.meta_path.insert(0, Block())
sys.exit(pytest.main(['tests/test_resilience.py','-q','--no-header','--color=no','-rf']))
"
FAILED tests/test_resilience.py::TestDoctorTzdata::test_zoneinfo_resolves_passes_plain          <-- NEW
FAILED ...TestParseLimitSignalLocalFormat::test_local_format_parsed_to_correct_utc_instant[...4:40am...]
FAILED ...TestParseLimitSignalLocalFormat::test_local_format_parsed_to_correct_utc_instant[...12am...]
FAILED ...TestParseLimitSignalLocalFormat::test_local_format_parsed_to_correct_utc_instant[...12pm...]
FAILED ...TestParseLimitSignalLocalFormat::test_local_format_parsed_to_correct_utc_instant[...11:59pm...]
FAILED ...TestParseLimitSignalLocalFormat::test_already_past_today_rolls_to_tomorrow
FAILED ...TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve[12am-...]  <-- NEW
FAILED ...TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve[12pm-...]  <-- NEW
FAILED ...TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve[1am-...]   <-- NEW
9 failed, 102 passed in 2.20s
```

And the check itself, on the same simulated box, behaves correctly:

```
$ py -3.13 notz.py
UNRESOLVED: ZoneInfoNotFoundError 'No time zone found with key Asia/Qyzylorda'
doctor check -> ('tzdata', True, 'zoneinfo cannot resolve a named zone (ZoneInfoNotFoundError: ...) -- local-format limit-signal parsing ("resets 4:40am (Zone/City)") will null-park until tz data is installed: py -3.13 -m pip install tzdata')
```

So the *production* behavior is right and the *test* is what breaks.

**Two distinct problems, one root.**
1. **New instance of a pre-existing class.** 5 of the 9 failures are pre-existing
   (`TestParseLimitSignalLocalFormat`, inherited from M-D). This branch raises the count from
   5 to 9 — a 80% increase in the undeclared-dependency footprint of a repo that CLAUDE.md pins
   **stdlib-only** and that ships no `requirements.txt`.
2. **The new one is worse in kind.** `test_zoneinfo_resolves_passes_plain` does not merely *use*
   tz data — it **asserts tz data exists**. It is the only test in the suite whose pass/fail
   encodes an environment fact the branch's own docstring calls a coincidence. On the clean box
   D1 was written for, the check correctly reports the degradation *and its own test goes red*.

**Exact fix.** Make both `TestDoctorTzdata` cases deterministic by stubbing the seam in both
directions, mirroring the existing failure-branch test:

```python
def test_zoneinfo_resolves_passes_plain(self, isolated_home, monkeypatch):
    import zoneinfo
    monkeypatch.setattr(zoneinfo, "ZoneInfo", lambda name: object())   # resolves, whatever the host has
    name, ok, msg = fleet._doctor_check_tzdata()
    assert (name, ok) == ("tzdata", True)
    assert "resolves named zones" in msg
```

Same treatment for `TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve`
is **not** recommended (stubbing ZoneInfo there would destroy the arithmetic under test); instead
mark that class and `TestParseLimitSignalLocalFormat` with a shared
`pytest.mark.skipif` guarded on a `_tzdata_available()` helper, so a clean box **skips** rather
than **fails**. **Test that must pin it:** the injection is the repro above — the blocked-`tzdata`
run must report `0 failed`.

---

## 5. Minor findings

### m1 — MINOR (comment lies about the code): the D4 "intentional gap" justification is factually wrong

**The claim**, `bin/fleet.py:1105-1117`:

> ```
> # ... a single-segment zone name -- "(UTC)", "(Singapore)", "(EST5EDT)" -- can never
> # match; ... admitting those shapes would mean either a curated alias table (UTC ->
> # Etc/UTC, etc.) whose coverage is inherently incomplete, or accepting an ambiguous
> # abbreviation (which IANA zone is "EST5EDT" really pinned to for a given message?)
> ```

**Repro:**

```
$ py -3.13 -c "import zoneinfo; ..."
UTC        RESOLVES  utcoffset(2026-01-01)=0:00:00
Singapore  RESOLVES  utcoffset(2026-01-01)=8:00:00
EST5EDT    RESOLVES  utcoffset(2026-01-01)=-1 day, 19:00:00
GMT / Japan / Zulu / PST8PDT / EST / Israel / Poland / Iran   all RESOLVE
in tzdb available_timezones(): 3 of 3 cited names present
```

All three names the comment cites as needing an alias table or as being ambiguous abbreviations
are **canonical IANA keys** that `zoneinfo.ZoneInfo` resolves directly and unambiguously.
`UTC -> Etc/UTC` is not a mapping anyone has to author — `ZoneInfo("UTC")` already works.
`EST5EDT` is not an abbreviation whose zone must be guessed — it *is* a tzdb key with a defined
rule set. The stated reason for the gap does not describe reality.

The gap itself (`_LIMIT_RESET_LOCAL_RE` requiring ≥1 `/`) is real and does fail safe — verified:

```
resets 4:40am (UTC)        -> (None, None)
resets 4:40am (Singapore)  -> (None, None)
resets 4:40am (Etc/GMT+5)  -> ('2026-07-16T09:40:00Z', None)     # multi-segment path works
```

**Exact fix.** Replace the justification with the one that is actually load-bearing: the shapes
have never been observed in a production message, and `zoneinfo` — not a hand-written table — is
already the arbiter, since `_next_local_reset_utc` null-parks anything `ZoneInfo` rejects. State
that the gap is a YAGNI decision, not a safety one. **Test that must pin it:** none needed; this
is prose.

### DQ1 — DESIGN-QUESTION: D4 asked for a follow-up and got a decline on the grounds refuted by m1

D4's ask was *"a bare `(UTC)` is plausible enough in a message to be worth a follow-up"*
(`MD-ULPARSER-REVIEW-2026-07-17.md:196-199`). U4 declined it and documented the decline as an
INTENTIONAL gap. Given m1, the safety argument for declining does not hold: widening the tz group
to `[A-Za-z_][A-Za-z_+\-0-9]*(?:/[A-Za-z_+\-0-9]+)*` would let `(UTC)` through and hand it to
`ZoneInfo`, which either resolves it (correct horizon) or raises into the existing blanket
`except` (null-park) — the same two outcomes the multi-segment path already has. Declining is
still a defensible call on YAGNI grounds; it is the **stated reason** that is wrong. Manager's
call whether to widen; I am not filing it as a defect.

### m2 — MINOR: `_doctor_check_tzdata` ships no injectable seam

Every sibling check takes a seam (`run=subprocess.run`, `which=shutil.which`). `_doctor_check_tzdata()`
takes nothing, so its failure-branch test must `monkeypatch.setattr(zoneinfo, "ZoneInfo", boom)` —
patching a **stdlib module attribute globally** for the duration of the test. It works (I5/I6/I9
all land), but it is a heavier hammer than the repo's convention and it is the reason M2's fix has
to use the same hammer on the pass branch. A `zone="Asia/Qyzylorda"` or `lookup=zoneinfo.ZoneInfo`
kwarg would match convention.

### m3 — nit: the remedy string uses the Windows-only `py` launcher

`py -3.13 -m pip install tzdata` — `py` does not exist on macOS/Linux.
**`[UNVERIFIED — no POSIX box]`** for runtime behavior; the launcher's Windows-only nature is a
fact, not a probe. Mitigating, and why this is a nit not a finding: (a) POSIX ships a system tz
database, so on POSIX `zoneinfo` resolves and this branch is not reached — I reason this out
rather than assert it, `[UNVERIFIED — no POSIX box]`; (b) it is repo-consistent — `pin-version`'s
remedy in the same doctor output reads `run FLEET_LIVE=1 py -3.13 -m pytest …`; (c) CLAUDE.md
pins `py -3.13` as *the* invocation.

### m4 — nit: the `_next_local_reset_utc(...)` call is duplicated across both am/pm arms

```python
elif ampm == "am":
    hour24 = 0 if hour == 12 else hour
    reset_at = _next_local_reset_utc(hour24, minute, tz_name, now=now)
else:
    hour24 = 12 if hour == 12 else hour + 12
    reset_at = _next_local_reset_utc(hour24, minute, tz_name, now=now)
```

The pre-fix shape (compute `hour24`, then one call after the branch) survives a guard cleanly:
`if not 1 <= hour <= 12: reset_at = None` / `else: hour24 = …; reset_at = _next_local_reset_utc(…)`.
Two identical call sites is two places to drift — the branch's own named error class.

### m5 — nit: `TestNowParameterRequired` asserts a bare `TypeError` with no message match

`pytest.raises(TypeError)` around `fleet._parse_limit_signal("resets 4:40am (Asia/Qyzylorda)")`
would stay green if a future refactor raised `TypeError` for an unrelated reason (e.g. a changed
positional arity). It has teeth **today** — I4 and I5 both land it — but `match="missing 1 required
keyword-only argument: 'now'"` would make it structural.

### m6 — nit: `"0am"` — the third pre-fix case D2 named — has no test

D2's ask listed three pre-fix behaviors: `13am → 1pm` (wrong), `0am → 00:00` (accepted), and
`13pm/99pm → None` (safe by accident). The new parametrization covers `13am` and `0pm`; `0am` is
covered *by the same lower bound* (I1 proves the bound is pinned via `0pm`) so this is coverage
redundancy, not a hole. Naming it because the review's own list is the natural test vector.

### m7 — nit: `_doctor_check_tzdata` is appended directly after `_doctor_check_supervisor_handoff`

Sibling-owned territory. No sibling line was edited (§7 confirms), but textual adjacency to the
handoff worker's function raises merge friction unnecessarily. The `check_calls` placement (last)
was chosen for exactly this reason and is correct; the function-body placement gives it back.

---

## 6. Failure-class hunt (mandatory method §3) — what did NOT fire

Reported for completeness; each is a receipted negative, not an assumption.

**6.1 Fix at one call site and not its twin — did not fire.** Repo-wide grep, §0. One production
call site, and it passes `now=`. All 7 pre-existing test call sites were updated (3 needed it,
verified in the diff at `tests/test_resilience.py:592,596,668`).

**6.2 3.10-floor break — did not fire.** `py -3.10 -m pytest tests/test_resilience.py -q` →
`111 passed in 1.68s`, run by **me**. The only new annotation risk is `_next_local_reset_utc`'s
bare `now: datetime`; `from __future__ import annotations` is at `bin/fleet.py:20` (verified),
and `datetime` is imported at module scope (`:36`) so it would evaluate even without the future
import. `_parse_limit_signal` keeps its string annotation `"datetime | None"` — cosmetically
inconsistent with its neighbor, functionally irrelevant.

**6.3 A fix that mints a new defect one call site away — did not fire.** I probed the adjacent
paths directly:

```
                                       me/ul @ 4b8a88e        base @ ac3e34d
resets 13am (Asia/Qyzylorda)        -> (None, None)           ('2026-07-16T08:00:00Z', None)
resets 0pm (Asia/Qyzylorda)         -> (None, None)           ('2026-07-16T07:00:00Z', None)
resets 4:75am (Asia/Qyzylorda)      -> (None, None)           (None, None)
resets 4:60am (Asia/Qyzylorda)      -> (None, None)           —
resets 99am (Asia/Qyzylorda)        -> (None, None)           —
```

Minute overflow (`4:60am`, `4:75am`) null-parks identically before and after — the D2 guard
validates the hour only, and the minute continues to rely on `replace()` raising into the blanket
`except`. Unchanged, safe, and the docstring does not overclaim about minutes. `kind` detection is
untouched by the D2 branch and is pinned (injection I10 goes RED on both parametrizations).

**6.4 A comment that lies about the code — FIRED TWICE.** M1 and m1. This was the productive lens,
as the brief predicted.

**6.5 Silently-changed public behavior / standing-goal-2 — did not fire.**
- `now=None` passed *explicitly* still does exactly what the docstring says: the
  `elif now is not None:` guard at `bin/fleet.py:1225` skips the local branch, `reset_at` stays
  `None`, `kind` is still detected. Verified by `TestParseLimitSignalLocalFormat` (3 call sites
  now pass `now=None` explicitly and still pass) and directly.
- **No production path raises where it previously parked.** The sole call site,
  `transcript_limit_scan` @ `bin/fleet.py:1430`, passes `now=_record_time(rec)` unconditionally
  (`_record_time` returns `None`, never raises — `:1334-1341`). Standing goal 2 intact.
- One theoretical wrinkle, filed as an observation only: `transcript_limit_scan`'s docstring
  promises *"Never raises (T6 fix wave C1)"*, but its `try/except OSError` wraps only the path/read
  block (`:1406-1412`) — the `_parse_limit_signal` call at `:1430` sits **outside** it. So U2's
  promised "structural `TypeError` at the call site" would, from inside `transcript_limit_scan`,
  propagate out of a function documented never to raise. Not reachable today (the call site is
  correct); noting it because U2's entire value proposition is about a *future* caller.

**6.6 Doctor regressions — none.** Runs on every `fleet doctor` (§2, verified in live output);
registered LAST, so the append-only `check_calls` conflict surface with sibling workers is minimal;
runs inside `cmd_doctor`'s per-check isolation wrapper (M-B T11), so a raise cannot kill doctor;
`zoneinfo` imported **inside** the function, never hoisted; performs one in-memory-cached
`ZoneInfo` lookup, no measurable cost; writes nothing; PASS-notes on a host **with** tz data
(observed) and PASS-notes with the remedy on a host without (simulated, §4).

---

## 7. SPURIOUS-FIX verdict (mandatory method §5) — **none spurious**

| | Was it actually broken? | Verdict |
|---|---|---|
| **U1 / D2** | **Yes, proven.** At `ac3e34d`, `"resets 13am (Asia/Qyzylorda)"` with `now=2026-07-16T01:00Z` returns `('2026-07-16T08:00:00Z', None)` = 13:00 Qyzylorda = **1pm**, a well-formed wrong horizon. `"0pm"` returns `('2026-07-16T07:00:00Z', None)` = noon. Both null-park post-fix. | **NOT SPURIOUS** |
| **U2 / §5.1** | **Yes** — the default existed at `ac3e34d:1110`/`:1136` and 3 test call sites actually relied on it. Latent, not live (§5.1 said so and the docstring repeats it honestly). | **NOT SPURIOUS** |
| **U3 / D1** | **Yes** — no tz-data check existed; D1 explicitly recommended this exact remedy. Delivered, but see C1 (unpinned) and M2 (env-dependent test). | **NOT SPURIOUS** |
| **U4 / D3+D4** | The asks were real. The D3 documentation is **substantively wrong** (M1); the D4 documentation's **justification** is wrong (m1) and the ask itself was declined (DQ1). | **NOT SPURIOUS, but mis-executed** |

**Reverse check — anything quietly fixed that wasn't asked for?** No. The diff is 2 files,
6 hunks in the parser region, 1 line in `cmd_doctor`, 1 new function, 4 hunks in tests. Nothing
outside the D1–D4 + §5.1 mandate.

**Anything quietly NOT fixed that was asked?** One: D4's "worth a follow-up" for `(UTC)` was
converted into a documented permanent gap rather than a follow-up (DQ1). This is a visible,
argued decline, not a silent omission — but it is a decline, and its stated reason is refuted.

---

## 8. Spec / doctrine conformance (mandatory method §4) and scope (§6)

| Rule | Status |
|---|---|
| `bin/fleet.py` stdlib-only, single file | ✅ no new import outside stdlib; `zoneinfo` is stdlib. ⚠️ but see M2: the *test suite* now leans harder on the non-stdlib `tzdata` package |
| `zoneinfo` imported inside the helper, never hoisted | ✅ both `_next_local_reset_utc:1162` and `_doctor_check_tzdata` do a local `import zoneinfo`; module-level imports unchanged (`bin/fleet.py:20-37`) |
| Views never probe / never write (`docs/specs/terminal-surface.md`) | ✅ not applicable — doctor is not a view, and the new check is registered only in `cmd_doctor` |
| Portability invariant 8 (Win/macOS/Linux) | ✅ on Windows (observed). On POSIX, a system tz database is normally present so the check PASS-notes the "resolves" branch — **`[UNVERIFIED — no POSIX box]`**, reasoned not asserted. See m3 for the Windows-only remedy string |
| Python 3.10 floor | ✅ `py -3.10` → 111 passed (§6.2) |
| Scope: no daemon/dispatch, no supervisor-handoff / autoclean-ownership | ✅ verified by hunk headers — see below |

Scope verification (`git diff ac3e34d..4b8a88e --unified=0 | grep '^@@'`), files touched:
`bin/fleet.py`, `tests/test_resilience.py` — nothing else.

```
@@ -1103,0  +1104,14 @@   _LIMIT_RESET_LOCAL_RE comment (D4)
@@ -1110    +1124   @@   _next_local_reset_utc signature (U2)
@@ -1115,6  +1129,33 @@   its docstring (U2 + D3)
@@ -1127    +1168   @@   wall-clock fallback removed (U2)
@@ -1136    +1177   @@   _parse_limit_signal signature (U2)
@@ -1149,4  +1190,20 @@   its docstring (U2 + D2)
@@ -1175    +1232,5 @@   the 1..12 guard (U1)
@@ -1176,0  +1238   @@   am-arm call (U1)
@@ -1179    +1241   @@   pm-arm call (U1)
@@ -6089,0 +6152   @@   cmd_doctor check_calls   <-- known shared hotspot, ONE appended line, last position
@@ -7568,0 +7632,30 @@   new _doctor_check_tzdata
```

The `cmd_doctor` touch is exactly the expected one-line conflict at the known shared hotspot,
appended last. `_doctor_check_supervisor_handoff` itself is **not** modified (the `+7632,30` hunk
appends after it; see m7). No daemon, dispatch, supervisor-handoff, or autoclean code touched.

**Injection hygiene.** All 10 injections reverted with `git checkout 4b8a88e -- …` between runs,
and the two files restored to `HEAD` (`39ec4f8`) afterwards:

```
$ git checkout HEAD -- bin/fleet.py tests/test_resilience.py && git status --porcelain
(empty)
```

Final tree is clean apart from this review file.

---

## 9. Probe-context declaration (template v1.7)

I am `me-ul-review`, a `--bg` fleet worker. **Every probe reported above was run by me** in
`C:/proga/fleet-me-ul-review` at the stated content (`HEAD = 39ec4f8` for the baseline;
`bin/fleet.py`/`tests/test_resilience.py` checked out from `4b8a88e` for everything else).

Not observable from here, and therefore **not asserted**:

- **`[MANAGER-VERIFICATION REQUIRED]`** — POSIX behavior of `_doctor_check_tzdata` (m3, §8).
  No POSIX box available; reasoned from the fact that POSIX ships a system tz database.
- **`[MANAGER-VERIFICATION REQUIRED]`** — behavior of the tzdata check on a genuinely clean
  Windows box. §4's no-`tzdata` result is an **import-blocker simulation**, faithful in mechanism
  (`TZPATH: ()` means the pip package is the only source) but still a simulation.
- **`[MANAGER-VERIFICATION REQUIRED]`** — `fleet doctor`'s exit code with the new check present.
  I read only piped output; `$?` after the pipe reports `tail`'s status.
- I did not run any mutating `fleet` verb, any `sup-*` verb, `claude daemon`, or `claude stop`;
  I did not modify anything under `C:/Users/Techn/.claude/`; I did not write to
  `C:/proga/fleet-me-ul` or `C:/proga/claude-fleet` (except my own journal, as instructed); I did
  not touch the `claude-fleet-autoclean` scheduled task or any sibling worktree.

---

## 10. Fix wave (ordered)

1. **C1 (CRITICAL)** — pin the doctor-check registration. Extend
   `tests/test_native.py::TestCmdDoctorRegistersNewChecks::test_new_checks_run_and_appear_in_output`
   with `assert "tzdata" in out` and `assert out.index("supervisor-handoff") < out.index("tzdata")`.
   *Pin proof:* deleting `functools.partial(_doctor_check_tzdata),` from `cmd_doctor` must turn the
   suite RED (today: injection I8 leaves it at `1145 passed, 6 skipped`).
2. **M1 (MAJOR)** — rewrite the D3 fall-back bullet at `bin/fleet.py:1153-1157` and delete
   "Both directions are bounded and late-erring, never early". Replacement prose in §3.
   If the early direction is to be *fixed* rather than documented, add `fold=1` to the `replace()`
   call and pin it with an `America/New_York` ambiguous-hour test (there is no DST test in the
   suite today).
3. **M2 (MAJOR)** — make `TestDoctorTzdata::test_zoneinfo_resolves_passes_plain` deterministic by
   monkeypatching `zoneinfo.ZoneInfo` to a stub that resolves; add a `skipif` on tz-data
   availability to `TestParseLimitSignalLocalFormat` and
   `TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve`.
   *Pin proof:* the blocked-`tzdata` pytest run in §4 must report `0 failed`.
4. **m1 (MINOR, same wave)** — replace the D4 justification at `bin/fleet.py:1109-1117`; the cited
   names are canonical IANA keys, not abbreviations needing an alias table.
5. **m2, m4, m5, m7 (nits, optional)** — seam on the doctor check; collapse the duplicated
   `_next_local_reset_utc` call; `match=` on the `TypeError` assertions; move
   `_doctor_check_tzdata` out of the handoff worker's textual neighborhood.
6. **DQ1** — manager's call on whether to widen `_LIMIT_RESET_LOCAL_RE` to admit single-segment
   zone names. Not filed as a defect.

None of U1–U4 is spurious. The behavioral code is correct; the wiring test and two comment
paragraphs are not.

---

`VERDICT: fix-wave(C1, M1, M2; m1 same wave)`


---
---

# RE-REVIEW — fix wave `706b94a`

**Reviewer:** fleet worker `me-ul-review` (`--bg`), worktree `C:/proga/fleet-me-ul-review`,
branch `me/ul-review`. **Under review:** `706b94a` on `me/ul` (base `4b8a88e`),
3 files, +201/−63. **Date:** 2026-07-21.

## RE-REVIEW VERDICT: `fix-wave(ND-1; ND-2 + ND-3 same wave)`

**All five ordered items landed and all three pin proofs I demanded pass when re-run by me.**
This is not ESCALATE territory: nothing here is structural, and the wave did not break a
neighbour's behavior. It did, however, mint one **new latent defect (ND-1, MAJOR)** — the very
`skipif` I asked for can silently disable **17 tests**, including every exact-instant assertion of
the parser *and* both DST tests this wave just landed, with the suite still reading green. That is
the 4-of-4 "one call site away, same direction" pattern firing a fifth time, this time in the test
harness rather than the code. The fix is a six-line canary test; **I wrote it and proved it goes
RED on the failure and green otherwise** (§R3), so a third wave is one paste, not an investigation.

**One deviation from an explicit manager ruling, and it was the right call.** M1 was ruled
"add `fold=1`". The builder shipped `max(fold=0, fold=1)` instead and documented why. I verified
the deviation: the literal ruling would have been a **silent no-op** in the day-rollover case, and
worse, it would have **broken the gap case** — the suite's own new gap test catches it (injection
J5 → RED). Ratify the deviation.

---

## R0. Disposition of every prior finding

| id | Ordered | Disposition | Evidence |
|---|---|---|---|
| **C1** | pin the doctor-check registration | **FIXED** | `tests/test_native.py:4925-4929`. Pin proof P1 re-run: unregistering now → `1 failed, 1148 passed` (was `1145 passed`, green). Position also pinned — J7 → RED. |
| **M1** | fix `fold`, pin with an `America/New_York` ambiguous-hour test | **FIXED (with a verified deviation from the literal ruling — ratify)** | `bin/fleet.py:1209-1211`, `TestNextLocalResetUtcDst`. Pin proof P3 re-run → RED. See §R2. |
| **M2** | deterministic doctor test + `skipif` | **FIXED** | Pin proof P2 re-run: blocked-`tzdata` run → `98 passed, 17 skipped`, **0 failed** (was `9 failed`). But see **ND-1**. |
| **m1** | remove the false D4 justification | **FIXED** | `bin/fleet.py:1105-1112` now states the truth and names the verification. But the *replacement* overclaims — see **ND-2**. |
| **DQ1** | widen the regex, `ZoneInfo` as validator | **FIXED as ruled** | `bin/fleet.py:1127-1128`. J3 (revert the widening) → RED. |
| m2 | seam on `_doctor_check_tzdata` | **NOT-FIXED** — filed optional, not ordered. Still no seam; both `TestDoctorTzdata` cases now monkeypatch the stdlib `zoneinfo` module. Acceptable at this cost. |
| m3 | Windows-only `py` remedy string | **NOT-FIXED** — filed optional, not ordered, repo-consistent. |
| m4 | duplicated `_next_local_reset_utc(...)` call | **FIXED** | `bin/fleet.py:1275-1280`, collapsed to one call. Verified behavior-preserving (J8 → 15 RED across both test files). |
| m5 | bare `pytest.raises(TypeError)` | **FIXED** | `match=r"missing 1 required keyword-only argument: 'now'"`, and it holds on the 3.10 floor (§R6). |
| m6 | `"0am"` untested | **NOT-FIXED** — filed as coverage redundancy, not ordered. |
| m7 | function placed in the handoff worker's neighborhood | **FIXED** | moved to sit after `_doctor_check_autoclean` (`bin/fleet.py:6057`), whose doctrine it cites. Registration order unchanged (verified in source and by J7). |

**`SPURIOUS-FIX`: none.** Every changed line traces to C1, M1, M2, m1, DQ1, m4, m5 or m7. I looked
specifically for the reverse failure — an author who accepts everything "fixing" something that
was never broken — and found none: the three items I filed as optional (m2, m3, m6) were correctly
left alone rather than reflexively closed, and nothing outside the ordered set was touched.

**`DISPUTED`: one — M1's implementation, in the builder's favour** (§R2). Recorded because
"DISPUTED: none" across a whole wave is a smell; here the disagreement is real, it is with the
*manager's* ruling rather than the builder's code, and the builder is right.

---

## R1. The three pin proofs, re-run by me — all pass

Method: worktree `C:/proga/fleet-me-ul-review`, with `bin/fleet.py`, `tests/test_resilience.py`
and `tests/test_native.py` checked out from `706b94a`. Baseline first, unmutated:

```
$ py -3.13 -m pytest tests/ -q
1149 passed, 6 skipped in 59.17s          # matches the manager-verified count exactly
```

**P1 (C1) — re-apply injection I8.** Delete `functools.partial(_doctor_check_tzdata),` from
`cmd_doctor`'s `check_calls`:

```
1 failed, 1148 passed, 6 skipped in 63.58s
FAILED tests/test_native.py::TestCmdDoctorRegistersNewChecks::test_new_checks_run_and_appear_in_output
```

**PASS.** It stayed at `1145 passed` before the wave. The registration is now pinned, and so is its
*position* — J7 (register the check first instead of last) also goes RED on the same test.

**P2 (M2) — the blocked-`tzdata` run must report 0 failed.** Same import-blocker harness as the
original review's §4:

```
$ py -3.13 -c "<meta_path blocker for 'tzdata'>; pytest.main(['tests/test_resilience.py', ...])"
98 passed, 17 skipped in 4.15s
```

**PASS** — 0 failed, down from `9 failed, 102 passed`. (The 17 skipped is itself the subject of
**ND-1**.)

**P3 (M1) — the new DST test must go RED without the fold fix.** Replace the `max(...)` block with
the pre-wave `return candidate.astimezone(...)`:

```
1 failed, 1148 passed, 6 skipped in 56.56s
FAILED tests/test_resilience.py::TestNextLocalResetUtcDst::test_ambiguous_fallback_resolves_late_not_early
```

**PASS.**

---

## R2. M1 — the builder deviated from the ruling, and the deviation is correct

The ruling was *"add `fold=1` and pin it with an `America/New_York` ambiguous-hour test"*. What
shipped (`bin/fleet.py:1206-1211`):

```python
        candidate = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < moment:
            candidate += timedelta(days=1)
        later = max(candidate.replace(fold=0), candidate.replace(fold=1),
                     key=lambda c: c.astimezone(timezone.utc))
        return later.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

The docstring makes two load-bearing claims for the deviation. I tested both rather than reading
them.

**Claim 1 — "per PEP 495, `aware_datetime + timedelta` resets `fold` to 0 on the result", so a
`fold=1` set inside the same `.replace()` is erased by the next line. VERIFIED TRUE:**

```
  before: 2025-11-02 01:30:00-05:00 fold=1 -> 2025-11-02 06:30:00+00:00
  +1day : 2025-11-03 01:30:00-05:00 fold=0   CLAIM 'fold resets to 0' -> TRUE
```

**Claim 2 — the literal one-liner would have been a silent no-op. VERIFIED TRUE**, and precisely in
the case that matters (the ambiguous horizon you reach by rolling over from a previous day):

```
  WITH day-rollover  replace(fold=1)-> fold=0 2025-11-02T05:30:00Z | shipped max()-> fold=1 2025-11-02T06:30:00Z | pre-fix-> 2025-11-02T05:30:00Z
                     ruled-fix a NO-OP here? YES (== pre-fix, WRONG/early)
  NO day-rollover    replace(fold=1)-> fold=1 2025-11-02T06:30:00Z | shipped max()-> fold=1 2025-11-02T06:30:00Z | pre-fix-> 2025-11-02T05:30:00Z
                     ruled-fix a NO-OP here? no
```

**And the ruling would have minted a new defect.** A *correctly placed* `fold=1` (i.e. after the
rollover, which is what the ruling meant) flips the **gap** case from its already-correct late
reading to an early one. The wave's own new gap test catches exactly this — injection **J5**
(`later = candidate.replace(fold=1)`):

```
1 failed, 1148 passed, 6 skipped
FAILED tests/test_resilience.py::TestNextLocalResetUtcDst::test_gap_still_resolves_late_unaffected_by_fold_fix
```

So the builder did not merely disobey a ruling — they wrote the test that proves the ruling wrong.
**Ratify the deviation.**

**The `max()` fix itself, attacked** (manager's ask: *"prove it does not shift a correct horizon"*).

*Production zone `Asia/Qyzylorda` (no DST) — 2928 samples across a full year:*

```
366 days x 4 hours x 2 minutes = 2928 samples, horizons shifted by the fold fix: 0
```

*`America/New_York` — every hour of a full year, shipped vs pre-fix:*

```
samples=8784  shipped EARLIER than pre-fix: 0   LATER: 1   identical: 8783
monotone-never-earlier invariant: HOLDS
  ('LATER', 2026-11-01 01:17Z, pre-fix '2026-11-01T05:30:00Z', shipped '2026-11-01T06:30:00Z')
```

Surgical: exactly one horizon in 8784 moves, it is the ambiguous fall-back hour, and it moves in
the intended direction. The change is **monotone-never-earlier** by construction — `max()` can only
return something ≥ what the old code returned — so no correct horizon can be shifted early even in
principle, and the sweep confirms it empirically.

*Safety invariants across five zones including 30-minute and negative DST
(`America/New_York`, `Asia/Qyzylorda`, `Australia/Lord_Howe`, `Europe/Dublin`, `Pacific/Chatham`):*

```
horizons before `now` OR more than 26h out: 0
```

Never resumes before the signal fired; never invents a horizon more than a day-plus-delta out.

*The three cases the docstring itemises — all confirmed:*

```
  fold  (fall-back 1:30am)   pre-fix=2025-11-02T05:30:00Z  shipped=2025-11-02T06:30:00Z   [second/EST = later]
  gap   (spring-fwd 2:30am)  pre-fix=2025-03-09T07:30:00Z  shipped=2025-03-09T07:30:00Z   [pre-transition = later, unchanged]
  plain (noon, no edge)      pre-fix=2025-07-01T16:00:00Z  shipped=2025-07-01T16:00:00Z   [fold irrelevant]
```

**M1: FIXED. No new defect in the fold fix.** Nit only: the continuation line
`                     key=lambda c: ...` is indented one column past `max(`'s opening paren.

---

## R3. ND-1 — MAJOR (new defect): the `skipif` guard can silently disable 17 tests with a green suite

This is the manager's own stated hazard — *"a test that silently stops running is worse than the
flakiness it fixes"* — and it is live.

**First, the narrow part is fine.** On this host, which HAS tz data, **nothing skips**:

```
$ py -3.13 -m pytest tests/ -q -rs
SKIPPED [6] tests/integration/test_native_pin.py: live tier gated: set FLEET_LIVE=1 ...
1149 passed, 6 skipped
```

The only skips are the pre-existing `FLEET_LIVE` gate. The guard is correctly narrow **today**.

**The defect is that nothing pins that.** `_tzdata_available()` (`tests/test_resilience.py:40-56`)
is evaluated once at collection time and gates four blocks. Injection **J9** — make it return
`False` while tz data is in fact present:

```
# tests/test_resilience.py, _tzdata_available():
         zoneinfo.ZoneInfo("America/New_York")
-        return True
+        return False

$ py -3.13 -m pytest tests/ -q
1132 passed, 23 skipped in 58.98s        # GREEN. No FAILED lines.
```

**17 tests vanish and the suite still reads green.** What silently stopped running:

- `TestParseLimitSignalLocalFormat` — the entire exact-instant coverage of the local-format parser;
- `TestParseLimitSignalHourValidation::test_valid_boundary_hours_still_resolve` — U1's valid-side boundary;
- `TestParseLimitSignalSingleSegmentZone` — all of DQ1, landed by *this* wave;
- `TestNextLocalResetUtcDst` — **both** DST cases, i.e. the entire M1 fix, landed by *this* wave.

**Severity = what it fails to protect**, per the brief: every behavioral assertion about horizon
arithmetic in the repo, including both of this wave's own headline fixes. And the trigger is not
hypothetical — a `pip uninstall pandas`, a venv, or a CI box is exactly the configuration D1 was
filed about. On the first such box the suite goes green while zero exact-instant assertions run,
and the `limited`-park horizon is unguarded.

**Exact fix — written and proven, not merely proposed.** Add one canary that is *deliberately not*
`skipif`-guarded and cross-checks the guard against the independent `_doctor_check_tzdata` probe:

```python
class TestTzdataGuardCanary:
    """`_tzdata_available()` gates 17 tests. If it ever silently returns
    False on a box that HAS tz data, those 17 vanish and the suite still
    reads green. Deliberately NOT skipif-guarded: it cross-checks the guard
    against the independent `_doctor_check_tzdata` probe, so a lying guard
    is loud. On a genuinely clean box both sides are False and this passes."""

    def test_guard_agrees_with_doctor_check(self):
        _name, _ok, msg = fleet._doctor_check_tzdata()
        assert _tzdata_available() == ("resolves named zones" in msg)
```

**Proof it works** (canary added; then the guard mutated to lie; then restored):

```
A. canary added, guard HONEST  -> 116 passed in 1.62s
B. canary added, guard LYING   -> 1 failed, 98 passed, 17 skipped in 1.58s
      tests/test_resilience.py::TestTzdataGuardCanary::test_guard_agrees_with_doctor_check
   canary catches the silent-skip?  YES
C. restored: 115 passed in 1.68s
```

It stays green on a real clean box too (both sides evaluate `False`), so it does not reintroduce M2.

---

## R4. ND-2 — MINOR (new defect, comment lies about the new code): "can never convert one into a *wrong* one" is false

**The claim**, `bin/fleet.py:1116-1123`:

> ```
> # ... a name it resolves yields a correct horizon, a name it rejects raises into
> # the existing blanket `except Exception: return None` and null-parks ... Widening
> # can therefore only convert a null-park into a *correct* horizon; it can never
> # convert one into a *wrong* one.
> ```

This is also the bar the manager's DQ1 ruling asserted. It does not hold, because the dichotomy
"resolves ⇒ correct / rejects ⇒ null-park" omits a third case: **a name `ZoneInfo` resolves to
something other than what the message meant.** The widened group admits **45** single-segment keys,
and several of them are not places:

```
CET, CST6CDT, Cuba, EET, EST, EST5EDT, Egypt, Eire, Factory, GB, GB-Eire, GMT, GMT+0, GMT-0,
GMT0, Greenwich, HST, Hongkong, Iceland, Iran, Israel, Jamaica, Japan, Kwajalein, Libya, MET,
MST, MST7MDT, NZ, NZ-CHAT, Navajo, PRC, PST8PDT, Poland, Portugal, ROC, ROK, Singapore, Turkey,
UCT, UTC, Universal, W-SU, WET, Zulu
```

`EST`, `MST`, `HST` and `GMT` are **fixed-offset legacy keys that never observe DST** — `EST` is
not "US Eastern time", it is a zone permanently at UTC−5. Through the real parser, anchored in
July:

```
  '(...EST)' -> 2026-07-16T09:40:00Z   but '(...America/New_York)' -> 2026-07-16T08:40:00Z   delta = +1h  LATE
  '(...MST)' -> 2026-07-16T11:40:00Z   but '(...America/Denver)'   -> 2026-07-16T10:40:00Z   delta = +1h  LATE
  '(...GMT)' -> 2026-07-16T04:40:00Z   but '(...Europe/London)'    -> 2026-07-16T03:40:00Z   delta = +1h  LATE
  '(...CET)' -> 2026-07-16T02:40:00Z   and '(...Europe/Paris)'     -> 2026-07-16T02:40:00Z   delta =  0h
```

`"resets 4:40am (EST)"` in July produces a horizon that is **wrong by one hour**. Before the
widening it null-parked. So widening *can* convert a null-park into a wrong horizon.

**The safety bar itself survives, and I say so plainly.** I hunted specifically for an **early**
case — the only direction that matters for standing goal 2 — across all 45 newly-admitted keys and
both DST phases, and **found none**. The `CET`/`MET`/`EET`/`WET` family are rule-only zones that
*do* observe DST and track their colloquial meaning exactly (verified in both January and July);
the mismatching keys are all never-DST fixed offsets, and reading a daylight-time abbreviation as
standard time always lands **late**. So the horizon can be wrong but never early, D4's real bar
holds, and this is MINOR — a wording defect, not a behavior defect. But the sentence as written is
false, and it is precisely the sentence a future maintainer will lean on when widening this again.

**Exact fix.** Replace "it can never convert one into a *wrong* one" with:

> Widening can convert a null-park into a correct horizon, and — for the handful of legacy
> non-geographic keys in tzdb (`EST`, `MST`, `HST`, `GMT`, `GMT0`, `Factory`, …) — into a horizon
> that is wrong by the DST delta, because e.g. `EST` is a permanent-UTC−5 zone and not "US Eastern
> time". Every such mismatch errs LATE (a never-DST reading of a daylight abbreviation is always
> later), verified across all 45 single-segment keys, so the standing bias is intact. It can never
> convert a null-park into an EARLY horizon, which is the bar D4 actually set.

**Test that must pin it:** a case asserting `"resets 4:40am (EST)"` with a July anchor resolves to
`2026-07-16T09:40:00Z` — documenting the known-late reading rather than leaving it undiscovered.

---

## R5. ND-3 — MINOR (new defect): the regex's char-class boundary is unpinned

Injection **J4** — replace the carefully-scoped tz group with `\(([^)]+)\)`, admitting *anything*
between the parens:

```
1149 passed, 6 skipped in 61.91s     # GREEN. No FAILED lines.
```

DQ1's widening is pinned only in two coarse directions: one single-segment name resolves
(`(UTC)`), one garbage word null-parks (`(NotAZone)`). Nothing pins that whitespace- or
punctuation-bearing bracketed text is rejected **by the regex** rather than reaching `ZoneInfo` at
all. A future maintainer can loosen the class arbitrarily with a green suite.

**Consequence today is bounded, and I checked rather than assumed** — `ZoneInfo` is a competent
validator:

```
'../../etc/passwd'  rejects ValueError        'local time'  rejects ZoneInfoNotFoundError
'/etc/passwd'       rejects ValueError        '4:40'        rejects ValueError
'..' / '.'          rejects ValueError        'a b'         rejects ZoneInfoNotFoundError
'Asia/../Asia/Qyzylorda' rejects ValueError   ''            rejects ValueError
```

Path traversal, absolute paths, whitespace and empty keys are all rejected — which *supports* the
builder's DQ1 safety argument and is why this is MINOR, not MAJOR.

**Exact fix.** Add negative assertions at the `_LIMIT_RESET_LOCAL_RE` level, so they fail on the
regex rather than on `ZoneInfo`:

```python
@pytest.mark.parametrize("brack", ["(local time)", "(see below)", "(4:40)", "( UTC)", "(UTC )"])
def test_regex_itself_rejects_non_zone_shapes(self, brack):
    assert fleet._LIMIT_RESET_LOCAL_RE.search(f"resets 4:40am {brack}") is None
```

Verified: all five fail to match today, and all five null-park through the parser.

### ND-4 — nit: the guard probes a different zone than the tests it gates need

`_tzdata_available()` resolves `America/New_York`, but gates `TestParseLimitSignalLocalFormat` and
`TestParseLimitSignalHourValidation` (which need `Asia/Qyzylorda`) and
`TestParseLimitSignalSingleSegmentZone` (which needs `UTC`). On a full tzdb these are equivalent;
on a **partial** one — a slim container image shipping a zone subset — the guard and the need
diverge in both directions (a false skip, or a skip that fails to fire).
`[UNVERIFIED — no POSIX box]` for whether any real image ships such a subset; the divergence itself
is structural. One-line fix: resolve all three keys in the guard.

---

## R6. Ordinary failure classes — receipted negatives

**A fix at one call site and not its twin — did not fire.** Injection **J8** (swap the am/pm arms
inside the m4-restructured branch) fails **15 tests across both test files**, including four in
`tests/test_native.py` that reach the parser through `transcript_limit_scan`:

```
tests/test_native.py::TestLimitParkViaDiscriminator::test_idle_no_outcome_limit_transcript_parks_limited
tests/test_native.py::TestTranscriptLimitScan::test_synthetic_429_record_detected
tests/test_native.py::TestTranscriptLimitScanAnchoring::test_anchors_correctly_even_when_scanned_a_day_late
tests/test_native.py::TestTranscriptLimitScanAnchoring::test_anchors_to_message_instant_same_evening
+ 11 in tests/test_resilience.py
```

The production seam is covered, and the m4 restructure is behavior-preserving.

**3.10-floor break — did not fire.** `py -3.10 -m pytest tests/test_resilience.py -q` →
**`115 passed in 1.90s`** (was 111; +4 new). This specifically clears m5's `match=` assertions,
whose expected text is a CPython error message that could have differed across versions:
`match=r"missing 1 required keyword-only argument: 'now'"` holds on both 3.10 and 3.13. Nothing in
the wave uses 3.11+ syntax; `max(..., key=...)` and `datetime.replace(fold=…)` are both ≥3.6.

**Catastrophic backtracking — did not fire.** The widened group has no ambiguous nesting (the `/`
separator is absent from the first char class, so the split point is deterministic). Timed:

```
  len= 100016 unterminated-paren      5.10 ms
  len=  40016 A/A/A/... no-close      4.74 ms
```

Linear, and the parser's input is bounded by `_TAIL_READ_BYTES` regardless.

**A partial match that shifts a capture group — did not fire.** `[A-Za-z_+\-0-9]` excludes both
`)` and space, so the group cannot span a bracket boundary; `(UTC )`, `( UTC)`, `(see below)` and
`(your time)` all fail to match and null-park.

**A new dependency on non-stdlib data — did not fire in the shipped code.** `_tzdata_available()`
imports only stdlib `zoneinfo`. The *test suite's* reliance on the `tzdata` pip package is now
explicit and skip-guarded rather than a silent failure — that was the point of M2. See ND-1 for
the cost of that trade.

**Doctor regressions — none.** `fleet doctor` read-only, run by **me** at `706b94a`:

```
[PASS] supervisor-handoff: no handoff in flight, no aborted-handoff flag
[PASS] tzdata: zoneinfo resolves named zones (tz data present)
```

Still last, still PASS-note, still writes nothing. Moving the function definition (m7) did not move
its registration — confirmed in source (`bin/fleet.py:6226`, last entry) and by J7 going RED.

---

## R7. Injection table — 7 RED / 9 total, **2 GREEN**

Worktree content `706b94a`; one mutation at a time; full suite each time; every mutation reverted
with `git checkout 706b94a -- …`. Driver: `$CLAUDE_JOB_DIR/tmp/inject2.py`.

| # | Injection | Full-suite result | Verdict |
|---|---|---|---|
| J1 | unregister `_doctor_check_tzdata` from `cmd_doctor` **(pin proof C1)** | 1 failed, 1148 passed | 🔴 RED |
| J2 | remove the fold `max()`, return `candidate` as before **(pin proof M1)** | 1 failed, 1148 passed | 🔴 RED |
| J3 | revert the DQ1 regex widening (back to ≥1 `/`) | 1 failed, 1148 passed | 🔴 RED |
| **J4** | **over-widen the regex to `\(([^)]+)\)`** | **1149 passed, 6 skipped** | **🟢 GREEN → ND-3** |
| J5 | force `fold=1` unconditionally (the *literal* manager ruling) | 1 failed, 1148 passed | 🔴 RED — *the ruling itself* |
| J6 | flip `max()` → `min()` (take the earlier fold) | 2 failed, 1147 passed | 🔴 RED (both DST cases) |
| J7 | register the tzdata check FIRST instead of LAST | 1 failed, 1148 passed | 🔴 RED |
| J8 | swap the am/pm arms in the m4-restructured branch | 15 failed, 1134 passed | 🔴 RED (both files) |
| **J9** | **`_tzdata_available()` lies (returns False on a box with tz data)** | **1132 passed, 23 skipped** | **🟢 GREEN → ND-1** |

Both GREENs are reported at the severity of what they fail to protect: ND-1 (MAJOR — every
behavioral horizon test, including this wave's own), ND-3 (MINOR — the regex boundary, bounded
today by `ZoneInfo`'s own validation).

---

## R8. Scope, hygiene, probe context

**Scope.** 3 files: `bin/fleet.py`, `tests/test_resilience.py`, `tests/test_native.py`. The
`tests/test_native.py` touch is +5 lines inside `TestCmdDoctorRegistersNewChecks` — exactly the C1
fix I demanded, nothing else. No daemon, dispatch, supervisor-handoff or autoclean code touched;
`cmd_doctor`'s `check_calls` list is **unchanged** by this wave (the m7 move relocated only the
function definition), so the known shared hotspot took zero additional conflict surface.

**Hygiene.** All 9 injections plus the canary experiment reverted:

```
$ git checkout HEAD -- bin/fleet.py tests/test_resilience.py tests/test_native.py && git status --porcelain
(empty)
```

Final tree clean apart from this review file. Commit only; not pushed; no PR.

**Probe context (template v1.7).** I am `me-ul-review`, a `--bg` worker. **Every probe above was
run by me**, in `C:/proga/fleet-me-ul-review`, with the three files at `706b94a` content unless
stated otherwise. Not observable from here and therefore **not asserted**:

- **`[MANAGER-VERIFICATION REQUIRED]`** — behavior on a genuinely clean box. §R1/P2 is an
  import-blocker *simulation*, faithful in mechanism (`TZPATH: ()` on Windows means the pip package
  is the only tz-data source) but still a simulation.
- **`[MANAGER-VERIFICATION REQUIRED]`** — POSIX behavior of `_doctor_check_tzdata` and its
  Windows-only `py -3.13` remedy (m3, still open by design); and whether any real container image
  ships a partial tzdb (ND-4).
- **`[MANAGER-VERIFICATION REQUIRED]`** — `fleet doctor`'s exit code; I read piped output only.
- I ran no mutating `fleet`/`sup-*` verb, no `claude daemon`/`claude stop`, wrote nothing under
  `C:/Users/Techn/.claude/`, touched no scheduled task, and wrote to no worktree but my own
  (plus my own journal, as instructed).

---

## R9. Fix wave (ordered)

1. **ND-1 (MAJOR)** — add `TestTzdataGuardCanary` (§R3; written and proven). *Pin proof:* mutate
   `_tzdata_available()` to return `False` on this box; the suite must go RED instead of
   `1132 passed, 23 skipped`.
2. **ND-2 (MINOR, same wave)** — replace the "can never convert one into a *wrong* one" sentence at
   `bin/fleet.py:1121-1123` with the wording in §R4, and pin the known-late `(EST)` reading.
3. **ND-3 (MINOR, same wave)** — add the negative regex assertions in §R5 so the char-class
   boundary is pinned. *Pin proof:* J4 must go RED.
4. **ND-4 (nit)** — resolve all three needed keys in `_tzdata_available()`.
5. **Ratify** the M1 deviation (`max(fold=0, fold=1)` instead of the ruled `fold=1`); §R2 shows the
   literal ruling was a no-op after rollover and would have broken the gap case.
6. Still open by design, not ordered, not defects: m2 (seam), m3 (`py` remedy), m6 (`0am`).

Nothing here is structural. `ESCALATE` is not warranted: the wave closed all five of its targets,
broke no neighbour's behavior, and the one MAJOR it minted has a six-line fix that is already
written and verified.

---

`RE-REVIEW VERDICT: fix-wave(ND-1; ND-2 + ND-3 same wave)`


---
---

# FINAL GATE — wave 2 = `380c210`

**Reviewer:** fleet worker `me-ul-review` (`--bg`), worktree `C:/proga/fleet-me-ul-review`,
branch `me/ul-review`. **Under review:** `380c210` on `me/ul` (base `706b94a`), 2 files, +89/−8.
**Date:** 2026-07-21.

## FINAL GATE VERDICT: `ESCALATE`

**Wave 2 did its job.** All four targets closed, **9 RED / 9** on the re-run injection table (was
7/9), the skip list is provably identical to the branch base, 3.10 clean. Wave 2 minted nothing.

**I am escalating rather than filing a third finding list, because the recurrence is not in the
code — it is in the reasoning about DQ1, and one of the three people who got it wrong is me.**
The DQ1 widening's safety has now been asserted three times and been wrong three times:

1. the manager's DQ1 ruling — *"widening can only convert a null-park into a correct horizon,
   never a wrong one"*;
2. my own re-review §R4, which corrected (1) and then prescribed the replacement wording —
   *"Every such mismatch errs LATE … never into an EARLY one, which is the bar D4 actually set"*;
3. wave 2's comment, which implemented my prescription faithfully (`bin/fleet.py:1130-1141`).

**My §R4 wording is false**, and wave 2 baked it into the source. **20 of the 45** newly-admitted
single-segment keys can resolve **EARLY** relative to a geographic zone at the same standard
offset (§F4). Every round of this has narrowed the claim and every round has still overreached,
because the underlying premise — that "single-segment tzdb key" is a category with a uniform
safety direction — is wrong. It is a heterogeneous bag: geographic aliases (exact), fixed-offset
legacy keys (late-drifting), and rule-only zones that observe DST (early-drifting). No
one-directional guarantee over that set exists.

**The restructuring I would name:** stop trying to characterise the whole set and admit only the
subset with *zero* semantic ambiguity — a fixed-UTC allowlist,
`{UTC, UCT, Universal, Zulu, Greenwich, GMT0, GMT+0, GMT-0}`. **Validated** (§F4): it admits the
motivating case `(UTC)` that D4 actually asked about, every member is permanently UTC+0, and it
admits **zero** of the 20 early-capable keys. Bare `GMT` is deliberately excluded (a UK operator
writing "GMT" in July means BST — late-only, but excludable for free).

**Manager's decision, which is why this is an escalation and not a wave:** either

- **(A) merge as-is with the residual documented** — defensible. The harm needs a compound,
  never-observed condition (Claude Code emitting a bare DST-observing abbreviation *and* the
  operator being in a non-DST zone at that standard offset), is bounded at ≤1h, and is
  self-correcting (an early resume re-hits the wall and re-parks; no worker is lost, so standing
  goal 2 is not breached). **But the comment must be corrected first regardless** — shipping a
  source comment that asserts a guarantee three rounds have failed to establish is how the next
  maintainer widens this again.
- **(B) take the allowlist restructuring** — ~3 lines plus a test, and the one-directional
  guarantee becomes true by construction instead of by argument.

I recommend **(B)**, or **(A)** with the §F4 wording. What I will not do is write the same
finding a fourth time in slightly narrower language.

---

## F0. Disposition

| id | Disposition | Evidence |
|---|---|---|
| **ND-1** (MAJOR, silent-skip hazard) | **FIXED** | `TestTzdataGuardCanary` added verbatim from my §R3. **Key pin proof re-run:** J9 → `1 failed, 1137 passed, 24 skipped`, `FAILED …TestTzdataGuardCanary::test_guard_agrees_with_doctor_check`. Was `1132 passed, 23 skipped`, **green**. |
| **ND-2** (MINOR, false "never wrong") | **FIXED** — but the remedy minted **ND-5** | `bin/fleet.py:1119-1141`. The "resolves ⇒ correct" dichotomy is gone and the third case is named. The *replacement* guarantee is the new defect, and the wording was mine. |
| **ND-3** (MINOR, unpinned char class) | **FIXED** | `TestLimitResetLocalRegexBoundary`, 5 parametrizations, not `skipif`-guarded (needs no tz data). J4 (over-widen to `\(([^)]+)\)`) → **5 failed**, was fully green. |
| **ND-4** (nit, single-zone guard) | **FIXED** | `_tzdata_available()` now loops `("America/New_York", "Asia/Qyzylorda", "UTC")` — exactly the three the gated classes need. Interacts with ND-1's canary → **ND-6** (nit). |
| **M1 deviation** (`max(fold=…)` vs the ruled `fold=1`) | still **awaiting ratification** — J5 re-run confirms the literal ruling breaks the gap case. |
| m2, m3, m6 | **NOT-FIXED**, by design — filed optional, never ordered. |

**`SPURIOUS-FIX`: none.** Every wave-2 line traces to ND-1, ND-2, ND-3, ND-4, or the §R2
indentation nit (`bin/fleet.py:1224`, whitespace inside the `max(` call — no behavior change).
Nothing outside the ordered set was touched; `tests/test_native.py` is untouched by wave 2.

---

## F1. Baseline, and the skip audit the manager asked for

```
$ py -3.13 -m pytest tests/ -q
1156 passed, 6 skipped in 57.94s          # matches the manager-verified count
```

**Every one of the 6 skips justified by name**, and none of them a test that used to run:

```
$ py -3.13 -m pytest tests/ -q -rs
SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness

$ py -3.13 -m pytest tests/integration/test_native_pin.py --collect-only -q
tests/integration/test_native_pin.py::test_1_pin_dispatch_and_roster_contract
tests/integration/test_native_pin.py::test_2_pin_stop_hook_outcome
tests/integration/test_native_pin.py::test_3_pin_fork_steer
tests/integration/test_native_pin.py::test_4_pin_stop_no_hook_tombstone
tests/integration/test_native_pin.py::test_5_pin_archive_rm
tests/integration/test_native_pin.py::test_6_pin_record_pass
6 tests collected
```

All six are the pre-existing tier-3 live-integration gate (`FLEET_LIVE=1`), nothing to do with tz
data. **Identity confirmed against the branch base** — I checked out `ac3e34d`'s `tests/` and
`bin/fleet.py` into this worktree and re-ran:

```
ac3e34d:  SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: ...
          1136 passed, 6 skipped
380c210:  SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: ...
          1156 passed, 6 skipped
```

Same file, same reason, same six node IDs. **Zero tz-data skips; zero tests silently stopped
running across the whole branch.**

**One correction to the brief's premise, for the record.** The manager wrote *"the skip count is
back to the baseline 6, so ND-1's over-broad skip appears resolved"*. There was never an
over-broad skip on a normal run — `706b94a` also reported `1149 passed, 6 skipped`. The `23
skipped` figure appeared **only under injection J9**. ND-1 was never an active over-skip; it was
that **nothing pinned the guard**, so a future silent `False` would have been invisible. That is
what the canary fixes, and J9 is the only way to observe it. Verified rather than taken, as asked.

---

## F2. The 9-injection table, re-run — **9 RED / 9**, no exceptions

Worktree content `380c210`; one mutation at a time; full suite each time; each reverted with
`git checkout 380c210 -- …`. Driver: `$CLAUDE_JOB_DIR/tmp/inject3.py`.

| # | Injection | Full-suite result | vs wave 1 | Verdict |
|---|---|---|---|---|
| J1 | unregister `_doctor_check_tzdata` from `cmd_doctor` | 1 failed, 1155 passed | RED → RED | 🔴 |
| J2 | remove the fold `max()` | 1 failed, 1155 passed | RED → RED | 🔴 |
| J3 | revert the DQ1 regex widening | 2 failed, 1154 passed | RED → RED *(now catches 2)* | 🔴 |
| **J4** | **over-widen the regex to `\(([^)]+)\)`** | **5 failed, 1151 passed** | **GREEN → RED** | 🔴 **ND-3 closed** |
| J5 | force `fold=1` (the literal M1 ruling) | 1 failed, 1155 passed | RED → RED | 🔴 |
| J6 | flip `max()` → `min()` | 2 failed, 1154 passed | RED → RED | 🔴 |
| J7 | register the tzdata check FIRST not LAST | 1 failed, 1155 passed | RED → RED | 🔴 |
| J8 | swap the am/pm arms | 16 failed, 1140 passed | RED → RED *(15 → 16)* | 🔴 |
| **J9** | **`_tzdata_available()` lies** | **1 failed, 1137 passed, 24 skipped** | **GREEN → RED** | 🔴 **ND-1 closed** |

Failing test names for the two that flipped:

```
J4  TestLimitResetLocalRegexBoundary::test_regex_itself_rejects_non_zone_shapes[(local time)]
    …[(see below)]  …[(4:40)]  …[( UTC)]  …[(UTC )]
J9  TestTzdataGuardCanary::test_guard_agrees_with_doctor_check
```

Both of last round's GREENs are now RED. No named exceptions.

---

## F3. 3.10 floor

```
$ py -3.10 -m pytest tests/test_resilience.py -q
122 passed in 1.93s
```

Was 115 at `706b94a`, 111 at `4b8a88e`, and the +7 are exactly wave 2's additions (canary 1,
`(EST)` case 1, regex boundary 5). Nothing in wave 2 uses 3.11+ syntax.

---

## F4. ND-5 — the escalation: the corrected DQ1 guarantee is still false

**The claim**, `bin/fleet.py:1130-1141` (implementing my own §R4 prescription):

> ```
> # The bar that actually matters survives: every such mismatch is a
> # never-DST reading of what would be a daylight-time hour, which always
> # resolves LATE, never early (verified across all 45 newly-admitted
> # single-segment keys, both DST phases). ... but never into an EARLY one,
> # which is the bar D4 actually set.
> ```

**The manager asked: "does it now state the true guarantee — never early, may be late for a
fixed-offset alias?" No. It states a guarantee that does not hold.**

**Method.** For each of the 45 single-segment keys `K`, compare `_next_local_reset_utc(4,40,K)`
against `_next_local_reset_utc(4,40,G)` for **every** geographic zone `G` whose January (standard)
offset equals `K`'s — i.e. every zone `K` could plausibly abbreviate — across four anchors
spanning both DST phases and both transition seasons. Flag any instant where `K` resolves
**earlier** than `G`. 5600 comparisons.

```
  keys=45  comparisons=5600
  instants where a single-segment key resolves EARLIER than a same-standard-offset
  geographic zone: 903
  CLAIM 'always resolves LATE, never early' -> REFUTED
```

**The 20 offending keys** and an example counterpart each:

```
  CET       vs 16 zones, e.g. Africa/Algiers, Africa/Bangui, Africa/Brazzaville
  MET       vs 16 zones   |  EET      vs 18 zones (Africa/Cairo, …)
  WET       vs 26 zones   |  Poland   vs 16 zones
  Portugal  vs 26 zones   |  Eire / GB / GB-Eire vs 26 zones each (Africa/Abidjan, Accra, Bamako)
  Egypt     vs 17 zones   |  Israel   vs 18 zones
  Cuba      vs 16 zones   |  Navajo   vs 12 zones
  CST6CDT   vs 17 zones   |  EST5EDT  vs 16 zones   |  MST7MDT vs 12 zones   |  PST8PDT vs 2 zones
  Jamaica   vs 2 zones    |  Kwajalein vs 1 zone
  EST       vs 2 zones, e.g. Chile/EasterIsland, Pacific/Easter
```

Worked counterexample, straight through the shipped parser:

```
'(CET)'            -> 2026-07-16T02:40:00Z
'(Africa/Algiers)' -> 2026-07-16T03:40:00Z        # Algiers is CET-standard year-round, no DST
                                                  # the abbreviation resolves 1h EARLY
```

Note `EST` is on that list too — the very key wave 2's new test documents as "known late". It is
late against `America/New_York` and **early** against `Pacific/Easter`. My §R4 asserted `EST` was
late-only; that was wrong, and the new test
`test_fixed_offset_legacy_key_resolves_but_known_late` pins only the late half.

**Why one more finding list is the wrong response.** The error is the same each round: treating
"single-segment tzdb key" as a category with a uniform safety direction. It is three categories —
geographic aliases (exact), never-DST fixed offsets (late-drifting), rule-only zones that *do*
observe DST (early-drifting) — and `EST`-vs-`Pacific/Easter` shows even the second category flips
once the counterpart zone observes DST on the other side of the year. No wording will make a
one-directional claim true over that set.

**The restructuring, validated.** Restrict the single-segment branch to an explicit fixed-UTC
allowlist:

```
Under the proposed allowlist ['GMT+0','GMT-0','GMT0','Greenwich','UCT','UTC','Universal','Zulu']
  early-capable keys still admitted: NONE
  all allowlist keys permanent UTC+0?  True
  motivating case (UTC) still admitted? True
```

Every member means UTC and nothing else, in every season, so no colloquial-vs-tzdb divergence is
possible in either direction — the guarantee becomes structural rather than argued. It keeps the
whole of what D4 asked for (`"a bare (UTC) is plausible enough in a message to be worth a
follow-up"`) and discards only shapes nobody has ever observed.

**If instead the widening stays**, the comment must say what is actually true:

> Widening admits 45 single-segment IANA keys. Most are aliases of geographic zones and resolve
> exactly. The remainder — legacy fixed-offset keys (`EST`, `MST`, `GMT`, …) and rule-only zones
> that observe DST (`CET`, `MET`, `EET`, `WET`, `EST5EDT`, …) — can diverge from what the message
> meant by up to the zone's DST delta (≤1h in every current tzdb zone), **in either direction**:
> late when a never-DST key stands in for a DST-observing zone, early when a DST-observing key
> stands in for a zone that is fixed at that standard offset (`CET` vs `Africa/Algiers`; `EST` vs
> `Pacific/Easter`). 20 of the 45 keys are early-capable. This is a bounded, self-correcting
> error — an early resume re-hits the wall and re-parks — not a lost worker, but it is NOT the
> one-directional guarantee earlier revisions of this comment claimed.

**Tests that must pin it:** the `(CET)` vs `(Africa/Algiers)` pair (early direction), alongside the
existing `(EST)` vs `(America/New_York)` pair (late direction). If the allowlist is taken instead:
assert `(CET)`, `(EST)` and `(Singapore)` all null-park while `(UTC)` and `(Zulu)` resolve.

### ND-6 — nit: ND-1's canary and ND-4's widened guard disagree on a partial tzdb

The canary asserts `_tzdata_available() == ("resolves named zones" in msg)`. After ND-4,
`_tzdata_available()` probes **three** zones while `_doctor_check_tzdata()` probes **one**
(`Asia/Qyzylorda`). On a tzdb subset holding Qyzylorda but not one of the others they diverge and
the canary **fails on a legitimate environment** — the M2 failure mode, reintroduced one call site
away by the ND-4 remedy. Repro:

```
  full tzdb (this host)                        guard=True  doctor=True  canary PASSES
  no tz data at all (the realistic clean box)  guard=False doctor=False canary PASSES
  partial: Asia/Qyzylorda MISSING              guard=False doctor=False canary PASSES
  partial: America/New_York MISSING            guard=False doctor=True  canary FAILS  <-- DIVERGENCE
  partial: UTC MISSING                         guard=False doctor=True  canary FAILS  <-- DIVERGENCE
```

**nit, not a finding-with-teeth**, and I am explicit about why: the trigger needs a tzdb subset
containing `Asia/Qyzylorda` but omitting `America/New_York` or `UTC`. No real subset ships the
obscure zone and drops the common ones. `[UNVERIFIED — no POSIX box]` that no such image exists;
the logical divergence itself is proven above.

**Exact fix, verified to keep ND-1's teeth** — compare the guard against an independent
recomputation over the *same* zone set, and keep the doctor cross-check as a one-way implication:

```python
    def test_guard_agrees_with_independent_recomputation(self):
        import zoneinfo
        def resolves(z):
            try:
                zoneinfo.ZoneInfo(z); return True
            except Exception:
                return False
        assert _tzdata_available() == all(
            resolves(z) for z in ("America/New_York", "Asia/Qyzylorda", "UTC"))

    def test_doctor_check_agrees_when_all_needed_zones_resolve(self):
        _name, _ok, msg = fleet._doctor_check_tzdata()
        if _tzdata_available():
            assert "resolves named zones" in msg
```

Proof it does not weaken ND-1:

```
A. ND-6 canary variant, guard HONEST -> 123 passed in 2.83s
B. ND-6 canary variant, guard LYING  -> 1 failed, 104 passed, 18 skipped
      tests/test_resilience.py::TestTzdataGuardCanary::test_guard_agrees_with_independent_recomputation
   still catches ND-1 (the J9 lie)?  YES
C. restored -> 122 passed in 1.51s
```

---

## F5. Third-pass hunt — what did NOT fire

**The narrowed skip guard.** `_tzdata_available()`'s three-zone loop is correct and the `skipif`
set is unchanged in extent (§F1: zero tz skips on a box with tz data; the guard's own canary is
deliberately ungated). Its only flaw is ND-6.

**The regex character-class boundary — no new hole.** Beyond the 5 shapes the new
`TestLimitResetLocalRegexBoundary` pins, I probed 11 neighbours. Everything null-parks:

```
  '(local time)' no match     '(UTC/)'  no match     '(UTC-)'  MATCH 'UTC-'    horizon=None
  '(see below)'  no match     '(/UTC)'  no match     '(UTC+)'  MATCH 'UTC+'    horizon=None
  '(4:40)'       no match     '(UTC.)'  no match     '(A/B/C/D)' MATCH         horizon=None
  '( UTC)'       no match     '(-UTC)'  no match     '(a)'     MATCH 'a'       horizon=None
  '(UTC )'       no match     '(UTC\tX)' no match    '()'      no match
  '(Etc/GMT+5)'  MATCH 'Etc/GMT+5'  horizon=2026-07-16T09:40:00Z   (pre-existing, multi-segment)
```

`(UTC-)` / `(UTC+)` do match the char class (trailing `+`/`-` are admitted) — cosmetic only, both
null-park at `ZoneInfo`. Worth a one-character tightening some day; not a defect.

**Anything the ND-3 boundary test touches.** The class is module-level, not `skipif`-guarded, and
asserts against the compiled pattern with no `ZoneInfo` call — so it runs on a clean box too,
which is the right call. J3 (narrowing the regex) still goes RED via a different class, so the
boundary test cannot mask a narrowing regression.

**The corrected DQ1 comment** — see ND-5. This is the one that fired.

**The `max(fold=…)` indentation change at `bin/fleet.py:1224`** is whitespace inside a call
argument list; J2/J5/J6 all still land on the same tests with the same counts as last round, so
no behavior moved.

**Doctor** — unchanged by wave 2; `cmd_doctor`'s `check_calls` untouched, J1/J7 both RED.

---

## F6. Scope, hygiene, probe context

**Scope.** 2 files (`bin/fleet.py`, `tests/test_resilience.py`). No daemon, dispatch,
supervisor-handoff or autoclean code; `cmd_doctor`'s `check_calls` untouched; `tests/test_native.py`
untouched. Across the whole branch (`ac3e34d..380c210`): 3 files, and the `test_native.py` touch is
the +5-line C1 fix only.

**Hygiene.** All 9 injections, the base-comparison checkout, and the canary-variant experiment
reverted:

```
$ git checkout HEAD -- bin/fleet.py tests/test_resilience.py tests/test_native.py && git status --porcelain
(empty)
```

Final tree clean apart from this review file. Commit only; not pushed; no PR.

**Probe context (template v1.7).** I am `me-ul-review`, a `--bg` worker. **Every probe above was
run by me**, in `C:/proga/fleet-me-ul-review`, with the files at `380c210` content unless stated.
Not observable from here, therefore **not asserted**:

- **`[MANAGER-VERIFICATION REQUIRED]`** — behavior on a genuinely clean box and on a partial tzdb;
  §F4/ND-6 use `ZoneInfo`-level simulations, faithful in mechanism but simulations.
- **`[MANAGER-VERIFICATION REQUIRED]`** — POSIX behavior of `_doctor_check_tzdata` and its
  Windows-only `py -3.13` remedy (m3, still open by design).
- **`[MANAGER-VERIFICATION REQUIRED]`** — whether Claude Code's rate-limit message can ever emit a
  bare single-segment zone abbreviation. The only observed sample is a full `Area/City` name. This
  is the fact that decides whether ND-5 is theoretical or live; I cannot observe it.
- I ran no mutating `fleet`/`sup-*` verb, no `claude daemon`/`claude stop`, wrote nothing under
  `C:/Users/Techn/.claude/`, touched no scheduled task, and wrote to no worktree but my own
  (plus my own journal, as instructed).

---

## F7. What the manager has to decide

1. **ND-5** — take the fixed-UTC allowlist (§F4, validated), or keep the widening and ship the
   corrected wording in §F4. **The current comment cannot ship as written.** Everything else on
   this branch is merge-ready.
2. **ND-6** — one-nit test swap (§F4, verified), or accept as documented residual.
3. **Ratify** the M1 deviation (`max(fold=0, fold=1)` rather than the ruled `fold=1`); J5 re-run
   again confirms the literal ruling breaks the gap case.
4. Still open by design, not defects: m2 (seam), m3 (`py` remedy), m6 (`0am`).

Everything wave 2 was asked to close is closed, and closed hard: 9/9 RED, six justified skips
identical to base, 122 on the floor. The branch is one comment away from mergeable and one
allowlist away from provably correct.

---

`FINAL GATE VERDICT: ESCALATE — ND-5 is doctrinal, not another finding. Restructuring named and
validated in §F4; merge-as-is-with-residual is defensible only with the corrected wording.`
