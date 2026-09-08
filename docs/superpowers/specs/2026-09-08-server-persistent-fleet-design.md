# Persistent fleet on a headless server — design

**Status:** DRAFT for operator review (2026-09-08). Brainstormed in-session against the live host; every host fact below was measured on 2026-09-08 and is `# volatile` by nature.
**Scope:** one machine (`kz-work`, `/home/altai`), one fleet home (`/home/altai/proga/fleet`), one operator. Multi-machine and multi-operator are out of scope.
**Operator rulings folded in (2026-09-08, in-session):**
1. The liveness timer **pages only**. It never dispatches a supervisor body. The 2026-07-27 doctrine ("nothing in fleet watches for the command tier's absence; the operator relaunching their session IS the trigger") is *narrowed*, not overturned: an external timer may *observe and page*, and the trigger for revival stays a human message.
2. Outbound notification goes **only through the ccgram-bound interface window**. No second Telegram client, no direct Bot API calls from fleet.
3. The server-side interface session runs in **bypass** permission mode.

## 1. Goal

An operator hands the fleet long-running, multi-day, multi-project work from a phone, walks away, and comes back to a fleet that is either still working or has told them precisely why it stopped. The fleet keeps one identity across bodies, reboots and login expiries; it folds what it learned into `knowledge/` on a cadence the operator does not have to remember; and every silent-death mode the journal has recorded (12h53m, 15h, 3h38m) becomes a Telegram message within one timer period.

Non-goals: rewriting fleet on the Agent SDK; driving fleet workers as tmux windows; a web UI; auto-respawn of anything; any change to the three-tier command doctrine.

## 2. What is already there (measured 2026-09-08)

### 2.1 Fleet

- Supervisor identity persists in `supervisor/INCARNATION` (claim), `supervisor/JOURNAL.md` (append-only, kinds BOOT/CHECKPOINT/…/RELEASED), `supervisor/GOALS.md` (operator-owned). Bodies are `claude --bg` sessions; a body at its context band hands off to a successor (`sup-handoff-*`) or releases (`sup-release`). Ceilings: supervisor 350–400k, worker 250–300k.
- Workers are native `--bg` sessions dispatched through the single choke point `dispatch_bg`; the four hooks in `worker-settings.template.json` write `state/outcomes/`, `state/journals/`, and drain `mailbox/`.
- The learning loop is prose: `knowledge/INDEX.md`, `knowledge/lessons.md`, `knowledge/playbooks/`, `knowledge/projects/`. No verb writes them. The mandate is `skills/fleet/SKILL.md` "Learning loop" and GOALS standing goal 4. The interface startup ritual reads them.
- **The hole:** nothing revives a dead fleet. `fleet sup-status` prints `RELEASED` in calm white; revival is step 5 of the *human* startup ritual. `docs/specs/phase-2-watchtower.md` is superseded; `docs/specs/phase-3-telegram.md` is an unclaimed stub whose constraints (owner-only chat, no listening ports, manager-on-call is a registry entry) remain sound.
- `fleet init` has **never been run on this box**: `fleet doctor` reports four `[FAIL]` rows for the missing `state/worker-settings.json`, and `state/fleet.json` does not exist.
- `bin/fleet_statusline.py` is the precedent for a second stdlib file beside `bin/fleet.py`.

### 2.2 Host

- tmux 3.4, one session `work`, created at boot by `~/.config/systemd/user/tmux-work.service` (Ansible `roles/devbox`, lingering enabled, deliberately no `Restart=`).
- **ccgram 4.10.3** (`~/.config/systemd/user/ccgram.service`, Ansible `roles/telegram_bridge`, `Restart=always`). One Telegram forum topic = one tmux window in `work`. It launches Claude with `CCGRAM_CLAUDE_COMMAND=claude --permission-mode auto`, reads the transcript JSONL under `~/.claude/projects/`, and identifies sessions through hooks registered in `~/.claude/settings.json` (`SessionStart`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `TeammateIdle`, `TaskCompleted`). It exposes no programmatic inbound API; it long-polls Telegram outbound only. Windows created by hand inside `work` are auto-detected and get a topic.
- **cmux** on this host is only the macOS terminal's SSH relay shim (`~/.cmux/bin/cmux`, not on PATH, daemon idle). It is a client-side display; it is not an integration surface here.
- Claude Code 2.1.263 via fnm. `--bg` sessions survive logout under `claude daemon`. `claude agents --json` lists them. `claude attach <id>` works inside tmux. No built-in self-waking timer exists; `/loop` needs a live session and expires in 7 days.
- **Hook-identity hazard (measured):** the running `claude daemon` carries `TMUX=…`, `TMUX_PANE=%10` and `CLAUDE_CODE_SESSION_ID=<this session>` frozen from its first dispatch. Every `--bg` worker inherits that environment, so ccgram's hook resolves *every fleet worker* to the pane that first launched the daemon. Fleet's `--setting-sources` flag (spawn/respawn) is the documented remedy for foreign hooks; `sup-spawn` does not carry it today.
- All host configuration is rendered by Ansible from `~/china-infra` ("DO NOT EDIT ON THE HOST"). Nothing in `crontab`, no other timers.

## 3. Architecture

Three layers. Each can fail without taking the others down.

```
Telegram (phone)
   │  ccgram topic  "fleet"            ← the only notify path (ruling 2)
   ▼
tmux work:fleet  — interactive claude, cwd=$FLEET_HOME, bypass (ruling 3)
   │  INTERFACE TIER (three-tier §1): fleet status / send / sup-spawn / sup-decision
   │  ▲ keeper pages by typing one line into this window (§5)
   ▼
claude daemon ── sup|<launch>|boot (SUPERVISOR TIER) ── workers in ~/proga/<repo>
   │
state/, supervisor/JOURNAL.md, knowledge/   ← identity + memory, unchanged

fleet-keeper.timer (systemd --user, every 15 min)
   reads status_snapshot() + sup-status --json + claude agents --json + git
   never locks, never dispatches, never writes fleet state (ruling 1)
   ensures work:fleet exists; pages into it; nothing else
```

### 3.1 Layer 1 — the interface window (`work:fleet`)

A dedicated tmux window named `fleet` in session `work`, running `claude --permission-mode bypassPermissions` with cwd `/home/altai/proga/fleet` and the fleet plugin enabled. ccgram detects it and creates the Telegram topic. Everything the operator does from the phone goes through this session: it is the interface tier as `docs/specs/three-tier-command.md` defines it, so the doctrine needs no change — it never runs `sup-boot`, never drives a worker directly, and holds no nonce.

Its launch prompt is the **server interface profile** (`docs/operator/server-interface-profile.md`, new): run startup-ritual steps 1–4 (gates, `fleet status`/`sup-status`/`autoclean`, knowledge index, project files), report in one message, and then **wait**. Step 5 (revive) is replaced by: "state that the fleet is dead and what brief you would dispatch; dispatch only when the operator says so in this topic." This is the mechanical form of ruling 1 — the paging arrives from the keeper, the decision arrives from the phone, the `sup-spawn` is typed by the interface session.

The interface session is disposable. It keeps no state of its own; the journal and `state/` are the state. When it dies, the keeper recreates the window and the new session runs the profile again; when its context grows large, the operator recycles it (below). The operator can force this from Telegram with the message `recycle interface` (the profile tells the session to exit after acknowledging; the keeper's next tick recreates it).

### 3.2 Layer 2 — the fleet itself (unchanged, plus one flag)

Supervisor and workers stay native `--bg` sessions. Two additions:

1. **`fleet sup-spawn --setting-sources <list>`** — the same passthrough `spawn` and `respawn` already have, so a supervisor body can be dispatched without the user-level ccgram hooks. The server standing brief instructs the supervisor to spawn every worker with `--setting-sources project,local` for the same reason. Verification is a canary (§7): after one worker turn, `~/.ccgram/events.jsonl` must contain **no** record with that worker's `session_id`.
2. **A server standing brief** at `supervisor/briefs/server-standing.md` (git-tracked; `state/` is not). It is what the interface session dispatches on `sup-spawn` when the operator says "revive". It tells the body to: boot, read the journal tail, continue the last CHECKPOINT plan; drain `state/inbox/*.md` as new campaign intake (§3.4); fold lessons into `knowledge/` and commit at every wave end (goal 4); `git push` after every fold and retry on rc≠0 (the 29-unpushed-commits failure); checkpoint at every wave boundary; hand off in-band. It carries no task of its own: the plan is in the journal, which is the point of a persistent identity.

### 3.3 Layer 3 — the keeper (new, small, dumb)

*Amended 2026-09-08 after the final review: the rules table below was written before the fix waves it describes and had drifted from the shipped rule set — `supervisor-dead`'s condition understated what the code checks (`claude agents` must itself have answered, and the roster join is the claim's session id, not a `sup\|*` name prefix), `login-expired`'s trigger no longer includes an outcomes-log auth error (that source was dropped; the rule now fires on any `agents` failure that is not a missing binary), and four rules the code has always had (`claim-unknown`, `claude-missing`, `not-initialised`, `registry-unreadable`) had no rows at all. The table now states what `bin/fleet_keeper.py` ships, plus the delivery and sanitiser rules that govern every row alike.*

`bin/fleet_keeper.py`: stdlib-only, Python ≥ `fleet.MIN_PYTHON_VERSION`, imports `fleet` for `status_snapshot()` and the sup-status projection only. It is run by `fleet-keeper.timer` every 15 minutes with `--once`, and never as a daemon.

**Rules** (pure functions over one observation; each yields zero or one page), in the order they are evaluated:

| rule | signal | page text (one line, typed into `work:fleet`) |
|---|---|---|
| registry-unreadable | `status_snapshot()` reads `ok=False` with a reason other than `not_initialized` | `KEEPER: registry unreadable (<reason>). Report it; do not repair.` |
| not-initialised | `status_snapshot()` reads `ok=False, reason="not_initialized"` — a home where `fleet init` never ran, not a corrupt registry | `KEEPER: fleet home not initialised (state/worker-settings.json or registry missing). Run fleet init from a plain shell.` |
| claude-missing | `claude agents --json` is not on the unit's PATH (a deploy fault, distinct from an expired login) | `KEEPER: claude binary not found on PATH for the keeper unit. Check the service PATH.` |
| login-expired | `claude agents --json` fails for any reason other than a missing binary | `` KEEPER: claude login appears expired (`claude agents` failed). Operator must /login on the box. `` |
| claim-unknown | GOALS active AND `claude agents` answered AND the claim's normalised state is `unknown` (a read failure, not evidence of death) | `KEEPER: supervisor claim unreadable (state unknown). Report it; do not repair.` |
| supervisor-dead | GOALS active AND `claude agents` answered AND (claim `released`/`none`, OR claim `held` with heartbeat missing or older than 60 min AND the claim's own `session_id` absent from `claude agents --json`) | `KEEPER: supervisor dead since <since> (<reason>). Report state; await operator before sup-spawn.` |
| supervisor-frozen | `sup-status --json`'s `pending_decision` carries an unanswered question | `KEEPER: supervisor parked on decision: <q> Carry it to the operator.` |
| worker-anomaly | `status_snapshot()` shows `dead-suspected`, `limited`, or `idle` with unread mail | `KEEPER: <n> worker anomalies: <names>. Summarise for the operator.` |
| unpushed | `git rev-list --count origin/main..main` > 0 for > 6 h (age from the oldest unpushed commit; an unreadable upstream reports on stdout and pages nothing) | `KEEPER: <n> commits unpushed for <h>h. Push or explain.` |
| hook-errors | `state/hook-errors.log` grew since last tick | `KEEPER: hook-errors.log grew by <n> lines. Read it.` |

`supervisor-dead`'s roster join is on the claim's SESSION ID, never a `sup\|*` name prefix: `claude agents --json` lists ACTIVE sessions only, so an idle-between-turns supervisor is legitimately absent from it while alive, and only a fresh heartbeat or a live session id (not a name, which `ai-title` can overwrite after a resume) settles the question.

**Delivery is a fact about tmux, not about the rule firing.** A page counts as sent — and is the only kind dedup ever records as sent — when `tmux send-keys` for both the literal line and `Enter` is accepted; a tick that only *created* `work:fleet` this cycle defers every page to the next tick instead (a freshly launched Claude TUI is not yet reading its prompt box, so anything typed into it is lost), and a tick whose delivery tmux refused carries the previous tick's record forward so the next tick retries rather than going silent for the re-page window.

**Every page is sanitised at the point of delivery**, not by each rule: prefixed with `KEEPER: ` (first, so a page beginning with `-` cannot read as a `send-keys` flag), then collapsed to one printable line — ANSI stripped, C0 controls (including `\r`, `\n`, `\t`) folded to spaces, whitespace collapsed, truncated with an ellipsis at 200 characters. This is what stops a worker-writable substring (a `sup-decision` question, a registry reason) from becoming a second submitted prompt line in the `bypassPermissions` interface session.

**Actions** — exactly two, both tmux-level, neither touches fleet state:

- **ensure-window:** if `work:fleet` is absent or its pane's current command is not `claude`, create it (`tmux new-window -t work -n fleet -c $FLEET_HOME 'claude --permission-mode bypassPermissions "<profile prompt>"'`). This is the same class of act as `tmux-work.service` creating `work`.
- **page:** `tmux send-keys -t work:fleet -l '<line>'` then `Enter`. Claude queues typed input while mid-turn, so a busy interface still receives it. The ccgram Stop hook then carries the interface's reply to the Telegram topic — that is the whole outbound path (ruling 2).

**Dedup:** `state/keeper/last-page.json` records, per rule, the last paged fingerprint and time. A rule re-pages only when its fingerprint changes or 6 hours pass. Keeper writes nothing else under `state/`.

**Doctrine check, rule by rule:**
- D7 (pull-only, no injection surface): the keeper types into one dedicated window whose sole purpose is fleet, launched by the keeper itself. It never touches another session, never installs a hook, never fires in a session that did not opt in. This is recorded as an OPERATOR-GATES ruling rather than treated as obviously inside D7.
- Views never lock (CLAUDE.md rule): the keeper reads `status_snapshot()` and `sup-status --json`, exits 0 on a corrupt registry, and pages `KEEPER: registry unreadable` instead of repairing anything.
- No auto-spawn (2026-07-27): the keeper contains no call to any dispatching verb. Pinned by an AST test the way `tests/test_load_registry_callers.py` pins loader reach.
- No Git-Bash `&`: the timer runs the keeper; the keeper runs `tmux`, `git`, `claude agents` synchronously with timeouts.
- Interpreter floor: the unit uses `bin/hooks/run_py.sh`'s selection; the suite runs on 3.10 and 3.13.

### 3.4 Task intake and long-running work

Two paths, both existing fleet mechanics:

- **Conversational:** the operator writes in the `fleet` topic. The interface session turns it into a brief file under `state/tasks/` and either `fleet send sup|<launch>|boot @file` (supervisor live) or `fleet sup-spawn --task @supervisor/briefs/server-standing.md` after the operator says revive (supervisor dead). Long tasks are supervisor waves, exactly as on the reference box; workers run with cwd in any `~/proga/<repo>`.
- **Queued:** `state/inbox/<yyyymmdd>-<slug>.md` files, written by the interface session (or by hand over SSH). The standing brief makes the supervisor drain the inbox at every wave boundary and move each file to `state/inbox/done/` with the campaign name appended. This survives a dead interface session and a dead supervisor: the file waits.

Persistence of *work* across bodies already exists (journal + checkpoint cadence). Persistence of *learning* is the standing brief's fold-and-push clause plus the keeper's `unpushed` rule, which is the only new enforcement.

## 4. Sequencing (each step has a receipt before the next starts)

- **S0 — install fleet on this box.** `fleet home` → `fleet init` from a plain shell (claim gate) → `claude plugin marketplace add /home/altai/proga/fleet` + `claude plugin install fleet@claude-fleet` → the canary worker from `docs/operator/fleet-init-recipe.md` §4, proof = `state/outcomes/<name>.jsonl` in this home. Also: `bin/fleet.cmd`'s hard-coded `py -3.13` is irrelevant here; `bin/fleet` → `run_py.sh` is the Linux path.
- **S1 — `sup-spawn --setting-sources`** in `bin/fleet.py`, with the ccgram-events canary as the acceptance test. Small, isolated change.
- **S2 — interface window by hand.** Create `work:fleet`, run the profile prompt, confirm ccgram makes a topic and relays the ritual report to the phone. Send `fleet status` from the phone. No keeper yet.
- **S3 — keeper.** `bin/fleet_keeper.py` + `tests/test_keeper.py` (rules over fixture snapshots; tmux and git through an injected runner; the no-dispatch AST pin). Run it by hand with `--once --dry-run` first.
- **S4 — Ansible.** New role `fleet_keeper` in `~/china-infra`: `fleet-keeper.service` (`Type=oneshot`, explicit `PATH` like `ccgram.service`, `EnvironmentFile=-~/.config/china-infra/claude.env`), `fleet-keeper.timer` (`OnBootSec=2min`, `OnUnitActiveSec=15min`, `Persistent=true`), `Wants=tmux-work.service`. Render-check via `scripts/render-check.sh`.
- **S5 — standing brief + first revival from the phone.** Dispatch through the interface topic; watch one wave complete; confirm the lessons fold and push landed.
- **S6 — one-week soak.** Record every page in `docs/operator/keeper-soak-2026-09.md`; false pages become rule fixes.

## 5. Failure modes considered

| failure | what happens | who tells the operator |
|---|---|---|
| supervisor releases at ceiling, nobody home | keeper `supervisor-dead` within 15 min; interface reports in topic; waits | ccgram |
| power cut / reboot | `tmux-work` + `ccgram` + `fleet-keeper.timer` (`Persistent=true`) come back with the user manager; keeper recreates `work:fleet`; supervisor body is gone → `supervisor-dead` page | ccgram |
| login expiry | every session dies; keeper `login-expired`; the interface window cannot start either — keeper page fails → keeper falls back to `journalctl` only. **Known blind spot:** ruling 2 forbids a second outbound path, so a login expiry that also kills the interface is silent until the operator looks. Recorded as a gate question. | nobody (gate) |
| interface context exhaustion | operator sends `recycle interface`; or the keeper recreates on pane death | ccgram |
| keeper itself broken | timer unit fails → `systemctl --user status` only. Second blind spot; same gate. | nobody (gate) |
| ccgram down | `Restart=always`; pages queue as typed input inside the interface session and are relayed when the Stop hook next fires | delayed |
| two interface windows | keeper creates only when `work:fleet` is absent; the window name is the lock | n/a |
| keeper pages while interface mid-turn | typed input queues; delivered at turn end | delayed |

## 6. Testing

- `tests/test_keeper.py`: each rule as a table of snapshot fixture → expected page or None; dedup window; `--dry-run` prints and performs nothing; AST pin that `fleet_keeper.py` never references `dispatch_bg`, `cmd_spawn`, `cmd_sup_spawn`, `cmd_send`, `cmd_respawn`, `fleet_lock`.
- `tests/test_sup_spawn_setting_sources.py`: the flag reaches the argv `dispatch_bg` builds.
- Live receipts (pinned `# at <sha>` per CLAUDE.md, `# volatile` where the evidence is host state): the canary outcome file, the empty ccgram-events check, one real page landing in the topic.
- The Ansible role gets the repo's existing render check.

## 7. Operator gates to file in `docs/OPERATOR-GATES.md`

- **G-K1** Keeper typing into `work:fleet` is ruled inside D7's intent (one dedicated opt-in window), or D7 is amended to say so.
- **G-K2** The two blind spots in §5 (login expiry killing the interface; keeper unit failure) stay silent under ruling 2. Accept, or permit one out-of-band alert path later.
- **G-K3** Server interface runs bypass (ruling 3) — already ruled; recorded for the receipt.
- **G-K4** `supervisor/briefs/` becomes a git-tracked home for standing briefs.

## 8. Out of scope, deliberately

Auto-revival by the timer (ruled out), a second Telegram client or direct Bot API use (ruled out), the phase-3 manager-on-call bridge (superseded by the ccgram-bound interface window, which is the same idea with someone else's plumbing), multi-fleet homes, and any change to the learning-loop *mechanism* — only its cadence is enforced.
