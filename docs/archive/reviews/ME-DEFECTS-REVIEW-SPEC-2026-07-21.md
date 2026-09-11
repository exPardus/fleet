# ME-DEFECTS — spec/doctrine-conformance review of `me/defects`

**Reviewer:** fleet worker `me-defects-spec` (spec lens), worktree `C:/proga/fleet-me-defects-spec`,
branch `me/defects-spec` based on `fleet-impl @ 7f99d84`.
**Under review:** `me/defects` = `ef0747f` (supervisor successor dispatch) + `0cbc517` (autoclean F4
ownership), on base `ac3e34d`. Target worktree `C:/proga/fleet-me-defects` verified clean at
`0cbc517` (`git status --short` → empty; `git rev-parse HEAD` → `0cbc517…`).
**Date:** 2026-07-21.

**VERDICT: fix-wave(D1, D2, D3, D4)** — D5–D10 fold in; D11 is a manager probe.

The **code** is right. Both commits fix defects that were genuinely filed, the fixes are minimal and
correctly scoped, the new tests are real pins (fault-injection reproduced below), and the suite
count reproduces exactly. Every defect below is in the **spec text** — which on this branch is the
higher-consequence artifact, because the branch's stated purpose was to make `docs/SPEC.md` stop
lying about the dispatch surface, and it half-succeeded: it corrected §6 and left the *same false
claim* standing in §12 of the same file and in `docs/specs/autoclean.md` three files away.

## Probe provenance (v1.7 clause)

Every receipt in this document was executed by **me**, `me-defects-spec`, on 2026-07-21, from
`C:/proga/fleet-me-defects-spec`, against pinned git objects (`git grep <rev>`, `git show <rev>:…`)
or against a `git archive 0cbc517` export in a contained scratch dir — never against another
worker's live checkout. Nothing below is inherited from a commit message unverified.

I am a `--bg` worker. I ran **no** mutating verb, no `sup-*` verb, no `schtasks`, no `claude
daemon`/`claude stop`, and touched nothing under `C:/Users/Techn/.claude/`. Items I cannot observe
are tagged `[MANAGER-VERIFICATION REQUIRED]` or `[UNVERIFIED — no POSIX box]`.

---

## 1. Re-run of every claimed receipt (9/9 reproduced)

### R1 — "TWO `--bg` argv builders, not one" (`ef0747f`)

The commit pastes `$ grep -n '"--bg"' bin/fleet.py` → `6650`, `7319`, with **no stated commit**
(gate nit → D12). Those line numbers are `ac3e34d`'s. Re-run, pinned three ways:

```
$ git grep -n '"--bg"' 0cbc517 -- .        # argv-builder literals in shipped code
0cbc517:bin/fleet.py:6724:    argv = [exe, "--bg"]
0cbc517:bin/fleet.py:7444:    argv = [exe, "--bg", "-n", name,
(remaining hits are docs/, tests/ and plan files — no other builder)

$ git grep -n 'argv = \[exe, "--bg"' c63d7dd -- bin/fleet.py   # SPEC's own declared pin
c63d7dd:bin/fleet.py:6196:    argv = [exe, "--bg"]
c63d7dd:bin/fleet.py:6865:    argv = [exe, "--bg", "-n", name]
```

**The true number is two**, at `0cbc517` and at `c63d7dd`. I hunted indirect paths as instructed:

```
$ git grep -n 'Popen|subprocess\.run|run\(argv|_claude_exe|which\("claude"\)' 0cbc517 -- bin/fleet.py
```
→ 40 hits. Every one that reaches `claude` is `--version`, `agents --json`, `rm`, or `stop`
(`_rm_native_session*` @4624/@4677, `_stop_native_session*` @6336/@6392, `_fetch_agents_roster`
@7119, `_doctor_check_claude_version` @5458, `_doctor_check_pin_version` @5490,
`_doctor_check_claude_agents` @5828). The remainder are `schtasks` (platform adapter @286/@331/@344)
and hook smoke (`_run_hook_smoke` @5626). **No third launcher, no helper argv builder, no resume-only
path** — `--resume` is a branch *inside* `dispatch_bg` (`0cbc517:bin/fleet.py:6726`), not a builder.
`tests/integration/test_native_pin.py` launches only through `fleet spawn`, i.e. through the choke
point — **not** a test-only launcher. `bin/fleet_statusline.py` and `bin/hooks/*` launch nothing.
**CLAIM TRUE.**

### R2 — `_autoclean_task_is_ours` call sites (`0cbc517`, pinned @ `ac3e34d`)

```
$ git grep -n '_autoclean_task_is_ours' ac3e34d -- bin/ tests/
ac3e34d:bin/fleet.py:5290:def _autoclean_task_is_ours(command: str) -> bool:
ac3e34d:bin/fleet.py:5331:    if existing is not None and not _autoclean_task_is_ours(existing) and not force:
```
Byte-identical to the pasted receipt. **One consumer. CLAIM TRUE.**

### R3 — "`_doctor_check_autoclean` does NOT use the predicate"

```
$ git grep -n '_autoclean_task_is_ours|_fleet_task_is_ours' 0cbc517 -- bin/ tests/
→ bin/fleet.py:5315, 5361, 5362, 5365, 5400 (+ 5 test refs). 5400 = _install_autoclean_task.
```
`_doctor_check_autoclean` (@5926) is absent from the list. Read at `0cbc517:bin/fleet.py:6018`, it
runs its own scan — `for tok in re.findall(r'"([^"]+)"', existing)` — for a quoted token ending in
`fleet.py` that **no longer exists on disk**. Different question (dead pin, not ownership), left
alone. **CLAIM TRUE.** Drift consequence → D9.

### R4 — "all four hooks"

```
$ git show 0cbc517:worker-settings.template.json      # git-tracked template
PostToolUse → bin/hooks/posttooluse_mailbox.py
Stop        → bin/hooks/stop_outcome.py, bin/hooks/stop_mailbox.py
PostCompact → bin/hooks/postcompact_journal.py
$ cat C:/proga/claude-fleet/state/worker-settings.json  # rendered instance, live home
(same four, {{PYTHON}}/{{FLEET_HOME}} substituted; forward slashes throughout)
```
Exactly **four**, template and instance agree, and SPEC §16 invariant 2 already says "now four hooks
(+ manager SessionStart)". `bin/hooks/sessionstart_fleet.py` is the manager hook, not in this
settings file; `run_py.sh` is a shim. **COUNT TRUE.**

Degradation for a session with **no registry record**, read at `0cbc517`:

| hook | no-record behavior | `hook-errors.log`? |
|---|---|---|
| `stop_outcome.py` | `key = _resolve_name(home, sid) or sid` (:197); `_resolve_name` returns `None` on miss without logging (:108-134) | no — `_log_hook_error` fires only on unsafe token or exception |
| `postcompact_journal.py` | `key = name if name is not None else session_id` (:160-163) | no |
| `posttooluse_mailbox.py` | never reads the registry: `_mailbox_path(session_id)` → `mailbox/<sid>.md` (:44-46, :113) | no |
| `stop_mailbox.py` | never reads the registry: same sid-keyed mailbox + sid-keyed ceiling (:50-52, :75-77, :185) | no |

**CLAIM TRUE for all four**, and §6.1's parenthetical attribution
("`stop_outcome`/`postcompact_journal` fall back to the sid when `_resolve_name` misses,
`posttooluse_mailbox`/`stop_mailbox` are sid-keyed throughout") is exactly right.

### R5 — "the successor's sid is exactly the handle `sup-handoff-complete --expect-sid` consumes"

Producer: `0cbc517:bin/fleet.py:7503` `print(f"SUCCESSOR-SID: {successor_sid}")`, :7506/:7508 print
the two ready-to-paste command lines. Consumer: :7870 `p_suphc.add_argument("--expect-sid", …)`,
:7874 `p_supha.add_argument("--successor-sid", …)`; :7524 compares `args.expect_sid` against the
HANDSHAKE's `session_id`. Same value on both ends. **CLAIM TRUE.**

### R6 — "`cmd_sup_boot` derives `caller_sid` from `CLAUDE_CODE_SESSION_ID`"

Two hops, not one: `0cbc517:bin/fleet.py:7189`
`caller_sid = getattr(args, "sid", None) or current_caller_session()`, and
`current_caller_session()` (@580-588) is `os.environ.get("CLAUDE_CODE_SESSION_ID")`. The `--sid`
override would shadow it — but the successor bootstrap `_render_successor_task` (@7331-7348) emits
`sup-boot --handoff-inc {inc}` with **no `--sid`** (:7339), so the env path is the binding one.
**CLAIM TRUE.** (What §6.1 states flatly and the code docstring hedges → D7.)

### R7 — "`--add-dir` not needed: cwd is FLEET_HOME and the task file is inside it"

`state_dir()` is `FLEET_HOME / "state"` (@61-62), unconditionally; the successor task file is
`state_dir() / f"supervisor-handoff-{inc}.md"` (:7412) and the dispatch is `cwd=str(FLEET_HOME)`
(:7452). Containment is by construction, so it holds for **every** layout the portability directive
binds: env-var `FLEET_HOME`, script-location fallback (@55-58), a linked git worktree home, and a
`~/.claude/fleet-home` marker pointing elsewhere (the marker is read only by `_marker_guard_problems`
@5262-5285, never by `state_dir()`). Contrast `dispatch_bg`, which genuinely needs `--add-dir`
because `tasks_dir()` is outside the *worker's* cwd, not fleet's. **CLAIM TRUE.**
One residual, unreachable from here: if `FLEET_HOME` is a symlink/junction and `claude` authorizes
the *resolved* cwd while the prompt names the unresolved path, the successor's first Read is outside
the authorized root. `dispatch_bg` carries the identical shape, so this is not a branch defect.
`[UNVERIFIED — cannot dispatch a real successor under containment]`

### R8 — suite counts (`1136 → 1142 → 1147 passed, 6 skipped`)

Run by me, on a `git archive 0cbc517` export in a contained scratch dir
(`py -3.13 -m pytest -q -p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`):

```
2 failed, 1145 passed, 6 skipped in 60.64s
FAILED tests/test_terminal_surface.py::TestCollaboratorInstall::test_interpreter_shim_is_tracked_and_executable
FAILED tests/test_terminal_surface.py::TestCollaboratorInstall::test_posix_cli_shim_is_tracked_and_executable
```
Both failures are artifacts of my export method, not of the branch — they shell out to `git ls-files`
and a `git archive` tree has no `.git`. Both files **are** tracked:
```
$ git ls-tree 0cbc517 bin/fleet bin/hooks/run_py.sh
100755 blob 2a9d2e9…  bin/fleet
100755 blob d1401d5…  bin/hooks/run_py.sh
```
1145 + 2 = **1147 passed, 6 skipped. CLAIM TRUE.**

### R9 — fault injection ("5 of 6 supervisor tests RED"; "all four autoclean directions RED")

Built by me: `git archive 0cbc517` → overwrite `bin/fleet.py` and `docs/SPEC.md` with
`git show ac3e34d:…` (tests stay at `0cbc517`).

```
10 failed, 171 passed
test_successor_dispatch_carries_instance_settings          RED
test_successor_dispatch_refused_without_rendered_settings  RED
test_successor_dispatch_uses_worker_env                    RED
test_spec_lead_sentence_scopes_the_choke_point             RED
test_spec_names_the_successor_dispatch_path                RED
test_exactly_two_bg_argv_builders                          GREEN  (shape guard — correctly unaffected)
test_same_fleet_py_different_subcommand_is_not_ours        RED    ← the defect
test_same_script_and_verb_different_fleet_home_is_not_ours RED
test_ownership_predicate_all_four_directions               RED
test_spec_states_full_identity_ownership                   RED
test_ownership_requires_an_explicit_fleet_home             RED
```
**5/6 and 5/5 — CLAIM TRUE** (the autoclean claim said "all four", meaning the four *directions*;
the fifth new test also goes red, so the claim understates). These are real pins, not
shape-assertions that would survive the bug.

---

## 2. Findings

### D1 — `docs/specs/autoclean.md` still specifies the **pre-fix** ownership predicate (MED)

`0cbc517:docs/specs/autoclean.md:48` (unchanged by this branch):

> **Ownership + fail-closed query (F3/F4):** a same-named task is fleet-owned **iff its command runs
> our exact fleet.py path (slash/case-normalized)** — never a substring match

That is the sentence the shipped code no longer implements, and it directly contradicts the
branch's own new `docs/SPEC.md:241` ("ownership by full identity … **and** the `autoclean`
subcommand **and** `--fleet-home <this home>`"). `autoclean.md` is the design spec of record for
this subsystem (SPEC §11 links it: "Full design: `docs/specs/autoclean.md`"). A builder
implementing the `--supervisor-beat` task — the exact scenario this fix exists for — reads
`autoclean.md`, implements path-only ownership for the new task, and rebuilds the bug.

The branch's own doc pin cannot catch this: `test_spec_states_full_identity_ownership`
(`tests/test_autoclean.py:807-816`) reads `docs/SPEC.md` only.

**Fix:** in `docs/specs/autoclean.md:48`, replace the F3/F4 ownership clause with the full-identity
statement (resolved `fleet.py` path **and** the subcommand token immediately after it **and**
`--fleet-home <this home>`, whole quote-stripped slash/case-normalized tokens, never a substring;
absent `--fleet-home` ⇒ not ours), naming `_fleet_task_is_ours`.
**Pin it needs:** extend `test_spec_states_full_identity_ownership` to assert the same three
anchors in `docs/specs/autoclean.md`, or the two docs drift apart again on the next wave.

### D2 — `docs/SPEC.md` §12 still says the successor is dispatched **`via dispatch_bg`** (MED)

`0cbc517:docs/SPEC.md:249`:

> - **Handoff** (`sup-handoff-begin/complete/abort` …): old dispatches a claim-pending successor
> **via `dispatch_bg`** …

False, and false in the same file that now devotes §6.1 to explaining why it *cannot* be
`dispatch_bg`. `git grep -n 'dispatch_bg' 0cbc517 -- bin/fleet.py` shows no call inside
`cmd_sup_handoff_begin` (:7351-7510); the argv is hand-built at :7444.

The adjudication (`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md:27`) filed this as
"SPEC §6 'one choke point' is inaccurate as written. **Fix + SPEC correction owed**". The branch
corrected §6 and skipped the other half of the same inaccuracy. This is the "quietly skip part of
what was asked" limb of the `SPURIOUS-FIX` verdict.

**Fix:** `docs/SPEC.md:249` → "old dispatches a claim-pending successor **on the sanctioned second
dispatch path (§6.1)**, not through `dispatch_bg`".
**Pin it needs:** add to `TestDispatchPathsAreDocumented` — assert `"via `dispatch_bg`"` does not
appear in the §12 section, and that §12 references §6.1.

### D3 — The spec edit makes a **false claim about its own pin** (MED)

`0cbc517:docs/SPEC.md:187`:

> Pinned by `TestDispatchPathsAreDocumented` (`tests/test_supervisor.py`), which fails if a third
> `--bg` argv builder appears **or if this subsection stops naming the path**.

The second clause is false. `_section()` (`tests/test_supervisor.py:910-912`) slices everything
between `## 6. Dispatch contract` and `\n## 7.`, so §6's own lead sentence and main argv block are
inside the window — and they already contain both strings the test looks for
(`cmd_sup_handoff_begin` in the lead sentence, `--settings` in the §6 argv block). Deleting §6.1
outright leaves the pin green. Receipt (run by me): `git archive 0cbc517` → delete the entire
`### 6.1 …` subsection up to `## 7.` → keep everything else:

```
$ py -3.13 -m pytest -q -p no:cacheprovider tests/test_supervisor.py::TestDispatchPathsAreDocumented
...                                                                      [100%]
3 passed in 2.22s
```

A spec sentence asserting protection that does not exist is worse than no sentence: the next
reviewer trusts it and skips the check.

**Fix (pick one):** (a) strengthen `test_spec_names_the_successor_dispatch_path` to assert against
`_section()` narrowed to the `### 6.1` subsection and to require the load-bearing tokens
(`_worker_env`, `_require_instance_settings`, `supervisor-handoff-`); or (b) reword :187 to what the
test actually pins.
**Pin it needs:** whichever is chosen, re-run the §6.1-deletion injection above and confirm RED.

### D4 — §6.1 and §11's new text are descriptive of a commit the document does not declare (MED)

`docs/SPEC.md:12` (§0, unchanged): "Everything here is **descriptive of `bin/fleet.py` at
`c63d7dd`**". At `c63d7dd` the second path was `argv = [exe, "--bg", "-n", name]` — receipt in R1 —
with no `--settings` and no `env=`. So §6.1's block "What the second path therefore **must** carry,
**and does**" is *false at the document's own declared pin*, as is §11's new "ownership by full
identity". A reader obeying §0 and grepping `c63d7dd` finds the new text contradicted, which is
precisely the C4 failure mode (`enumeration by inspection`, §0's own warning) inverted.

**Fix:** pin the new text explicitly — e.g. §6.1 heading gains "(descriptive of `bin/fleet.py` at
`<merge sha>`)" and the §11 scheduler-bridge bullet gains the same, or §0 gains a "sections
re-pinned after `c63d7dd`" list. Do **not** silently rewrite §0's global pin: that would implicitly
re-assert every other unverified claim in the document at a new commit.
**Pin it needs:** none mechanically enforceable; it is a one-line editorial obligation, so state it
in the fix-wave brief.

### D5 — new `@`-receipt `@7280` was stale before the branch finished (LOW)

`docs/SPEC.md:166`: `### 6.1 … (`cmd_sup_handoff_begin` @7280)`.

```
$ for c in ac3e34d ef0747f 0cbc517; do git show $c:bin/fleet.py | grep -n 'def cmd_sup_handoff_begin'; done
ac3e34d: 7277   ef0747f: 7280   0cbc517: 7351
```
Correct at `ef0747f`, invalidated 74 lines later by `0cbc517` — the branch's own second commit.
Same for the code docstring's "`the choke point's own name guard (@6631)`" (:7366): at `0cbc517`
the guard is at `bin/fleet.py:6705`. §0 licenses drift against `c63d7dd`, but `@7280` is pinned to
neither `c63d7dd` nor any stated commit.
**Fix:** drop the `@`-ref from the §6.1 heading (function names are the durable anchor, per §0), or
pin it to the merge sha alongside D4.

### D6 — §6.1's parity enumeration omits the mode flags (LOW→MED)

§6.1 frames the second path as "**sanctioned**, not a bypass: it carries the same `--settings`
instance and the same `_worker_env` process identity the choke point carries", then explicitly
justifies the two things it deliberately drops (`--add-dir`, `--setting-sources`). It is silent on
the third asymmetry, which is real:

```
$ git grep -n 'MODE_FLAGS = ' -n 0cbc517 -- bin/fleet.py     → :949
  "dontask": ["--permission-mode", "dontAsk"]
$ git show 0cbc517:bin/fleet.py | sed -n '7734p'
  p_spawn.add_argument("--mode", choices=list(MODE_FLAGS), default="dontask")
$ git show 0cbc517:bin/fleet.py | sed -n '7865p'
  p_suphb.add_argument("--permission-mode", dest="permission_mode", help=...)   # no default
```
`dispatch_bg` always emits `mode_flags(mode)` and every worker defaults to `dontask`; the successor
gets a permission-mode flag **only** if the operator types one, and its bootstrap task's very first
instruction is to run `py -3.13 …/fleet.py sup-boot` — a tool call, in a headless session, under
whatever `claude`'s default mode is. This is pre-existing behavior and **not** a defect this branch
introduced; the defect is that a spec section whose whole job is to enumerate what the second path
carries now asserts parity while leaving the one remaining gap unnamed.
**Fix:** one clause in §6.1 — state that mode flags are **not** carried, that the successor
therefore runs in `claude`'s default permission mode, and either why that is safe or tag it
`[UNBUILT — owned by the claim-nonce/three-tier slice]`.

### D7 — §6.1 drops the `UNOBSERVED` hedge the branch itself carries (LOW)

`docs/SPEC.md:184` states the env-inheritance causal chain flatly. The branch's own code docstring
(`0cbc517:bin/fleet.py:7396-7399`) and commit message both hedge it: "*Whether the daemon actually
propagates the launcher's environment into the hosted session is **UNOBSERVED** here*". The spec is
the artifact a future builder trusts; it should be the *more* careful of the two, not the less.
**Fix:** append `[UNVERIFIED — daemon env propagation into a hosted session unobserved; the strip is
defense-in-depth and costs nothing if the daemon already isolates]` to that bullet.

### D8 — portability: `_normalize_task_token` is Windows-shaped beyond the caveat it documents (LOW)

`0cbc517:bin/fleet.py:5297-5303`:
```python
text = str(value).strip().replace("\\", "/").lower()
return text.rstrip("/") or text
```
The docstring (and §6.1's sibling claim "Platform-neutral by construction — it only ever sees a
string") flags **one** caveat: `.lower()` conflating two paths on a case-sensitive filesystem. There
is a second: `replace("\\", "/")` is a Windows path fixup, but on POSIX a backslash is a legal
filename character *and* a shell escape inside a crontab line — so the same normalizer silently
mangles a legitimate POSIX path, in the opposite direction from the case bug (false *match*, not
false miss). Invariant 8 requires new adapter-adjacent code to ship all-OS or with an explicit gap
note; this one has a partial note. Unreachable today (`_PosixPlatform.autoclean_task_query` raises,
:357+), so it is a documentation obligation, not a live bug.
`[UNVERIFIED — no POSIX box; reasoned, not run]`
**Fix:** extend the existing docstring caveat to name the backslash rewrite alongside the case fold,
both scoped "revisit when Phase 1.5 lands launchd/cron".

### D9 — doctor and the install guard now disagree about "ours" (LOW, note-only)

`_doctor_check_autoclean` (@5926, unchanged) reports `task installed` for any task whose quoted
`fleet.py` token exists on disk. After this branch, `_install_autoclean_task` can **refuse** that
same task as not-ours (wrong verb, or wrong `--fleet-home`). The operator's health surface says
green; the install says foreign. Pre-fix the two agreed by accident (both keyed on the path).
Not a correctness defect — doctor is note-only by design (`docs/specs/autoclean.md` D4) — but the
gap widened and nothing records it.
**Fix:** either a sentence in SPEC §11 / `autoclean.md` noting doctor does not check ownership, or
(better, cheap) reuse `_autoclean_task_is_ours` in the doctor note.

### D10 — `docs/NEXT-SESSION.md:23` still lists both defects as outstanding work (LOW)

> **Two shipped-code defects surfaced by the design gate …** (a) `cmd_sup_handoff_begin` hand-rolls
> argv and bypasses `dispatch_bg`, so **successor supervisor sessions launch with no hooks** … (b)
> `_autoclean_task_is_ours` matches fleet.py path only …

Both are present-tense and both are now false of the branch. This is a live operator-facing planning
doc, not history. Per the standing rule (`knowledge/lessons.md:507-508`, campaign-template §2):
**move a stale pin, never delete it** — the entry should become a done row pointing at these two
commits, not vanish.
**Fix:** manager/ledger-owned, not the builder's; flagged, not charged to this branch.

### D11 — `[MANAGER-VERIFICATION REQUIRED]` — the live task may now be refused as foreign

The new predicate returns **False** for a command with no `--fleet-home` token
(`0cbc517:bin/fleet.py:5352-5355`; pinned by `test_ownership_requires_an_explicit_fleet_home`). If
the `claude-fleet-autoclean` task currently installed on this machine predates F2, the next
`fleet init --autoclean` will **refuse** where it previously overwrote — a new
`--force`-or-nothing state for the operator. The commit's justification ("F2 embeds it in every task
fleet installs") is true of every task *this* fleet.py installs but says nothing about a task
installed by an older build.

I am barred from running `schtasks` against the live task, so I did not.
**Manager probe:** `schtasks /Query /TN claude-fleet-autoclean /XML` → confirm `<Arguments>` carries
`--fleet-home`. If it does not, the fix wave owes a one-line migration note in the refusal message
("a pre-F2 task has no `--fleet-home`; `--force` is safe if the path is yours").

### D12 — grep receipt without its stated commit (LOW, gate conformance)

`ef0747f`'s message pastes `$ grep -n '"--bg"' bin/fleet.py` → `6650`/`7319` with no commit stated.
Campaign-template §2 C4: "paste the grep command AND its output … **pinned to a stated commit**".
`0cbc517` does it correctly ("Call-site receipt (pinned @ ac3e34d)"). The output is in fact correct
for `ac3e34d` (R1), so this is form, not substance — but the whole point of the gate is that a
reader can re-run it without guessing.
**Fix:** none to the code; note it in the ledger so the next builder pins the receipt.

---

## 3. `[UNBUILT]` / prescriptive-vs-descriptive discipline — clean

```
$ git grep -n 'UNBUILT|unbuilt|PRESCRIPTIVE|not shipped|NOT SHIPPED|UNVERIFIED|UNOBSERVED' 0cbc517 -- docs/SPEC.md
:8   [PRESCRIPTIVE] portability directive   (pre-existing, still true)
:12  §0 pin declaration                     (→ D4)
:214 "value shape UNOBSERVED at 2.1.207"    (pre-existing, untouched)
```

- The branch adds **no** `[UNBUILT]` tag, and needs none: every sentence it adds to §6/§6.1/§11
  describes code that ships on this branch (verified clause by clause in §1 and §4). The one
  sentence that should carry a hedge carries none → **D7**; the one that should carry a pin carries
  none → **D4**.
- No pre-existing `[UNBUILT]` tag anywhere in the repo becomes false because of this branch:
  `git grep -n 'UNBUILT' 0cbc517 -- docs/specs/ skills/ knowledge/ README.md` returns only
  `phase-5-intelligence.md:50,55`, `portability.md:380,392,400`, `terminal-surface.md:254` and
  knowledge/playbook prose — all about the PID probe, F20/F33 and the librarian, none about dispatch
  or scheduled-task ownership.
- **Prose audit** (the C4 corollary — `grep "[UNBUILT"` misses a *sentence*): three prose claims
  became false with this branch and are recorded above — `docs/specs/autoclean.md:48` (**D1**),
  `docs/SPEC.md:249` (**D2**), `docs/NEXT-SESSION.md:23` (**D10**). `knowledge/INDEX.md:5` and
  `knowledge/lessons.md:625` also describe both defects, but in the past tense as *what the design
  gate found* — those stay true and must not be edited.

## 4. §6/§6.1 clause-by-clause against shipped code

| §6.1 clause | receipt @ `0cbc517` | verdict |
|---|---|---|
| "`NAME_RE` is `^[a-z0-9-]+$`" | `bin/fleet.py:472` | true |
| "incarnation id is `inc-<8>T<6>Z-<hex4>`, T/Z uppercase" | `mint_incarnation_id` @6993 | true |
| "`dispatch_bg(name=<inc>)` raises before dispatching" | guard @6705 (`NAME_RE.match` + `_SID_SHAPE_RE`) | true |
| "task file written to `state/supervisor-handoff-<inc>.md`" | :7412 | true |
| "journaled **by path** in the HANDOFF-BEGIN entry" | :7416-7418 `task={task_path.as_posix()}` | true |
| "`task_file_path(name)` would create a second one" | `task_file_path` @102-103 → `state/tasks/<name>.md` | true |
| "single safe wedge-retry … re-dispatches the whole launch once" | `_dispatch_once` @6746, `dispatch_retried` event @6868, give-up @6877 ("two consecutive `--bg` dispatches …") | true |
| argv block `-n "sup\|<inc>\|successor" --settings … [--model] [--permission-mode] "Read …"` | :7442-7450 | true (mode flags omitted → **D6**) |
| "`--settings` (the rendered instance)" | `instance_settings_path()` @211-216 = `state/worker-settings.json`; same default `dispatch_bg` resolves (@6715) | true |
| "pre-flighted by `_require_instance_settings` **before the lock**" | `:7407` immediately precedes `with fleet_lock():` `:7408` | true |
| "a refusal writes neither the journal entry nor the task file" | both writes are inside the lock, :7412/:7416 | true; pinned by `test_successor_dispatch_refused_without_rendered_settings` |
| "all four hooks degrade to sid-keyed writes … no `hook-errors.log`" | R4 table | true |
| "the successor's sid is exactly the handle … print and consume" | R5 | true |
| "`cmd_sup_boot` derives `caller_sid` from `CLAUDE_CODE_SESSION_ID`" | R6 | true (stated without the branch's own hedge → **D7**) |
| "No `--add-dir` (cwd is `FLEET_HOME`; the task file is already inside it)" | R7 | true |
| "No `--setting-sources` (per-worker persisted; a successor has no record)" | `dispatch_bg` forwards it @6740-6742; no registry record is created for the successor anywhere in :7351-7510 | true |
| "Everything else — short-id join, pre-snapshot exclusion, G6 name-join fallback — is shared logic, called directly" | `_parse_bg_short_id` :7466, `_join_roster_by_short_id(..., exclude_sids=pre_sids)` :7473, name-join fallback :7478-7493, `pre_sids` :7439 | true |
| "Pinned by `TestDispatchPathsAreDocumented` … if this subsection stops naming the path" | **refuted by injection** | **false → D3** |
| §6 lead: "exactly **two** argv builders" | R1 | true at `0cbc517` and at `c63d7dd` |

§11's new sentence is likewise true clause by clause of `_fleet_task_is_ours` (:5315-5358): resolved
script path (:5345), the token immediately after it (:5351, matching fleet's own
subcommand-first parser at :7731+), `--fleet-home` value (:5353-5358), whole quote-stripped
slash/case-normalized tokens (:5297-5312), never a substring.

## 5. Invariants (§16) the branch touches

- **2 — exit-0 hooks, "now four hooks".** *Strengthened.* Before this branch, the one session class
  that ran with **zero** hooks was the supervisor successor; now it runs with all four (R4). No
  invariant text needs changing.
- **6 — single-writer registry.** Intact: the successor gets no registry record and no hook writes
  `fleet.json` (both `_resolve_name`s are read-only, `stop_outcome.py:108`,
  `postcompact_journal.py:78`).
- **7 — one live session per name.** Intact and deliberately protected: §6.1 documents that the
  wedge-retry must *not* be inherited, because one re-dispatch of a successor is two live sessions
  on one incarnation id. The branch adds no retry.
- **8 — platform-adapter-only OS branching.** Held with one gap-note shortfall: `_fleet_task_is_ours`
  contains no OS branch of any kind and lives above the adapter, correctly:

  ```
  $ git grep -n 'os\.name|sys\.platform|IS_WINDOWS' 0cbc517 -- bin/fleet.py
  :260 :261 :268   (comments: the adapter is the ONLY permitted branch site)
  :379 :381        (comments)
  :382             PLATFORM = _WindowsPlatform() if os.name == "nt" else _PosixPlatform()
  ```
  Six hits, all in the adapter header block; **none** in :5290-5365. (A source-scan test in
  `tests/test_steering.py` already enforces this, per the comment at :381.) But its
  normalization is Windows-shaped in a second way the docstring does not name → **D8**.
  `_PosixPlatform` still raises (:357+), so the tracked gap the header already lists is unchanged.
- **9 — one-state-many-views.** Unaffected; see §6 below.

## 6. Doctrine conformance (CLAUDE.md / terminal-surface)

| rule | check | result |
|---|---|---|
| `bin/fleet.py` stdlib-only, single file | `git show 0cbc517:bin/fleet.py \| grep '^import\|^from'` → argparse, ctypes, functools, json, math, os, re, shutil, subprocess, sys, tempfile, time, uuid, contextlib, datetime, pathlib. Branch adds **no** import. | PASS |
| `py -3.13`, 3.10 floor where it could run there | new code uses only `re`/`Path`/slicing/`try/except ValueError`; no `match`, no walrus, no 3.11+ typing. Hooks untouched. | PASS |
| hook commands use forward slashes | template unchanged; new argv uses `instance_settings_path().as_posix()` (:7445) and `task_path.as_posix()` (:7450) | PASS |
| no Git-Bash `&` background launch | no shell invocation added; `run(argv, …)` list form only | PASS |
| runtime dirs gitignored, `knowledge/` tracked | branch touches neither | PASS |
| **views never probe / never take `fleet.lock` / never write** | `git grep -n '_fleet_task_is_ours\|_autoclean_task_is_ours\|_require_instance_settings\|_task_command_tokens\|_normalize_task_token' 0cbc517 -- bin/ commands/ skills/` → consumers are `_install_autoclean_task` (:5400) and the mutating verbs `cmd_spawn`/`cmd_send`/`_resume_one_limited`/`cmd_respawn`/`cmd_sup_handoff_begin` (:2291, :3349, :3524, :3969, :7407). **Zero hits in `bin/fleet_statusline.py`, `bin/hooks/`, `commands/`, `skills/`.** Nothing the branch added is reachable from `status_snapshot`, the statusline, `/fleet:*`, or the SessionStart hook. | PASS |
| mutating slash commands stay prompt templates | branch touches no file under `commands/`; lint present at `tests/test_terminal_surface.py:543` and **still able to catch a violation** — I appended `` !`py -3.13 bin/fleet.py status` `` to `commands/kill.md` in a scratch copy: `FAILED …::test_mutating_commands_never_inline_exec[kill] - kill is a mutating command and must not use inline !`` exec` (1 failed, 13 passed) | PASS |

## 7. Test doctrine

- **Real pins, not shape assertions.** R9's injection takes 5/6 + 5/5 red. The one green
  (`test_exactly_two_bg_argv_builders`) self-declares as a shape guard.
- **Weakness, not a defect:** `ARGV_BUILDER_RE = r'^\s*argv = \[exe, "--bg"'`
  (`tests/test_supervisor.py:907`) only catches a third builder written in that exact form —
  `argv = [claude_exe, "--bg"` or `argv = [exe] + ["--bg", …]` walks past it. §6.1 says the test
  "fails if a third `--bg` argv builder appears"; strictly, it fails if a third builder *in this
  shape* appears. Same over-claim family as **D3**, one notch weaker; fold into D3's reword.
- **No hard-asserted hook source.** No new test reads a hook script or asserts a hook's `source`
  field — the C2 revert+refix class is not re-opened.
- **No real machine state touched.** `sup_home`/`home` fixtures monkeypatch `fleet.FLEET_HOME` to
  `tmp_path` (`tests/test_autoclean.py:30-37`, `tests/test_supervisor.py:22-27`);
  `canonical_install` monkeypatches `_autoclean_script_path`; `platform_stub` replaces all three
  `PLATFORM.autoclean_task_*` methods — **no `schtasks` runs**, no `~/.claude` access, no dispatch.
  `TestDispatchPathsAreDocumented` reads `bin/fleet.py` and `docs/SPEC.md` from the repo — read-only,
  same pattern as the pre-existing `test_terminal_surface.py` lints.
- **Pre-existing round-trip coverage survives the change:**
  `test_own_task_recognized_slash_and_case_insensitive` (`tests/test_autoclean.py:750`) feeds
  `cmd.replace("\\","/").upper()` and still passes under the new predicate — the schtasks XML
  variance path is genuinely covered.

## 8. `SPURIOUS-FIX` verdict (mandatory)

**`ef0747f` — NOT SPURIOUS.** Filed verbatim by
`docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md:27` ("successor supervisor sessions have no
hooks at all today … Fix + SPEC correction owed regardless of three-tier's fate"). The defect was
real: at `c63d7dd`/`ac3e34d` the argv carried no `--settings` (R1). Extra beyond the filing: the
`_require_instance_settings()` pre-flight — not scope creep, it is what makes `--settings`
load-bearing (`claude` silently ignores a nonexistent settings path, so without it the fix would be
invisible when it failed). **Partially skipped:** the "SPEC correction" half — §12's `via
dispatch_bg` (**D2**) — and the doc-pin obligations (**D3**, **D4**).

**`0cbc517` — NOT SPURIOUS.** Filed by the adjudication :28 and specified by
`docs/reviews/THREE-TIER-DESIGN-REVIEW-2026-07-17-spec.md:778(ii)` ("a predicate that distinguishes
*which* fleet task it is looking at — fleet.py path **and** the verb"). Ships a superset (path +
verb + `--fleet-home`), justified in-commit and strictly tightening. It correctly did **not** take
on item (i) (generic `_install_scheduled_task`) or (v) (a doctor check for the new task) — those
belong to the three-tier build, which is operator-gated. **Partially skipped:** the sibling spec
(**D1**).

Neither commit fixes anything not asked for. Nothing was promoted: no `[PENDING OPERATOR
RATIFICATION]` row moved, no spec status changed — `git diff ac3e34d..0cbc517 --stat` is 4 files,
and `docs/specs/native-substrate.md` is untouched. **I promote nothing here either.**

---

## VERDICT: fix-wave(D1, D2, D3, D4)

Ship the code as-is. Before merge, one small doc-only wave:

1. **D1** — `docs/specs/autoclean.md:48`: full-identity ownership; extend
   `test_spec_states_full_identity_ownership` to pin that file too.
2. **D2** — `docs/SPEC.md:249`: successor dispatches on §6.1's path, not `dispatch_bg`; pin it.
3. **D3** — `docs/SPEC.md:187` or `test_spec_names_the_successor_dispatch_path`: make the sentence
   and the test agree; re-run the §6.1-deletion injection and confirm RED.
4. **D4** — pin §6.1 and §11's new text to an explicit commit; do not silently move §0's global pin.

Fold in **D5–D9** (one-line edits each) and hand **D10/D12** to the ledger. **D11** needs the
manager's `schtasks /Query` before the wave closes.

**Files changed by me:** this review file only. I edited no code, ran no mutating verb, and left no
process running.

---

# FINAL GATE — docs wave `97c980a`

**Gate run:** 2026-07-21, by `me-defects-spec`, against `me/defects @ 97c980a`
(`ef0747f` → `0cbc517` → `1c0eb42` → `97c980a` on base `ac3e34d`). Target worktree clean at
`97c980a`. Scope per the manager brief: **document truth only** — the break lens owns the code, the
injections and the M0 correction. `docs/NEXT-SESSION.md` (D10) untouched by ruling.

**VERDICT: merge.** All four MEDs are `FIXED` and D3 re-proves RED. Three new LOW doc nits (G1–G3)
are named below; none blocks, and **ESCALATE beats a third wave** — they belong in the ledger, or in
the merge commit if the builder is still live.

## Collateral — 0

```
$ git diff --name-only ac3e34d..97c980a
bin/fleet.py  docs/SPEC.md  docs/specs/autoclean.md  tests/test_autoclean.py  tests/test_supervisor.py
$ git status --short          (empty)
```
Five files, all in scope. No stray edit anywhere in the tree.

## Suite

Run by me on a `git archive 97c980a` export in a contained scratch dir:
`2 failed, 1171 passed, 6 skipped`. Both failures are the same `git ls-files` artifacts of exporting
without a `.git` (documented in R8 above; both files confirmed tracked). **1171 + 2 = 1173 passed,
6 skipped — the manager's number reproduces exactly.**

## Disposition, D1–D12

| id | verdict | evidence |
|---|---|---|
| **D1** | **FIXED** | `docs/specs/autoclean.md:48` rewritten to full identity, naming `_fleet_task_is_ours` and adding the forward rule ("Any new scheduled task must go through `_fleet_task_is_ours(command, <its own subcommand>)`, never a fresh path-only predicate") — more than I asked for, and the part that actually protects `--supervisor-beat`. Now pinned: `test_autoclean_design_spec_states_full_identity_ownership` (`tests/test_autoclean.py:845-858`) asserts `"runs our exact fleet.py path" not in design` and requires `_fleet_task_is_ours` / `--fleet-home` / `subcommand`. Residual → **G3**. |
| **D2** | **FIXED** | `docs/SPEC.md:252` now reads "on the sanctioned second dispatch path (§6.1), **not through `dispatch_bg`** — which cannot be used here and is refused at its own name guard if attempted". Pinned by `test_spec_12_does_not_claim_the_successor_uses_dispatch_bg`, which asserts both that "via `dispatch_bg`" is absent from §12 **and** that "§6.1" is present — so a future edit cannot quietly drop the cross-reference either. The replacement anchor `_render_successor_task` exists (`bin/fleet.py:7398`). |
| **D3** | **FIXED — re-proved RED** | see below |
| **D4** | **FIXED** | §6.1 carries an explicit `> **Pin:**` block naming itself *and* §11's scheduler-bridge bullet as descriptive of branch `me/defects`, not of §0's `c63d7dd`, and states why §0's global pin is deliberately left alone — the reasoning I asked for, adopted. Its two factual claims re-checked by me: at `c63d7dd` the successor argv was `[exe, "--bg", "-n", name]` (R1) and ownership was path-only (`git show c63d7dd:bin/fleet.py` :4949-4955 → `ours in (command or "")…`). One number in it is wrong → **G1**; discoverability residual → **G2**. |
| **D5** | **FIXED** | §6.1's heading drops `@7280` for the bare function name; the docstring's `@6631` becomes "the `NAME_RE`/`_SID_SHAPE_RE` check opening `dispatch_bg`". Durable anchors, per §0's own rule. Vindicated immediately: `def cmd_sup_handoff_begin` sits at 7280 / 7351 / **7418** across `ef0747f` / `0cbc517` / `97c980a` — a third move inside one branch. |
| **D6** | **FIXED** | see "§6.1 vs the shipped argv" below — exact match. |
| **D7** | **FIXED** | `docs/SPEC.md:188` now ends `[UNVERIFIED — whether the daemon propagates the launcher's environment into the hosted session is unobserved; …]`. Pinned by `test_spec_61_keeps_the_unobserved_hedge`. The spec is now the more careful of spec-and-docstring, which was the point. |
| **D8** | **FIXED** | `_fleet_task_is_ours`'s portability block now names **both** Windows-shaped normalizations and their opposite failure directions (`.lower()` → false MISS; the backslash rewrite → false MATCH, "the more dangerous direction"), still `[UNVERIFIED — no POSIX box; reasoned, not run]`. |
| **D9** | **FIXED** | doctor's dead-pin scan now tokenizes through `_task_command_tokens` — one tokenizer over the string instead of two (`bin/fleet.py:6053-6078`). The added `Path(tok).is_absolute()` narrowing is a real behavior change, disclosed in-comment with its reason (a relative token resolves against the scheduler's cwd, which fleet cannot know). The code lens owns the "no assertion weakened" claim. |
| **D10** | **NOT-FIXED (by ruling)** | `docs/NEXT-SESSION.md` is manager-owned and rewritten at campaign close. Not charged to this branch; confirmed untouched. |
| **D11** | **ADDRESSED** | the live task's command is now a verbatim literal fixture (`test_live_installed_task_command_is_ours`, manager-supplied via `schtasks /Query` 2026-07-21 — I did not and could not run it), and B11 makes the refusal message name the pre-F2 migration path explicitly. The builder disputes the M0 regression claim itself; **the break lens owns that adjudication**, not this gate. |
| **D12** | **NOT-FIXED** | form nit (a grep receipt in `ef0747f`'s message with no stated commit). Not fixable without rewriting a landed commit message; ledger item. |

### D3 — re-proved, the same way I disproved it

Same injection as before: `git archive 97c980a`, delete the entire `### 6.1 …` subsection up to
`## 7.`, change nothing else.

```
$ py -3.13 -m pytest -q -p no:cacheprovider tests/test_supervisor.py::TestDispatchPathsAreDocumented
3 failed, 4 passed in 0.47s
  test_spec_names_the_successor_dispatch_path   IndexError (split on "### 6.1")
  test_spec_61_records_the_mode_flag_decision   IndexError
  test_spec_61_keeps_the_unobserved_hedge       IndexError
```
Was `3 passed` at `0cbc517`. **RED.** `_subsection_61()` slices §6.1 alone and the assertions now
require the load-bearing tokens (`_worker_env`, `_require_instance_settings`, `supervisor-handoff-`,
`NAME_RE`), so hollowing the subsection fails as surely as deleting it.

**The wave also published a *new* claim about the same pin, so I tested that too.** §6.1's closing
sentence now asserts the builder-count guard "matches `--bg` inside **any** same-line list literal
and additionally asserts both hits sit in `dispatch_bg` and `cmd_sup_handoff_begin`, so a third
builder under any name — or one that *replaces* an existing builder, keeping the count at two — goes
RED." Both limbs, injected by me into separate `97c980a` exports:

```
(a) appended a real third builder under a different identifier:
        def _third_launcher(claude_exe, name):
            cmd = [claude_exe, "--bg", "-n", name, "hello"]
    -> 2 failed:  test_exactly_two_bg_argv_builders  (assert 3 == 2)
                  test_both_bg_argv_builders_live_in_the_documented_functions
                    (['_third_launcher', 'dispatch_bg'] != known)

(b) RELOCATED the successor builder into a new `_successor_argv()` helper --
    builder count unchanged at 2:
    -> 1 failed:  test_both_bg_argv_builders_live_in_the_documented_functions
                    (['_successor_argv', 'dispatch_bg'] != known)
```
Both limbs hold. The self-pin sentence is now true, which is what D3 was about.

## §6.1 vs the shipped argv — exact (B4/D6)

Published block (`docs/SPEC.md:178-183`) against `cmd_sup_handoff_begin`'s argv
(`bin/fleet.py:7538-7551`):

| published | shipped | |
|---|---|---|
| `claude --bg` | `argv = [exe, "--bg",` | ok |
| `-n "sup\|<inc>\|successor"` | `"-n", name`, where `name = f"sup\|{successor_inc}\|successor"` | ok |
| `--settings state/worker-settings.json` | `"--settings", instance_settings_path().as_posix()` (= `state/worker-settings.json`, @211-216) | ok |
| `[--model m]` | `if args.model: argv += ["--model", args.model]` | ok |
| `(--permission-mode p \| <mode_flags(SUCCESSOR_DEFAULT_MODE)>)` | `if args.permission_mode: … else: argv += mode_flags(SUCCESSOR_DEFAULT_MODE)` | ok — and the `(A \| B)` notation is exactly right: it is an `if/else`, so exactly one mode opinion ever reaches the argv |
| `"Read …/supervisor-handoff-<inc>.md and follow it exactly."` | `argv.append(f"Read {task_path.as_posix()} …")` | ok |
| `cwd=<FLEET_HOME>  env=_worker_env(…)` | `run(argv, cwd=str(FLEET_HOME), env=_worker_env(name), …)` | ok |
| "No `--add-dir` … and no `--setting-sources`" | neither appears in the argv | ok — the "deliberately does not carry" enumeration is now **complete**, which is what D6 was |

`SUCCESSOR_DEFAULT_MODE = "dontask"` (`bin/fleet.py:6964`) is the same fleet mode name
`p_spawn --mode` defaults to (:7734, verified last turn), and `mode_flags("dontask")` →
`["--permission-mode", "dontAsk"]` (:952), so the default branch really does emit a flag.
Corroborating — and the reason the choice matters — `docs/specs/native-substrate.md:76` records that
`--permission-mode acceptEdits` "does **not** auto-approve Bash tool calls — a Bash call under this
mode can sit pending, surfacing as roster `status: "waiting"`". The successor's first act is a Bash
call, so `acceptEdits` would have been the wrong default; `dontask` is contradicted by no substrate
row.

## Receipts re-run in the rewritten sections (15 groups)

A rewrite moves text out from under its receipt, so each of §6.1's bullets was re-attached:

1. **"all four hooks degrade cleanly … with no `hook-errors.log` entry on any of the four (verified
   empirically, hooks run as real subprocesses …)"** — this is a claim about an *experiment*, and no
   test in the suite performs it (`tests/test_supervisor.py` contains no `hook-errors` reference,
   and the wave touched only `test_autoclean.py` / `test_supervisor.py`). So I ran it myself: four
   real subprocesses, `FLEET_HOME` a scratch dir, `state/fleet.json` present but **not** containing
   the sid — a successor's exact situation:
   ```
   stop_outcome rc=0   stop_mailbox rc=0   posttooluse_mailbox rc=0   postcompact_journal rc=0
   state/hook-errors.log   -> does not exist
   artifacts written       -> state/outcomes/<sid>.jsonl, state/journals/<sid>.md
   ```
   **Independently reproduced.** (`tests/test_hooks.py` does exercise the hooks as real subprocesses
   and pins the sid-keyed fallbacks at :559/:607, so the class is covered; the four-at-once
   no-`hook-errors` run was not, and now has a receipt here.)
2. **`[UNBUILT — no sweep owns these]`** (B10) — the premise checks out and the tag is correctly
   applied. `cmd_clean` enumerates `names = sorted(data["workers"])` from `load_registry()`;
   `cmd_archive` likewise (`data = load_registry()` → `names = sorted(data["workers"])`). A
   successor has no record, so neither reaches the two files my probe above just produced. This is
   the branch's only new `[UNBUILT]` tag, it describes an *absence*, and the absence is grep-verified
   — the discipline §0 demands.
3. **B5 / "both external pre-flights run before the lock"** — `_require_instance_settings()` then
   `try: exe = resolve_claude_executable(which=which) / except ClaudeNotFoundError: raise
   FleetCliError(...)`, both above `with fleet_lock():` (`bin/fleet.py:7514-7519`). The bullet's
   supporting claim that the other post-lock caller `_fetch_agents_roster` "cannot raise through
   here" is true: it catches `ClaudeNotFoundError` and returns `(False, reason)` (:7186-7190).
4. **D4 pin-note claims** — both re-run (R1 for the argv; `c63d7dd:4949-4955` for path-only
   ownership).
5. Plus: collateral, full suite, D3 re-proof, both B3 guard limbs, the argv table above,
   `SUCCESSOR_DEFAULT_MODE`, D1's pin test, the `=VALUE` grep, the line-number series, and the
   cross-document sweep.

## Cross-document sweep

`docs/SPEC.md`, `docs/specs/autoclean.md`, `docs/specs/native-substrate.md`,
`docs/specs/terminal-surface.md`, `docs/specs/three-tier-command.md`, `skills/fleet/`, plus
`README.md` and `docs/concepts.md` for good measure:

```
$ grep -rn 'choke point|dispatch_bg|is_ours|exact fleet.py|path-only|permission-mode|no hooks|hookless' \
        docs/specs/ skills/ README.md docs/concepts.md
$ grep -rn 'one choke point|single choke point|only --bg|single --bg' docs/ skills/ knowledge/ README.md
$ grep -rn 'successor' docs/specs/ skills/ README.md docs/concepts.md
```
**No sentence in any of them is made false by this branch.** Specifically:

- `native-substrate.md:57/75/76` — the G-row dispatch argv is the substrate's flag inventory, not an
  ordering contract, and :76 *corroborates* the mode-flag fix rather than conflicting with it.
- `terminal-surface.md` — only hit is `statusLine` refresh triggers; unrelated. Nothing the branch
  added is reachable from a view path (re-confirmed at `97c980a`: `_task_command_tokens`'s one new
  consumer is `_doctor_check_autoclean`, a `doctor` check, not a view).
- `three-tier-command.md:1-3` — still `DRAFT PROPOSAL` / `PROPOSAL — RESTRUCTURE REQUIRED`.
  **Nothing promoted, by this branch or by me.**
- `skills/fleet/supervisor.md:14,55-61` — operational handoff steps; none asserts a dispatch
  mechanism or a hook state.
- The one remaining stale sentence in the tree is `docs/NEXT-SESSION.md:23`, reserved to the manager
  (D10). Correctly untouched.

## New findings (all LOW — ledger, not a wave)

- **G1 — a wrong number inside the sentence about numbers being wrong.** `docs/SPEC.md:168`: "the
  `@7280` this heading first carried was invalidated **74 lines later** by this branch's own second
  commit."
  ```
  $ for c in ef0747f 0cbc517; do git show $c:bin/fleet.py | grep -n 'def cmd_sup_handoff_begin'; done
  ef0747f -> 7280      0cbc517 -> 7351
  ```
  7351 − 7280 = **71**, not 74. *Fix:* say 71, or drop the figure — the sentence works without it,
  and it is the one sentence in the document arguing that line numbers should not be trusted.
- **G2 — D4's pin is correct but not discoverable where it is needed.** The `> **Pin:**` block sits
  in §6.1 and names §11's bullet by reference. A reader arriving at §11 (`:247`, untouched this
  wave) or at `docs/specs/autoclean.md:48` (rewritten this wave, carrying **no** pin of any kind)
  sees only §0's `c63d7dd` declaration — under which both texts are false, since ownership was
  path-only there. *Fix:* one clause at §11 ("pinned as in §6.1") and a one-line pin on
  `autoclean.md`'s Command-surface bullet.
- **G3 — the `--fleet-home=VALUE` spelling is accepted by the predicate and documented in neither
  spec.** `grep -c 'fleet-home=' docs/SPEC.md docs/specs/autoclean.md` → `0`, `0`, while
  `_task_command_tokens` deliberately splits it and `TestOwnershipQuotingVariants`
  (`tests/test_autoclean.py:925+`) fixes its acceptance **as a decision**. Both specs say ownership
  is "matched on whole, quote-stripped, slash/case-normalized tokens", which no longer fully
  describes the tokenizer. Same family as D1: the spec of record must be complete about what counts
  as ours, because that is exactly what the `--supervisor-beat` builder will copy. *Fix:* one clause
  in `autoclean.md` (and, if cheap, §11) naming the accepted and refused quoting forms.

## Doctrine, `[UNBUILT]`, promotion

- `[UNBUILT]` / prescriptive discipline on changed text: **clean.** One new tag
  (`[UNBUILT — no sweep owns these]`, receipt above), one restored `[UNVERIFIED]` (D7, pinned), no
  tag made false, none deleted rather than moved. `docs/SPEC.md` still carries exactly the
  pre-existing `[PRESCRIPTIVE]` at :8 and the §0 pin at :12.
- Doctrine table from the first review re-checked at `97c980a`: still stdlib-only (neither wave
  commit adds an import), forward slashes, no Git-Bash `&`, nothing new reachable from a view path,
  `commands/` untouched.
- **Nothing promoted.** No `[PENDING OPERATOR RATIFICATION]` row moved; `three-tier-command.md`
  still `PROPOSAL`; §0's global pin deliberately left in place. I ratified nothing.

## VERDICT: merge

Ship it. Fold **G1–G3** into the merge commit if the builder is still live, otherwise into the
ledger — three one-clause doc edits, none of which changes a claim's truth value for a reader who
follows the §6.1 pin. A fix-wave verdict for these would be the third wave, and **ESCALATE beats a
third wave**.

**Files changed by me this gate:** this review file only. No code edited, no mutating verb run, no
`schtasks`, nothing written outside `C:/proga/fleet-me-defects-spec`, no process left running.
