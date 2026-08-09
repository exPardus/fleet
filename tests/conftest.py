"""Test bootstrap: make bin/fleet.py importable as `fleet` without turning bin/
into a package (fleet.py must stay a standalone single-file CLI).

Also auto-applies the SPEC §12 tier markers (unit/hooks/live) by file name so
individual test files need no per-test marker edits, and enforces the
`FLEET_LIVE=1` gate on the tier-3 live suite (tests/integration/) -- when the
env var is unset the live tier is SKIPPED cleanly (never failed), keeping the
unit/hook tiers claude-free by default.
"""
import os
import sys
from pathlib import Path

import pytest

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


@pytest.fixture(autouse=True)
def _never_touch_the_real_home(tmp_path_factory, monkeypatch):
    """Redirect every path fleet resolves from `Path.home()` into a tmp dir.

    `fleet init --statusline` writes `~/.claude/settings.json`, and doctor
    reads `~/.claude/daemon.{lock,log}`. Historically `cmd_init` also stamped
    `~/.claude/fleet-home` unconditionally: tests monkeypatched the settings
    path but not the marker, so running the SUITE overwrote the developer's
    real marker with a pytest tmp dir, silently repointing it at a directory
    that no longer exists (caught 2026-07-09). That marker was deleted on
    2026-07-22 along with its only reader, so the specific hazard is gone --
    but the sandbox is what makes it a class rather than an incident, and any
    new `Path.home()` path added to fleet lands here by default.

    M-E adds the two READ-only daemon paths for a different reason: fleet never
    writes them, but `_doctor_check_daemon_wedge` reads them, and a check whose
    verdict depends on the developer's live daemon state is a flaky test. The
    sandbox keeps the `.claude/<name>` shape so path-shape assertions still hold.

    MULTI-FLEET SLICE (e) ADDS `homes_list_path`, AND CORRECTS THIS DOCSTRING.
    The sentence above used to promise that *"any new `Path.home()` path added
    to fleet lands here by default"*. **That was never true**: this fixture
    redirects HELPERS BY NAME, so a helper added later is covered only when
    someone remembers to add it, and `homes_list_path` (slice a1, 2026-08-05)
    was not. Slice a1 saw the gap, could not close it -- editing this file was
    outside its fence -- and escalated it in
    `tests/test_homes_list.py`'s module docstring, where it sat while four test
    files carried four private copies of the redirect and every OTHER file
    resolved the operator's real list. MEASURED before this line landed: 19
    calls to the real `~/.claude/fleet-homes.list` across `test_cli.py`,
    `test_view_quarantine.py` and `test_supervisor.py` alone, 0 to a sandbox --
    because `main()` transitively reaches `read_homes_list` and 15 test files
    outside those four drive `main()`. The reads were harmless on a machine
    with no list; the list is one `fleet homes --add` away from existing, and
    an append to it is RATIFIED DESTRUCTIVE. Receipts: `docs/lanes/
    w51-slicee.md` §3. The DEFAULT is pinned from a file that deliberately does
    not opt in (`tests/test_slice_e_pins.py::TestTheConftestRedirectReaches
    EveryFile`), because a pin written inside an opted-in file would have gone
    green on the broken world -- which is exactly what happened for six days.

    Tests that assert on these paths override them again with their own value;
    this fixture only guarantees the default is never the real home."""
    import fleet
    sandbox = tmp_path_factory.mktemp("fake-home")
    (sandbox / ".claude").mkdir()
    monkeypatch.setattr(fleet, "user_settings_path",
                        lambda: sandbox / ".claude" / "settings.json")
    monkeypatch.setattr(fleet, "claude_daemon_lock_path",
                        lambda: sandbox / ".claude" / "daemon.lock")
    monkeypatch.setattr(fleet, "claude_daemon_log_path",
                        lambda: sandbox / ".claude" / "daemon.log")
    monkeypatch.setattr(fleet, "homes_list_path",
                        lambda: sandbox / ".claude" / "fleet-homes.list")


@pytest.fixture(autouse=True)
def _never_touch_the_real_install(tmp_path_factory, monkeypatch):
    """The code-plane twin of `_never_touch_the_real_home`, and it exists
    because the multi-fleet slice-0 split BROKE THE SANDBOX AND THE SUITE PROVED
    IT IMMEDIATELY.

    Before the split, `template_settings_path()` resolved under `FLEET_HOME`, so
    every test that fixtured a template was sandboxed for free by monkeypatching
    the home. The split re-points it at `INSTALL_ROOT` -- correctly: the template
    is git-tracked source, not one fleet's state -- and `INSTALL_ROOT` is
    deliberately NOT overridable by env, so nothing redirected it. The first full
    run after the change overwrote the developer's real
    `worker-settings.template.json` with fixture bytes, which is the same class as
    the 2026-07-29T22:58:39Z incident in `docs/specs/multi-fleet.md`'s opening
    (fleet run inside the repo overwrote the real registry with fixture data),
    reached through the code plane instead of the data plane.

    §7 of that spec pins test isolation for the HOME only. This is the missing
    half, and it is deliberately the same SHAPE as the home's: redirect the
    plane's root, not the individual helpers, so every install-plane path added
    later lands in the sandbox by default instead of needing to be remembered.

    The default is therefore an EMPTY install, which is byte-for-byte the
    contract tests had before the split: `isolated_home` was an empty tmp dir, so
    `template_settings_path()` and the hook scripts were absent unless the test
    created them. Tests that need the real code plane opt in with
    `monkeypatch.setattr(fleet, "INSTALL_ROOT", _REAL_REPO_ROOT)` -- which is
    exactly what the hook-smoke tests already did to FLEET_HOME, for exactly this
    reason. Their docstring said so: *"FLEET_HOME must point at the real repo root
    here (where bin/hooks/*.py actually live)"*. That sentence was the conflation,
    written down in a test."""
    import fleet
    monkeypatch.setattr(fleet, "INSTALL_ROOT", tmp_path_factory.mktemp("fake-install"))


def code_plane_files(root):
    """The git-tracked install-plane files the suite must never modify.

    Module-level and parameterised on `root` so
    `tests/test_install_home_split.py` can seed the guard below -- a
    before/after hash comparison is the shape that passes vacuously when its
    file list silently goes empty."""
    return sorted(
        [root / "worker-settings.template.json"]
        + list((root / "bin").rglob("*.py"))
        + list((root / "bin").rglob("*.sh"))
    )


def code_plane_snapshot(root):
    import hashlib
    out = {}
    for path in code_plane_files(root):
        try:
            out[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            out[path] = "<unreadable>"
    return out


def code_plane_drift(root, before):
    return sorted(str(p.relative_to(root)) for p, h in code_plane_snapshot(root).items()
                  if before.get(p) != h)


@pytest.fixture(autouse=True, scope="session")
def _the_real_install_plane_is_byte_identical_afterwards():
    """The sandbox above is a redirect, and a redirect only covers the paths it
    knows about. This is the proof that it covered them all: hash the git-tracked
    code plane before and after the whole run and fail loudly on any drift.

    Without it, the next install-plane path someone writes through is caught by a
    developer noticing a dirty `git status`, which is how the incident this
    fixture documents was actually caught."""
    root = Path(__file__).resolve().parents[1]
    before = code_plane_snapshot(root)
    yield
    changed = code_plane_drift(root, before)
    assert not changed, (
        f"the test suite modified git-tracked install-plane files: {changed}. "
        f"Something resolved a WRITE through INSTALL_ROOT without going via the "
        f"`_never_touch_the_real_install` sandbox. Redirect it there rather than "
        f"fixing the one test -- the sandbox is what makes this a class.")


def real_homes_list_path():
    """`~/.claude/fleet-homes.list` resolved from the REAL home.

    Deliberately NOT `fleet.homes_list_path()`. That helper is redirected by
    the autouse sandbox above, so a guard that asked fleet for the path would
    hash the tmp file and ignore the one it exists to protect -- which is the
    same defect as the pin this replaces, one level down. Pinned by
    `tests/test_slice_e_pins.py::test_the_guard_asks_the_real_home_not_the_
    redirected_helper`."""
    return Path.home() / ".claude" / "fleet-homes.list"


def homes_list_snapshot(path):
    """`(exists, digest_or_None, size_or_None)`.

    CONTENTS, NOT EXISTENCE, and that is the whole repair. The pin this
    replaces (`tests/test_home_resolution.py::test_the_real_list_is_untouched`)
    compared `exists()` before and after -- and an APPEND, the only write the
    list's own writer can perform, does not move `exists()`. Measured: mutants
    that appended 122 and 117 records to a simulated real list left that pin
    green (`docs/lanes/w51-slicee.md` §3.2).

    Never raises. A session-scoped guard that dies at teardown takes the whole
    run's report with it, so an unreadable list is a STATE -- the same
    `list_unreadable` reason §4 already names."""
    import hashlib
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return (False, None, None)
    except OSError as exc:
        return (True, f"<unreadable: {type(exc).__name__}>", None)
    return (True, hashlib.sha256(raw).hexdigest(), len(raw))


def homes_list_drift(path, before):
    """`None` if unchanged, else `(before, after)`. Parameterised on `path` so
    the seeds can drive it against a file they may modify -- the same shape
    `code_plane_files(root)` uses, and for the same reason."""
    after = homes_list_snapshot(path)
    return None if after == before else (before, after)


@pytest.fixture(autouse=True, scope="session")
def _the_real_homes_list_is_untouched_afterwards():
    """§7's *"real-list-untouched pin"*, as the conftest half slice a1
    escalated and could not build inside its own fence.

    `~/.claude/fleet-homes.list` is APPEND-ONLY FOREVER and appending to it is
    RATIFIED DESTRUCTIVE -- only the fold reverses a record, and no verb
    un-appends one. So unlike the install-plane guard beside it, this one is
    not protecting a file that a human would notice going dirty in
    `git status`: the list is outside the repo entirely, and a stray record
    would be permanent and invisible.

    WHY A SESSION GUARD AND NOT A PER-TEST ASSERTION. `main()` transitively
    reaches `read_homes_list` -- measured, a 15-scope chain via
    `apply_resolved_home` -> `resolve_home` -> `resolution_population` -- and
    15 test files outside the four that sandbox it drive `main()`. Enumerating
    them is the shape that rots; hashing the file once around the whole run is
    the shape that does not.

    FALSE POSITIVE, NAMED SO IT IS NOT MISREAD: if the operator runs
    `fleet homes --add` in another terminal DURING a suite run, this fails and
    the suite is not at fault. The message says so."""
    path = real_homes_list_path()
    before = homes_list_snapshot(path)
    yield
    drift = homes_list_drift(path, before)
    assert drift is None, (
        f"the test suite changed the operator's real homes list at {path}: "
        f"{drift[0]} -> {drift[1]}. That file is append-only forever and an "
        f"append to it is RATIFIED DESTRUCTIVE -- only the fold reverses a "
        f"record. Something resolved a write through `homes_list_path()` "
        f"without the sandbox. Redirect it in `_never_touch_the_real_home` "
        f"rather than fixing the one test. (If you ran `fleet homes --add` in "
        f"another terminal while this suite was running, that is this "
        f"assertion working correctly on an innocent cause.)")


@pytest.fixture(autouse=True)
def _no_inherited_claude_session(monkeypatch):
    """Run every test as a HUMAN SHELL, not as whichever Claude session invoked
    pytest.

    The destructive-command guard (SPEC §5.1) keys off CLAUDE_CODE_SESSION_ID.
    When pytest itself is launched from a Claude Code session, that variable is
    inherited, every fixture worker looks foreign, and `fleet kill`/`clean`
    tests get refused -- a test outcome that depends on who ran the tests.
    Tests that exercise the guard set the variable explicitly.

    FLEET_WORKER is stripped for exactly the same reason, and it became
    load-bearing with claim-nonce §6.5's worker refusal in
    `_require_claim_holder`: `_worker_env` stamps it on every fleet-launched
    session, so a suite run FROM a fleet worker (which is how this repo is
    routinely developed) would see every `sup-*` test refused, while the same
    suite run from a human shell or CI passed. Tests that exercise the arm set
    it explicitly."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("FLEET_WORKER", raising=False)


def pytest_collection_modifyitems(config, items):
    """Tag every collected test with its tier (SPEC §12) and skip the live
    tier unless FLEET_LIVE=1 is set in the environment."""
    live_enabled = bool(os.environ.get("FLEET_LIVE"))
    live_skip = pytest.mark.skip(
        reason="live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness"
    )
    for item in items:
        name = Path(str(item.fspath)).name
        if name == "test_live_smoke.py" or "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.live)
            if not live_enabled:
                item.add_marker(live_skip)
        elif name == "test_hooks.py":
            item.add_marker(pytest.mark.hooks)
        else:
            item.add_marker(pytest.mark.unit)
