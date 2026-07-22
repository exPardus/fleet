# Docs index

Every doc and doc-adjacent directory in this repo, one line each, tagged by audience:

- **[USERS]** — you're using fleet to run workers. Start here.
- **[CONTRIBUTORS]** — you're changing fleet's code or its design.
- **[INTERNAL]** — fleet's own working docs: campaign plans, design reviews, accumulated knowledge. Not needed to use the tool, but genuinely interesting archaeology — this repo's adversarial-review culture (`docs/reviews/`) is one of its stronger arguments for trustworthiness, and it's all public.

If a doc isn't listed here, that's a gap — file an issue or add it in the same PR that adds the doc.

## Start here (users)

| Doc | Audience | What it's for |
|---|---|---|
| [`concepts.md`](concepts.md) | USERS | **How claude-fleet works** — the idea, the problem it solves, the layered architecture, the worker lifecycle, the knowledge loop. Diagrams throughout. The friendly companion to `SPEC.md`. |
| [`getting-started.md`](getting-started.md) | USERS | Install → become the manager → spawn, steer, respawn, and run a first parallel campaign. The hands-on path. |

## Root

| Doc | Audience | What it's for |
|---|---|---|
| [`README.md`](../README.md) | USERS | Pitch, quickstart, feature list, architecture sketch. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | CONTRIBUTORS | Dev setup, binding rules, how review works here, PR expectations. |
| [`LICENSE`](../LICENSE) | USERS | MIT. |
| [`CLAUDE.md`](../CLAUDE.md) | INTERNAL | Instructions Claude Code itself reads when working *in* this repo (rules a session must never violate: `py -3.13`, forward slashes in hook commands, no Git-Bash `&`, views are read-only, etc.). Useful to a contributor as a second binding-rules source, but written for an AI session, not a human onboarding doc. |

## `docs/` — design, spec, and process

| Doc | Audience | What it's for |
|---|---|---|
| [`SPEC.md`](SPEC.md) | CONTRIBUTORS | The canonical architecture: registry schema, the nine numbered load-bearing invariants, every CLI command's contract, the launch detail. Read this before changing `bin/fleet.py` — including its §0 pin-staleness banner, which says how far the line numbers have drifted. |
| [`SPEC-v2-history.md`](SPEC-v2-history.md) | INTERNAL | The complete v1→v2.3 spec body, moved verbatim (blame preserved) when v3 rewrote against the native-substrate pivot: detached-launch design, PID liveness, the F1–F33 finding record. The record of *why* the current rules exist; not buildable surface. |
| [`OPERATOR-GATES.md`](OPERATOR-GATES.md) | INTERNAL | The live decision queue — the things only the operator may settle. Step 1 of the `fleet` skill's startup ritual reads this file, so a manager session cannot start work without meeting the open items. (Until 2026-07-22 a SessionStart hook injected them instead; it leaked into every unrelated project and was removed — terminal-surface D7.) Format is load-bearing and test-pinned. |
| [`longcat-fleet-usage.md`](longcat-fleet-usage.md) | INTERNAL | Working notes on running fleet against an alternate provider via an isolated `CLAUDE_CONFIG_DIR` daemon namespace — the approach that survived after the native-provider spike came back negative. |
| [`ROADMAP.md`](ROADMAP.md) | CONTRIBUTORS | Phases 1 through 6, the design principles behind them, and the soak-gate discipline that gates each phase behind real usage rather than calendar time. |
| [`PRIOR-ART.md`](PRIOR-ART.md) | CONTRIBUTORS | Competitive survey (tmux orchestrators, native Agent View, the wider ecosystem) and the decision points it fed into the spec. Good context for "why not just use X." |
| [`IDEA-FORGE-REPORT.md`](IDEA-FORGE-REPORT.md) | INTERNAL | Output of an ideation-and-adversarial-judging pipeline that killed all 10 of its candidate ideas — kept as a graveyard so nobody re-proposes the same dead ends. Genuinely fun to read if you like watching ideas get taken apart. |
| [`PLAN.md`](PLAN.md) | INTERNAL | The self-build campaign contract fleet's own manager sessions execute against — task-file conventions, quality-gate pipeline, permission mechanisms. This is process documentation for fleet building itself, not for using fleet. |
| [`PLAN-PROGRESS.md`](PLAN-PROGRESS.md) | INTERNAL | The live, mutable wave-by-wave ledger tracking `PLAN.md`'s execution. Changes constantly; treat as a session-to-session cursor, not a stable reference. |
| [`NEXT-SESSION.md`](NEXT-SESSION.md) | INTERNAL | Handoff notes written at the close of the most recent self-build campaign, for whichever manager session picks the work back up. |
| [`specs/`](specs/) | CONTRIBUTORS | One spec per phase/topic (`native-substrate.md`, `autoclean.md`, `claim-nonce.md`, `fleet-index.md`, `three-tier-command.md`, `portability.md`, `providers.md`, `terminal-surface.md`, `phase-2-watchtower.md`, `phase-3-telegram.md`, `phase-4-webui.md`, `phase-5-intelligence.md`, `phase1-hardening-kernels.md`). Each carries a `Status:` line (`stub` / `drafting` / `ready-for-build` / `PROPOSAL` / `SUPERSEDED`) — check it before assuming a spec describes shipped behavior. **`ready-for-build` means reviewed and buildable, never shipped**; §18 of `SPEC.md` is the shipped list. |
| [`reviews/`](reviews/) | INTERNAL (but read this one) | Every adversarial review this project has run against its own specs and code, receipts included — the thing this directory proves is that features here get attacked before they ship, not just written. `SPEC-PORTABILITY-REVIEW-2026-07-10.md` (five hostile passes, live WSL repro, 19 findings) and `c2-review-adversarial.md` (found a HIGH-severity double-launch bug past green tests) are good places to start if you want to see the process work. |
| [`superpowers/`](superpowers/) | INTERNAL | Working specs and execution plans for whatever is being designed next. More volatile than `docs/specs/`; this is where design happens before it is stable enough to move there. Currently: the native-substrate pivot and its build plans (closed), `specs/2026-07-18-sdd-drift-control-design.md` (v4, operator-ratified, unbuilt — the M-F candidate) with `plans/2026-07-22-sdd-mf-phase1.md`, `specs/2026-07-22-fleet-index-design.md` (whose reviewed spec now lives at `../specs/fleet-index.md`), `specs/2026-07-22-oracle-design.md` (DRAFT v2), and `specs/2026-07-21-worker-providers-native-design.md` (**self-contradicting — header says approved, its own §4.2 says do not implement; open operator gate**). |

## Outside `docs/`

| Path | Audience | What it's for |
|---|---|---|
| [`knowledge/`](../knowledge/) | INTERNAL | Fleet's git-tracked memory: `INDEX.md` (one-line pointers), `lessons.md` (append-only postmortems), `playbooks/` (reusable doctrine like the campaign template), `projects/` (per-project quirks fleet has learned). Every manager session reads this at startup and writes back to it after every campaign — it's the accumulated experience that makes fleet-managed campaigns get better over time. Worth reading to see what a real multi-week campaign log looks like. |
| [`spike/`](../spike/) | INTERNAL | Throwaway experiment scripts and their dated verdicts — currently `spike/m0/`, the go/no-go probes against Claude Code's native background-agent daemon that the current pivot depends on. `spike/m0/VERDICTS.md` is the receipts file: each experiment quotes its exact command and exact output. |
| [`supervisor/`](../supervisor/) | INTERNAL | `GOALS.md`: the operator-owned target and standing goals for fleet's forthcoming persistent supervisor identity. Becomes live once the native-substrate pivot ships a supervisor that boots against it. |
| [`skills/fleet/SKILL.md`](../skills/fleet/SKILL.md) | USERS | The manager skill itself — what a Claude Code session reads to become a fleet manager. Installed automatically by the plugin; read it if you want to know exactly what doctrine the manager operates under. |
| [`commands/`](../commands/) | USERS | The `/fleet:*` slash command definitions shipped by the plugin (`status`, `spawn`, `send`, `attach`, `kill`, ...). |
| [`.claude-plugin/`](../.claude-plugin/) | CONTRIBUTORS | Plugin and marketplace manifests — what makes `claude plugin install fleet@claude-fleet` work. |
| [`tests/`](../tests/) | CONTRIBUTORS | The pytest suite (unit, hook, and live-integration tiers) — see `CONTRIBUTING.md` for how to run it. |
| [`bin/`](../bin/) | CONTRIBUTORS | The CLI itself: `fleet.py` (single-file, stdlib-only), the shim, and the hook scripts. |
