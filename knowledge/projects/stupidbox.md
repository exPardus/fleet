# Project: stupidbox

`C:\proga\stupidbox` — a deliberately useless Python CLI toy, built from scratch by the fleet as the first **external dogfood campaign** (2026-07-09). Non-fleet project → counts toward Soak Gate 1 usage.

## What it is
A tiny stdlib-only CLI: `py -3.13 -m stupidbox <command> [args...]`. Commands: `cow` (cowsay + `--think`), `fortune`, `roll` (d6/dN/coin/NdM), `hodor`. Each command is one self-contained module exposing `run(args: list[str]) -> str`; the dispatcher (`stupidbox/__main__.py`) lazy-imports by name with a "not built yet" fallback.

## Structure (why it parallelizes cleanly)
- Manager writes the scaffold + dispatcher **first**, referencing all N command names upfront (lazy import → missing module degrades gracefully, never breaks siblings).
- Each worker owns **exactly one** module file (`stupidbox/<cmd>.py`). Fully disjoint write sets → safe N-wide parallelism.
- This "dispatcher + lazy-import + one-file-per-worker" shape is the reusable template for "build N independent things in parallel in a fresh repo."

## Facts learned live
- Fresh local repo, `git init`, workers commit their own path with exact-path staging. 4-wide concurrent commits → **zero index.lock casualties** (confirms disjoint-parallelism holds in a brand-new/foreign repo, not just claude-fleet).
- Haiku is dirt cheap here: ~$0.09–0.13 per module worker; ~$0.5 total for 5 workers + 2 respawns.
- Repo is throwaway; no network/secrets/live processes → `bypass` is the correct permission mechanism for every worker.

## Gotchas
- Git on Windows warns `LF will be replaced by CRLF` on commit — cosmetic, ignore.
- Keep CLI output ASCII-only; the manager's cp1252 console mangles unicode (em-dash → `�`).
