# Lane w69-wc — wave-close accounting

DONE means: defects 2-7 are fixed with targeted tests green on Python 3.10 and 3.12.

Implemented in `bin/fleet.py`:

- omitted `--base` resolves to the newest prior `fleet wave-close: wave N` commit;
  explicit `--base` remains an override;
- THROUGHPUT workers are merge-commit lanes since base, with substrate evidence;
- Claude roster and Codex mcx result/event usage are summed, with source-specific
  `UNMEASURED` when a source is absent;
- reap accounting reports `protected: N (unread mail)`;
- close refuses when any merge since base lacks a CHANGELOG line keyed by its SHA;
- interface rulings include only non-`lens/` task files without a `RULED:` line.

Checks:

- `tests/test_wave_close.py` + `tests/test_interface_state.py`: 21 passed on each
  Python 3.10 and 3.12.
- related archive/reap/docs/effect suites: 216 passed on each interpreter.
- Full-suite attempt hit the 300s harness limit; first failure is the documented
  pre-existing drive-qualified-path assumption test.
- `py_compile` and `git diff --check` pass on both interpreters.

Full logs: `/tmp/w69-wc-full-py310.log`, `/tmp/w69-wc-full-py312.log`,
`/tmp/w69-wc-first-failure-py310.log`.

PATH LIST:

- `bin/fleet.py`
- `tests/test_wave_close.py`
- `tests/test_interface_state.py`
- `docs/lanes/w69-wc.md`
- `state/journals/w69-wc.md`
