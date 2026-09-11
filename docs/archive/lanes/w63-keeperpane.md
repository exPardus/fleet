# Lane w63-keeperpane — find the interface by pane

DONE means: after the operator resumes and registers the interface in any tmux window, the next keeper tick sends any due pages to that pane and creates nothing.

MEASURED: started on `w63/keeper-pane` at `4923e16`; `MCX_WORKER=1` retained. No subagents or independent workers launched.
MEASURED: the requested model/effort is Codex `gpt-6-astra` / high.

## Outcome

MEASURED: `main()` now reads `state/interface-pane` before either its dry-run window check or `ensure_window()`, scans all panes with the specified format, and selects the registered ID only when `pane_dead` is `0`.
MEASURED: the argv pin records literal `send-keys -t %42 -l ...` followed by `send-keys -t %42 Enter`, with zero `new-window` or `kill-window` calls, when `%42` belongs to `claude` and no `fleet` window exists.
MEASURED: registration wins regardless of the current command (including `node` and `zsh`); missing/dead/gone registrations retain the existing window fallback and startup page deferral.
MEASURED: a separate named window produces `keeper: two interface candidates` once per tick; a registered pane in the named window, including splits, does not. Neither candidate is killed.
BELIEVED: “ONCE” means once per one-shot keeper tick, not a warning suppressed across timer processes; no persistent warning state was added.
MEASURED: unreadable/invalid registration and failed global scans defer without creating, sending, or changing delivery state. Failed delivery to a live registration retries through existing dedup behavior and never creates a replacement.
MEASURED: profile step 0 registers on launch AND resume, renames the window, guards against empty `$TMUX_PANE`, and writes the explicit fleet home's registration. The keeper adds no file writer; the targeted doctrine tests pass.
MEASURED: `git check-ignore -v state/interface-pane` returned `.gitignore:1:state/` before edits and `.gitignore:2:state/` after the explanatory comment. No new ignore pattern was necessary.
BELIEVED: live recovery will follow the fake-runner result when the resumed interface completes step 0 before the tick; no live host recovery was performed. Existing page dedup still applies, so only due pages are sent.

## Pin: RED, then GREEN

MEASURED: the following RED ran after adding the pin, before modifying the keeper at `4923e16`; the failure is the recorded `new-window` argv, not a return-value assertion.
MEASURED: command: `/home/altai/.cache/uv/archive-v0/hRf30whVn5xzWp_8/bin/python -m pytest -q -p no:cacheprovider --color=no tests/test_keeper_pane.py`.

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__ test_manual_resume_in_claude_window_pages_registered_pane_without_creating __

tmp_path = PosixPath('/tmp/pytest-of-altai/pytest-439/test_manual_resume_in_claude_w0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7e8f96f0a2d0>

    def test_manual_resume_in_claude_window_pages_registered_pane_without_creating(
            tmp_path, monkeypatch):
        register(tmp_path)
        runner = TmuxRunner(window="claude")  # No window named fleet exists.
        tick(tmp_path, runner, monkeypatch)
    
>       assert runner.tmux("new-window") == [], runner.calls
E       AssertionError: [['tmux', 'list-panes', '-t', 'work:fleet', '-F', '#{pane_current_command} #{pane_dead}'], ['tmux', 'new-window', '-d', '-t', 'work', '-n', ...]]
E       assert [['tmux', 'ne...', '-n', ...]] == []
E         
E         Left contains one more item: ['tmux', 'new-window', '-d', '-t', 'work', '-n', ...]
E         Use -v to get more diff

tests/test_keeper_pane.py:73: AssertionError
=========================== short test summary info ============================
FAILED tests/test_keeper_pane.py::test_manual_resume_in_claude_window_pages_registered_pane_without_creating
1 failed in 0.91s
```

MEASURED: after the fix, the same pin was green; the final focused re-run below selects its full node ID after the adjacent cases were added to that same file.
MEASURED: command: `/home/altai/.cache/uv/archive-v0/hRf30whVn5xzWp_8/bin/python -m pytest -q -p no:cacheprovider --color=no tests/test_keeper_pane.py::test_manual_resume_in_claude_window_pages_registered_pane_without_creating`.

```text
.                                                                        [100%]
1 passed in 0.12s
```

## Targeted checks

MEASURED: Python 3.12 targeted keeper suite: `154 passed in 4.85s`.
MEASURED: Python 3.10 targeted keeper suite: `154 passed in 2.18s`.
MEASURED: both commands used the cached environment's `bin/python -m pytest -q -p no:cacheprovider --color=no tests/test_keeper_*.py`; 3.12 environment `/home/altai/.cache/uv/archive-v0/hRf30whVn5xzWp_8`, 3.10 environment `/home/altai/.cache/uv/archive-v0/e_1AVh8OIO1kmAsH`.
MEASURED: new test file adds 15 cases covering the required pin, current-command independence, candidate conflicts/splits, absent/dead/gone registration, named fallback, dry-run, read/scan errors, and failed-delivery retry.
MEASURED: `git diff --check` passed; `bin/fleet.py` is unchanged. No full suite was run, as instructed.
BELIEVED: supplied baseline plus 15 tests predicts 5087 collected, 6 failed, 5064 passed, 16 skipped, 1 xfailed on the supervisor's full floor; this lane did not remeasure the supplied baseline.
MEASURED: full logs are `/tmp/w63-keeperpane/{pin-red,pin-green,keeper-3.12,keeper-3.10,python-setup}.log`.

## WHERE THIS BRIEF WAS WRONG

MEASURED: the reported `main -> ensure_window -> _panes(work:fleet)` path was correct. The uncertainty about pane-addressed sending is resolved: `page()` delegates to `fleet.type_interface_line()`, which already forwards any target unchanged to `send-keys -t`; no different send invocation or `bin/fleet.py` edit is needed.
MEASURED: the brief omitted a second window lookup in dry-run; it now shares registration selection, so it cannot claim it would create a window when a registered live pane exists.
MEASURED: the `state/` ignore assertion was correct; `.gitignore` only needed an explanatory comment.
MEASURED: the requested journal location is outside writable roots and its write returned read-only filesystem; the complete journal is retained at `/tmp/w63-keeperpane/journal.md` for supervisor placement.
MEASURED: prerequisite DONE — the documented uv command could not acquire its read-only cache lock; used its already-installed Python/pytest environments directly, without installation, network access, or permission escalation.
BELIEVED: treating a failed scan as “pane gone” would recreate the original duplicate-session risk; this implementation reports and defers instead, documented in the profile.

## Delivery

MEASURED: changed paths are `.gitignore`, `bin/fleet_keeper.py`, `docs/operator/server-interface-profile.md`, `tests/test_keeper_pane.py`, and this required report `docs/lanes/w63-keeperpane.md`.
MEASURED: the report is the explicit deliverable exception to the four-file implementation fence; SPEC/progress edits remain with the supervisor per this brief's scope.
MEASURED: no live tmux command, live fleet mutation, lock acquisition, repair, push, merge, or other ref movement was performed; the pre-existing untracked `.mcx/` directory was left untouched.
MEASURED: docs updated: `docs/operator/server-interface-profile.md`, `docs/lanes/w63-keeperpane.md`.

MEASURED: commit blocked at staging: `git add` exited 128 because `/home/altai/proga/fleet/.git/worktrees/fleet-w63-keeperpane/index.lock` could not be created (read-only filesystem). `git commit` was therefore not run; all five changed files are left in the worktree for the supervisor to commit on `w63/keeper-pane`. Full failure: `/tmp/w63-keeperpane/commit.log`. No sandbox workaround attempted.
