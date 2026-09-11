# Adversarial design review — fleet-index

**Target:** `docs/superpowers/specs/2026-07-22-fleet-index-design.md` (341 lines, as of `c991cd4`)
**Reviewer:** `idx-adv2`, hostile brief
**Repo state:** branch `fleet-impl`, HEAD `c991cd4`; `bin/fleet.py` is the implementation checked against
**Vantage of every receipt below:** worktree `.claude/worktrees/idx-adv2-review` reset `--hard` to `fleet-impl` (`c991cd4`), design doc byte-identical to the reviewed copy. Scratch git repos under `$CLAUDE_JOB_DIR/tmp/`.

**Result: 10 defects — 2 CRITICAL, 5 HIGH, 2 MED, 1 LOW.** Not shippable as one milestone.

---

## Trap 1 — the impossibility claim (§2)

### Verdict: DEFECT — MED

The **conclusion** survives; the **stated mechanism is false**, and the false mechanism is what makes §6.3 pick the worst available delivery channel.

§2 says:

> Prompt caching does not bridge them: the cache is prefix-keyed, and every worker's prefix differs (name, task text, journal), so file content sitting mid-context never hits a shared entry.

Name, task text and journal are **not in the prefix**. They are not in the prompt at all.

```
bin/fleet.py:7379-7381   tasks_dir().mkdir(...); task_path = task_file_path(name)
                         task_path.write_text(prompt_body, encoding="utf-8")
bin/fleet.py:7385        tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
bin/fleet.py:7407        argv.append(tiny_prompt)
```

`compose_prompt`'s entire output — preamble, mailbox, task, journal — is written to a **file on disk**. The string handed to `claude` is a single short sentence. Everything §2 names as prefix-varying therefore arrives as a `tool_result` from the worker's first `Read`, i.e. *mid-context*, which is exactly the position §2 says cannot be shared.

The real prefix for N workers spawned into the same `--dir` is the Claude Code system prompt, the tool schemas, and the target project's `CLAUDE.md` — byte-identical across those N workers. The only argv-level differences are `-n <rendered name>`, `--resume`, mode flags and `--model` (`bin/fleet.py:7386-7407`), none of which are model-prefix content.

**Why this breaks.** §2's framing is used in §6.3 to justify putting `map.md` inside the task file. That is the one place in the whole launch path where content is guaranteed *never* to be shared and is re-paid in full by every worker on every dispatch. A shared, always-identical channel that reaches every worker in a project demonstrably exists — this reviewing session received `C:\proga\claude-fleet\CLAUDE.md` without `compose_prompt` being involved — which also falsifies §6.3's load-bearing sentence:

> `compose_prompt` is the only channel that reaches workers.

**What the design would have to change.** §2 must stop asserting an API property it never tested and instead state the mechanism it can prove from this repo: the composed prompt is delivered as a tool result, so it is per-worker by construction. Whether a shared-prefix channel (project `CLAUDE.md`, or an equivalent) is cheaper for `map.md` than a per-worker task-file paste is a measurable question and the design must answer it with a receipt before choosing §6.3's placement.

*Honest limit on this finding:* I can prove where fleet puts the bytes. I cannot produce a repo witness for Anthropic's cache-sharing semantics, and neither can the design — which is the point. §2 asserts an unmeasured external property as settled fact and builds a delivery decision on it.

---

## Trap 2 — index-in-git under parallel workers

### Verdict: DEFECT ×2 — one CRITICAL, one HIGH

### 2a. `symbols.tsv`'s sort key produces merge conflicts at **N = 2**. CRITICAL

§5.2 sorts `symbols.tsv` **by name then path**. That interleaves every file's symbols throughout the whole file, so a change confined to one source file produces edit hunks scattered across the entire TSV. Two workers on *completely disjoint files* then collide.

Reproduced with this repo's real symbol table — 2090 symbols extracted by `ast` from the 24 tracked `.py` files, three commits, two branches, disjoint source files (`tests/test_native.py` vs `bin/hooks/stop_outcome.py`):

```
# live: scratch repos under $CLAUDE_JOB_DIR/tmp, built from this repo's real symbols
$ cd "$CLAUDE_JOB_DIR/tmp/mrg" && git merge A 2>&1 | tail -2
Auto-merging symbols.tsv
CONFLICT (content): Merge conflict in symbols.tsv
```

Control — identical symbols, identical two edits, **sorted by path instead of name**:

```
# live: same scratch construction, sort key changed to (path, line)
$ cd "$CLAUDE_JOB_DIR/tmp/mrg3" && git merge A 2>&1 | tail -3
Merge made by the 'ort' strategy.
 symbols.tsv | 1132 +++++++++++++++++++++++++++++------------------------------
 1 file changed, 566 insertions(+), 566 deletions(-)
```

The sort key is the entire cause. Path-sorted merges clean; name-sorted conflicts.

**Why this breaks.** `knowledge/lessons.md:24` states fleet's load-bearing concurrency rule:

> Disjoint-file parallelism is safe (hooks + docs + core in parallel, exact-path staging, index.lock retry); same-file parallelism is not — sequence all `bin/fleet.py` work.

A committed, name-sorted `symbols.tsv` converts **every** parallel campaign into a same-file campaign, because every code change dirties it. `knowledge/lessons.md:103` records 7-wide disjoint-file parallelism as a proven capability; this design retires it. Quantified answer to the brief's question: **it bites at 2 workers**, not at some larger threshold.

**What the design would have to change.** Either sort by path (and pay a worse grep-locality story), or shard per directory, or stop committing the symbol table. §5.2's stated reason for name-sorting — grep locality — is a query-side convenience traded against fleet's central concurrency invariant, and §5.2 never mentions the trade.

### 2b. A working-tree refresh leaves a tracked file dirty, breaking the worktree recipe. HIGH

§5 makes `.fleet-index/` git-tracked by default (`gitignore = false`, §7). §6.4 authorises `fleet q` to write it "working-tree only." Git does not have a "working-tree only" mode for a tracked file — it just means *dirty*.

`knowledge/lessons.md:251` is the campaign-3/4 recipe, verbatim:

> `git worktree add -b <br> ../wt HEAD` per task → `fleet spawn --dir <wt> --mode bypass` → `fleet wait --all` (background) → review → merge → **`git worktree remove`** + `branch -d` + `kill`.

The last step now fails:

```
# live: scratch repo demonstrating git's own refusal
$ cd "$CLAUDE_JOB_DIR/tmp/wtdemo" && git worktree remove ../wtdemo-wt; echo "exit $?"
fatal: '../wtdemo-wt' contains modified or untracked files, use --force to delete it
exit 128
```

The only thing modified in that worktree was `.fleet-index/symbols.tsv`.

Compounding: `CLAUDE.md` states the repo's own rule — "Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored; `knowledge/` is git-tracked" — and `.gitignore` confirms it:

```
# live: this repo's ignore rules
$ cat .gitignore
state/
logs/
mailbox/
__pycache__/
*.pyc
.superpowers/
supervisor/INCARNATION
supervisor/HANDSHAKE
```

`.fleet-index/` is a runtime-mutated directory. §5 tracks it by default, against the repo's own stated split.

---

## Trap 3 — does the arithmetic work?

### Verdict: DEFECT — HIGH. There is no task mix in *this* repo where the always-on map is clearly net-positive, and the design ships it always-on anyway.

Measured, this repo:

| quantity | value | how |
|---|---|---|
| `bin/fleet.py` | 436,914 chars ≈ **109,228 tok**, 8,706 lines | `py -3.13` char count; §7's chars/4 estimator |
| whole indexable corpus (tracked `*.py` + `*.md`) | 4,002,989 chars ≈ **1.00M tok**, 113 files | `git ls-files '*.py' '*.md'` |
| markdown share of indexable files | **88 / 113** | same |
| `map.md` cap | 2,000 tok (§7 default) | §7 |

**The break-even, stated with assumptions.**

Let `M` = map tokens injected (≤2000), `D` = dispatches per worker (spawn + steers + respawns), `S` = orientation tokens the map actually saves. The map is net-positive iff `S > M × D`.

Assumption 1 — `D > 1`. `compose_prompt` is not spawn-only:

```
bin/fleet.py:2470   prompt, _claim = compose_prompt(args.name, cwd, task, None)          # spawn
bin/fleet.py:3408   prompt, claim = compose_prompt(name, cwd, "", old_sid)               # idle-send
bin/fleet.py:3545   prompt, claim = compose_prompt(name, cwd, "", old_sid, journal_path=journal_path)
bin/fleet.py:4028   prompt, claim = compose_prompt(name, cwd, task_for_record, old_sid, journal_path=journal_path)
```

and `bin/fleet.py:3410-3412` dispatches that with `resume_sid=old_sid` — the **same session**. So an idle-send re-emits the whole preamble, and would re-emit the map, into a context that already contains it. A worker steered six times pays `6 × 2000 = 12,000` map tokens for zero new information. §5.4 calls the map "a fixed per-spawn cost." It is per-dispatch. (Counted separately as defect 8 below.)

Assumption 2 — what `S` actually is. `map.md` is §5.4 "directory tree plus **one line per file**." It is file-granular. It cannot tell a worker where `compose_prompt` is; that is `symbols.tsv`, which is **not injected**. But this repo's orientation cost is overwhelmingly *inside one 8,706-line file*, and 88 of 113 indexable files are markdown. So the map answers "what files exist" — a question `Glob`/`ls` answers for ~0 tokens — and does not answer "where is the thing," which is the question §1 opens with.

Assumption 3 — the counterfactual read. §1 asserts "A worker that Reads it to find one function pays for all of it." No worker does that. `Read` is offset/limit-capable and workers grep first. A realistic orientation on `bin/fleet.py` is 2–3 `Grep` calls plus 1–2 windowed `Read`s ≈ 3k–8k tokens, not 109k. §1's headline number is the cost of a behaviour that does not occur.

**Where it lands.** With `D = 1` and a task whose files the manager already named, `S ≈ 0` and `M = 2000` → strictly negative. With `D = 4` (one spawn, three steers — ordinary for a babysat worker) the map must save 8,000 tokens to break even, which requires it to prevent roughly one full windowed read of `bin/fleet.py` *per dispatch*. It cannot, because it does not carry symbol coordinates.

The map is defensible only where `D = 1`, the worker has no named target, and the repo is wide and shallow (many small files). That is the opposite of this repo, and §11 already states the manager names files explicitly.

**Self-indictment in the document.** §10b ranks the cut order if the milestone shrinks:

> the order to cut is `relevance` degradation first, **then `map.md`**, then `fleet q`, keeping digest injection last — it is the piece with the clearest ratio

The author already ranks `map.md` as the second-weakest component, and ships it as the only *always-on, every-worker* cost in the design. Digest injection — ranked best, and gated behind an explicit `--context` — is the one the arithmetic supports.

**What the design would have to change.** `map.md` must be opt-in per spawn (a flag, or `--context`-triggered), not always-on; or §7's default cap must drop to a size where being wrong is cheap. A 2000-token default that the design's own priority ordering ranks second-to-cut is not defensible.

---

## Trap 4 — adoption

### Verdict: DEFECT — CRITICAL. Adoption is not merely unlikely; `fleet q` is **blocked** for the default spawn mode.

§6.2 says:

> Permission grants stay subcommand-scoped per the CLAUDE.md rule (`Bash(fleet q:*)` is read-only and safe to allowlist broadly …)

The design never says *where* that grant is added, and the file that would carry it ships without a permissions block at all:

```
# live: the git-tracked template `fleet init` renders into state/worker-settings.json
$ cat worker-settings.template.json
{
  "hooks": {
    "PostToolUse": [{ "hooks": [{ "type": "command",
      "command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/posttooluse_mailbox.py\"" }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/stop_outcome.py\"" }, { "type": "command",
      "command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/stop_mailbox.py\"" }] }],
    "PostCompact": [{ "hooks": [{ "type": "command",
      "command": "\"{{PYTHON}}\" \"{{FLEET_HOME}}/bin/hooks/postcompact_journal.py\"" }] }]
  }
}
```

No `permissions` key. And the default spawn mode is not `bypass`:

```
bin/fleet.py:8478   p_spawn.add_argument("--mode", choices=list(MODE_FLAGS), default="dontask")
```

So the default worker runs under `dontAsk` with an empty allowlist. `bin/fleet.py` already documents what that does to an unauthorised tool call, in the comment that motivated `--add-dir`:

```
bin/fleet.py:7390-7395
    # T12 fix wave (finding 1): the task file lives under FLEET_HOME/tasks,
    # virtually always outside the worker's own --dir cwd -- under any
    # non-bypass mode the worker's first Read on it hangs forever on an
    # unapprovable headless permission prompt. --add-dir pre-authorizes
    # tasks_dir() specifically (least privilege -- never FLEET_HOME wholesale).
```

`fleet q` is the identical failure class one layer up, and the design proposes no equivalent of `--add-dir` for it.

**How `_PREAMBLE_TEMPLATE` is actually consumed** (the brief's specific question): it is `parts[0]` of `compose_prompt` (`bin/fleet.py:945`), whose output is written to a task file (`bin/fleet.py:7381`) that the worker reaches only via `Read` (`bin/fleet.py:7385`). The teaching lines therefore arrive **inside a tool result**, not as an instruction in the user turn — the weakest position in the context for a behavioural directive. This review's own task file confirms it: `state/tasks/idx-adv2.md:1-5` is `_PREAMBLE_TEMPLATE` (`bin/fleet.py:909-914`) rendered verbatim.

The preamble is 5 lines today. §6.3's "+ ~4 lines" nearly doubles it, and competes against `Read`/`Grep` — always present, zero learning cost, and named in the model's own tool schemas, which sit in the *system* region that the preamble does not.

**What the design would have to change.** `worker-settings.template.json` must gain a `permissions.allow` entry for `Bash(fleet q:*)`, and that is a change to a git-tracked hook-wiring template with its own freshness gate (`bin/fleet.py:5876-5891`, `instance-freshness` doctor check) — every existing install must re-run `fleet init`. That is a migration the design does not mention. Until it exists, ship only the injection half; the query half is dead weight.

---

## Trap 5 — the staleness split

### Verdict: DEFECT — HIGH. Not the race the brief guessed, but a worse one: **no lock is specified anywhere**, and §9's recovery undoes §8's correctness argument.

**Whose hash wins across worktrees: nobody's.** §5 puts the index at `<project>/.fleet-index/`, and dispatch is cwd-scoped (`docs/SPEC.md:280`, invariant 5 — "Every dispatch runs with `cwd=<registered cwd>` (immutable after spawn)"). Two workers in two worktrees have two different `<project>` roots and therefore two independent indexes. There is no cross-worktree clobber — and equally no cross-worktree *sharing*, so N workers each rebuild the same index. That is duplicated work in a design whose entire premise is removing duplicated work, and §6.4's table does not acknowledge it.

**The real race is single-directory concurrency, which fleet does run.** `knowledge/lessons.md:103` records "7-wide parallel disjoint-file commits: zero index.lock casualties" in one checkout. All seven share one `.fleet-index/`. §8 gives `fleet q` write authority with **no lock, no atomic-replace, no ordering** — the words do not appear in §6.2, §6.4 or §8. And because §5.2 sorts by *name*, one file's symbols are scattered through the whole table, so a single-file refresh is necessarily a **whole-file rewrite**. Concurrent whole-file rewrites are lost updates and torn reads.

This matters because §9's recovery is exactly wrong for it:

> | Index corrupt | Same as missing — malformed lines are skipped, not fatal. |

A torn write does not produce malformed lines. It produces **missing well-formed lines** (truncation), which is indistinguishable from "symbol not found," and a partially-flushed line can still present six valid tab-separated fields with a wrong `line`/`end`. §8 states the consequence in its own words:

> **a stale line number does not error.** It silently slices the wrong code, and the worker has no way to detect it.

§9 reintroduces precisely that, and calls it a handled failure mode. The two sections contradict.

Note the contrast with fleet's existing discipline: `bin/fleet.py` guards its own state with `fleet_lock()` and `_atomic_append_bytes` (`bin/hooks/stop_outcome.py:208`). The design gives its new writer neither.

**Can unreviewed coordinates land in a committed artifact?** Not via the worker's own commit — `knowledge/lessons.md:24` mandates exact-path staging, so `.fleet-index/` stays out (which is why 2b's dirty-worktree break happens instead). But §6.4's gated update is `fleet index update --paths <files touched by the merge>`, i.e. **path-scoped**. Any entry a refresh wrote for a file that was edited and then reverted, or for an untracked scratch file, is outside `--paths` and is never repaired. Nothing in the design enforces the invariant §6.4 claims — "the committed index describes reviewed code." It is a convention with no check. `fleet index status` reports stale files (§6.1) but staleness is hash-vs-worktree, not committed-vs-reviewed; it cannot see this class.

**One more, unstated:** §6.2 says `fleet q` "never writes source files and never touches fleet state." True, and it obscures the actual novelty — `fleet q` is the **first fleet subcommand that mutates a git-tracked file in a user's own repository**. The `--no-refresh` escape exists but is not the default. That deserves an explicit statement and a decision; §6.2 gives it a parenthetical.

---

## Trap 6 — verified claims about the codebase

### Verdict: DEFECT — HIGH. Six of eight cited facts are wrong, including every one used to build the worked example.

```
# at c991cd4
$ grep -n "^def compose_prompt\|^def dispatch_bg\|^def mailbox_dir\|^_PREAMBLE_TEMPLATE" bin/fleet.py
69:def mailbox_dir() -> Path:
909:_PREAMBLE_TEMPLATE = """You are fleet worker `{name}` in `{cwd}`.
917:def compose_prompt(name: str, cwd, task: str, sid: str | None, journal_path=None) -> tuple[str, Path | None]:
7357:def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
```

```
# at c991cd4
$ wc -l bin/fleet.py
8706 bin/fleet.py
```

```
# at c991cd4
$ py -3.13 -c "import ast;t=ast.parse(open('bin/fleet.py',encoding='utf-8').read());[print(f'{n.name}\t{n.lineno}\t{n.end_lineno}') for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name in ('compose_prompt','dispatch_bg','mailbox_dir')]"
mailbox_dir	69	70
compose_prompt	917	972
dispatch_bg	7357	7573
```

| Design claim | Where cited | Actual | Verdict |
|---|---|---|---|
| `bin/fleet.py` is **7832** lines | §1 ×3, §5.1, §5.3, §10b | **8706** | WRONG |
| `compose_prompt` @ **887** | §5.2, §6.2 ×2, §6.3, §10a | **917** | WRONG |
| `compose_prompt` sig `(name, task, sid) -> str` | §5.2, §5.3, §6.2 | `(name: str, cwd, task: str, sid: str \| None, journal_path=None) -> tuple[str, Path \| None]` | WRONG |
| `compose_prompt` end **946** | §5.2, §6.2 | **972** | WRONG |
| `dispatch_bg` @ **6621**, end **6702** | §5.2, §5.3 | **7357**, end **7573** | WRONG |
| `dispatch_bg` sig `(worker, prompt_body) -> int` | §5.2, §5.3 | `(name, cwd, prompt_body, mode, model=None, category=None, hint="", resume_sid=None, settings_path=None, setting_sources=None, run=…, which=…, sleep=…, roster_fetch=None, clock=…)` | WRONG |
| `mailbox_dir` @ **69**, end **71** | §5.2, §5.3 | **69** ✓, end **70** ✗ | HALF |
| `_PREAMBLE_TEMPLATE` @ **879** | §6.3 (via the brief) | **909** | WRONG |
| `compose_prompt` assembles four sources, preamble → mailbox → task → journal | §6.3 | ✓ `bin/fleet.py:945, 951, 960, 970` | **CORRECT** |

**Why this breaks.** These are not incidental prose citations. §5.2 and §5.3 present them as the design's *worked example of the artifact itself* — three sample `symbols.tsv` rows and a sample digest. Not one of the three rows is fully correct: wrong start line, wrong end line, wrong signature, in a file whose stated line count is also wrong. The design's demonstration of "exact derived facts — real signatures, real line numbers — never summaries treated as truth" (§3.1) is a hand-written summary treated as truth. §10a then reuses the same wrong coordinate as the argument for why the index does not duplicate `CLAUDE.md`:

> this is generated structural fact ("`compose_prompt` is at `bin/fleet.py:887`")

It is neither generated nor fact.

**What the design would have to change.** Every §5.2/§5.3/§6.2 example must be produced by running something, pinned per the repo's receipt convention, or replaced with obviously-synthetic placeholders (`foo`, `bar.py`) that make no claim about this repo. Hand-written examples that look like index output are the one thing this design must not contain.

---

## Trap 7 — receipt-format collision

### Verdict: DEFECT — HIGH. Exhaustive enumeration below.

**Parser contract** (`tools/verify_receipts.py:224-238, 241-287`): every line whose lstrip starts with ` ``` ` toggles block state (language tags included, per gap 3); inside a block, a line starting with `$ ` becomes a `Receipt`; subsequent non-`$` lines become its expected stdout; `# at `, `# live`, `# volatile` at line start are pin directives. `tests/test_receipts.py` runs `check(..., strict=True, skip_volatile=True)`.

**The design has 12 fenced blocks. Exactly 2 parse as executable receipts. Both fail today:**

```
# live: the harness, run against the design as written
$ py -3.13 tools/verify_receipts.py --strict docs/superpowers/specs/2026-07-22-fleet-index-design.md; echo "exit $?"
shell: C:\Program Files\Git\bin\bash.exe
root:  C:\proga\claude-fleet\.claude\worktrees\idx-adv2-review
=== docs/superpowers/specs/2026-07-22-fleet-index-design.md ===
FAIL  line 161 [UNPINNED]: fleet q compose_prompt
      UNPINNED: no `# at <sha>` and not marked `# live` -- would be checked against the working tree, which any unrelated commit can rot
FAIL  line 168 [UNPINNED]: fleet q compose_prompt --src
      UNPINNED: no `# at <sha>` and not marked `# live` -- would be checked against the working tree, which any unrelated commit can rot

0/2 receipts reproduce exactly (12 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 2 FAILED)
exit 1
```

Adding pins does not save them — I injected `# at 52b7432` into both blocks in memory and re-ran `check()`:

```
FAIL  line 162 [pinned @ 52b7432]: fleet q compose_prompt
      output line 1
      EXPECTED: 'bin/fleet.py:887  func  compose_prompt(name, task, sid) -> str'
      ACTUAL:   None
FAIL  line 170 [pinned @ 52b7432]: fleet q compose_prompt --src
      output line 1
      EXPECTED: 'bin/fleet.py:887-946'
      ACTUAL:   None
```

`ACTUAL: None` rather than an error string, because:

```
# live: the subcommand does not exist, and argparse writes to stderr
$ fleet q compose_prompt; echo "exit $?"
exit 2
```

(the `usage:` / `invalid choice: 'q'` text goes to stderr, which the harness never captures — `tools/verify_receipts.py:72-77`, gap 1). So the receipt reads as a silent empty-output mismatch, the least diagnosable failure shape the harness has.

**Per-construct enumeration — exactly which constructs collide:**

| # | Block (line, §) | Contains `$ `? | Fate under `--strict` |
|---|---|---|---|
| 1 | 60–70, §4 architecture ASCII | no | inert |
| 2 | 82–86, §5.1 `files.tsv` | no | inert |
| 3 | 94–99, §5.2 `symbols.tsv` | no | inert |
| 4 | 112–119, §5.3 ` ```markdown ` digest | no | inert (tagged fence handled, gap 3) |
| 5 | 129–134, §6.1 CLI synopsis | no | inert |
| 6 | 153–156, §6.2 flag synopsis | no | inert |
| 7 | **160–163, §6.2 default output** | **yes** | **FAIL** — unpinned; wrong coordinate/signature baked into expected output (trap 6); still fails after `fleet q` ships |
| 8 | **167–171, §6.2 `--src` output** | **yes** | **FAIL** — unpinned; expected line 3 is the placeholder `<actual source of those 60 lines>`, which is not a transcript and can *never* match |
| 9 | 181–188, §6.3 composition list | no | inert |
| 10 | 190–192, §6.3 spawn example | no | inert **by one character** — `fleet spawn foo …` is prose; `$ fleet spawn foo …` would be a third failing receipt |
| 11 | 215–222, §6.4 ordering arrow-chain | no | inert |
| 12 | 234–243, §7 ` ```toml ` | no | inert — **conditionally**. Its `#` comments are trailing (`max_tokens = 2000        # hard cap on map.md`). Any reflow that moves a `# at …`, `# live …` or `# volatile …` comment to column 0 inside a fence is silently consumed as a pin directive with no warning (`tools/verify_receipts.py:244-254`). |

**Structural collision, independent of content.** `tests/test_receipts.py:35` sets `SPEC_DIR = REPO/"docs"/"specs"` and `_all_specs()` globs `*.md` — **non-recursive**. So:

- Leaving the design at `docs/superpowers/specs/` keeps it entirely outside the harness. That is the "green-while-blind" hole `tests/test_receipts.py`'s own docstring says the file exists to close.
- Moving it to `docs/specs/`, as `CLAUDE.md` implies for a spec, reddens the suite immediately:

```
# live: design copied into docs/specs/, suite run, copy removed
$ cd .claude/worktrees/idx-adv2-review && cp docs/superpowers/specs/2026-07-22-fleet-index-design.md docs/specs/ && py -3.13 -m pytest tests/test_receipts.py -x -q 2>&1 | tail -3; rm -f docs/specs/2026-07-22-fleet-index-design.md
E       AssertionError: spec(s) neither receipt-enforced nor declared in UNENFORCED: ['2026-07-22-fleet-index-design.md']. Add pinned `# at <sha>` receipts, or add an entry to UNENFORCED in this file stating why not.
FAILED tests/test_receipts.py::test_every_spec_is_classified - AssertionError: spec(s) neither receipt-enforced nor declared in UNENFORCED...
1 failed, 1 passed in 1.92s
```

**Second-order problem the design will hit even after `fleet q` exists.** Pinned receipts execute inside a `git archive` export of the pinned commit (`tools/verify_receipts.py:147-159`) — a tree with no `.git`. `fleet` resolves from `PATH` (`/c/proga/claude-fleet/bin/fleet`), so a pinned `$ fleet q …` receipt runs **today's** `fleet` against an **old** tree, and reads that tree's committed `.fleet-index/`. Whether that composition is stable is an open question the design has not asked.

**What the design would have to change.** Illustrative CLI output must not be written in `$ cmd` / output form, or must carry a pin plus real captured stdout. And the design has to state which directory it lands in and take the corresponding consequence — a pinned receipt set, or an `UNENFORCED` entry with a reason.

---

## Trap 8 — everything else

### 8a. §5.4's "fixed per-spawn cost" is false — it is per-dispatch. DEFECT — MED

§5.4: "This is the artifact injected into **every** worker, so its size is a fixed per-spawn cost."

`compose_prompt` is called on four paths, three of which are not spawns:

```
bin/fleet.py:2470   spawn
bin/fleet.py:3408   cmd_send idle-resume     -> dispatch_bg(..., resume_sid=old_sid)   [3410-3412]
bin/fleet.py:3545   respawn / resume-limited
bin/fleet.py:4028   fork-steer
```

Line 3410-3412 dispatches with `resume_sid=old_sid`, i.e. into the *same* session that already holds the map. A steered worker re-pays the full map on every steer for zero information. The design must either move the map out of `compose_prompt` or make it spawn-only, and §5.4's sentence must be corrected either way.

### 8b. §10c's invariant-4 argument does not hold on the idle-send path. DEFECT — MED

§10c claims invariant 4 is preserved because "the journal … retains final position; index material is inserted ahead of the task."

On the idle-send path the journal is not composed at all:

```
bin/fleet.py:3408   prompt, claim = compose_prompt(name, cwd, "", old_sid)
```

No `journal_path`. Compare `3545` and `4028`, which do pass it. So on a steer the map would be injected with *no journal present* — the ordering guarantee §10c relies on simply does not exist on that path. §10c argues only the respawn case and generalises.

### 8c. Success criterion 1 is not measurable with shipped telemetry. DEFECT — LOW

§12.1: "issues measurably fewer orientation Reads." Fleet's outcome record carries no tool-call data:

```
bin/hooks/stop_outcome.py:203-206
        record = {"ts": …, "session_id": sid, "kind": "result", "result_text": text,
                  "input_tokens": tokens_in, "output_tokens": tokens_out,
                  "model": model, "transcript_path": transcript_path}
```

`transcript_path` makes it *recoverable* by hand-parsing the transcript, but no fleet command does, and §10's test plan adds none. As written, criterion 1 cannot be evaluated, which means the milestone has no acceptance test for its headline claim.

### 8d. `--context` path resolution is unspecified — noted, not scored

§6.3's example is `fleet spawn foo --dir /c/proj --task @task.md --context bin/fleet.py,docs/SPEC.md`. Manager-relative or `--dir`-relative? §10c lists invariant 5 (cwd-scoped dispatch) as untouched, but `--context` introduces a second cwd frame at the manager. Not a defect until the resolution rule is written down; it must be written down.

### 8e. Section numbering — cosmetic

§10a/§10b/§10c are appended after §10 *Testing* and are not sub-parts of it. Renumber before this becomes a citable spec.

---

## Verdict

**Not shippable as one milestone. Restructure — do not reject.**

The core idea is sound and correctly argued against its strongest objection: a hash-keyed tag file is not a rotting tag file, and §3.1's refusal of embeddings is right. Three things are wrong with the *milestone*, not the idea:

1. **Two components have opposite economics and opposite risk, and are bundled.** `--context` digest injection is defensible (opt-in, targeted, and the design's own §10b ranks it best). Always-on `map.md` is not, at this repo's shape (trap 3). `fleet q` cannot execute for the default spawn mode (trap 4). Bundling them means the weak two block the strong one.

2. **Committing the index is the single most damaging decision in the document** and it is made on an aesthetic argument ("reviewability was the reason for choosing a text format," §5). It costs fleet its proven 7-wide disjoint-file parallelism at N=2 (trap 2a), breaks the documented worktree teardown recipe (trap 2b), and creates an unlocked multi-writer on a file whose corruption mode §8 itself identifies as undetectable and §9 then waves through (trap 5). Nothing else in the design depends on the index being committed.

3. **The document does not meet this repo's own evidence bar.** Six of eight code citations are wrong (trap 6), the wrong ones are exactly the values used to demonstrate the artifact, two blocks fail the receipt harness today and cannot be made to pass without being rewritten (trap 7), and §2 asserts an untested external API property that the repo's own dispatch path contradicts (trap 1). By `CLAUDE.md`'s standard — "a pasted command+output block is a claim until something re-runs it" — this design is currently a set of claims.

**Suggested split, for the author to accept or reject:**

- **M1 (small, defensible):** indexer + `.fleet-index/` **gitignored**, `--context` digest injection only. No `map.md`, no `fleet q`, no committed artifact, no concurrency question, no permissions migration. Measurable against §12.2 and §12.3.
- **M2:** `fleet q`, gated on `worker-settings.template.json` gaining `Bash(fleet q:*)` and on the `fleet init` migration that implies.
- **M3:** `map.md`, opt-in per spawn, shipped with the break-even measurement §12.1 currently cannot produce.
- **Committing the index:** a separate decision, requiring a path-sorted table, an atomic-replace writer, and an answer for `git worktree remove`.

Before any of it: re-derive every citation in §5.2/§5.3/§6.2 by running something, and pin it.
