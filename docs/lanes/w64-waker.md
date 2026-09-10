# w64-waker — G-K6 B existing-body wake [MEASURED implementation]
DONE means: [BELIEVED acceptance still owed] an idle existing claim-holder receives a turn through a no-model-call keeper mechanism outside the plan limit, C monitors progress, no supervisor body is dispatched, ordinary eight-hour retirement is avoided, and targeted keeper tests pass on Python 3.10 and 3.12.

- **MEASURED — outcome:** implemented an opt-in wake in `bin/fleet_keeper.py`, with operator-only unit templates and installation recipe. Implementation is ready for review; the full DONE criterion is **not claimed** because actual daemon delivery, a successful model turn, and real plan-limit refusal were not measured in this fenced sandbox.
- **MEASURED — model and fence:** this mcx worker used the requested Astra/high context, kept `MCX_WORKER=1`, and delegated only bounded native source research/review. No independent worker launch, live fleet write, tmux input, systemd action, git index/ref mutation or `bin/fleet.py` edit occurred. The native reviewer completed; its evidence is in this worktree’s `state/journals/w64-waker-research.txt`.

## Mechanism and evidence [MEASURED]

- **MEASURED — local source:** installed Claude 2.1.267 binary SHA256 `0399c793ff571d5946ef923d80b4f330d05ac4b6842a6b0775468f5d389403c0`; daemon-lock version also 2.1.267. Embedded source exposes newline JSON `{proto:1,op:"reply",short:<8 hex>,text:<prompt>,auth:<key>}` and ACK `{ok:true,op:"reply"}`. Source excerpts and byte offsets are preserved in the research log; `reply` handler calls the existing handle’s `reply`, never dispatch. `ENOJOB`, `ERESPAWNING`, `ENOREPLY`, authentication and protocol refusals have no keeper fallback.
- **MEASURED — identity:** fresh read-only claim and roster checks select only the current claim sid, with a live PID, `kind:background`, `state:working`, `status:idle`. Any busy/waiting/other live union status suppresses the wake; a retired-only live body remains C’s operator-page case. Another claim read follows roster collection. Read-only `{proto:1,op:"list"}` on the explicitly selected socket verifies the same short, session ID and PID and rejects dying/outcome-bearing jobs before reply; this avoids cross-daemon short-ID collisions.
- **MEASURED — limits:** the transport is bounded (five-second socket deadlines; 1MiB list and 16KiB reply limits); key reads require a regular file no larger than 4096 bytes. No auth key or raw daemon list is logged. The daemon protocol has no atomic session/PID/claim compare-and-deliver operation; a transition after the last checks remains possible, so the fixed wake prompt requires authority/GOALS verification before work.
- **MEASURED — dispatch line:** `fleet send` on idle enters `_cmd_send_native`, takes `fleet.lock`, calls `dispatch_bg(resume_sid=...)` and mints a new sid; it is unsuitable here. This keeper sends bytes to an existing daemon job handle. It does not invoke `fleet send`, `sup-spawn`, `--resume`, a model client, or the vendor reply wrapper that can bootstrap a daemon. Existing interface-window fallback behavior is unchanged.
- **BELIEVED — first model call:** the existing target **Claude supervisor process**, after the daemon delivers into its existing PTY/RV transport, makes the first inference call. Python keeper and local daemon forwarding make no model call of their own. A plan-limit refusal prevents useful supervisory work, but cannot consume the keeper’s systemd schedule; B retries on later ticks. Source separation supports this claim; actual plan refusal has not been exercised by this lane.
- **MEASURED — cadence:** two idle observations separated by 900 seconds authorize an attempt; subsequent attempts, including refused/ambiguous ones, wait at least another 900 seconds. A fresh heartbeat defers a wake. With a functioning quarter-hour timer this is 15–30 minutes from ordinary idle onset, plus timer/probe latency, far inside ordinary eight-hour retirement. No claim is made about a stopped timer or suspended host.
- **MEASURED — state and C:** one new top-level key `_supervisor_wake` in keeper-owned `last-page.json` records identity, idle onset, attempt time and transport result. Intent is persisted before sending; result before interface-pane work. A broken pane does not prevent retries. `accepted` is a transport ACK only; B does not refresh heartbeat or clear `supervisor-stalled` dedup. Tests show both accepted and refused wakes leave C armed on stale non-busy observations; a fresh heartbeat or busy observation suppresses C by its existing rule. C cannot prove wake-caused progress, and its pre-existing busy-mid-turn blind spot remains.
- **MEASURED — G-K1 collision check:** B is off unless the operator supplies **both** `--wake-socket` and `--wake-key` to the existing `--once` tick. There is no extra service, background loop or hook; shipped templates replace the existing keeper unit names. G-K1 can gate this whole tick without unpicking an always-on surface. No G-K1 implementation or gate-box edit was made. Stale `supervisor-dead` dedup is deliberately untouched.
- **MEASURED — prerequisite completed:** corrected the interface profile’s “B is not built” sentence and documented transport ACK versus progress so C’s existing two-live-body guard is not bypassed by an accepted wake.
- **MEASURED — docs currency:** updated SPEC §18 and PLAN-PROGRESS; SPEC’s unpinned current-rule sentence now says `supervisor-stalled`. Dated historical quotations retain the old rule name. Updated the owning project’s host facts, operator recipe and unit templates. No ratified native-substrate contract text or live append-only journal/lessons/changelog was rewritten.

## Checks and limits [MEASURED]

- **MEASURED — prediction before tests:** journal predicted the 154-case keeper baseline would stay green and new wake transport/eligibility/throttle/watchdog cases would raise the count. The final keeper population is **223 collected: 222 passed, 1 skipped** on **both Python 3.10 and 3.12**: 154 existing passes plus 68 new passes and one new real-wire probe skipped.
- **MEASURED — command:** `UV_CACHE_DIR=/tmp/w64-waker-clean-uv-cache FLEET_HOME=/home/altai/proga/fleet-w64-waker uv run --no-project --offline --python 3.1x --with pytest python -m pytest -q tests/test_keeper*.py`. Full logs are retained in `state/receipts/w64-waker/`; only targeted suites were run, never the full floor.
- **MEASURED — final verification:** two final tests exercise the real `collect`→`main` path and reject mismatched claim snapshots; both interpreter keeper runs passed after these additions. Four selected docs-currency checks passed on each interpreter (branch history, new lane DONE lines, dispatched-task DONE lines and the detector seed); `git diff --check` passed. Synthetic git-mutating docs fixtures were not run.
- **MEASURED — first failure:** first run had 202 passes and eight failures, all on sandbox-denied AF_UNIX bind (`EPERM`); socketpair also failed. Deterministic socket fixtures now exercise production framing, fragmented replies, refusals, size bounds and retry semantics. One isolated real-socket test explicitly skips on the measured sandbox prohibition. This is not a live-daemon receipt disguised as a green test.
- **MEASURED — environment repair:** the copied prior-lane UV cache failed Python 3.10 dependency materialization before tests; a private copy of the existing user cache resolved it offline. The user’s environment was not changed. Environment diagnostics and initial test failure log are retained.
- **BELIEVED — remaining acceptance:** the operator must install/enable the text templates and capture same sid/PID, accepted delivery, an actual busy turn and a refreshed heartbeat, then continued keeper attempts during a naturally occurring plan refusal. The supplied recipe makes this concrete. This lane neither installs units nor sends live daemon messages, and its sandbox rejects even throwaway Unix socket creation.

## WHERE THIS BRIEF WAS WRONG [MEASURED]

- **MEASURED:** the suggested `fleet send`/mailbox choice misses the available direct daemon reply. Idle `fleet send` forks; mailbox alone needs an existing turn/hook to consume it. The installed local reply API reaches the existing process without either action. A typed tmux line is unnecessary.
- **MEASURED:** “B means the body never sits idle at all” is too strong: observation intentionally waits 15 minutes, refusals can leave it idle, and ACK is not progress. C stays the watchdog; the new state key is needed for bounded retries and transport evidence, not to manufacture success.
- **MEASURED:** eight hours is the ordinary idle-retirement delay, not a lower bound on lifetime. The same installed source has a low-memory path with 60-second delays. A 15-minute keeper cannot guarantee survival against that path; dead-body handling remains the existing interface/C remedy.
- **MEASURED:** the worktree allows code and fixture measurements, but not proof that an actual body receives a turn: AF_UNIX creation is denied, live fleet writes and tmux input are forbidden, and unit installation is explicitly reserved to the operator. Consequently this report separates implemented behavior from the brief’s still-unmeasured live DONE criterion.

## PATH LIST — every authored or modified deliverable [MEASURED]

- **MEASURED:** `/home/altai/proga/fleet-w64-waker/bin/fleet_keeper.py`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/tests/test_keeper_wake.py`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/SPEC.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/PLAN-PROGRESS.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/operator/server-interface-profile.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/operator/keeper-wake.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/operator/systemd/fleet-keeper.service`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/operator/systemd/fleet-keeper.timer`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/knowledge/projects/claude-fleet.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/docs/lanes/w64-waker.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/journals/w64-waker.md`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/journals/w64-waker-research.txt`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/environment.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.12-first.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.12-pre-review.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.12.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.10.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.10-pre-collect.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/keeper-3.12-pre-collect.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/docs-3.10.log`
- **MEASURED:** `/home/altai/proga/fleet-w64-waker/state/receipts/w64-waker/docs-3.12.log`
