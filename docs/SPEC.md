# claude-fleet — one Claude Code session managing many

**Status:** draft-v3 (2026-07-17), **pending review** — not ratified; an adversarial reviewer gates promotion.
**Changelog (v2.3 → v3):** full rewrite against post-pivot reality. The native-substrate pivot (M-0 spike → M-A supervisor → M-B native dispatch → M-C deletions/autoclean/hardening) is complete and live-verified; `bin/fleet.py` no longer contains the detached-Popen launcher, PID probing, or the stdout log pipeline the v2.x body described (9345 → 7378 lines). The entire v2.3 body — every section, banner, and appendix (F1–F33) — is MOVED, not deleted, to `docs/SPEC-v2-history.md` (`git mv`, blame preserved). This v3 body is new prose, descriptive of `bin/fleet.py` at `c63d7dd` unless a paragraph is explicitly marked prescriptive; every central claim carries a grep/read receipt against that commit.
**Owner:** Altai
**Location:** `C:\proga\claude-fleet` (system-wide tool, own repo — never part of any managed project)
**Target machine:** Windows 10, PowerShell, Git Bash present, Python via `py -3.13`, Claude Code CLI ≥ 2.1.207 (the pin-tested version; see §2).

*(v3 body lands in the commits following the structure move.)*
