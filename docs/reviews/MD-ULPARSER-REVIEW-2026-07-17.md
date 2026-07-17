# Review — `md/ulparser` (UL local-format horizon parser)

**Diff:** `c1277bd..md/ulparser` — one commit, `3d55b51` *fix(limits): parse local-format UL reset times into ISO-UTC horizon*
**Reviewer:** `md-ulparser-review` (fleet worker) · **Date:** 2026-07-17
**Lenses:** (a) spec conformance — G11 contract + task-brief §Required behavior; (b) BREAK — construct timelines yielding a WRONG horizon rather than None.
**Suite:** full `pytest -q` → **1063 passed, 6 skipped** (see §7).

---

## VERDICT: `fix-wave(C1 blocking; D5 + D6 same wave; D1/D2/D3/D4 follow-ups)`

The core arithmetic is **right** — I corroborated it against the real production timeline and
it predicts the actual reset instant to the minute (§5.1). The gap it closes is **real**, not
spurious (§6). But the diff anchors "next occurrence" to the **wall clock at parse time**
instead of to the **timestamp of the message being parsed**. On the exact production timeline
this feature exists to serve — the overnight park documented in `knowledge/lessons.md:607` —
that yields a confidently **wrong horizon, 24 hours late**, which is strictly worse than the
null it replaced. The brief's own standard ("a wrong horizon is worse than a null one …
delays a resume by hours") makes this blocking.

The irony worth stating plainly: **the diff built the exact seam the fix needs** (`now=`,
keyword-only) and documented it as *"never passed by any existing call site"* — then left it
unwired in production. C1 is ~2 lines at one call site.

| Class | Count | IDs |
|---|---|---|
| CONFIRMED-BUG | 1 | C1 |
| DESIGN-QUESTION | 6 | D1–D6 |
| OK (attacks that failed) | 8 | §5 |

**tz on this machine: RESOLVES — but by accident.** See D1. The fix is not dead weight today.

---

## 1. C1 — CONFIRMED-BUG (blocking): horizon anchored to parse time, not message time

**Receipts (all `# at 3d55b51`):**
- `bin/fleet.py:1127-1131` — `moment = (now if now is not None else datetime.now(timezone.utc)).astimezone(tz)`; `candidate = moment.replace(hour=..., minute=...)`; `if candidate < moment: candidate += timedelta(days=1)`
- `bin/fleet.py:1316` — the **sole production call site**: `reset_at, kind = _parse_limit_signal("\n".join(parts))` — no `now=`.
- `bin/fleet.py:1367` — `_NATIVE_STICKY = ("dead", "over_budget", "over_ceiling", "limited", ...)`; early-return `bin/fleet.py:1468`.
- `bin/fleet.py:1147-1151` (docstring, this diff) — *"`now` is an optional keyword-only override (real clock when omitted) … it is never passed by any existing call site."*

**Mechanism.** `_parse_limit_signal` computes the next occurrence of the quoted wall-clock time
*relative to the instant the parse runs*. The text it parses is a **historical transcript
record** (`transcript_limit_scan` walks the tail newest-first). Parse time ≠ message time. Once
the quoted reset has already passed at parse time, `candidate < moment` fires and rolls the
horizon forward a full day.

Because `limited` is **sticky**, the first park is the *only* parse — the record is never
re-derived, so a wrong horizon written once is never self-corrected. (Stickiness does close
the re-parse-drift attack I opened with — that one is OK. It converts it into this sharper one.)

**Repro — the M-C overnight-park timeline (`lessons.md:607`, *"resumed past midnight"*), RUN:**

```
Worker hits limit 2026-07-16 22:00 local. Message: "resets 4:40am (Asia/Qyzylorda)".
TRUE reset instant                             : 2026-07-16T23:40:00Z

recompute PROMPT   (22:05 local, same evening) -> horizon=2026-07-16T23:40:00Z  OK
recompute at 04:39 local (1min early)          -> horizon=2026-07-16T23:40:00Z  OK
recompute at 04:41 local (1min LATE)           -> horizon=2026-07-17T23:40:00Z  WRONG by +1 day
recompute 09:00 local (operator's morning)     -> horizon=2026-07-17T23:40:00Z  WRONG by +1 day
```

**Consequence at 09:00 local, the operator's morning:**

```
parsed-late horizon : 2026-07-17T23:40:00Z
limit already reset?: True   (true reset was 2026-07-16T23:40:00Z)
_limit_reset_passed({'limit_reset_at': '2026-07-17T23:40:00Z'}) -> False
=> worker RESUME-INELIGIBLE for another 19:40:00
```

- **Pre-diff:** `reset_at=None` → null-horizon park → `resume-limited --force-now` → resumes **immediately**.
- **Post-diff:** confident wrong horizon 24h out → `resume-limited` refuses; `--force-now` is still
  the escape hatch, but the feature's whole purpose was to remove the `--force-now` dependence.
  It now *creates* a case that needs it **and** hides the need behind a plausible-looking timestamp.

**A 1-minute-late scan is enough.** The trigger window isn't exotic: it's any recompute that
first observes the park after the quoted reset — a manager asleep overnight, the first
`fleet status` of the morning, or a host restart (the M-C campaign logged **2 host process
deaths**, `lessons.md:607`).

**The correct anchor exists and is unused.** Real transcript records carry `timestamp` —
`spike/m0/VERDICTS.md:441,443,445`: `"isMeta":true,"timestamp":"2026-07-13T23:48:10.741Z"`.
`transcript_limit_scan` already holds that `rec` dict when it reads `rec.get("message")`
(`bin/fleet.py:1313-1316`).

**Suggested fix (fleet.py:1316):**

```python
reset_at, kind = _parse_limit_signal("\n".join(parts), now=_record_time(rec))
```

…where `_record_time` parses `rec.get("timestamp")` and returns `None` on absence/garbage
(preserving today's wall-clock behavior as the fallback).

> ⚠️ **Do not reach for `_parse_iso` here.** It is `strptime(..., "%Y-%m-%dT%H:%M:%SZ")`
> (`bin/fleet.py:709`) and **rejects the fractional-second form transcripts actually emit**.
> Verified: `_parse_iso("2026-07-13T22:32:01.933Z")` → `ValueError: time data
> '2026-07-13T22:32:01.933Z' does not match format '%Y-%m-%dT%H:%M:%SZ'`. Use
> `datetime.fromisoformat` (Python 3.11+ accepts the trailing `Z`) inside a try/except.

Semantics to pin in the fix wave: the horizon should be the **first occurrence at-or-after the
message instant** — not "next from now". Anchored that way, every row of the repro above
returns the correct `2026-07-16T23:40:00Z`.

---

## 2. Findings table

| ID | Class | Finding | Receipt |
|---|---|---|---|
| **C1** | **CONFIRMED-BUG** | Horizon anchored to parse time, not message time → +24h wrong horizon on late scan. Blocking. | fleet.py:1127-1131, :1316, :1367, :1468 |
| D1 | DESIGN-QUESTION | tz-data resolves here only via an **incidental** pip `tzdata` pulled by `pandas` for an unrelated project. Unpinned. | `pip show tzdata` → `Required-by: pandas`; `zoneinfo.TZPATH == ()` |
| D2 | DESIGN-QUESTION | No 1..12 hour validation: `"resets 13am"` → 1pm silently (wrong horizon, not None). | fleet.py:1104-1107, :1159-1165 |
| D3 | DESIGN-QUESTION | DST: `replace()` inherits `fold`; gap times resolve via pre-transition offset. Errs ≤1h **late**. | fleet.py:1129 |
| D4 | DESIGN-QUESTION | tz regex requires ≥1 `/` → `"(UTC)"`, `Singapore`, `EST5EDT` can't match → null park (safe gap). | fleet.py:1104-1107 |
| D5 | DESIGN-QUESTION | Caller's contract docstring left **stale** — still states the behavior this diff removed. | fleet.py:1258-1262 |
| D6 | DESIGN-QUESTION | `test_native` assertions weakened to shape-only against the **real clock** → structurally cannot catch C1. | test_native.py:1779, :1428 |

---

## 3. D1 — tz-data on THIS machine (the brief's gating question)

**Answer: RESOLVES.** The fix is **not** dead weight today. Verbatim, `py -3.13` on this host:

```
py 3.13.12 (tags/v3.13.12:1cbe481, Feb  3 2026, 18:22:25) [MSC v.1944 64 bit (AMD64)]
tzdata pip pkg installed: True
TZPATH: ()
OK   Asia/Qyzylorda -> Asia/Qyzylorda
OK   America/New_York, UTC, Etc/GMT+5, America/Argentina/Buenos_Aires
available_timezones count: 598
```

**But the qualifier is load-bearing.** `TZPATH: ()` is empty — Windows ships no system tz
database, so `zoneinfo` is resolving **entirely** through the pip `tzdata` package. And:

```
Name: tzdata   Version: 2026.2
Required-by: pandas
```

`pandas` is not a claude-fleet dependency. It is installed globally for
`C:\proga\polymarket_experimenting` (`pmbot`). claude-fleet ships **no** `requirements.txt`,
`pyproject.toml`, or `setup.py` (checked — none exist) and CLAUDE.md pins it stdlib-only.

So the feature works on this host **by coincidence of an unrelated project's transitive
dependency**. `pip uninstall pandas`, a clean Windows box, or a venv → `ZoneInfoNotFoundError`
→ `None` → silent null-horizon park, i.e. the exact pre-diff behavior, with no operator signal
that the feature quietly stopped working.

The failure is **conservative** (null, never a guessed offset) — the helper's design is right
and its docstring anticipates exactly this. The open question is only that nothing *pins* it.
Options for the wave: declare `tzdata` a real dependency (breaks stdlib-only), add a
`fleet doctor` check that reports tz-data presence, or accept-and-document. **Recommend the
doctor check** — cheapest, keeps stdlib-only, and converts a silent degradation into a visible one.

---

## 4. D2–D6, briefly

**D2 — garbage hours.** The regex admits `\d{1,2}` and the am-branch (`hour24 = 0 if hour == 12
else hour`) never range-checks 1..12. Run:

```
resets 13am  -> ('2026-07-18T08:00:00Z', None)   # silently parsed as 1pm — WRONG, not None
resets 0am   -> ('2026-07-17T19:00:00Z', None)   # accepted as 00:00
resets 13pm  -> (None, None)                     # 13+12=25 -> ValueError -> None (safe BY ACCIDENT)
resets 99pm  -> (None, None)                     # same accident
```

`13pm`/`99pm` are safe only because `replace(hour=25)` happens to raise into the blanket
`except`. `13am` produces a well-formed lie. Low real-world likelihood (the API is unlikely to
emit `13am`), but it's the wrong-horizon class the brief targets, and the guard is one `if not
1 <= hour <= 12: return None`. Minutes are fine: `4:60am`/`4:99am` → `None`.

**D3 — DST.** `moment.replace(...)` inherits `moment`'s `fold`, and nonexistent spring-forward
times resolve via the pre-transition offset rather than being rejected. Run against
America/New_York:

```
2:30am NY on 2026-03-08 (time does not exist) -> 2026-03-08T07:30:00Z   # == 3:30am EDT
1:30am NY 2026-11-01, now=00:30 EDT (fold=0)  -> 2026-11-01T05:30:00Z
1:30am NY 2026-11-01, now=01:30 EST (fold=1)  -> 2026-11-01T06:30:00Z   # fold inherited from `now`
```

No crash; error bounded at ≤1h and in the **late** (safer) direction. `Asia/Qyzylorda` has no
DST, so production is unaffected **today** — but `_next_local_reset_utc` is generic and the tz
comes from untrusted message text. Documenting the fold semantics is enough; not blocking.

**D4 — tz-name regex.** `[A-Za-z_]+(?:/[A-Za-z_+\-0-9]+)+` requires at least one `/`. So
`"resets 4:40am (UTC)"` → `(None, None)`. Single-segment zones (`UTC`, `Singapore`, `Japan`)
and `EST5EDT`-style names can never match. Fails **safe** (null park), and a bare `(UTC)` is
plausible enough in a message to be worth a follow-up. Not blocking.

**D5 — stale caller contract.** `bin/fleet.py:1258-1262` still reads:

> *"the observed real signal carries a LOCAL-format time, not ISO, so reset_at is usually None
> (park with an unknown horizon; `resume-limited --force-now` is the realistic recovery)"*

That is precisely the behavior `3d55b51` removed. The diff updated `_parse_limit_signal`'s own
docstring and the plan doc but not its caller's contract paragraph — the one a maintainer reads
at the call site. (Same stale claim survives at
`docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md:1068`, though that's a historical
plan and arguably should stay frozen.) Fix in the same wave as C1 — C1 edits that call site anyway.

**D6 — weakened tests.** The two assertions that previously pinned the null horizon:

```python
# test_native.py:1779 (was: assert out["limit_reset_at"] is None)
assert fleet._LIMIT_RESET_RE.fullmatch(out["limit_reset_at"])
# test_native.py:1428-ish (was: assert reset_at is None)
assert fleet._LIMIT_RESET_RE.fullmatch(reset_at)
```

These now assert **shape only**, against the **real wall clock** (no frozen `now`). A horizon
that is 24h wrong — C1's exact output — is still a well-formed `...Z` string and passes. They
do catch `None` (`fullmatch(None)` raises `TypeError`), so they aren't vacuous, but they cannot
regress-guard the one bug that matters. The comment redirects exact-instant coverage to
`TestParseLimitSignalLocalFormat`, which is fair — but that class only ever passes a frozen
`now` **directly** to `_parse_limit_signal`, so no test anywhere exercises the
`transcript_limit_scan` → parser path with a controlled clock. That's the seam C1 lives in, and
it is untested by construction. The C1 fix should land with a test that freezes `now` *and*
goes through `transcript_limit_scan`.

---

## 5. OK — attacks that FAILED (receipted)

Recorded so the fix wave doesn't re-litigate them.

**5.1 The arithmetic is corroborated against real production evidence.** The strongest
positive result here. From the G7 capture (`spike/m0/VERDICTS.md:431`, verbatim record 201;
timeline at `:434`):

```
429 hit at (real)      : 2026-07-13 22:32:01.933+00:00   # timeline.jsonl state -> blocked
session alive again at : 2026-07-13 23:48:10.741+00:00   # next transcript record
parser anchored at 429 : 2026-07-13T23:40:00Z            # <- prediction of the real reset
=> real resume happened 0:08:10.741 after predicted horizon. ARITHMETIC CORROBORATED.
```

The parser, anchored at the message instant, predicts the true reset to the minute — the
session came back 8 minutes later. The 12-hour table, the tz conversion, and the roll-forward
are all **correct**. C1 is purely an *anchoring* defect, not a math defect. (And this same
evidence is C1's proof: re-parse that identical message 20 minutes late and you get
`2026-07-14T23:40:00Z` — 24h out.)

**5.2 "will reset at" hypothesis — REFUTED.** I expected the regex's hard-required literal
`resets\s+` to miss a real message phrased *"Your limit will reset at 4:40am"*, which would
have made the whole fix a no-op in production. The verbatim capture at
`spike/m0/VERDICTS.md:431` settles it: `"You've hit your session limit — resets 4:40am
(Asia/Qyzylorda)"`. The token `resets` is real, and the em-dash before it is absorbed by the
un-anchored `search`. **The regex matches the real signal.** Attack failed; parser is right.

**5.3 `Etc/GMT+5` semantic inversion — handled correctly.** The classic trap (POSIX `Etc/GMT+5`
is UTC**−**5) is `zoneinfo`'s to handle, and it does: `resets 4:40am (Etc/GMT+5)` →
`2026-07-18T09:40:00Z` = 04:40 at UTC−5 ✓. `Etc/GMT-5` → `2026-07-17T23:40:00Z` = UTC+5 ✓.
No sign bug. The regex's `[A-Za-z_+\-0-9]+` correctly admits both.

**5.4 Three-segment IANA names match.** `America/Argentina/Buenos_Aires` →
`2026-07-18T07:40:00Z` ✓. Also OK: `Asia/Ho_Chi_Minh` (underscore), `America/Port-au-Prince`
(hyphens), `Pacific/Chatham` (:45 offset → `15:55:00Z` ✓). `Bogus/Nowhere` → `None` ✓.

**5.5 Minute validation.** `4:60am` → `None`; `4:99am` → `None`; `4:0am` → `None` (single-digit
minute unmatched); `4:00am` → correct. Safe.

**5.6 ISO precedence holds.** `"resets 4:40am (Asia/Qyzylorda) or 2026-07-18T09:00:00Z"` →
`2026-07-18T09:00:00Z`. The local branch is in an `else` on the ISO match (`fleet.py:1153-1157`) —
existing consumers cannot regress. Multiple local `resets` → first match wins (`search`),
deterministic. Kind keywords compose independently (`weekly` + local → `('...', 'weekly')`) ✓.

**5.7 Signature change is safe.** Grep-receipt, all `_parse_limit_signal(` at `3d55b51`:
`bin/fleet.py:1136` (def) and `bin/fleet.py:1316` (sole production call, positional text only) —
plus test call sites `tests/test_resilience.py:569,573,577,589,628,636`. `now` is
**keyword-only** (`*,`) with a `None` default, so no positional-arity break is possible. ✓
(This is also C1's root cause: the seam is production-dead.)

**5.8 Re-parse drift — blocked by stickiness.** I attacked the idea that repeated recomputes
would re-derive a drifting horizon. `limited ∈ _NATIVE_STICKY` (`fleet.py:1367`) with an
early-return at `:1468`, so a parked record is never re-parsed. Attack failed — but it
sharpened into C1: stickiness means the single first parse is *permanent*.

---

## 6. SPURIOUS-FIX check

**Not spurious.** The gap is documented from production, twice, independently:

- `knowledge/lessons.md:607` — *"Gap found: 'resets 12am (Asia/Qyzylorda)' horizon format unparsed → null-horizon park needing --force-now; scanner needs that format."*
- `supervisor/JOURNAL.md:100` — same gap, logged as a G11 item.
- `docs/NEXT-SESSION.md:19` — queued as the intended next task.

And the pre-diff design explicitly *expected* the null
(`docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md:1068`: *"reset_at will usually be
None ⇒ park with null horizon, `resume-limited --force-now` is the realistic resume path"*), so
this diff is a sanctioned change to a stated assumption (M-D item 3), not invented work. The
`12am` hour-only form — the literal production string — is covered
(`test_resilience.py` param 2). Nothing in the diff fixes something that was never broken.

One scope note, not a finding: `docs/PLAN-PROGRESS.md` loses 5 lines in this diff. Consistent
with closing the item; flagged only for the record.

---

## 7. Spec conformance (lens a)

| Contract | Status |
|---|---|
| G11: `reset_at` is ISO-UTC string **or** `None` | ✅ `strftime("%Y-%m-%dT%H:%M:%SZ")` (fleet.py:1132), else `None`. `_LIMIT_RESET_RE.fullmatch` passes on output — round-trips through `_parse_iso`. |
| `_limit_reset_passed` consumer unchanged | ✅ Not touched by the diff; still null → `False`. |
| Null-horizon park stays the conservative default | ✅ Every failure path (unknown tz, missing tz-data, bad hour/minute, no match) → `None`. Never a guessed offset. |
| Kind detection unchanged | ✅ Untouched; composes independently. |
| ISO precedence over local | ✅ §5.6. |
| stdlib-only (CLAUDE.md) | ⚠️ Code yes (`zoneinfo` is stdlib; imported inside the helper so `import fleet` gains no hard tz-data dep — good call). **Data** no: see D1. |
| Task-brief §Required behavior: 12am/12pm normalized; next occurrence; tz-resolution failure → None | ✅ all three, modulo C1's anchor. |
| Never swallow a genuine crash as a park | ✅ Structured 429 gate (`fleet.py:1313`) untouched. |

**Conformant in every letter of the contract.** C1 is not a contract violation — `reset_at` is a
well-formed ISO-UTC string exactly as G11 requires. It is a **correctness** defect *inside* the
contract, which is precisely why the type-shaped tests (D6) can't see it and why the brief asked
for the BREAK lens.

**Test suite:** `pytest tests/test_resilience.py tests/test_native.py -q` → **468 passed** (15.53s).
Full suite `pytest -q` → **1063 passed, 6 skipped** (55.95s).
`.pytest_cache/v/cache/lastfailed` carries 4 stale entries from a
mid-development run — all pass now; noted so nobody mistakes the cache for a live failure.

---

## 8. Recommended wave

1. **C1** (blocking) — anchor the parse to `rec["timestamp"]` at `fleet.py:1316`; semantics =
   first occurrence at-or-after the message instant; `datetime.fromisoformat`, **not**
   `_parse_iso` (fractional seconds). Land with a frozen-clock test **through**
   `transcript_limit_scan`.
2. **D5** — refresh the stale contract paragraph at `fleet.py:1258-1262` (same call site as C1).
3. **D6** — restore exact-instant assertions on a frozen clock; keep shape-only checks only
   where the real clock is genuinely unavoidable.
4. **D2** — `if not 1 <= hour <= 12: return None`.
5. **D1** (follow-up) — `fleet doctor` tz-data check; make the silent degradation visible.
6. **D3 / D4** (follow-up) — document fold/gap semantics; consider admitting single-segment zones.

Per the M-C standard (*"fix waves minted new defects in 3 of 5 waves"*, `lessons.md:607`), the
C1 fix wants the new-defect-hunt re-review — the anchor change moves the horizon for **every**
parked worker, and the `--force-now` path must keep working when `timestamp` is absent or malformed.

---
---

# RE-REVIEW — fix wave `ee68eb6` (2026-07-17)

**Diff:** `19173ad..ee68eb6` — *fix(limits): anchor UL reset horizon to transcript record timestamp, not parse time*
**Scope:** verify C1 / D5 / D6 + mandatory new-defect hunt on the new code.
**Suite:** full `pytest -q` → **1068 passed, 6 skipped** (58.37s; was 1063+6 — the wave adds 5 tests, none removed).

## RE-REVIEW VERDICT: `fix-wave(N2 blocking; N1 + N3 same wave)`

**All three ordered findings are genuinely fixed** — C1's anchor is real, correct, and
corroborated; this is not a paper fix. But the hunt turned up a **new defect that silently
reverts C1 on a documented-supported platform** (N2), which is exactly the failure mode the
wave was warned about. It is a one-line fix.

| Finding | Verdict |
|---|---|
| **C1** — horizon anchored to parse time | ✅ **FIXED** |
| **D5** — stale caller contract docstring | ✅ **FIXED** |
| **D6** — tests can't catch C1 | ✅ **FIXED** |
| **N1** — canonical fixture lacks the field the fix depends on; comment asserts a falsehood about the real record | 🆕 DESIGN-QUESTION |
| **N2** — `fromisoformat("…Z")` is **3.11+**; violates the documented 3.10+ floor → **C1 silently reverts on 3.10** | 🆕 **CONFIRMED-BUG (blocking)** |
| **N3** — bad-timestamp fallback reproduces C1's wrong horizon rather than a null park | 🆕 DESIGN-QUESTION |
| SPURIOUS-FIX check on the wave | ✅ None — every line traces to an ordered finding |

---

## 1. C1 — **FIXED**

**Receipts (`# at ee68eb6`):** `bin/fleet.py:1243-1260` (`_record_time`), `bin/fleet.py:1345`
(`_parse_limit_signal("\n".join(parts), now=_record_time(rec))`).

The §1 repro, re-run against the fixed code:

```
Message fired 2026-07-16 22:00 local (17:00Z). TRUE reset = 2026-07-16T23:40:00Z
anchored horizon = 2026-07-16T23:40:00Z  OK
  ^ same answer no matter when the scan runs -- `now` is not consulted at all.

=== the real G7 case ===
429 at 22:32:01.933Z -> horizon 2026-07-13T23:40:00Z  OK (== corroborated 23:40Z same-day)
```

**The overnight 23:40Z case now produces 23:40Z same-day, as mandated.** The defect is
eliminated at the root rather than papered over: because the horizon is a pure function of the
message instant, the entire class of "when did the scan run" bugs is gone — the 04:41-local and
09:00-local rows that were `WRONG by +1 day` in the original review are now structurally
impossible, not merely tested-against.

**The wave took the review's `_parse_iso` warning.** `_record_time` uses
`datetime.fromisoformat`, not `_parse_iso` — so the fractional-second trap (`…:01.933Z`) that
would have made this fix a silent no-op was avoided. Good. (But see N2: `fromisoformat` carries
its own version trap the wave did not clear.)

**Verified the anchor is genuinely load-bearing, not decorative.** `_record_time` is only
consulted at the limit branch (`:1345`), so there is no per-record cost on the tail walk.

## 2. D5 — **FIXED**

`bin/fleet.py:1277-1292` — the stale paragraph is gone, replaced with an accurate account that
also records *why* (stickiness + the 24h roll). Grep-receipt for the stale claim across live
code and specs:

```
grep -rn "usually None|realistic recovery|realistic resume path" bin/ docs/   # excl. docs/reviews, docs/superpowers/plans
(no hits)
```

Only the historical plan doc (`docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md:1068`)
still carries the old claim, which is correct — it's a frozen historical record, as the original
review noted.

## 3. D6 — **FIXED**

`tests/test_native.py` gains `TestTranscriptLimitScanAnchoring` (4 tests) plus
`test_idle_no_outcome_limit_transcript_anchors_to_record_timestamp`.

**Yes — the e2e test is genuinely end-to-end, and I checked this specifically.** It is not a
`_parse_limit_signal` unit test wearing an e2e costume:

- `test_anchors_to_message_instant_same_evening` writes a real transcript file and calls
  `fleet.transcript_limit_scan(SID, transcript_path=t)`, asserting the exact
  `"2026-07-13T23:40:00Z"` — the full scan path.
- `test_idle_no_outcome_limit_transcript_anchors_to_record_timestamp` goes one layer further
  out, through `fleet.recompute_worker_native(...)` — the actual discriminator — asserting
  `out["limit_reset_at"] == "2026-07-13T23:40:00Z"`. **This is the seam the original review
  flagged as untested by construction.** It is now covered.
- `test_anchors_correctly_even_when_scanned_a_day_late` monkeypatches `fleet.datetime.now` to
  `2026-07-14T04:00Z` — a moment when the *broken* code returned `2026-07-14T23:40:00Z` — and
  asserts `2026-07-13T23:40:00Z`. **This is a true regression guard**: it fails if the anchor
  ever reverts to wall-clock. I confirmed the monkeypatch actually bites (`_next_local_reset_utc`
  resolves `datetime` as a module global, so the patched subclass is what `now()` hits).

The wave's design insight is worth crediting: with the anchor correct, the expected value is a
**constant**, so most of these tests need no clock freezing at all. That is a stronger guard than
the frozen-clock test the review asked for.

---

## 4. N2 — 🆕 **CONFIRMED-BUG (blocking): C1 silently reverts on the documented 3.10 floor**

**The wave introduces a Python 3.11+ runtime requirement into a codebase whose spec pins a
3.10+ floor.** `datetime.fromisoformat` only accepts a trailing `Z` from **3.11**. On 3.10 it
raises `ValueError` — which `_record_time` catches and converts to `None`, falling back to the
wall clock. That is C1, in full, restored, silently.

**Receipts:**
- `bin/fleet.py:1250-1256` (`ee68eb6`) — `dt = datetime.fromisoformat(ts)` / `except ValueError: return None`.
- `docs/specs/portability.md:42` (**D9**) — *"Python floor: **3.10+**"*, and it reasons explicitly that *"Ubuntu 22.04 LTS ships Python 3.10 as `python3`"*.
- `docs/SPEC.md:8` — **[PRESCRIPTIVE]** operator directive, dated **2026-07-17** (this wave's own day): *"everything must be multi-platform — Windows, macOS, and Linux … never with silent Windows-only assumptions."*
- `CLAUDE.md:8` — *"Python is `py -3.13` (bare `python` resolves to 3.10)."*

**Demonstrated on a real 3.10 interpreter on this machine, using `_record_time`'s verbatim logic
and the real G7 record shape:**

```
interpreter: 3.10.1
_record_time({'timestamp': '2026-07-13T22:32:01.933Z'}) -> None
=> None on 3.10 => _parse_limit_signal falls back to datetime.now()
=> C1 SILENTLY REVERTS IN FULL on the documented floor. No error, no signal.
```

Compare 3.13, same input → `2026-07-13 22:32:01.933000+00:00`. The failure is **total** (every
real record, not an edge case), **silent** (no raise, no log, no operator signal), and
**invisible to the suite** (tests run on 3.13 and pass). The 3.10-only degradation would surface
as workers mysteriously parked a day long on Linux, with the exact symptom C1 described and a
green test suite pointing away from it.

**Note D9's own grep list** — it enumerates 3.10+-only features (`match`, `tomllib`,
`datetime.UTC`, `removeprefix`, `zip(strict=)`, …) and asserts zero hits. `fromisoformat`-with-`Z`
is a **3.11+** feature that list doesn't cover, so the existing guard could not have caught this.
The wave's own docstring even says *"`datetime.fromisoformat` (3.11+)"* — the requirement was
noticed and written down, but not checked against the floor.

**Fix — one line, 3.7+ safe (verified on 3.10 above):**

```python
dt = datetime.fromisoformat(ts[:-1] + "+00:00" if ts.endswith("Z") else ts)
```

Fold into the same wave; add the `Z`-suffix form to D9's grep list so the floor is guarded going
forward.

## 5. N1 — 🆕 DESIGN-QUESTION: the canonical fixture lacks the field the fix depends on

`tests/test_native.py` `LIMIT_RECORD` carries **no** `timestamp`, and the wave's new comment
elevates that into a claim about reality:

> *"LIMIT_RECORD (the pinned real G7 evidence shape) carries no `timestamp` field"*

**That claim is empirically false.** I checked 12 real transcripts on this machine
(`~/.claude/projects/*/*.jsonl`, 3,707 records):

```
record type                   with_ts /  total
assistant                        1545 /   1545      <-- 100%
user                              754 /    754      <-- 100%
attachment                        368 /    368
last-prompt                         0 /    185   <-- missing
mode / permission-mode / ai-title   0 /    493   <-- missing
file-history-snapshot               0 /     36   <-- missing
```

**Every `assistant` record carries a timestamp.** The records that lack one are pure bookkeeping
types, none of which can pass the scanner's limit gate (`isApiErrorMessage` + 429/`rate_limit`,
`bin/fleet.py:1341`) — the limit record is `type: "assistant"`.

The fixture's omission is an artifact of the *doc quote*, not of the record: `spike/m0/VERDICTS.md:431`
abridges record 201 to its `message` + error fields (note the mismatched braces — the envelope is
elided), while the adjacent records quoted verbatim at `:441-445` all show `"timestamp":"…"`.

**Why it matters** (the fix is still correct in production — this is about the tests):
1. The **default** fixture exercises the *fallback* path, not the production path. The two
   headline assertions (`test_native.py:1677`, `:1855`) are therefore shape-only when production
   would give an exact instant — they are weaker than they need to be, and weaker than D6 asked.
2. It writes a false fact about the real evidence into the suite, where the next maintainer will
   read it as settled and may reason from it.
3. **It interacts with N2.** The comment frames the wall-clock fallback as the normal path for
   "the real record shape". If that were true, N2 would be harmless. It isn't — which is why the
   fallback must be treated as genuinely exceptional.

**Fix:** add `"timestamp": "2026-07-13T22:32:01.933Z"` to `LIMIT_RECORD`, promote the two
shape-only assertions to exact instants, and keep the fallback tests on an explicitly
timestamp-stripped copy (they already build records via a local `_record` helper, so this is cheap).

## 6. N3 — 🆕 DESIGN-QUESTION: the fallback reproduces C1 rather than parking null

When `_record_time` returns `None`, `_parse_limit_signal` falls back to `datetime.now()` — i.e.
it re-enters exactly the code path this review classified as a **wrong horizon**. Run:

```
ts=garbage  anchor=None  -> reset_at=2026-07-17T23:40:00Z kind=session_5h   # wall-clock roll = C1
```

By this review's own accepted standard — *"a wrong horizon is worse than a null one"* — the
fallback for an **unparseable** timestamp should arguably be a **null horizon** (`reset_at=None`
→ conservative park → `--force-now`), not a confident guess. The wave chose "preserve pre-anchor
behavior", which is a defensible read of *"falls back to the real wall clock (today's pre-anchor
behavior)"*, and given N1's finding that real records always carry a timestamp, this path is
defensive-only and rare.

**But it stops being rare the moment N2 bites**: on 3.10, this fallback is the *only* path. N3 is
what converts N2 from "the anchor is skipped" into "the anchor is skipped **and** a wrong horizon
is confidently written". Fixing N2 makes N3 low-stakes again; fixing N3 too would make the 3.10
degradation safe-by-default rather than wrong-by-default. **Recommend both** — they are
independent one-liners and together they turn a silent 24h-wrong horizon into a visible null park.

---

## 7. New-defect hunt — attacks that FAILED (the new code held)

**7.1 `_record_time` fuzz — 21/21 clean, never raised.** Every case returned `None` or an
**aware** datetime (the invariant `_parse_limit_signal.astimezone()` depends on):

```
absent / None / empty / garbage / int / float / list / dict / bool / "Z" /
"2026-13-45T99:99:99Z" / year-0 / epoch-str          -> None            ok
"…933" (naive)        -> 2026-07-13 22:32:01.933+00:00                  ok  (assumed UTC)
"…933+05:00"          -> 2026-07-13 22:32:01.933+05:00                  ok
"…933-08:00"          -> 2026-07-14 03:32:01.933-08:00                  ok
"2026-07-13" (date)   -> 2026-07-13 00:00:00+00:00                      ok
nanosecond precision  -> 2026-07-13 22:32:01.933123+00:00               ok
rec not a dict / None -> None                                           ok
```

The `isinstance(rec, dict)` and `isinstance(ts, str)` guards are load-bearing and correct —
without them `.get` / `fromisoformat` would raise `AttributeError` / `TypeError`, neither caught
by the bare `except ValueError`. **No input escapes as an exception**, so the scanner's
never-raises contract holds.

**7.2 "What tz is the timestamp in?" — handled.** Offset-aware inputs are preserved and converted
correctly; naive inputs are assumed UTC (`dt.replace(tzinfo=timezone.utc)`), which matches the
observed `Z`-suffixed reality. Verified the semantics end-to-end — the naive and `+05:00` forms
denoting the *same instant* both yield the identical, correct horizon:

```
ts=naive       anchor=2026-07-13 22:32:01.933+00:00 -> reset_at=2026-07-13T23:40:00Z
ts=offset+05   anchor=2026-07-14 03:32:01.933+05:00 -> reset_at=2026-07-13T23:40:00Z
```

**7.3 Does a bad timestamp crash the scanner? No.** Falls back cleanly (see N3 for the
*semantics* of that fallback — the mechanism itself is sound and `is_limit` stays `True`, so a
park still happens; only the horizon degrades).

**7.4 Arithmetic overflow at `datetime.MAX` — safe.** `"9999-12-31T23:59:59Z"` anchors fine, then
`candidate += timedelta(days=1)` overflows — but raises `OverflowError`, **not** `ValueError`,
and is caught by `_next_local_reset_utc`'s blanket `except Exception` → `None`. Verified:
`(None, 'session_5h')`. The blanket catch there is doing real work; the review notes the
asymmetry (`_record_time` catches only `ValueError`) is nonetheless **correct as written**, since
7.1 proves nothing else can escape its guards.

**7.5 No regression in D1–D4.** The wave did not touch the regex, the 12-hour table, or
`_next_local_reset_utc`'s DST handling; D2/D3/D4 stand exactly as filed. tz-data availability
(D1) is unchanged and still incidental.

**7.6 SPURIOUS-FIX check on the wave — none.** Every changed line traces to C1, D5, or D6. No
speculative refactors, no unrelated cleanups, and the wave correctly declined to touch the
follow-up findings it wasn't asked to fix.

---

## 8. Recommended wave (all one-liners)

1. **N2 (blocking)** — `ts[:-1] + "+00:00" if ts.endswith("Z") else ts` before `fromisoformat`;
   add the `Z`-suffix form to `portability.md` D9's grep list.
2. **N1** — put `timestamp` on `LIMIT_RECORD`, promote the two shape-only assertions to exact
   instants, keep fallback tests on a stripped copy, and correct the comment's claim about the
   real record shape.
3. **N3** — consider `reset_at=None` (conservative null park) when the timestamp is
   present-but-unparseable, per "a wrong horizon is worse than a null one".

**Ideally N2 lands with a test that would actually catch it** — a 3.10 CI job (`port-ci` is
already spec'd in `portability.md:42`) or, cheaper, a direct unit test on `_record_time`
asserting the `Z` form parses, which at least pins the intent even though it can't fail on 3.13.
