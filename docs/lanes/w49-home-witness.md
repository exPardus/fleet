# `w49/home-witness` — the parked `fleet doctor` row, and what it would cost to land it

**Status: PARKED on an operator ruling.** Nothing on this branch is broken and nothing on it is
being thrown away. It is here because a `fleet doctor` row is a public surface and this one was
built from a derivation rather than from a ratified sentence — and because, independently of who
authorised it, the row as written has one shipped defect and three unpinned design decisions.

**Read this if:** you are the operator returning to docket gate 4, or you are a successor who was
not here and has been told "the home-witness row is parked on a branch."

- **Branch:** `w49/home-witness`, forked at **`1161d39`** — the exact sha the `w48-gc` gate measured.
- **Base:** `fa236cb`.
- **Sibling:** `w48/hookargv` continues from the same sha **with the row removed**. Everything else
  in slice (c) — the hook argv work, `_render_successor_task`'s argv, the `_render_sup_spawn_task`
  sibling fix — lives there and lands there.
- **Evidence:** the build report is `docs/lanes/w48-c.md` on this branch (§0 and §3 are the
  derivation); the gate is `git show w48/gc:docs/lanes/w48-gc.md` (findings 2, 3 and 6).

---

## 1. What this branch holds that `w48/hookargv` will not

All of it is at `1161d39`. Line numbers are that sha's.

| what | where |
|---|---|
| `_doctor_check_home_witness()` — 72 lines, ~40 of them the docstring that argues the derivation | `bin/fleet.py:11252–11323` |
| its registration, one `functools.partial`, deliberately placed third of the three instance rows | `bin/fleet.py:12564` |
| `TestTheHomeWitness` — **4 tests**, plus the `rendered_home` fixture and the `_FakeVersion` stub they alone use | `tests/test_hook_fleet_home_argv.py:397–507` |
| the doctor check count bumped `28 → 29` at **7 of its 8 sites**: `README.md` ×3, `docs/getting-started.md` ×3 (one of them the `N PASS / 0 FAIL` sentence), `docs/launch-readiness.md` ×1. The **8th** — `docs/launch-readiness.md`'s own `N PASS / 0 FAIL` — was missed, which is the gate's finding 1 | those three files |
| the derivation and the escalation that went with it | `docs/lanes/w48-c.md` §0a–§0d, §3 |

The other 74 tests in `tests/test_hook_fleet_home_argv.py` are the hook-argv work and are **not**
part of this parking — they go with the slice.

**What the row does.** It reads `<home>/state/worker-settings.json` — the instance `fleet init`
renders — extracts the `--fleet-home` value baked into each of its four hook commands, and compares
that value against `FLEET_HOME`. Disagreement means every worker this home dispatches runs hooks
that drain mailboxes and file outcomes into a *different* home, while every surface in this home
still reads this home and sees nothing wrong. Report-only, like every other doctor row.

**Nothing else in the tree can see that state.** `instance-freshness` compares mtimes and is a known
false alarm; `instance-grants` compares grant lists. Neither compares homes. That is the row's case
for existing, and the gate did not dispute it.

---

## 2. The gate's finding 2 — MAJOR, governance. Why the row is parked and not merged.

Substance of `w48-gc` §1 finding 2, and the operator's ruling on top of it:

**The lane's reading was sound and it misread nothing.** MEASURED by the gate with a control: in
`docs/specs/multi-fleet.md` at `fa236cb`, the word `witness` occurs **exactly twice** — line 143
(§5 step 1's flag/lookup witness, which Sequencing §3 assigns to slice **(a)**, and which (a)
shipped) and line 707 (the slice-(c) list itself, the phrase being interpreted). The control: `home`
occurs 199 times in the same file, so the grep was not silently matching nothing. **No third
occurrence, and no sentence anywhere in the spec defines a hook- or successor-plane witness.**
§3's word *"disjoint"* is verbatim in the spec, so slice (c)'s witness genuinely cannot be slice
(a)'s line.

**The objection is not that the reading is wrong — it is that deriving a public surface from prose
is origination.** When a slice's own name contains a term the ratified document never defines, the
in-scope act is to build the two parts that ARE defined (`hook argv`, `_render_successor_task argv`)
and **escalate the third**. The lane escalated *one* reading — a runtime hook-side witness record,
`docs/lanes/w48-c.md` §0d — and **built** another, the one it derived itself. Escalating the reading
you reject while shipping the reading you prefer is not the same as escalating the question.

**And a new doctor row is not an internal detail.** Its count is restated in three shipped
documents across **eight** sites in two phrasings, so adding one is a multi-site documentation edit
by construction — and that edit is what produced the gate's finding 1: seven sites were updated and
the eighth was not, leaving `docs/launch-readiness.md` reading *"29 checks … goes to 28 PASS / 0
FAIL"* inside one bullet, self-contradictory, with the pin that exists to stop exactly this
structurally blind to the second phrasing.

**Graded fairly by the gate, and worth repeating here:** the derivation quotes real sentences (the
cross-fleet interference audit's *"donor facts; fenced by hook argv"*; this file's own established
meaning of the word at `_doctor_check_identity_witness` — *"THE REGISTRY JUDGES, THE ENVIRONMENT
ONLY WITNESSES"*). The row is report-only. It PASSes on a fresh `fleet init` (measured). It
correctly declines to duplicate the instance rows' fault — measured: in a pre-`init` run it PASSed
with a NOTE while the three instance rows FAILed. And the lane disclosed all of it unprompted.
**This is MAJOR as governance, not as defect. Nothing here is wrong; it is unauthorised.**

---

## 3. The gate's finding 3 — MAJOR, defect. Why it would not be ready to land even if authorised.

Substance of `w48-gc` §1 finding 3. This is the half that decides the parking on merit, and it is
independent of the governance question.

The row is a **third parser of the `--fleet-home` option string** — `bin/fleet.py:11302`:

```python
found = re.search(r'--fleet-home\s+"([^"]*)"', command)
```

— and it agrees with neither of the other two. The lane's own §1b makes a point of the hook grammar
*deliberately* matching `strip_global_fleet_home`, because *"a hook that disagreed with `fleet.py`
about its own flag's spelling would be drift by construction."* The row is that drift.

### The four properties. One is a shipped defect; three have no pin.

| # | property | state | evidence |
|---|---|---|---|
| **P1** | the row recognises **one of the three `--fleet-home` spellings its own hooks accept** | **SHIPPED DEFECT** | driven by the gate |
| **P2** | `os.path.normcase` on both sides of the home comparison | correct in code, **UNPINNED** | mutant X2 survived the full 4217-test floor |
| **P3** | an empty `--fleet-home ""` is not "fenced" | correct in code, **UNPINNED** | mutant X4 survived the full floor |
| **P4** | the row is registered immediately after `instance-grants`, third of the three instance rows | as documented, **UNPINNED** | mutant X5 survived the full floor |

**P1 — the shipped defect, measured.** The gate fed the same instance command to the hook's real
`_argv_fleet_home()` and to the doctor row:

```
space + quotes  (what the template renders)   HOOK: resolves home   DOCTOR: [PASS]   agree: True
--fleet-home=C:/.../home  (hook accepts it)   HOOK: resolves home   DOCTOR: [FAIL]   agree: False
space, unquoted (a hand edit)                 HOOK: resolves home   DOCTOR: [FAIL]   agree: False
```

A **correctly fenced instance is reported as unfenced**, with a remedy (`re-run fleet init`) that
would not fix it. That is a permanently-red row — the precise harm the lane's own §3 cites when it
refuses to route witnesses to `hook-errors`. Reachability is narrow and the gate checked it:
`template_settings_path()` is hard-wired to `INSTALL_ROOT / "worker-settings.template.json"` with no
override, so reaching it needs an edited clone template rather than a supported config knob. That is
what keeps it MAJOR-with-a-narrow-mouth rather than blocking.

**P2 — reachable on Windows without tampering.** Mutant X2 replaced
`os.path.normcase(b) != os.path.normcase(here)` with a raw `b != here` and **survived**
`4217 passed, 14 skipped, 1 xfailed in 394.50s`, with the immediately preceding clean floor green.
Driven, the mutant turns a same-home-different-case bake into a false `LEAK:` on a correctly
configured home. `here` is `FLEET_HOME.as_posix()` and `FLEET_HOME` can arrive un-resolved from the
environment, so the case difference is ordinary, not contrived. **The `normcase` is load-bearing and
nothing holds it.**

**P3 — a message-quality gap, NOT a fail-open.** Worth stating precisely, because the gate nearly
graded it wrongly from an armchair reading and corrected itself by driving it: with an empty baked
value, **both shipped and mutant FAIL**. The mutant only degrades the remedy — the actionable
*"unfenced … re-run `fleet init`"* becomes an unactionable `LEAK -> ['']`.

**P4 — the argument has no pin behind it.** `TestCmdDoctorRegistersNewChecks`
(`tests/test_native.py:5190`) pins only the `pin-version` and `tzdata` positions. The row's docstring
and the registration comment both argue that *"the three instance rows read as one answer"*; nothing
in the suite holds that ordering.

### And one more, MINOR — the gate's finding 6

A CR-suffixed baked home produces a FAIL whose two paths render **identically**:

```
[FAIL] home-witness: LEAK: this home is C:/.../home, but its own settings instance
       dispatches hooks at C:/.../home -- every worker launched from here drains mailboxes ...
```

The row correctly *detects* it — a real mitigation the base does not have — but renders the `\r`
invisibly, so the operator reads a leak between two identical strings and cannot act. Given this
campaign's four CRLF-shaped instrument failures, a `repr()`-style rendering of a mismatching value
would be cheap.

---

## 4. The re-land recipe

**Do not merge this branch as it stands.** In order:

**Step 0 — the ruling.** The operator answers docket gate 4: is a `fleet doctor` row derived from
undefined spec prose authorised at all? If **no**, this branch is evidence and closes here; the
question of what slice (c)'s "witness" was meant to be returns to the spec (`docs/lanes/w48-c.md`
§0d holds the alternative reading — a runtime hook-side witness record — which is unbuilt). If
**yes**, continue.

**Step 1 — rebase onto landed `main`.** `w48/hookargv` will have merged by then, and it removes the
row and returns every doc-count site to `28`. Expect the conflicts to be exactly there: the
`_doctor_check_home_witness` body, its `functools.partial` line, `TestTheHomeWitness` + its fixture
+ `_FakeVersion`, and the seven `28`/`29` doc sites. Take **this** branch's side in all of them.
Nothing else on this branch differs from what `w48/hookargv` lands.

**Step 2 — fix P1, and do it by sharing the grammar, not by widening a third regex.** The remedy the
gate names is *"one regex covering `=`, unquoted, and single-quoted forms — or better, reuse the
grammar the hooks and `fleet.py` already share."* Prefer the second: the whole objection is that this
is a third independent parser of one option string. `strip_global_fleet_home` and the hooks'
`_argv_fleet_home()` are the two that already agree; the row should call one of them, not imitate
them.

**Step 3 — pin P2, P3 and P4.** Three tests. Each must be watched RED with the property mutated
before being trusted — all three of these decisions survived a full 4217-test floor, which is
exactly what "unpinned" means and exactly why a green run is not evidence here.

**Step 4 — fix finding 6.** Render a mismatching value through `repr()` (or otherwise make a
trailing `\r` visible) so the FAIL line is actionable.

**Step 5 — the doc-count edit, and check the pin first.** Adding the row back moves the count
`28 → 29` at all **eight** sites, not the seven this branch changed. `w48/hookargv` widens
`tests/test_doc_claims.py`'s pin to also hold the `N PASS / M FAIL` phrasing, so the two
second-phrasing sites are held once that lands — but re-derive the site list by grep rather than
trusting this table. The gate's whole lesson on finding 1 is that an author's enumeration of their
own change is a claim about what they remembered.

**Step 6 — floors.** Both interpreters, `py -3.13` and `py -3.10`. The floor is 3.10, not this
machine's 3.13 preference. Derive the expected count by `pytest --collect-only -q` on both sides,
never by arithmetic on a diff and never by counting `def test_` lines.

---

## 5. Numbers a successor will want, all measured at `1161d39`

- `bin/fleet.py`: 21,533 lines (base `fa236cb`: 21,438).
- `tests/test_hook_fleet_home_argv.py`: **78 tests collected**, of which **4** are `TestTheHomeWitness`.
- Full floor on this branch, both interpreters: `4217 passed, 14 skipped, 1 xfailed`.
- `fleet doctor` on a fresh home with this branch's `bin/fleet.py`: **29 rows**, `25 PASS / 4 FAIL`
  before `fleet init`, **`29 PASS / 0 FAIL`** after. (`w48/hookargv` measures 28 in both places.)

**This branch is not maintained.** It is a parked artefact at a fixed sha. Do not push it, do not
merge it, and do not treat its floor numbers as current after `w48/hookargv` lands.
