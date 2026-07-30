# When does the final transcript record land, relative to the Stop hook?

**Lane:** `outcount2`, worktree `C:/proga/fleet-wt/w29-outcount` (detached at
`3747461`). **Date:** 2026-07-30. **Deliverable:** report only — no production
code was changed, by design (the lane decides whether a poll is worth
implementing; implementing one would prejudge it).

**Verdict: A, with a caveat the brief's A/B framing has no slot for.** The
harness writes the final assistant record to the transcript file *while the
Stop hook is running*, not after the session process exits. When the hook loses
the race, a bounded poll inside the hook does see the record arrive. Measured
latency, in the one miss this harness could provoke and instrument
end-to-end: **27.17 ms**.

That makes the withholding in `bin/hooks/stop_outcome.py` **not permanent on
mechanical grounds** — it is permanent only if the operator decides the residual
risk is not worth the counter. The evidence for *how long* a poll must run is
one sample, and this report says so plainly rather than dressing it up.

---

## 1. What the brief got wrong

The brief asked to be refuted where wrong. Four things:

### 1.1 There is no TODO. The lane is owed against nothing in the tree.

The brief: *"Find the TODO this experiment is owed against and quote it."*

There is no such TODO. The entire worktree contains exactly two occurrences of
the token, neither about polling, `out=`, or usage provenance:

```
$ grep -rlE "\bTODO\b" . --include=*.py --include=*.md
./docs/reviews/c1-review-spec-core.md
./knowledge/lessons.md
```

The shipping commit `f5b8125` (merged as `6b2c824`) touched
`bin/fleet.py`, `bin/hooks/stop_outcome.py` and four test files and **added no
document**. No file under `docs/**` or `knowledge/**` mentions a bounded poll
against the transcript. The source comment at
`bin/hooks/stop_outcome.py:283-323` explains the withholding and does not
promise a future poll; it says the opposite —
*"An absent counter is a true statement; a stale one is not."*

So this lane is not discharging a debt recorded anywhere. It is answering a
question the manager brief invented, which is a fine reason to run it, but the
report should not pretend to close a ticket that does not exist.

### 1.2 The "~50 ms" figure has no provenance and is not what was measured.

The brief flagged it as a rumour. It is: nothing in the repo, in `f5b8125`, or
in the review corpus contains that number in this context. It happens to be the
right order of magnitude (measured: 27 ms), but that is luck, not inheritance.

### 1.3 Arm B — "only after the session process exits" — is not a coherent arm
for fleet workers.

Fleet dispatches native workers as `claude --bg` (`bin/fleet.py:10580`,
`argv = [exe, "--bg"]`). A `--bg` session does not exit when a turn ends; it
stays resumable and is re-entered by `fleet send`. There is no "session process
exit" at the moment the Stop hook fires. The real question behind arm B is
whether the write is *gated on the hook returning* — that would make polling
self-defeating (the poll blocks the write it waits for). It is not gated: see
§5.

### 1.4 The binary is wrong for a second reason: it is a distribution, not a
coin with two faces.

Measured offsets between the final record's arrival and hook entry range over
four orders of magnitude within one machine and one model (−6.5 s … +27 ms).
The useful output is that distribution and its positive tail, which is what
§4 reports.

---

## 2. Soft spot (c): does `fleet status` actually omit `out=` today? Yes.

Checked before spending anything on timing, as the brief asked. Two levels:

**Record level** — read-only scan of the real fleet's `state/outcomes`
(124 files), split at the merge time of `6b2c824` (`2026-07-30T11:50:46+05:00`
= `06:50:46Z`):

```
before: total= 201 with_out= 200 without_out=   1
 after: total=   7 with_out=   0 without_out=   7
```

**Render level** — `fleet._native_token_summary` called directly against this
lane's own temp-fleet outcomes (no registry read, no lock, no mutation):

```
'probe2' -> ''
'probe3' -> 'tokens:in=8 out=2833'
```

`probe2`'s record has `output_tokens: null`; the summary is the empty string,
so the status table shows no `tokens:` cell at all. The withholding is live and
the brief's premise (c) is confirmed.

## 3. What the code does, and where

`bin/hooks/stop_outcome.py`:

* `_transcript_result(transcript_path)` — **:203**. Reads the whole transcript
  with `Path(...).read_text()` (**:214**), groups assistant records by
  `message.id` (**:246-248**), and returns the last message's text plus its
  four usage summands.
* `main()` — **:264**. Calls it once at **:281-282**, with no retry and no
  poll, then applies the provenance guard at **:324-326**:

  ```python
  if not (isinstance(text, str) and isinstance(t_text, str)
          and text == t_text):
      tokens_in = tokens_out = cache_creation = cache_read = None
  ```

  `text` is the payload's `last_assistant_message` (**:276**). So the four token
  fields survive only if the transcript's last assistant message is the message
  the harness says the turn ended on.
* Consumer: `fleet._native_token_summary` (**bin/fleet.py:4762**) appends
  `out=` only `if outcome.get("output_tokens") is not None`.

The read happens exactly once, at hook entry, before anything else in `main`
except the stdin decode.

## 4. Experimental design

**Isolation.** Everything ran against a temp `FLEET_HOME` at
`C:\Users\Techn\.claude\jobs\ff0dfd44\tmp\fh` — a copy of this worktree's
`bin/` plus `worker-settings.template.json`, with `fleet init` run there. The
real fleet (61 workers, live supervisor) was only ever *read*: no fleet verb
ran against it, including `fleet status`, which merges and calls
`save_registry` and is therefore a mutating verb despite being a view.

**Instrumentation.** Three independent clocks, all `time.time_ns()` so they are
comparable across processes:

1. `bin/hooks/probe_first.py` — an extra Stop hook, **first** in the chain,
   that reproduces `stop_outcome`'s comparison exactly (same `message.id`
   grouping, same payload-vs-transcript equality), records whether it matched
   on its **first read**, then **polls** the transcript (stat-gated, 2 ms
   interval, 20 s budget), logging every observed change of the file with a
   timestamp. `probe_last.py` is the same probe at the **end** of the chain.
2. `tmp/watch_transcript.py` — an external watcher, outside every hook and
   every session, sampling `os.stat` on the projects directory every 2 ms and
   parsing each growth so that the *arrival time of each individual transcript
   record* is known independently of the hook.
3. The shipped `stop_outcome.py` itself, unmodified, whose published-or-withheld
   token fields are the ground truth for "did the shipped comparison pass".

**Runs.** Real `fleet spawn` / `fleet send` dispatches in the temp home, haiku
except where noted, trivial tasks (150 numbered lines; some preceded by a
~200 KB file read to inflate the transcript).

**A note on the Stop hook chain.** The hooks run **in parallel**, not
sequentially: `probe_first` and `probe_last` entry timestamps differ by
9–60 ms across runs, far less than a Python interpreter start. This matters —
it is why a race can be lost by one hook in the chain and won by another in the
same turn, which is exactly what happened in the run that first exposed the
effect.

## 5. The mechanism (this is the part the brief did not anticipate)

A transcript record's own `timestamp` field is **not** when the line reaches the
file. Comparing each record's `timestamp` against the watcher's observation of
the growth that carried it, in one temp session:

```
rec# 22 assistant blocks=['thinking']  arrival - record_ts = +0.515s
rec# 23 assistant blocks=['tool_use']  arrival - record_ts = +0.154s
rec# 26 assistant blocks=['thinking']  arrival - record_ts = +19.654s
rec# 27 assistant blocks=['text']      arrival - record_ts = +1.904s
```

The final message's records are buffered and flushed **as one batch at the end
of the turn** — records 26 and 27 land together, 19.7 s after the thinking block
was produced. That flush and the Stop-hook fire are the same event, within
milliseconds, and which one wins is not deterministic.

This also reconciles the live fleet with the temp harness. On live sessions the
final record's `timestamp` sits 1.6–4.5 s *before* the outcome record's `ts`,
which naively reads as "the record was there in plenty of time"; it was not —
the timestamp is the message-completion time, and the line arrived ~2 s later,
at the hook instant.

Two competing explanations for the live withholding were tested and **refuted**:

* *The payload was missing or not a string.* No: every temp run recorded a
  `last_assistant_message` string in the payload (lengths 74–10,349), including
  resumed turns and fork-steered turns.
* *The final message spans several text records, so `_transcript_result`'s
  per-record overwrite loses part of the text and the comparison fails
  structurally.* No: in all 6 live post-fix sessions the final message has
  exactly one record carrying text, and the text the hook would compute is
  byte-identical to the record's `result_text`.

What is left is the race, and the race is real.

## 6. Independent re-derivation of the live miss rate

The fix's headline number (95/130 = 73 % stale) was re-derived from the live
corpus by a different method: for each pre-fix record that published a counter,
locate the assistant message whose text *is* that record's `result_text` (the
message the turn ended on), then find which message owns the published
`(input_tokens, output_tokens)` pair, searching at or before that point.

```
pre-fix records with a published out= that could be classified: 199
  usage described the FINAL message: 61 (31%)
  usage described an EARLIER message: 138 (69%)
  distance in messages: [0, 1]
```

Two things worth keeping: **69 %**, independently reproduced; and the stale
value is *always* exactly the second-to-last message, never further back. On the
live corpus the rate does not vary with transcript size (69 % below 1 MB,
70 % at or above; median 1.10 MB).

## 7. Raw per-run timings

One row per Stop-hook invocation seen by the probe. `hit` = the shipped
comparison would have passed on the hook's **first** read (so the counter is
published today); `poll_ms_to_match` = how long the poll had to wait when it
did not. `hook_ms` is the probe's own wall time, which is the cost a poll would
add.

```
probe worker    sid        size@entry   hit  poll_ms_to_match  hook_ms  reads
3rd   probe1    9db5faa8        67944  True              None      1.6      1
3rd   probe2    151daa97        58852  True              None     13.4      1
1st   probe3    5cc8e5e9        58324  True              None      1.3      1
1st   probe4    27a9b3f5        70406  True              None      1.6      1
1st   probe5    ba481bab        71651  True              None      1.7      1
1st   probe6    2b0db5b8        60004  True              None      1.7      1
1st   probe7    1a52278e        59031  True              None      1.5      1
1st   probe8    1f5bc8b3        58180  True              None      1.7      1
1st   probe9    8ca42c70        58787  True              None      1.6      1
1st   probe10   b6989911        70118  True              None      2.5      1
1st   grow1     ea4649a8       413362  True              None     13.9      1
1st   grow1     ea4649a8       599861  True              None      5.0      1
1st   probe11   5c35790b        60236  True              None      1.5      1
1st   grow1     ea4649a8       786302  True              None      7.5      1
1st   grow1     ea4649a8      1126463 False           27.1707     48.2      2
1st   son1      10793b2f        79133  True              None      1.7      1
1st   son2      02fbe035        65281  True              None      1.4      1
1st   son3      9123ae46        79069  True              None     25.5      1
1st   son4      de4bd3f0        79201  True              None      1.7      1
1st   grow1     b2d3f72e      1588406  True              None     13.3      1
1st   grow1     fc1b7b5d       669273  True              None      6.0      1
1st   grow1     38fc5fde       903055 False           39.9379     59.1      2
1st   grow1     b5b84043      1143414  True              None     12.5      1
1st   grow1     538834d7      1438117  True              None     11.5      1
1st   grow1     d2de96c3       501715  True              None      5.0      1
1st   grow1     04855306       735030  True              None      6.9      1
1st   grow1     b4a1f12e       966180 False           22.3996     42.1      2
1st   grow1     0108c946      1200326 False           17.7285     42.2      2
1st   burst1    8d963942        58831  True              None      2.1      1
1st   burst2    38642a0b        58644  True              None      1.3      1
1st   burst3    b3142a4f        59652  True              None      1.5      1
1st   burst4    540fed8b        58496  True              None      1.5      1
1st   burst5    1fa0fa9c        58981  True              None      1.4      1
1st   burst6    6c61ccae        59448  True              None      1.4      1
1st   burst7    531f237b        58348  True              None      1.9      1
1st   burst8    46004977        44181 False           45.5187     54.6      2

probe_first invocations: 34   misses: 5   resolved by poll: 5
  poll latency of each miss (ms): [27.1707, 39.9379, 22.3996, 17.7285, 45.5187]
  transcript >= 1 MB: 2/5 miss
  transcript < 1 MB: 3/29 miss
```

`son1`–`son4` are sonnet; everything else is haiku. `burst1`–`burst8` are eight
workers dispatched back-to-back so their turns overlap. `grow1` is one worker
steered repeatedly, its transcript growing to 1.59 MB (fork-steers mint a new
session id, which is why the size is not monotonic).

**Offsets from the external watcher, on the runs where it was up** — arrival of
the final assistant record minus hook entry, in ms:

```
-6504.7  -3407.9  -2167.4  -245.0  -184.7  -125.0  -87.3  -65.1  -39.7  -20.2  +3.2
n=11  median=-125.0  positive (hook read too early): 1/11
```

**The interrupted-turn tail case.** `fleet interrupt` on a mid-turn worker
produced **no Stop-hook invocation at all** — 0 probe records for session
`b7d4e882`, and the outcome file holds a fleet-side tombstone instead:

```
{'ts': '2026-07-30T09:27:31Z', 'kind': 'interrupted', 'output_tokens': None,
 'model': None} len 0
```

So the scenario "the hook polls for a record that never comes because the turn
was killed" does not exist: on that path the hook never runs.

**Instrument fidelity.** The probe's reader was diffed against the shipped
`stop_outcome._transcript_result` over 43 real transcripts (this lane's 23 plus
20 from the live fleet): **0 mismatches** on both the text and the
`output_tokens`. The probe is measuring the shipped comparison, not an
approximation of it.

## 8. Verdict, and what follows from it

### Verdict: **A**.

The final record lands *around* the Stop-hook fire, on both sides of it, and
when it lands after, it lands **17.7–45.5 ms** after — inside a poll that the
hook can afford. Decisively, in all five misses the record was written **while
the hook was blocked polling**, so the harness's write is not gated on the hook
returning. Arm B is refuted twice over: there is no process exit at turn end for
a `--bg` worker, and the write does not wait for the hook either way.

The consequence the brief attached to B — *"the withholding is permanent and the
TODO should be closed as WONTFIX"* — does not follow. There is no TODO to
close, and the mechanism it would have been closed on does not hold.

### What a poll would actually need

* **Bound.** Observed max 45.5 ms over five misses. A bound of **250 ms** is
  ~5× the observed maximum and still an order of magnitude below any
  human-perceptible stop latency; anything under ~50 ms would be fitting the
  bound to the sample. I would not pick a number from this sample alone — see
  the caveat below about the population it came from.
* **Shape.** Stat-gated: re-read the transcript only when `(st_size, st_mtime_ns)`
  changes. Every miss here needed exactly **2 reads**, not a busy loop of
  full-file parses. On a 3.4 MB transcript one full read+parse costs 91 ms, so
  an ungated 5 ms-interval poll would be genuinely expensive; a gated one is not.
* **Cost on a hit: zero.** The poll is entered only when the existing comparison
  fails. Hits stay at their present 1.3–13.9 ms.
* **Cost on a miss: +18–46 ms of hook wall time** (measured: total hook duration
  42.1–59.1 ms on misses vs 1.3–13.9 ms on hits). Stop hooks run in parallel, so
  this is added to turn teardown once, not three times.
* **Cost on the pathological case** (Stop fires, record never arrives): the full
  bound, once per such stop. Not observed in 34 invocations, and the obvious
  candidate for it — an interrupted turn — never reaches the hook.
* **Safety.** Such a poll is strictly additive to the existing guard: it retries
  *the same* payload-vs-transcript equality and, on timeout, withholds exactly
  as today. It can only turn "withheld" into "published **and proved**". It
  cannot reintroduce the stale counter, because the equality test is what proves
  freshness, not the timing.
* **Value.** On the live fleet ~69 % of stops currently publish nothing. If the
  live misses are the same race at the same latency, a poll recovers most of
  that.

### The caveat that decides whether to build it

**I could not reproduce the live miss rate.** Live: 69 % (138/199, §6), and
7/7 post-fix records withheld. This harness: **5/34 (15 %)**. Everything I could
vary failed to close that gap:

| varied | result |
|---|---|
| model (haiku → sonnet) | 0/4 sonnet misses |
| transcript size (58 KB → 1.59 MB) | 2/5 miss ≥1 MB vs 3/29 <1 MB; and the largest miss latency came from a **44 KB** transcript. Live data shows no size effect either (69 % vs 70 %) |
| 8 concurrent workers | 1/8 miss |
| **long-lived steered session vs fresh spawn** | **4/13 (31 %) vs 1/21 (5 %)** — the only variable that moved the rate |

That last row is the one lead worth following. All 13 `grow1` rows are one
worker steered repeatedly (12 steered turns after the spawn); it missed 4 times.
The 21 fresh single-turn workers missed once. 31 % is still not 69 %, and the
comparison is confounded — `grow1`'s turns also carried a 200 KB tool read and
a larger transcript — but it points the same way the live corpus does: the
fleet's real workers are long-lived steered sessions, and those are where the
hook loses.

So the poll latencies above are from a population whose miss rate is 4.6× lower
than the live one, and the honest reading is that **something about live fleet
sessions makes the hook lose this race far more often; the best candidate my
data offers is session longevity/steering, and I could not raise it past 31 %.**
A latency distribution measured where the race is rare is weak evidence about
the latency distribution where it is common. If those live misses are losing by
seconds rather than tens of milliseconds, a 250 ms bound recovers nothing and
costs 250 ms on ~70 % of stops.

### Recommendation

Verdict A holds — the poll is mechanically possible and the withholding is not
permanent. But **do not size the poll from this report.** The one cheap thing
that would settle it is to run the probe hook (unmodified, logging only, no
change to `stop_outcome.py`'s behaviour) as an *additional* Stop hook on the
real fleet for a day. It writes one JSONL line per stop, takes no lock, touches
no registry, and would produce the live latency distribution directly. That is
an operator decision, not a worker's, because it means adding a hook to
`state/worker-settings.json` on the live fleet.

## 9. What this design could not isolate

* **Sample size.** 34 hook invocations, **5 misses**. Five is a sample, not a
  distribution; the tail is unmeasured. Everything in §8 about a bound is
  extrapolation from five points.
* **Population mismatch**, as above — the single biggest weakness.
* **Observer effect.** The external watcher `stat`s and re-reads the transcript
  every 2 ms, and two extra Python processes were added to every Stop chain.
  Neither can be ruled out as a perturbation of the very timing being measured.
  (The watcher was down for part of the burst series; those rows have hook data
  but no arrival offset.)
* **One machine, one OS, one CLI version** (`claude 2.1.220`, Windows 10). The
  flush behaviour is a harness implementation detail and is not contracted.
* **The `--bg` daemon.** All runs went through fleet's native `claude --bg`
  dispatch. A foreground `claude -p` session was scaffolded
  (`tmp/run_fg.py`) but not needed once the interrupt case showed the hook does
  not fire on kill; its arm — "does the record land only after the process
  exits" — was answered by the misses themselves, where the write happened with
  the session very much alive and the hook blocking.
* **Not a `docs/specs/**` receipt.** The blocks pasted here are timing
  measurements against live sessions; they are not re-executable and
  deliberately do not live where `tools/verify_receipts.py` would try to
  re-execute them.

## 10. The instruments

Committed beside this report so the recommended live measurement in §8 does not
have to be rebuilt:

* `docs/reviews/outcount-timing/probe_stop_timing.py` — the Stop-hook probe.
  Reproduces `stop_outcome`'s comparison, then stat-gated-polls, and appends one
  JSON object per invocation to `probe.jsonl` beside itself (override with
  `$PROBE_LOG`; budget with `$PROBE_POLL_BUDGET_MS`). It writes nothing else,
  takes no lock, reads no registry, and always exits 0. To use it, add it as an
  extra `Stop` hook command in a rendered `worker-settings.json`.
* `docs/reviews/outcount-timing/watch_transcript.py` — the external watcher.
  `watch_transcript.py <projects-dir-glob> <out.jsonl> <seconds>`.

Neither is production code and neither is imported by anything in `bin/`.
