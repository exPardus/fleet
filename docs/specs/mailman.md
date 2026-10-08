# Spec: `fleet mailman` — the interface wakes only for mail it must act on

**Status:** implemented (`bin/fleet_mailman.py`, wired in `bin/fleet.py`; tests `tests/test_mailman.py`).
Supervisor rulings on the draft's open questions are folded in and recorded in §11. Where this
document and the code differ, the code is the authority.

**Inherits:** `docs/SPEC.md` (command surface §relay-ack/watch rows), `docs/specs/multi-fleet.md` §5
(verb-effect tiers), `docs/specs/terminal-surface.md` (views doctrine D4/D7), root `CLAUDE.md`
(pull-only, stdlib-only, Python 3.10 floor, receipts rule).

**Receipts.** Every `$ ` block below is pinned `# at 936af0a7` (the base of this branch) and is
re-executed by `tools/verify_receipts.py` / `tests/test_receipts.py`. Line numbers belong to that
commit, not to HEAD.

---

## 1. Problem

The interface session watches `mailbox/to-fleet/` with `fleet watch`, which reports the first mail
file it has not seen (`cmd_watch`, `_watch_mail_names`). Every landed-report, status note and FYI
therefore wakes the interface, and each wake costs a model turn and a relay in the operator's chat.
Only a minority of mail needs the interface to act: a question, a claim, a merge-ready or retract
notice, a blocker. The rest only needs to be acknowledged and remembered.

`mailman` is one blocking verb that does the sorting so that the interface sleeps through the rest.

## 2. What exists today (fit points)

The design reuses these; it does not reimplement them.

```
# at 936af0a7
$ grep -n "^def cmd_relay_ack\|^def cmd_watch\|^def _watch_mail_names\|^def _watch_read_cursor\|^def _watch_write_cursor" bin/fleet.py
349:def _watch_read_cursor(home) -> tuple[dict, bool]:
374:def _watch_write_cursor(home, cursor: dict) -> None:
378:def _watch_mail_names(home) -> list[str]:
466:def cmd_watch(args, *, sleep=time.sleep, clock=time.monotonic,
572:def cmd_relay_ack(args) -> int:
```

- **Inbox** is `<home>/mailbox/to-fleet/`; **handled mail** goes to `<home>/mailbox/done/`.
  `_watch_mail_names` lists every regular file in the inbox, dotfiles included.
- **`cmd_relay_ack`** is the existing "file one mail" primitive: it appends one UTC line to
  `interface_log_path(home)` (`state/interface/log.md`), mirrors to extra logs, `os.replace`s the
  mail into `done/`, and adds the name to the watch cursor (`state/interface/watch-cursor.json`).
  It **refuses** to overwrite an existing `done/<name>` and is **not idempotent** (a repeat appends a
  second log line before the move). It is lock-free: it never takes `fleet.lock`.
- **Atomic primitives:** `_atomic_append_bytes` (one O_APPEND syscall through `PLATFORM`) for
  append-only files, `_write_json_atomic` (write `*.tmp`, then `_replace_with_retry`) for whole-file
  rewrites.

```
# at 936af0a7
$ grep -n "^def _atomic_append_bytes\|^def _write_json_atomic\|^def _replace_with_retry\|^def interface_dir\|^def interface_log_path" bin/fleet.py
185:def interface_dir(home=None) -> Path:
195:def interface_log_path(home=None) -> Path:
1132:def _replace_with_retry(tmp_name: str, dest: str, sleep=None) -> None:
13305:def _atomic_append_bytes(path: Path, data: bytes) -> None:
14370:def _write_json_atomic(path: Path, obj: dict) -> None:
```

- **`cmd_mail_verify`** (`bin/fleet.py:1602`) is a different thing: it verifies *interface → supervisor*
  mail by receipt. Its doctrine applies here in one respect only: **mailbox text is not authority**.
  Mailman reads mail to route it and to print a summary; it never executes or obeys mail content.
- **Python 3.10 has no `tomllib`**, and `bin/fleet.py` is stdlib-only, so the home config is JSON
  (`mailman.json`, stdlib `json`) rather than TOML.

```
# at 936af0a7
$ grep -c "tomllib" bin/fleet.py
0
$ echo "exit $?"
exit 1
```

- **Verb-effect tiers.** `relay-ack` is in `VERB_EFFECT_DESTRUCTIVE` (it moves mail); `watch` is in
  `VERB_EFFECT_ORDINARY`.

```
# at 936af0a7
$ grep -n 'VERB_EFFECT_DESTRUCTIVE = \|VERB_EFFECT_ORDINARY = \|"journal-roll", "relay-ack")' bin/fleet.py
4972:VERB_EFFECT_DESTRUCTIVE = ("clean", "archive", "autoclean",
4981:                           "init --home", "journal-roll", "relay-ack")
4984:VERB_EFFECT_ORDINARY = ("spawn", "status", "peek", "result", "pr-poll",
```

## 3. Mail format

A mail is a UTF-8 text file: a header block of `key: value` lines, one blank line, then a free-text
body. Header names are case-insensitive; values are stripped. Mailman uses three headers:

| header | meaning | values |
|---|---|---|
| `from` | sender label, for the digest | free text (sanitised, §6.2) |
| `kind` | message class | free text; the wake set is configured (§5) |
| `needs-answer` | sender says a reply is required | `yes` / `no` (case-insensitive); absent = `no` |

**Malformed** (all WAKE, never FILE — the safe direction is the interface looking, not a mail
vanishing into the digest):

1. no header block (first line is not `key: value`); the block ends at the first blank line or at end of file;
2. `kind` missing or empty;
3. `needs-answer` present with a value other than `yes`/`no`;
4. not valid UTF-8, or empty file, or larger than `MAIL_MAX_BYTES` (1 MiB, the same bound as
   `MAIL_RECEIPT_MAX_BYTES`; oversize files are never read in full);
5. not a regular file (symlink, directory, fifo) — never followed, never moved;
6. a header line that is neither `key: value` nor blank before the terminating blank line.

Duplicate headers: for `needs-answer`, any `yes` wins; conflicting non-`yes` values are malformed.
For `kind`, the first occurrence is used and a differing second one is malformed.

**In-flight files.** Mailman ignores names starting with `.` and names ending in `.tmp`. Senders
(and the bridge hook, §7) must write `.<name>.tmp` in the inbox and `rename` into place; a half-written
file is otherwise indistinguishable from a malformed one and would wake. (`_watch_mail_names` and `relay-ack` do not
filter these; aligning them is future work.)

## 4. Verbs

```
fleet mailman init   --fleet-home H [--force]
fleet mailman run    --fleet-home H [--timeout S] [--interval S] [--dry-run] [--include-reported]
fleet mailman digest --fleet-home H [--since WHEN]
```

`--fleet-home` is required and explicit on every verb (no env/legacy fallback), as for `relay-ack`;
without it the verb refuses.

`init` writes the seed `mailman.json` (§5) into the home atomically and refuses to overwrite an
existing file without `--force`.
Both follow the existing parser conventions (`_watch_timeout_arg`/`_watch_interval_arg`: finite,
non-negative timeout; interval > 0).

### 4.1 `mailman run`

One pass, in order:

1. **Load rules** (§5). A missing or invalid `mailman.json` is **not** an error exit: the pass runs in
   *fail-safe mode*, says why on stderr (`FAIL-SAFE, waking on every mail: <reason>`), WAKEs on every
   mail and files nothing. The bridge hook is not run in fail-safe mode.
2. **Bridge hook** (§7), if configured. Failure is recorded, never fatal to the pass.
3. **Sort** every inbox name (sorted order): classify (§6.1) → WAKE or FILE.
4. **File** every FILE mail (§6.2–6.3).
5. **Report** WAKE mails not yet reported (§6.4): print their absolute paths, one per line, to stdout;
   exit 0.
6. If there are none: sleep `--interval` (default 30 s) and repeat from 2, until `--timeout` seconds
   have elapsed since start, then exit **3**. No `--timeout` blocks indefinitely. `--timeout 0` is
   exactly one pass (the non-blocking probe).

Exit codes: **0** wake (paths on stdout), **3** timeout, **4** bridge unhealthy (§7), **1** error.
stdout carries paths only; reasons and counters go to stderr, e.g.
`WAKE <path> reason=pattern:blocker`, `filed 7 mails`.

`--dry-run`: runs steps 1 and 3 only, prints one `FILE|WAKE <name> reason=…` line per mail to stdout,
mutates nothing (no bridge, no files, no state), exit 0. This is the rule-tuning tool.

`--include-reported`: print every wake mail currently in the inbox, not only unreported ones
(re-listing after an interface restart). Still exits 3 on timeout if there are none.

### 4.2 `mailman digest`

A read-only rollup of FILED mail. `--since WHEN` accepts an ISO-8601 UTC timestamp or a duration
`<n>m|h|d`; default `24h`. Output: a one-line header (`N filed since <ts>`), counts by `kind` and by
`from`, then entries oldest first. Duplicate entries (same marker, §6.3) are printed once. An absent
or empty `digest.md` prints `no filed mail since <ts>` and exits 0. A torn trailing line (no marker)
is ignored. Digest **writes nothing, creates no directory, takes no lock** — it is a view in the
D4 sense (it reads a file that exists or reports that it does not).

## 5. Wake rules live in the home

Rules are read from `<home>/mailman.json` on every pass (edit while running; no restart). The file
is created by `fleet mailman init`, which writes the seed below. **No rule exists in code at run
time**: the seed constant is only what `init` writes. A missing or unparseable file puts `run` in
fail-safe mode (§4.1 step 1): it wakes on everything and says why.

```json
{
  "wake": {
    "kinds": ["question", "claim", "design-question"],
    "needs_answer": true,
    "ignore_case": true,
    "patterns": ["merge-ready", "retract", "do-not-merge", "blocker",
                 "founder action", "CRITICAL", "\\bP0\\b"]
  },
  "bridge": {"command": [], "timeout_s": 60, "max_failures": 5},
  "digest": {"summary_max": 160}
}
```

- **Format.** JSON (stdlib `json`; Python 3.10 has no `tomllib`). Unknown tables or keys and wrong
  types are config errors, which means fail-safe mode.
- **`patterns`** are Python `re` expressions matched per line with `re.search` over the **body only**
  (everything after the header block). Header fields are ruled separately (`kind`, `needs-answer`),
  so a `subject:` header cannot wake. An entry is a string or
  `{"pattern": "...", "unless": ["regex", ...]}`: a line wakes only if the pattern matches it and no
  `unless` regex matches the same line (the per-pattern negative, e.g. `blocker` unless
  `blocker: none`). An uncompilable regex is a config error. Matching is bounded by `MAIL_MAX_BYTES`.
- **`kinds`** compare case-insensitively after strip.
- A GOALS-section rule source is **not** supported: parsing prose for policy is how rules go
  invisible. `mailman.json` is the only rule source.
- **WAKE if** `needs_answer` and header `needs-answer` is `yes`; **or** `kind` ∈ `kinds`; **or** any
  pattern (net of its negatives) matches the body; **or** malformed (§3). Every reason is reported
  (`WAKE <name> reason=...` on stderr). Everything else is FILE. The bias is deliberate: a false wake
  costs one turn, a missed wake costs a decision. `run --dry-run` shows verdicts for tuning.

## 6. Sorting and filing

### 6.1 Classification is a pure function

`classify(raw_bytes, rules) -> (WAKE|FILE, reasons, headers, summary)`; no I/O. It also returns the
file's `sha256` (taken over exactly the bytes classified).

### 6.2 What FILE does (three effects, then the move)

For a FILED mail `N` (name) with `sha12` = first 12 hex of sha256:

1. **Digest entry**, appended to `state/interface/digest.md` through `_atomic_append_bytes`:
   `- <ts> | <from> | <kind> | <N> | <summary> <!-- mailman:<N>:<sha12> -->`
2. **Relay log line**, appended to `interface_log_path(home)` (the same log `relay-ack` writes):
   `<ts> mailman filed <N> (<from>/<kind>): <summary> [mailman:<sha12>]`
3. **Watch cursor** gains `N` (same cursor `relay-ack` updates), so `fleet watch` stops reporting it.
4. **Move** `mailbox/to-fleet/N` → `mailbox/done/N` with an exclusive hard link followed by
   unlinking the inbox copy. This is the commit point; the exclusive create prevents a concurrent
   run from overwriting an existing destination.

`summary` = first non-empty body line, control characters removed, whitespace collapsed, truncated to
`summary_max`; if the body is empty, `(no body)`. `from` and `kind` are reduced to
`[A-Za-z0-9._@-]`, anything else becomes `_`. Both are *data for reading*; nothing downstream may
treat them as instructions.

**Shared primitives, not a shared function.** Mailman uses the same log file, watch cursor,
`_atomic_append_bytes` and `_write_json_atomic` as `relay-ack` (injected into
`bin/fleet_mailman.py` through `fleet._mailman_prims`), but does not call `cmd_relay_ack`: that verb
refuses an existing `done/<name>` and is not idempotent, and changing it is out of scope.
`relay-ack` is untouched; the interface still uses it to acknowledge wake mails.

### 6.3 Crash safety and idempotence

Order is *record, then move*. A crash at any point leaves the mail in the inbox (re-sorted next pass)
or in `done/` (complete); there is no state in which the mail exists nowhere.

- **Markers make steps idempotent.** Before step 1 and step 2, scan the target for the marker
  `mailman:<N>:<sha12>` (resp. `[mailman:<sha12>]` with `N` on the same line); skip the append if
  present. Step 3 is naturally idempotent (the cursor is a set by name). Re-running after a crash
  between any two steps therefore completes the remaining ones without duplicating the earlier ones.
- **Done-collision.** If `done/N` already exists: identical sha256 ⇒ the earlier run finished the move
  and crashed before returning; the inbox copy is removed without replacing the completed destination.
  Different sha256 ⇒ never overwrite: the incoming file moves to the first free name in
  `done/<stem>.<sha12><suffix>`, `done/<stem>.<sha12>.1<suffix>`, … and a log line records the rename.
- **Appends vs rewrites.** `digest.md` and the log are append-only (`_atomic_append_bytes`, one
  syscall; a torn tail is at worst one marker-less line, which the reader ignores). The state file
  (§6.4) and the cursor are whole-file rewrites through `_write_json_atomic` (write temp, then rename).
  The move is an exclusive link plus unlink. Nothing is truncated in place.
- **Re-check before move.** Immediately before step 4, re-read the file and compare sha256 with the
  classified one; a mismatch (the mail changed under us) aborts that mail's filing and leaves it for
  the next pass. A mail that classified WAKE is never passed to step 1–4 at all (§6.5).
- **Lock-free.** Mailman takes no `fleet.lock` (like `relay-ack` and `watch`). Two concurrent runs are
  safe: the second exclusive link finds the source gone (`FileNotFoundError`) and treats it as filed;
  the worst case is one duplicate digest line, which `digest` collapses by marker.

### 6.4 State: "already reported" wake mails

`state/interface/mailman-state.json` (`_write_json_atomic`):

```json
{"schema": 1,
 "reported": {"<name>": "<sha12>"},
 "bridge": {"last_run": "<ts>", "last_rc": 0, "consecutive_failures": 0}}
```

A wake mail stays in `to-fleet/` until the interface `relay-ack`s it, so without memory every later
`run` would return instantly on it. `reported` records `name → sha12` for wake mails already printed;
a changed sha re-wakes. The order is **print and flush, then persist**: a crash between the two
re-prints (a duplicate wake), never drops. Entries whose file is gone from the inbox are pruned each
pass. A lost or unreadable state file resets to empty: every pending wake mail is printed again.
Mailman never writes `reported` for a mail it did not print.

### 6.5 A wake mail is never filed

Enforced structurally: `classify` returns the verdict; only `FILE` verdicts reach the filing helper;
the helper takes the classified verdict object as an argument and asserts `verdict == FILE` before any
write. There is no "file anyway" flag. The interface acts on a wake mail by running `relay-ack` on it,
exactly as today.

## 7. The pluggable pull/bridge hook

`[bridge].command` is an argv list (no shell). Before each pass mailman runs it with
`cwd=<home>`, `FLEET_HOME=<home>` in its environment, stdin closed, stdout discarded, stderr tail
(≤ 2 KiB) kept for the state file, and a `timeout_s` deadline after which the child is killed. It is
not detached and not backgrounded (CLAUDE.md: no `&`; this is a bounded foreground child).

Contract with the hook: it delivers pulled mail into the inbox using the in-flight convention of §3
(`.name.tmp` then rename). Mailman does not interpret its output and does not know what it pulls
from; the repo ships no peer/kz specifics, only this seam.

Failure: non-zero exit, timeout or spawn error increments `consecutive_failures`; the pass proceeds
to sort what is already local. When `consecutive_failures ≥ max_failures`, `run` prints
`BRIDGE-FAILED <rc|timeout|spawn> <n>x` to stderr and exits **4** instead of sleeping on, so a dead
bridge cannot look like "no mail". Success resets the counter.

## 8. Doctrine: a verb, not a hook

- Mailman runs **only when invoked** by the interface (typically under `run_in_background`, as
  `fleet watch` is). It registers nothing, installs no hook, injects nothing into any session,
  starts no daemon. It is pull-only.
- It is **not a view**: it moves files. `mailman` is deliberately in no verb-effect tuple, so
  `verb_effect_tier("mailman")` returns the fail-safe default, `destructive` (multi-fleet §5: an
  unclassified verb is destructive), and every subcommand requires an explicit `--fleet-home`.
  `digest` is read-only in behaviour but shares the tier; adding tuple tokens would also have to
  change the ratified-table pin file, which this feature does not need.
- Views stay views: statusline and `/fleet:*` never call mailman and never read `digest.md` or
  `mailman-state.json` as a precondition; `fleet.status_snapshot()` is unchanged. `digest` honours
  D4 (no write, no lock, no quarantine) and exits 0 on absent files.
- It never reads `state/fleet.json`, never takes `fleet.lock`, never writes the registry.

## 9. Files touched

| file | change |
|---|---|
| `bin/fleet_mailman.py` | new leaf module: config, `classify`, filing, state, bridge, `cmd_run`/`cmd_digest`/`cmd_init` |
| `bin/fleet.py` | `mailman` subparser (`init`, `run`, `digest`), `cmd_mailman`, `_mailman_prims`, dispatch |
| `tests/test_mailman.py`, `tests/fleet_sources.py` | tests; the new module joins the implementation source census |
| `docs/SPEC.md`, `skills/fleet/SKILL.md` | command rows |

Local operator data written at run time lives under the home's ignored paths (`mailman.json`,
`state/interface/…`, `mailbox/…`); none of it is tracked.

## 10. Test plan

Tests use pytest, a temporary fleet home, and fake `clock`/`sleep` injection as `cmd_watch` does;
no network, no real hook binary beyond a tiny Python script in `tmp_path`.

**Required (mapped from the feature list):**

| # | test | asserts |
|---|---|---|
| T1 | `test_filing_is_lossless` | A FILE mail ends with: one log line (`mailman filed <N>`), one digest entry (same marker), the file in `done/` byte-identical, absent from `to-fleet/`, name in the watch cursor. |
| T2 | `test_wake_mail_is_never_filed` | For every WAKE cause (needs-answer yes; each kind; each default pattern; malformed), the file stays in `to-fleet/` untouched, no digest entry, no log line, path printed, exit 0. Plus a direct test that the filing helper refuses a WAKE verdict. |
| T3 | `test_crash_mid_sort_never_loses_a_mail` | Inject a failure after each of steps 1, 2, 3 and just before/after the move (monkeypatched helper raising `OSError`/`KeyboardInterrupt`); at every point the mail exists in exactly one of inbox/`done`; a re-run completes the filing. |
| T4 | `test_rerun_is_idempotent` | Run twice and with a crash replay: digest and log each hold exactly one line per mail; `done/` has one file; no `done/` collision rename for identical bytes. |
| T5 | `test_malformed_headers_wake` | Cases 1–6 of §3 each wake, none filed. |
| T6 | `test_timeout_exit_3` | Empty/only-FILE inbox with `--timeout 0` and with a fake clock: stdout empty, exit 3; FILE mails still filed during the pass. |

**Behaviour pins:**

| # | test | asserts |
|---|---|---|
| T7 | `test_rules_come_from_the_home`, `test_bad_or_missing_config_wakes_on_everything`, `test_body_only_patterns_and_negatives` | A `mailman.json` changes verdicts; a missing/invalid file wakes on every mail, files nothing and says why; patterns are body-only with per-pattern negatives. Source-scan: no wake word outside the seed constant. |
| T8 | `test_reported_wake_not_reprinted` | Second `run` skips a reported wake mail; `--include-reported` lists it; a changed sha re-wakes; lost state file re-prints. Print-before-persist ordering (a crash after print re-prints). |
| T9 | `test_done_collision_never_overwrites` | Pre-existing different `done/N`: incoming goes to `done/<stem>.<sha12><suffix>`, both survive. |
| T10 | `test_changed_mail_not_filed` | File rewritten between classify and move: left in inbox, not moved. |
| T11 | `test_inflight_files_ignored` | `.x.tmp`, `*.tmp`: not classified, not moved, not woken. |
| T12 | `test_unsafe_files_wake` | Symlink, directory, oversize: wake, never read in full / followed / moved. |
| T13 | `test_bridge_hook` | Hook argv runs with `cwd=home` and `FLEET_HOME`; mail it delivers is sorted in the same pass; non-zero/timeout does not abort the pass; `max_failures` consecutive failures exit 4; success resets. |
| T14 | `test_digest_view` | `--since` as duration and ISO; counts; dedupe by marker; absent file exits 0; torn tail ignored; the home tree is byte-identical before/after (no write, no mkdir, no lock). |
| T15 | `test_dry_run_mutates_nothing` | Tree hash identical before/after; no bridge spawned. |
| T16 | `test_init_seeds_config_and_refuses_overwrite` | `init` writes the seed, refuses overwrite, `--force` overwrites; `test_requires_explicit_fleet_home`. |
| T17 | `test_mailman_takes_no_registry_lock` | No `fleet_lock`/`fleet.json` in the module; `verb_effect_tier("mailman")` is `destructive` by default. |
| T18 | `test_py310` | Collected and passing under 3.10 and 3.12 (no `tomllib`, no 3.11+ syntax). |

**Receipt convention.** Receipts in this document and in the build's doc updates are `# at <sha>`
pinned; any receipt about the working repository carries `# live: <reason>`, external evidence
`# volatile: <reason>`. `tests/test_receipts.py` must pass; an unclassifiable block is a failure.
The build wave adds a post-build receipt block (`grep -n "def cmd_mailman_run" bin/fleet.py`) pinned
to the build commit, as `autoclean.md` does.

**Gates for the build PR:** `uv run --no-project --python 3.10 --with pytest python -m pytest -q`
and the 3.12 equivalent over `tests/test_mailman.py`, `tests/test_interface_watch.py`, `tests/test_docs_currency.py`, `tests/test_receipts.py`,
`tests/test_views_doctrine.py`.

## 11. Rulings on the draft's open questions (supervisor)

1. No wake rules in code: `fleet mailman init` seeds the home config; a missing or unparseable config
   makes `run` wake on every mail and say why (§4.1, §5).
2. `watch --no-mail` is out of scope. **Future work:** an interface using both `watch` and `mailman`
   is still woken by `watch` for any mail it sees first.
3. Exit 4 on a persistently failing bridge hook is accepted and documented (§4.1, §7).
4. Patterns match the body only; header fields are parsed and ruled separately; malformed headers
   wake (§3, §5).
5. `.tmp` files and dotfiles in the inbox are ignored (§3). Aligning `watch`/`relay-ack` is future work.
6. Per-pattern negatives (`unless`), configured in the home (§5).
7. `digest` defaults to the last 24 h (§4.2).
8. Config format is JSON (`mailman.json`), not TOML.
