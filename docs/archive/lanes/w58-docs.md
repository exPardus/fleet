# Lane report — `w58-docs`: landing the 2026-09-09 succession ruling across the prose surface

**Branch** `w58/docs`, based at `2a15dec`. **Fence:** prose only. `bin/fleet.py`, `bin/fleet_keeper.py`
and `tests/**` are a sibling lane's and were **read but never edited** — verified by the diffstat at the
end of this report.

Every line below is tagged **MEASURED** (I ran it, on this branch, in this worktree) or **BELIEVED**
(reasoned from what I read; not executed). A command I did not run is not quoted as if I had.

---

## 1. What binds, in one paragraph

The 2026-09-09 operator ruling **plus its `## AMENDMENT`** supersedes the 2026-09-08 "the timer pages,
a human revives" ruling. The keeper **never** dispatches; on a dead-or-released supervisor with GOALS
active it types a `KEEPER: … relaunch` line into `work:fleet`, and the **interface** runs `sup-spawn` on
that line **without waiting for the operator**, carrying the **two-live-body guard** the amendment moved
off the keeper. The interface is the operator's own persistent session and is never recycled by fleet;
the supervisor is the swappable layer, and **reaching its band is routine, not an incident** — a
four-step graceful end: checkpoint with the successor queue → notify the interface with a one-line
`SUPERVISOR:` message typed into `work:fleet` → the handoff protocol → `sup-release` **only** if the
handoff is stillborn. Superseding is not deleting: the 2026-09-08 ruling stays on the record, dated,
everywhere it appears as history.

---

## 2. WHERE THIS BRIEF WAS WRONG

### 2.1 The ruling's step 3 is wrong about shipped code, and following it would mint a second live body — **MEASURED**

The ruling (and the brief repeating it) says the graceful end's step 3 is *"`sup-handoff-begin`, **the
interface runs `sup-spawn` for the successor**, the successor boots with `--handoff-inc`/`--handoff-token`,
the outgoing body runs `sup-handoff-complete`."*

**`sup-handoff-begin` dispatches the successor itself.** MEASURED by reading `cmd_sup_handoff_begin` in
`bin/fleet.py` at `2a15dec`: it builds `argv = [exe, "--bg", "-n", name, …]` and runs it, and its own
docstring says it is the one `--bg` launch that deliberately does **not** go through `dispatch_bg`. The
task file it writes (`_render_successor_task`) already opens with `sup-boot --handoff-inc`. So:

- an interface `sup-spawn` during a handoff mints a **gen-0 body with no token**, alongside the
  token-bearing successor that is already booting — **two live bodies over one `supervisor/GOALS.md`**,
  the single condition the claim system exists to prevent;
- the successor cannot be produced by `sup-spawn` anyway: `sup-spawn` dispatches a gen-0 body whose
  first act is a plain `sup-boot`, which has no token to hash into `HANDSHAKE`.

**What I landed instead**, in every surface: during a handoff the interface **watches**
`fleet sup-status --json` until the claim moves, and dispatches **only** on the stillborn path (step 4)
or on a `KEEPER: … relaunch` page. The ruling's *behavioural* requirement — the two tiers work the
succession together, the interface is informed and able to act — is landed in full; only the mechanical
clause is corrected, and it is flagged inline at every site rather than silently fixed.

**BELIEVED:** the ruling's parenthetical *"(or the keeper, if the interface is absent)"* in the same
sentence is also dead under its own amendment — the keeper never dispatches — and I treated it as such.

### 2.2 The suite command in the brief does not work on this host — **MEASURED**

`/home/altai/.venv/china-infra/bin/python3.12 -m pytest -q` → `No module named pytest`. **MEASURED:**
no interpreter on this box has pytest importable (`/usr/bin/python3`, `~/.local/bin/python3.10`,
`~/.local/bin/python3.12`, the china-infra venv — all `ModuleNotFoundError`). What works, and what this
lane used:

    uv run --no-project --python 3.12 --with pytest python -m pytest -q
    uv run --no-project --python 3.10 --with pytest python -m pytest -q

Worth putting in the next brief; two lanes will otherwise each rediscover it.

### 2.3 The inherited baseline is 4845, not 4836 — **MEASURED**

The brief predicts `4836 collected` with six pre-existing failures. At `2a15dec`, before any edit:

- 3.12: **6 failed, 4822 passed, 16 skipped, 1 xfailed** → **4845 collected**
- `--collect-only`: **4845** on 3.12 **and** on 3.10

**Six pre-existing failures, exactly as predicted, and the same six named in the soak log's baseline**
(`test_fleet_index.py::TestPathContainment` ×3, `test_fleet_q.py::TestOutlinePathContainment` ×1,
`test_terminal_surface.py::TestCollaboratorInstall` ×2). The failure count was right; the collection
number was stale by 9 — **BELIEVED** because `4836` was measured at `0dc9be2` and `2a15dec` added the
2026-09-09 lessons entry, and `test_doc_claims` parametrizes twice over `git ls-files '*.md'`. I did not
bisect that; it is a nine-test discrepancy in a number nothing depends on.

### 2.4 "A docs-only landing moves the floor by construction" did **not** apply here — prediction written before measuring

**Predicted, in `state/journals/w58-docs.md` before the post-edit run: no movement. 4845 on both
interpreters, the same six failures.** Grounds, all **MEASURED** by reading the harness:

- `docs/lanes/` is in `test_doc_claims._HISTORICAL_PREFIXES`, so committing **this** report adds no case
  to either `@pytest.mark.parametrize("rel", CHECK_COUNT_DOCS)`;
- I added **no** fenced `# at <sha>` block to any `docs/specs/**` file, so `test_receipts`' extracted set
  and `RECEIPT_FLOOR` are untouched (the floor forbids *losing* receipts, not gaining prose);
- no new tracked markdown outside a historical prefix, no new test file, no code change.

Result: **§6 below.** The brief's rule is right in general and simply had no purchase on this shape of
landing — which is why it asked for the prediction in writing.

### 2.5 Two named files needed less than the brief expected; one needed more

- **`docs/specs/three-tier-command.md`** says nothing about revival being a human's act. Its §3.5.3(a)
  already rules that **the interface tier dispatches the fallback**, on the ground that it is "the one
  actor that is never parked" — the 2026-09-09 ruling *generalises* that rather than contradicting it.
  I added two dated notes (§3.1 persistence + the guard; §11.3 the four-step graceful end) and changed
  no threshold, enumeration or ceiling arm. **MEASURED:** no receipt block touched.
- **`docs/SPEC.md` §18** carried no contradiction either — its server entry's "it never dispatches,
  never takes `fleet.lock`" is still **true** under the amendment. It needed an *addition*, not a repair.
- **`docs/specs/graceful-succession.md` contradicts the ruling in the way the brief hoped someone would
  find** — §2.6 below. That is the substantive one.

### 2.6 The ruling knowingly takes a horn a ratified refusal called forbidden — **MEASURED (the text), BELIEVED (that the operator intended it)**

`docs/specs/graceful-succession.md` §1.2 records a 2026-07-27 operator refusal of any fleet-side restart
path, on two grounds:

> Any fleet-side watcher for a rebooted host would have to either fire in a session nobody asked to be
> fleet-aware — the **D7 leak** — or **dispatch a replacement with no operator in the loop, which is how
> two live supervisors happen.**

The 2026-09-08 ruling narrowed the *first* horn (page into one dedicated opt-in window; gate **G-K1**,
still open). **The 2026-09-09 amendment takes the second**: the interface dispatches with no operator
keystroke. §2 of the same spec states *"Succession is never automatic"* as a hard constraint, and §5.8
grounds its whole safety argument on *"a verb that ends in a fresh supervisor body is acceptable
**because a human typed it**."* Both are now false as written.

**I did not smooth this over and I did not delete the refusal.** All three sites carry a dated amendment
box that keeps the 2026-07-27 text verbatim and states the new ground beside the old one: **the
dispatcher is not an autonomous actor but the operator's own persistent session, which can read an
ambiguous claim and decline** — which is exactly why the two-live-body guard rides with the dispatch.
§5.8's forbidden class is restated so it still does work: *a **self**-triggering path — an actor
dispatching its own replacement, or a view acting on what it renders*. The keeper is a scheduler-driven
observer that reaches no dispatching verb (pinned by an AST test, **BELIEVED** — I read the pin's
description in the design spec and `tests/test_keeper_doctrine.py`'s name, I did not read the pin body).
`sup-recover` remains unbuilt and unaffected.

**This is a ratified-spec-level reversal and I am a lane. I amended the specs' prose to stop them stating
a superseded rule as current; I did not tick anything. If the operator wants the reversal recorded as a
ratification rather than as an amendment box, that is theirs — §7 has the proposed text.**

### 2.7 A contradiction the ruling did not anticipate, which is not mine to fix

**`supervisor/GOALS.md` — the file a booting supervisor loads FIRST — still states a `150–200k` context
band and an `[UNBUILT]` §11.3 ceiling.** MEASURED at `2a15dec`. Both have been dead since the 2026-08-05
raise; the approved replacement text has sat unlanded at
`docs/proposals/2026-08-09-goals-band-section-replacement.md` since the 2026-08-10 docket ruling that
approved it. MEASURED: `test_supervisor_context.py`'s `SURFACES` tuple is
`("skills/fleet/SKILL.md", "skills/fleet/supervisor.md")` — GOALS.md was ruled into that tuple on
2026-08-08 and **is still not in it**, so nothing goes red.

**Consequence for this lane specifically:** I landed a four-step graceful end triggered at the band into
two files a supervisor reads, while the file it reads *first* tells it the band is 150k. That is a
half-landing, and it is a half-landing by construction — `supervisor/GOALS.md` is operator-owned, no lane
may originate its content, and the test tuple is a sibling lane's. **Flagged, not fixed.** Proposed
docket text in §7.

---

## 3. The census — every hit, and what I did with it

Grep over the tracked tree (excluding `state/`, `logs/`) for `pages only`, `page-only`,
`human revives`, `await operator`, `Do not revive`, `revive`, `timer pages`, `never dispatch`.
All rows **MEASURED**.

### 3.1 Changed — stated the superseded ruling as currently binding

| File | What it said | What it says now |
|---|---|---|
| `docs/operator/server-interface-profile.md` | §3 *"Do not revive the fleet … Dispatch only after the operator replies with the word `revive`"*; `revive` as the only dispatch trigger | Rewritten. Step 3 revives without being told; a **two-live-body guard** section; a `KEEPER: … relaunch` rule that dispatches with no operator keystroke; a new **`SUPERVISOR:` lines** section with the interface's exact handoff steps (and the explicit "do NOT `sup-spawn` a handoff successor"); the persistence/swappable-layer framing. `revive` still honoured, no longer the only trigger. |
| `supervisor/briefs/server-standing.md` | *"dispatched … after the operator said `revive`"*; band handling was one bullet ending in `sup-release` | Swappable-layer framing; **"The graceful end of your generation — four steps"**; release demoted to step 4; the `Never dispatch a second supervisor body` bullet keeps its force but no longer reads as forbidding `sup-handoff-begin`'s own successor. |
| `skills/fleet/SKILL.md` | step 5 *"there is no other one"*; *"The operator relaunching their session IS the trigger"*; keeper row *"revival is the operator's `revive` message (ruling 2026-09-08)"* | Step 5 headline narrowed to "on a host with no keeper"; a keeper-host paragraph with the guard; the trigger sentence narrowed twice, with both horns named; keeper row rewritten; the succession doctrine bullet gained the four-step graceful end. |
| `skills/fleet/supervisor.md` | "Handoff" had no notify step; "Standing down" read as a first resort | "Handoff" opens with **REACHING YOUR BAND IS ROUTINE, NOT AN INCIDENT** and the four steps; "Standing down" opens with **release is the FOURTH step**, and what follows a release is no longer a wait for a human. |
| `docs/specs/graceful-succession.md` | §1.2 refusal, §2 *"Succession is never automatic"*, §5.8 *"because a human typed it"* | Three dated amendment boxes; original text kept verbatim. See §2.6. |
| `docs/specs/three-tier-command.md` | (no contradiction) | §3.1 gained the interface's persistence + the guard; §11.3 gained the four-step graceful end. No threshold or enumeration changed. |
| `docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md` | ruling 1's *"the trigger for revival stays a human message"*; §3.1's *"dispatch only when the operator says so"*; §5's first failure row ("waits"); §8's auto-revival exclusion | A top-level **AMENDMENT 2026-09-09** section (including the step-3 correction), plus in-place dated markers at all four sites. §8's exclusion **still stands** and now says why. |
| `docs/SPEC.md` §18 | (no contradiction; incomplete) | The server entry records the ruling, the amendment, the four steps, the step-3 correction, the unshipped verb name, the code/prose disagreement, and that no gate was ticked. |
| `knowledge/lessons.md` `#2026-09-09-keeper-revives` | recorded principle 3 **pre-amendment** | **EXTENDED, not duplicated** (per the brief): the amendment, the four steps and the framing, the step-3 correction with its general lesson, the unshipped verb, the taken horn, and the two unfixed contradictions. The pre-amendment paragraph is left standing as the record of what the first pass recorded. |
| `knowledge/INDEX.md` | **had no line for the 2026-09-09 entry at all** — the entry was invisible from the file the manager reads at every session start | One line added, amendment-first. |
| `docs/NEXT-SESSION.md` | 2026-09-09 CURRENT block predated the ruling | Ruling paragraph added, with the code/prose disagreement named. |
| `docs/operator/gate-docket.md` | G-K4's descriptive sentence said the brief is dispatched *"when you say `revive` from the phone"* | Amended with a dated note; **the gate is unchanged and still open, and nothing was ticked.** This file is the digest, never the record. |

### 3.2 Deliberately left, with the reason

| File | Hit | Why left |
|---|---|---|
| `bin/fleet_keeper.py` | module docstring *"revival is a human message"*; `supervisor-dead` page *"await operator before sup-spawn"*; `page-only` in the argparse description | **Code. Sibling lane's.** This is the sharpest live disagreement between doctrine and shipped behaviour, and it is named in `SPEC.md` §18, `NEXT-SESSION.md`, `lessons.md` and the soak log so no reader hits it cold. **Operationally handled:** the interface profile's `KEEPER:` rule keys on the page's *meaning* (supervisor dead or released), not on the word "relaunch", and says in so many words that the shipped `await operator before sup-spawn` sentence is superseded — so the profile is correct **before** the sibling lane lands and stays correct after. |
| `bin/fleet.py` | `_render_successor_task`, `cmd_sup_handoff_begin`, the `sup-notify` mechanism | **Code. Sibling lane's.** Read only. |
| `docs/OPERATOR-GATES.md` | Settled 2026-09-08 line stating *"the keeper timer PAGES ONLY … "* | **Forbidden by the brief and by the ruling** — the Settled line is the operator's to write or authorise. Proposed text in §7. **No box ticked, no line added, file untouched.** |
| `supervisor/GOALS.md` | stale `150–200k` band | Operator-owned; no lane may originate its content. §2.7, and §7 has the proposed docket line. |
| `docs/operator/keeper-soak-2026-09.md` | four recorded pages ending *"await operator before sup-spawn"* | Those strings are **what was actually typed on those dates** — host evidence, not doctrine. A dated note was added at the top; **not one recorded page was edited.** |
| `docs/superpowers/plans/2026-09-08-server-persistent-fleet.md` | pastes whole verbatim copies of the profile and the standing brief as of 2026-09-08 | An executed plan is a historical record and I did not rewrite it — **but it pastes files that have since changed**, and a future rebuild would re-paste the superseded text. Given a banner at the top pointing at the live files; the body is untouched. |
| `supervisor/JOURNAL.md` | the 2026-09-09 ruling as the incarnation recorded it | Append-only, claim-holder-only, written via `sup-checkpoint`. Not a lane's file. |
| `docs/AUTONOMOUS-2026-07-26.md`, `docs/reviews/**`, `docs/PLAN.md`, `knowledge/playbooks/campaign-template.md` | `revive` / `never dispatch` | Dated historical records, or a different sense of the word (`git revert`, the red path). A claim about a past tree is not rot. |
| `docs/specs/native-substrate.md`, `docs/specs/multi-fleet.md`, `tests/**`, `REVIEW-INPUT-GATE-ARM.md` | *"only a dispatch revives the daemon"*, `fleet homes … never dispatch` | **A different subject.** The daemon, and the `homes` verb. Not the succession doctrine. |

---

## 4. The verb name

Every surface that names it writes **`fleet sup-notify`** and marks the line **NAME UNSHIPPED —
reconcile at merge**. **MEASURED at `2a15dec`: `grep -rn "sup.notify" bin/ tests/ docs/` returns
nothing.** What is stated as binding is the **behaviour**: one `SUPERVISOR:`-prefixed line typed into
tmux window `work:fleet` with the same sanitising the keeper uses. **No receipt of the verb running is
pasted anywhere** — I cannot run it, it does not exist on this branch, and a command nobody has run is a
claim.

Sites carrying the marker (**MEASURED**, `grep -rn "sup-notify"`): the interface profile, the standing
brief, `SKILL.md`, `supervisor.md`, the design spec's amendment, `three-tier-command.md` §11.3,
`SPEC.md` §18, `lessons.md`, `INDEX.md`.

---

## 5. Things I read and did not change, so a reviewer does not re-derive them

- **BELIEVED:** `docs/specs/graceful-succession.md`'s ratified element 3 (*"not auto-spawn — a body
  dispatching its own replacement is how two live supervisors happen"*) is **not** contradicted by
  `sup-handoff-begin` dispatching its own successor: there the claim moves through the one-shot token and
  the outgoing body exits. I say so in the standing brief's `Never` bullet rather than leaving a reader
  to reconcile it.
- **MEASURED:** `docs/OPERATOR-GATES.md` has three open gates (G-K1, G-K2, G-K4) and they are exactly the
  three the docket digest carries. None moved.
- **MEASURED:** the ruling's own file (`state/tasks/20260909-succession-ruling.md`) lives in gitignored
  `state/` — it is cited by every surface I edited and **is in no commit**. That is the same class of
  loss `docs/lanes/README.md` exists for. Not mine to move; worth the operator's attention, because a
  dozen documents now cite a path that dies with the worktree.

---

## 6. Verification

All **MEASURED**, in this worktree, on the final tree.

**Baseline at `2a15dec`, before any edit** — 3.12: `6 failed, 4822 passed, 16 skipped, 1 xfailed`
(**4845 collected**); `--collect-only` **4845** on 3.12 and **4845** on 3.10.

**Prediction, written to the journal before the post-edit run:** no movement — 4845, six failures, both
interpreters.

**After the edits:** see the block below; if it disagrees with the prediction, the prediction is what was
wrong, and both are on the record.

**MEASURED on the final tree** (`uv run --no-project --python <ver> --with pytest python -m pytest -q -rf`,
run SERIALLY, in this worktree — 3.12 was re-run after two late prose edits so that both numbers are
about the same tree):

| interpreter | result | collected |
|---|---|---|
| 3.12 | **6 failed, 4822 passed, 16 skipped, 1 xfailed** in 293.46s | **4845** |
| 3.10 | **6 failed, 4822 passed, 16 skipped, 1 xfailed** in 324.02s | **4845** |

**PREDICTION HIT TO THE DIGIT on both interpreters, and the six failures are the same six as the
baseline, by name** — `test_fleet_index.py::TestPathContainment` ×3, `test_fleet_q.py::TestOutlinePathContainment` ×1, `test_terminal_surface.py::TestCollaboratorInstall` ×2. **No test changed state in
either direction.**

**MEASURED, targeted, before the floors** — `test_doc_claims.py test_supervisor_context.py
test_receipts.py test_terminal_surface.py test_views_doctrine.py test_handoff_seams.py
test_self_citations.py test_lane_report_durability.py` on 3.12: **2 failed, 568 passed, 2 skipped**, the
two failures being the pre-existing `TestCollaboratorInstall` pair. The receipt harness, the band pins,
the views doctrine and the citation pins are all green over the edited specs.

**MEASURED: no line citation was introduced.** `git diff -U0 | grep '^+' | grep -oE
'[A-Za-z0-9_./-]+\.(md|py):[0-9]+'` returns nothing — the rolling-document rule (`lessons.md` is
append-at-top, `bin/fleet.py` moves every wave) is respected; every cross-reference is by grep-able name
or by anchor.

---

## 7. Proposed text for the operator (nothing was ticked)

**For `docs/OPERATOR-GATES.md`, if the operator chooses to write it — a Settled line, not a new gate:**

> - [x] **Succession on the server fleet — who revives, and what a supervisor does at its band?**
>   *(2026-09-09 by Altai, in-session through the interface, amended the same day.)* Answer: **the keeper
>   still PAGES ONLY and never dispatches; on a dead or released supervisor it instructs the interface to
>   relaunch, and the interface runs `sup-spawn` on that line WITHOUT waiting for the operator, carrying
>   the two-live-body guard (`sup-status --json` + the roster; page instead of dispatching when the state
>   is ambiguous). The interface session is the operator's own and is never recycled by fleet; the
>   supervisor is a swappable layer whose generation ends gracefully in four steps — checkpoint, notify
>   the interface, hand off, and release only if the handoff is stillborn.** SUPERSEDES the 2026-09-08
>   revival answer, which stays above as the record. Ruling:
>   `state/tasks/20260909-succession-ruling.md` (with its `## AMENDMENT`);
>   `knowledge/lessons.md#2026-09-09-keeper-revives`; landing: `docs/lanes/w58-docs.md`.
>   **One correction the ruling earned:** its step 3 has the interface `sup-spawn` the handoff successor;
>   `sup-handoff-begin` dispatches it itself, so the interface watches instead and dispatches only on the
>   stillborn path.

**Three things the operator may want to decide, which I am NOT filing as gates:**

1. **Does the 2026-09-09 amendment amend `docs/specs/graceful-succession.md` §1.2/§2/§5.8, or ratify a
   replacement?** I landed amendment boxes that keep the 2026-07-27 refusal verbatim. A ratified spec
   reversal is above a lane's pay grade (§2.6).
2. **`supervisor/GOALS.md` is still on the dead 150–200k band**, and `test_supervisor_context.py`'s
   `SURFACES` tuple still excludes it despite the 2026-08-08 ruling that it should join (§2.7). Landing
   the approved draft at `docs/proposals/2026-08-09-goals-band-section-replacement.md` needs an operator
   or an authorised lane.
3. **`state/tasks/20260909-succession-ruling.md` is gitignored** (§5). Every surface this lane touched
   cites it.

---

## 8. Fence proof — **MEASURED**

`git diff --stat` against `2a15dec` names 14 files: `docs/NEXT-SESSION.md`, `docs/SPEC.md`,
`docs/operator/gate-docket.md`, `docs/operator/keeper-soak-2026-09.md`,
`docs/operator/server-interface-profile.md`, `docs/specs/graceful-succession.md`,
`docs/specs/three-tier-command.md`,
`docs/superpowers/plans/2026-09-08-server-persistent-fleet.md`,
`docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md`, `knowledge/INDEX.md`,
`knowledge/lessons.md`, `skills/fleet/SKILL.md`, `skills/fleet/supervisor.md`,
`supervisor/briefs/server-standing.md` — plus this report. **No file under `bin/`, `tests/`,
`docs/OPERATOR-GATES.md` or `supervisor/GOALS.md` is in it.**
