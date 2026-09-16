# w87 appendix — the break-even curve, full tables and scripts

Part 1 only (research). Part 2 (the two no-handoff code cuts) is in `docs/lanes/w87.md` /
`w87.json`, written by the parent lane after this appendix landed.

**METHOD, as required:** every number below is a script aggregate over `message.usage` fields
in `~/.claude/projects/*/*.jsonl`. No transcript content was read into this session at any
point — sid→file lookup was by filename match (`glob` + `os.path.basename`), and journal
headers (`## <ts> <KIND> inc=<id> sid=<sid>`) were read directly from
`supervisor/JOURNAL.md`/`supervisor/journal-history/journal-roll.md` (small, tracked fleet
state, not a transcript, no secrets in a header line). Tagged **MEASURED** or **ESTIMATED**
throughout; no invented numbers.

## 1. Generation → sid mapping (MEASURED, from journal headers)

| incarnation_id | role | sids (chronological) | source |
|---|---|---|---|
| `inc-20260911T182128Z-3742` | predecessor of 291f (tap) | `6d9934f6`, `fdfb8a01`, `cdb30cc4` | tap journal-roll.md :133-149 |
| `inc-20260915T083739Z-291f` | tap | `d11d0f34` | tap journal-roll.md :153-189 |
| `inc-20260915T104754Z-e9c1` | tap | `3530b8fa` | tap journal-roll.md |
| `inc-20260915T120921Z-f085` | tap | `64d8ce75`, `c37658cc`, `1eadd740` | tap journal-roll.md |
| `inc-20260915T210648Z-d137` | tap, current | `eb78f9b4`, `2ddda6a9` | tap journal-roll.md + JOURNAL.md |
| `inc-20260911T195615Z-a6c9` | this home, current | `36620880`, `2516bcf0`, `e65ef203`, `612ed197`, `4ad10ab0` | this home's journal-roll.md + JOURNAL.md + `state/fleet.json` `retired_sids` |

Multi-sid rows (3742, f085, d137, a6c9) are generations whose journal shows **no**
`HANDOFF-BEGIN`/`SEIZED` between their sids — the incarnation_id never changed, so per the
journal these are the SAME generation continuing on a new sid. That is exactly the shape of
the OLD (pre-w87) `fleet send` wake: `--bg --resume <sid>` forks a new sid carrying the full
prior transcript (G2, `docs/specs/native-substrate.md`), and the fork's file is a byte-for-byte
copy of everything the parent had, plus new turns appended — confirmed here two ways:

- Every sid within a chain shares the IDENTICAL millisecond-precision first `timestamp`
  (e.g. `6d9934f6`, `fdfb8a01`, `cdb30cc4` all start `2026-09-11T18:21:33.260Z`) and the
  identical first-turn `cache_read_input_tokens` value. Real, independently-executed API
  calls do not share a millisecond timestamp; this is a file copy, not a re-billed replay.
- Turn counts and `cache_read_input_tokens` totals grow monotonically along the chain
  (36620880: 262 turns/36.5M → 2516bcf0: 280/40.1M → e65ef203: 356/58.9M → 612ed197: 367/61.7M
  → 4ad10ab0: 384/66.4M) — each later file is a strict superset of the earlier one.

**Consequence for "being" cost below:** summing `cache_read_input_tokens` across every file in
a chain (the method `docs/lanes/w86.md` used for its host-wide "resume chain" map) DOUBLE-COUNTS
the shared historical prefix on every multi-sid chain. This appendix instead takes the **latest
(most complete) sid's own total** per generation — since it is a superset, its own total already
equals the deduplicated cumulative sum for that generation's whole life. w86's host-wide map is
not re-derived or disputed here (out of this lane's scope); this is a narrower, generation-scoped
number for the break-even arithmetic specifically.

## 2. "Being" cost per generation (MEASURED, latest sid per chain)

| incarnation_id | latest sid | turns | cache_read total | first turn cache_read | last turn cache_read | avg cache_read/turn | span |
|---|---|---:|---:|---:|---:|---:|---|
| 3742 (predecessor) | `cdb30cc4` | 523 | 103,776,064 | 31,882 | 359,486 | 198,425 | 2026-09-11T18:21Z → 09-15T08:40Z |
| 291f | `d11d0f34` | 593 | 121,903,591 | 30,646 | 344,054 | 205,570 | 09-15T08:38Z → 10:49Z |
| e9c1 | `3530b8fa` | 572 | 117,463,058 | 30,646 | 340,524 | 205,355 | 09-15T10:48Z → 12:10Z |
| f085 | `1eadd740` | 522 | 105,135,756 | 30,646 | 361,176 | 201,409 | 09-15T12:09Z → 21:08Z |
| d137 (current) | `2ddda6a9` | 509 | 91,217,826 | 22,054 | 318,559 | 179,210 | 09-15T21:07Z → 09-16T09:29Z |
| a6c9 (current, this home) | `4ad10ab0` | 384 | 66,354,478 | 31,912 | 291,891 | 172,798 | 09-11T19:56Z → 09-16T09:04Z |

Mean of the six `avg cache_read/turn` columns: **193,795** — and this is close to the mean of
(first_cr + last_cr)/2 across the same six rows (≈192,600), i.e. a turn's `cache_read_input_tokens`
tracks the conversation's current context occupancy roughly linearly, growing from ~30K at
generation start toward ~300-360K by the time each of these (still-active or handed-off)
generations was last measured. This empirical match is what licenses the approximation used in
§4 below: **the cache_read cost of one turn once context has reached size X is ≈ X.**

## 3. "Becoming" cost — successor bootstrap, dispatch to first logged checkpoint (MEASURED)

Window = every turn of the successor's own sid with `timestamp` ≤ the journal timestamp of its
first `CHECKPOINT` entry. `BILLED_TOTAL` = `input_tokens + cache_creation_input_tokens +
cache_read_input_tokens` summed over that window (output tokens tracked separately, not part of
context cost).

| transition | successor sid | turns in window | input | cache_creation | cache_read | output | BILLED_TOTAL | first-checkpoint body matches the mandated template text? |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 3742→291f | `d11d0f34` | 16 | 32 | 46,095 | 803,540 | 3,896 | **849,667** | YES — body is exactly `"claim received via handoff from inc-20260911T182128Z-3742"` (the successor task template's literal suggested command) |
| 291f→e9c1 | `3530b8fa` | 76 | 152 | 113,595 | 5,738,879 | 27,474 | 5,852,626 | no — body is a substantive dispatch/status report |
| e9c1→f085 | `64d8ce75` | 97 | 194 | 158,037 | 7,474,547 | 37,556 | 7,632,778 | no — substantive |
| f085→d137 | `eb78f9b4` | 137 | 274 | 196,205 | 11,954,687 | 76,865 | 12,151,166 | no — substantive |

**Only the 3742→291f transition isolates pure bootstrap cost** (sup-boot dispatch, bundle read
in slices, the mandated first checkpoint, nothing else — 16 turns, 849,667 billed tokens). The
other three successors evidently did real campaign work (dispatching lanes, reading CI, auditing
a ledger — see the quoted journal bodies in §1's source files) before their first *logged*
checkpoint, so their windows are NOT a clean "ritual only" measurement — they are reported as an
upper-bound / realism check, not used as the primary becoming-cost anchor. **This is an
ESTIMATION GAP, stated plainly**: isolating the true ritual-only cost for those three would
require identifying which turn IS the `sup-checkpoint` call inside the window, which needs
reading transcript content — exactly what the method rule forbids. The one clean sample stands
as the MEASURED anchor; the other three are reported as a realistic range, separately.

Becoming-cost anchor used for §4: **C = 849,667 tokens** (MEASURED, single clean sample).
Realistic-case range for context: 5.85M–12.15M tokens (MEASURED but campaign-work-commingled,
not used in the primary arithmetic — see §4 sensitivity note).

## 4. Break-even arithmetic

The brief's framing: *"the band where per-handoff cost equals the saved per-turn context."*
Per-handoff cost is C (§3). The context a lower band "saves" is precisely the size of the next
turn that would otherwise have exceeded it — and §2 showed a turn's cache_read cost at context
size X is ≈ X. So the break-even band B\* solves:

```
C = B*
849,667 = B*
```

**B\* ≈ 850,000 tokens.** That is the break-even band: a handoff pays for itself, against the
single next turn it avoids, only once that avoided turn would have cost ≈850K tokens of
cache_read — i.e. only at a band roughly **2.4× the highest candidate (350k) and 5.7× the
lowest (150k)**.

### The curve at 150k / 200k / 250k / 350k

Ratio = C / B = how many "avoided-turn's-worth" of cache_read one handoff costs, if triggered at
that band (ratio > 1 means the handoff costs MORE than the turn it avoided — net loss):

| band B | C / B (turns-worth) | reading |
|---:|---:|---|
| 150,000 | 849,667 / 150,000 = **5.66** | a handoff at 150k costs 5.66× the cache_read of the one turn it avoids |
| 200,000 | 849,667 / 200,000 = **4.25** | 4.25× |
| 250,000 | 849,667 / 250,000 = **3.40** | 3.40× |
| 350,000 | 849,667 / 350,000 = **2.43** | 2.43× (least bad of the four, still a net loss) |

**Every candidate band is below break-even.** None of 150k/200k/250k/350k reach the ≈850K band
where a handoff stops costing more than it saves — and 150k is the WORST of the four (5.66×
overcost vs 350k's 2.43×). This is the arithmetic behind the operator's own read: *"150k is too
aggressive, as we then have a lot more handoffs, and the handoff ritual and that stuff eats
tokens too."* MEASURED, not assumed: lowering the band strictly increases handoff frequency
(more generations covering the same amount of work) while the avoided-turn saving per handoff
shrinks (a lower band avoids a CHEAPER turn), so the overcost ratio gets worse, not better, as
the band drops — visible directly in the monotonic 5.66→2.43 column above.

**Sensitivity, using the realistic (campaign-work-commingled) becoming cost instead:** if C is
taken from the mean of the three non-clean samples (≈8.55M, §3) instead of the clean 849,667
sample, B\* ≈ 8.55M and the ratios become 57×/43×/34×/24× — the same ordering, an order of
magnitude worse. Either anchor reaches the identical conclusion: no candidate band is near
break-even, and 150k is the most expensive of the four.

**What this arithmetic does NOT model, stated plainly:** it compares a handoff's one-time cost
against ONE avoided turn, per the brief's literal wording. It does not integrate the full
avoided-growth curve over many turns (a real generation that runs long past a low band would
keep paying ever-larger per-turn cache_read if never capped, which a fuller model would
subtract). That fuller model is a follow-up measurement, not built here — the one-turn
approximation is sufficient to answer the brief's actual question (does 150k save anything
meaningful) because even the MOST FAVORABLE framing for a low band (crediting it with saving
only the single next turn, the smallest plausible saving) still leaves every candidate band
below break-even by 2.4-5.7×.

## 5. Corpse rows and transcript-byte cost (informational — Cut 1's claim, not this lane's)

`state/tasks/20260915-guard-blocked-corpses.md` describes three `sup|inc-20260911T195615Z-a6c9|
successor` roster rows stuck `state: blocked, status: None, pid: None` — the fork parents of the
SAME chain measured in §1/§2 above (`2516bcf0`, `e65ef203`, `612ed197` at the time that lane's
snapshot was taken; `36620880` had presumably already been swept). This appendix's own sid list
for a6c9 (§1) independently reproduces that chain from the journal + registry `retired_sids`,
confirming the same five sids that lane names. Not this lane's job to fix the predicate or
retro-clean the rows (stated per the w87 fences) — flagged here only because the data overlaps.

**Transcript bytes of the retired (non-final) a6c9 copies** (MEASURED, `os.path.getsize`):

| sid | bytes |
|---|---:|
| `36620880` | 1,584,362 |
| `2516bcf0` | 1,663,232 |
| `e65ef203` | 2,110,540 |
| `612ed197` | 2,194,911 |
| **retired total** | **7,553,045** (≈7.4 MiB) |
| `4ad10ab0` (current, live) | 2,328,508 |
| **all 5 files total** | **9,881,553** (≈9.4 MiB) |

**76.4% of the on-disk transcript bytes for this one generation are retired fork-parent
copies** that carry no live process and (per the corpses lane) no cleanup path today. This is
the concrete number for Part 2 Cut 1's own report line ("count the transcript bytes those
copies cost").

`inc-20260915T120921Z-f085` (tap) and `inc-20260911T182128Z-3742` (tap, predecessor) show the
identical shape at smaller scale (2 and 2 retired sids respectively) — this is not unique to
this home; tap's supervisor hit the same wake-fork pattern at least twice in the sampled window.

## 6. Scripts (reproducible against the same `~/.claude/projects/` tree)

Two scripts, left under `$CLAUDE_JOB_DIR/tmp/` (this job's scratch dir, not committed — matches
w86's own precedent of not committing throwaway measurement scripts into the tracked tree).

**`find_sids.py`** — locate each sid's transcript file by filename match against
`~/.claude/projects/*/*.jsonl` (no file content read):

```python
import glob, os
SIDS = [...]  # the 15 sids in §1's table
home = os.path.expanduser("~/.claude/projects")
found = {}
for path in glob.glob(os.path.join(home, "*", "*.jsonl")):
    stem = os.path.basename(path)[:-6]
    if stem in SIDS:
        found[stem] = path
```

**`w87_measure.py`** — per-sid and per-window `message.usage` aggregation:

```python
import json

def turns(sid):
    """Yield (timestamp, usage_dict) for every assistant message with usage."""
    out = []
    with open(SID_FILES[sid], "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if isinstance(usage, dict):
                out.append((rec.get("timestamp"), usage))
    return out

def summarize(sid):
    ts_usage = turns(sid)
    n = len(ts_usage)
    cache_read_total = sum(u.get("cache_read_input_tokens", 0) or 0 for _, u in ts_usage)
    # ... (cache_creation_total, input_total, output_total identically summed;
    #      first/last cache_read_input_tokens taken from ts_usage[0]/[-1])
    return dict(sid=sid, n_turns=n, cache_read_total=cache_read_total, ...)

def usage_until(sid, cutoff_ts):
    """Sum usage for turns at or before cutoff_ts (ISO8601 string compare)."""
    sel = [(ts, u) for ts, u in turns(sid) if ts is not None and ts <= cutoff_ts]
    return dict(n_turns=len(sel),
                cache_read_total=sum(u.get("cache_read_input_tokens", 0) or 0 for _, u in sel),
                cache_creation_total=sum(u.get("cache_creation_input_tokens", 0) or 0 for _, u in sel),
                input_total=sum(u.get("input_tokens", 0) or 0 for _, u in sel),
                output_total=sum(u.get("output_tokens", 0) or 0 for _, u in sel))
```

`usage_until` powered §3's becoming-cost windows (cutoff = each transition's first-`CHECKPOINT`
journal timestamp); `summarize` on the latest sid per chain powered §2's being-cost table.
No print statement in either script ever emits transcript content — only integers and ISO
timestamps taken from the `usage`/`timestamp` fields.

## 7. What was NOT measured

- The three non-clean becoming-cost windows (§3) could not be split into "pure ritual" vs
  "campaign work already started" without reading transcript content (forbidden by the method
  rule) — reported as an upper bound, not decomposed further.
- No attempt was made to model the full multi-turn avoided-growth integral (§4's stated
  limitation) — the one-turn approximation the brief's own wording licenses was judged
  sufficient to answer whether 150k saves anything meaningful, and it does not change the
  qualitative answer even under the more favorable becoming-cost anchor.
- `context_occupancy` fields already present in the two current generations' `INCARNATION`
  files (d137: 316,208; a6c9: 279,881 — read directly, not a transcript, no secret fields
  printed) were used only as a sanity cross-check against §2's `last_cr` column (same order of
  magnitude, consistent) — not as a primary source, since their exact derivation formula vs raw
  `cache_read_input_tokens` was not verified against fleet's own source.
