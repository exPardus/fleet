# SDD / drift-control — M-F Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the deterministic SDD acceptance gate — an accepted, machine-checkable campaign spec that workers bind to and `fleet spec verify` checks deterministically — entirely behind an off-by-default feature flag.

**Architecture:** A campaign spec is a git-tracked markdown file at `docs/specs/campaigns/<campaign>.md` carrying a fenced ```json machine block (criteria + scopes) and a human EARS/ADR body. `fleet spec new/accept/verify` manage its lifecycle; `spawn --spec` binds a worker, recording `spec`/`spec_slice` on the registry record and injecting a `## BINDING SPEC` section into the worker's task file. `verify` runs two deterministic criteria kinds (`files` scope containment, `pytest` node results) anchored to the bound worker's `cwd`, and writes an atomic stamp that views and doctor read. Every behavior is gated by `sdd_enabled()`; flagged off, fleet is byte-identical to today.

**Tech Stack:** Python 3.13 stdlib only (`json`, `hashlib`, `fnmatch`, `subprocess`, `pathlib`, `re`). Single file `bin/fleet.py`. pytest for tests.

## Global Constraints

- `bin/fleet.py` is **stdlib-only and single-file**. No new dependencies, no new modules under `bin/` except hooks. (CLAUDE.md)
- Python is invoked as `py -3.13` **from a human shell only**; inside `fleet.py`, always spawn Python via `sys.executable`. (CLAUDE.md + in-module doctrine)
- **Line numbers in this plan are anchors that have drifted** — M-E shipped since the source spec was written. Always `grep -n "def <name>" bin/fleet.py` to locate a function. Function names are the durable anchors. (SPEC.md §0)
- **Additive-schema rule:** registry fields are added, never renamed/removed; readers default missing fields with `.get()`; the single writer round-trips unknown keys. No migration step. (SPEC.md §4)
- **Views never take `fleet.lock`, never probe, never write** — they read `status_snapshot()` and exit 0. (CLAUDE.md, SPEC.md §14)
- **No lock is ever held across a subprocess.** (SPEC.md §5, F4 lock shape)
- Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored; `docs/` and `knowledge/` are git-tracked.
- Everything in this plan is **inert unless `sdd_enabled()` is true**. Default is off.
- Tests live in `tests/`; run with `py -3.13 -m pytest`.

---

### Task 1: Feature flag — `sdd_enabled()`

**Files:**
- Modify: `bin/fleet.py` (add near the other `state_dir`/`tasks_dir` path helpers — `grep -n "def tasks_dir" bin/fleet.py`)
- Test: `tests/test_spec.py` (new file)

**Interfaces:**
- Produces: `sdd_enabled() -> bool`, `config_path() -> Path`. Every later task guards on `sdd_enabled()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_spec.py`:

```python
import json
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "fleet", Path(__file__).resolve().parents[1] / "bin" / "fleet.py")
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


def test_sdd_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.delenv("FLEET_SDD", raising=False)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    assert fleet.sdd_enabled() is False


def test_sdd_enabled_by_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.delenv("FLEET_SDD", raising=False)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    fleet.config_path().write_text(json.dumps({"sdd": {"enabled": True}}), encoding="utf-8")
    assert fleet.sdd_enabled() is True


def test_sdd_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    fleet.config_path().write_text(json.dumps({"sdd": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setenv("FLEET_SDD", "1")
    assert fleet.sdd_enabled() is True


def test_sdd_tolerates_corrupt_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.delenv("FLEET_SDD", raising=False)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    fleet.config_path().write_text("{not json", encoding="utf-8")
    assert fleet.sdd_enabled() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -v`
Expected: FAIL — `AttributeError: module 'fleet' has no attribute 'sdd_enabled'`

- [ ] **Step 3: Write minimal implementation**

Add to `bin/fleet.py` beside the other path helpers:

```python
def config_path() -> Path:
    """Optional machine-local fleet config (gitignored). Absent == all defaults."""
    return state_dir() / "config.json"


def sdd_enabled() -> bool:
    """SDD subsystem master switch. Default OFF.

    FLEET_SDD env var wins (1/true/yes/on == enabled); else state/config.json
    {"sdd": {"enabled": true}}. Any read/parse failure == disabled: a flag that
    fails open would silently arm an unproven subsystem.
    """
    env = os.environ.get("FLEET_SDD")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("sdd", {}).get("enabled") is True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -v`
Expected: 4 passed

- [ ] **Step 5: Verify the full suite still passes**

Run: `py -3.13 -m pytest -q`
Expected: all pre-existing tests pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): sdd_enabled() master flag, default off"
```

---

### Task 2: Spec file location + machine-block parser

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: `sdd_enabled()` (Task 1).
- Produces: `campaign_specs_dir() -> Path`, `spec_path(campaign: str) -> Path`, `parse_spec(text: str) -> dict` (raises `SpecFormatError`), `SpecFormatError(Exception)`, `load_spec(campaign) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
import pytest

GOOD_SPEC = '''# Campaign md-demo

```json
{
  "spec": "md-demo",
  "status": "proposed",
  "author": "altai",
  "accepted_by": "",
  "reviewed_by": "",
  "accepted_digest": "",
  "scope_allow": ["src/**"],
  "scope_deny": ["state/**"],
  "criteria": [
    {"id": "C1", "ears": "The tool SHALL work.", "kind": "pytest",
     "nodes": ["tests/test_x.py::test_y"]}
  ]
}
```

## Context
Body prose here.
'''


def test_parse_spec_reads_first_json_fence():
    data = fleet.parse_spec(GOOD_SPEC)
    assert data["spec"] == "md-demo"
    assert data["criteria"][0]["id"] == "C1"


def test_parse_spec_rejects_missing_fence():
    with pytest.raises(fleet.SpecFormatError):
        fleet.parse_spec("# no machine block here\n")


def test_parse_spec_rejects_malformed_json():
    with pytest.raises(fleet.SpecFormatError):
        fleet.parse_spec("```json\n{not json\n```\n")


def test_parse_spec_rejects_missing_required_key():
    bad = GOOD_SPEC.replace('"criteria"', '"kriteria"')
    with pytest.raises(fleet.SpecFormatError):
        fleet.parse_spec(bad)


def test_spec_path_is_git_tracked_docs_location(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    p = fleet.spec_path("md-demo")
    assert p.parent == tmp_path / "docs" / "specs" / "campaigns"
    assert p.name == "md-demo.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -v`
Expected: FAIL — `AttributeError: module 'fleet' has no attribute 'parse_spec'`

- [ ] **Step 3: Write minimal implementation**

Add to `bin/fleet.py`:

```python
_SPEC_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
_SPEC_REQUIRED_KEYS = ("spec", "status", "author", "criteria")


class SpecFormatError(Exception):
    """A campaign spec is unparseable or structurally invalid. Never a silent pass."""


def campaign_specs_dir() -> Path:
    """Git-tracked campaign specs (R4) -- NOT a runtime dir."""
    return FLEET_HOME / "docs" / "specs" / "campaigns"


def spec_path(campaign: str) -> Path:
    return campaign_specs_dir() / f"{campaign}.md"


def parse_spec(text: str) -> dict:
    """Parse the FIRST fenced ```json block as the machine contract."""
    m = _SPEC_JSON_FENCE_RE.search(text)
    if not m:
        raise SpecFormatError("no fenced ```json machine block found")
    try:
        data = json.loads(m.group(1))
    except Exception as exc:
        raise SpecFormatError(f"machine block is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecFormatError("machine block must be a JSON object")
    missing = [k for k in _SPEC_REQUIRED_KEYS if k not in data]
    if missing:
        raise SpecFormatError(f"machine block missing required key(s): {', '.join(missing)}")
    if not isinstance(data.get("criteria"), list):
        raise SpecFormatError("'criteria' must be a list")
    return data


def load_spec(campaign: str) -> dict:
    path = spec_path(campaign)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SpecFormatError(f"no spec at {path}") from exc
    return parse_spec(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): campaign spec location + JSON machine-block parser"
```

---

### Task 3: `accepted_digest` — canonical hash of executable fields

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: `parse_spec` (Task 2).
- Produces: `spec_executable_fields(data: dict) -> dict`, `spec_digest(data: dict) -> str` (hex sha256).

The digest covers only fields that *drive execution* — criteria and scopes. Prose (`ears`, the body) is excluded so a human can fix wording without breaking the signature; anything that changes what runs must break it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
def test_digest_is_stable_across_key_order():
    a = fleet.parse_spec(GOOD_SPEC)
    b = dict(reversed(list(a.items())))
    assert fleet.spec_digest(a) == fleet.spec_digest(b)


def test_digest_ignores_prose_changes():
    a = fleet.parse_spec(GOOD_SPEC)
    b = fleet.parse_spec(GOOD_SPEC)
    b["criteria"][0]["ears"] = "totally different prose"
    assert fleet.spec_digest(a) == fleet.spec_digest(b)


def test_digest_changes_when_a_test_node_changes():
    a = fleet.parse_spec(GOOD_SPEC)
    b = fleet.parse_spec(GOOD_SPEC)
    b["criteria"][0]["nodes"] = ["tests/test_x.py::test_EVIL"]
    assert fleet.spec_digest(a) != fleet.spec_digest(b)


def test_digest_changes_when_scope_widens():
    a = fleet.parse_spec(GOOD_SPEC)
    b = fleet.parse_spec(GOOD_SPEC)
    b["scope_allow"] = ["**"]
    assert fleet.spec_digest(a) != fleet.spec_digest(b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k digest -v`
Expected: FAIL — `AttributeError: ... 'spec_digest'`

- [ ] **Step 3: Write minimal implementation**

Add to `bin/fleet.py` (ensure `import hashlib` exists at the top):

```python
def spec_executable_fields(data: dict) -> dict:
    """Only what drives execution. Prose is deliberately excluded."""
    crit = []
    for c in data.get("criteria") or []:
        crit.append({
            "id": c.get("id"),
            "kind": c.get("kind"),
            "nodes": sorted(c.get("nodes") or []),
            "scope_allow": sorted(c.get("scope_allow") or []),
            "scope_deny": sorted(c.get("scope_deny") or []),
        })
    crit.sort(key=lambda c: (c["id"] or ""))
    slices = {}
    for name, sl in sorted((data.get("slices") or {}).items()):
        slices[name] = {
            "scope_allow": sorted(sl.get("scope_allow") or []),
            "scope_deny": sorted(sl.get("scope_deny") or []),
            "criteria": sorted(sl.get("criteria") or []),
        }
    return {
        "scope_allow": sorted(data.get("scope_allow") or []),
        "scope_deny": sorted(data.get("scope_deny") or []),
        "slices": slices,
        "criteria": crit,
    }


def spec_digest(data: dict) -> str:
    canon = json.dumps(spec_executable_fields(data), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k digest -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): accepted_digest over executable fields only"
```

---

### Task 4: Scope resolution — slice ∩ whole-spec (R2)

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces: `effective_scope(data: dict, slice_name: str | None) -> tuple[list[str], list[str]]`, `glob_contains(outer: str, inner: str) -> bool`, `check_slice_scopes(data: dict) -> list[str]` (returns problem strings; empty == OK).

R2: a slice may only **narrow**. A slice `scope_allow` pattern not contained by some whole-spec pattern is an error, as is a pattern-domain intersection between two slices.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
def test_glob_containment_prefix_and_doublestar():
    assert fleet.glob_contains("src/**", "src/app/**")
    assert fleet.glob_contains("src/**", "src/a.py")
    assert fleet.glob_contains("**", "anything/at/all.py")
    assert not fleet.glob_contains("src/**", "docs/a.py")
    assert not fleet.glob_contains("src/a.py", "src/**")


def test_effective_scope_intersects_slice_with_whole_spec():
    data = fleet.parse_spec(GOOD_SPEC)
    data["slices"] = {"w1": {"scope_allow": ["src/app/**"], "scope_deny": ["src/app/gen/**"],
                             "criteria": ["C1"]}}
    allow, deny = fleet.effective_scope(data, "w1")
    assert allow == ["src/app/**"]
    assert "state/**" in deny and "src/app/gen/**" in deny


def test_effective_scope_without_slice_is_whole_spec():
    data = fleet.parse_spec(GOOD_SPEC)
    allow, deny = fleet.effective_scope(data, None)
    assert allow == ["src/**"] and deny == ["state/**"]


def test_slice_widening_is_rejected():
    data = fleet.parse_spec(GOOD_SPEC)
    data["slices"] = {"w1": {"scope_allow": ["docs/**"], "criteria": []}}
    problems = fleet.check_slice_scopes(data)
    assert any("widen" in p for p in problems)


def test_overlapping_slices_are_rejected():
    data = fleet.parse_spec(GOOD_SPEC)
    data["slices"] = {
        "w1": {"scope_allow": ["src/**"], "criteria": []},
        "w2": {"scope_allow": ["src/app/**"], "criteria": []},
    }
    problems = fleet.check_slice_scopes(data)
    assert any("overlap" in p for p in problems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k "scope or glob or slice" -v`
Expected: FAIL — `AttributeError: ... 'glob_contains'`

- [ ] **Step 3: Write minimal implementation**

Add to `bin/fleet.py`:

```python
def _glob_prefix(pattern: str) -> str | None:
    """Literal directory prefix of a '<prefix>/**' pattern, else None."""
    if pattern == "**":
        return ""
    if pattern.endswith("/**"):
        head = pattern[:-3]
        if "*" not in head and "?" not in head:
            return head
    return None


def glob_contains(outer: str, inner: str) -> bool:
    """True if every path matching `inner` also matches `outer`.

    Pure pattern-domain reasoning -- NEVER a filesystem match, which would be
    blind to files that do not exist yet (round-2 F5).
    """
    if outer == inner:
        return True
    op = _glob_prefix(outer)
    if op is None:
        return False
    if op == "":
        return True
    ip = _glob_prefix(inner)
    target = ip if ip is not None else inner
    return target == op or target.startswith(op + "/")


def effective_scope(data: dict, slice_name: str | None):
    """R2: effective scope = slice INTERSECT whole-spec. A slice only narrows."""
    allow = list(data.get("scope_allow") or [])
    deny = list(data.get("scope_deny") or [])
    sl = (data.get("slices") or {}).get(slice_name) if slice_name else None
    if sl:
        allow = list(sl.get("scope_allow") or allow)
        deny = deny + list(sl.get("scope_deny") or [])
    return allow, deny


def check_slice_scopes(data: dict) -> list[str]:
    problems = []
    whole = list(data.get("scope_allow") or [])
    slices = data.get("slices") or {}
    for name, sl in sorted(slices.items()):
        for pat in sl.get("scope_allow") or []:
            if whole and not any(glob_contains(w, pat) for w in whole):
                problems.append(
                    f"slice '{name}' pattern '{pat}' would widen beyond the whole-spec scope")
    names = sorted(slices)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for pa in slices[a].get("scope_allow") or []:
                for pb in slices[b].get("scope_allow") or []:
                    if glob_contains(pa, pb) or glob_contains(pb, pa):
                        problems.append(
                            f"slices '{a}' and '{b}' overlap on '{pa}' / '{pb}'")
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k "scope or glob or slice" -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): pattern-domain scope resolution, slice may only narrow"
```

---

### Task 5: Touched-path enumeration — the four git commands

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces: `touched_paths(cwd: Path, base: str | None, run=subprocess.run) -> set[str]`.

The `--exclude-standard`-only query **omits ignored files** — the ignored query is mandatory or every gitignored deny target is invisible (round-2 F2). `run` is injected so tests need no real repo.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
class _FakeRun:
    def __init__(self, outputs): self.outputs, self.calls = outputs, []
    def __call__(self, argv, **kw):
        self.calls.append(argv)
        key = tuple(a for a in argv if a.startswith("--") or a in ("diff", "ls-files"))
        class R: pass
        r = R(); r.returncode = 0; r.stdout = self.outputs.get(key, ""); r.stderr = ""
        return r


def test_touched_paths_unions_all_four_queries():
    fake = _FakeRun({
        ("diff", "--name-only"): "src/a.py\n",
        ("diff", "--cached", "--name-only"): "src/b.py\n",
        ("ls-files", "--others", "--exclude-standard"): "src/new.py\n",
        ("ls-files", "--others", "--ignored", "--exclude-standard"): "state/secret.json\n",
    })
    got = fleet.touched_paths(Path("."), "HEAD", run=fake)
    assert got == {"src/a.py", "src/b.py", "src/new.py", "state/secret.json"}
    assert len(fake.calls) == 4


def test_touched_paths_includes_ignored_query():
    fake = _FakeRun({})
    fleet.touched_paths(Path("."), "HEAD", run=fake)
    assert any("--ignored" in c for c in fake.calls), \
        "the ignored query is mandatory: without it every gitignored deny target is invisible"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k touched -v`
Expected: FAIL — `AttributeError: ... 'touched_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
def touched_paths(cwd: Path, base: str | None, run=None) -> set[str]:
    """Union of FOUR git queries. Three is not enough (round-2 F2)."""
    run = run or subprocess.run
    base_args = [base] if base else []
    queries = [
        ["diff", "--name-only", *base_args],
        ["diff", "--cached", "--name-only", *base_args],
        ["ls-files", "--others", "--exclude-standard"],
        ["ls-files", "--others", "--ignored", "--exclude-standard"],
    ]
    out: set[str] = set()
    for q in queries:
        try:
            r = run(["git", "-C", str(cwd), *q], capture_output=True, text=True, timeout=30)
        except Exception:
            continue
        if getattr(r, "returncode", 1) != 0:
            continue
        for line in (r.stdout or "").splitlines():
            line = line.strip().replace("\\", "/")
            if line:
                out.add(line)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k touched -v`
Expected: 2 passed

- [ ] **Step 5: Add a real-git integration test**

```python
def test_touched_paths_against_a_real_repo(tmp_path):
    import subprocess as sp
    sp.run(["git", "init", "-q", str(tmp_path)], check=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / ".gitignore").write_text("state/\n", encoding="utf-8")
    (tmp_path / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    sp.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    sp.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    (tmp_path / "tracked.py").write_text("x = 2\n", encoding="utf-8")   # modified
    (tmp_path / "fresh.py").write_text("y = 1\n", encoding="utf-8")     # untracked
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "leak.json").write_text("{}", encoding="utf-8")  # IGNORED
    got = fleet.touched_paths(tmp_path, "HEAD")
    assert "tracked.py" in got and "fresh.py" in got
    assert "state/leak.json" in got, "the ignored file must be visible or scope_deny is dead"
```

Run: `py -3.13 -m pytest tests/test_spec.py -k touched -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): four-query touched-path union incl. the ignored query"
```

---

### Task 6: Criteria evaluation — `files` and `pytest` kinds

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: `effective_scope` (T4), `touched_paths` (T5).
- Produces: `CriterionResult` namedtuple `(id, status, detail)` where status ∈ `"PASS"|"FAIL"|"INFRA"`; `eval_files_criterion(...)`, `eval_pytest_criterion(...)`, `eval_criterion(...)`.

Exit-class rules (round-2 F4): a node that **resolves but collects zero tests** is under-delivery → FAIL, never INFRA. INFRA is only runner/interpreter absent or a project-wide collection crash. Ambiguity resolves toward FAIL. Unknown `kind` → FAIL (fail-closed).

- [ ] **Step 1: Write the failing test**

```python
def test_files_criterion_passes_when_all_paths_in_scope():
    r = fleet.eval_files_criterion("C9", {"src/a.py"}, ["src/**"], ["state/**"])
    assert r.status == "PASS"


def test_files_criterion_fails_on_out_of_scope_path():
    r = fleet.eval_files_criterion("C9", {"docs/x.md"}, ["src/**"], [])
    assert r.status == "FAIL" and "docs/x.md" in r.detail


def test_files_criterion_fails_on_denied_path():
    r = fleet.eval_files_criterion("C9", {"state/leak.json"}, ["**"], ["state/**"])
    assert r.status == "FAIL" and "state/leak.json" in r.detail


def test_unknown_kind_fails_closed():
    r = fleet.eval_criterion({"id": "C9", "kind": "wishful"}, Path("."), set(), [], [], run=None)
    assert r.status == "FAIL" and "unknown kind" in r.detail.lower()


def test_pytest_zero_collect_is_FAIL_not_infra():
    def run(argv, **kw):
        class R: pass
        r = R(); r.returncode = 5; r.stdout = "collected 0 items"; r.stderr = ""
        return r
    r = fleet.eval_pytest_criterion("C9", Path("."), ["tests/t.py::nope"], run=run)
    assert r.status == "FAIL", "zero-collect is under-delivery; INFRA would let a worker dodge"


def test_pytest_missing_runner_is_INFRA():
    def run(argv, **kw): raise FileNotFoundError("no pytest")
    r = fleet.eval_pytest_criterion("C9", Path("."), ["tests/t.py::x"], run=run)
    assert r.status == "INFRA"


def test_pytest_assertion_failure_is_FAIL():
    def run(argv, **kw):
        class R: pass
        r = R(); r.returncode = 1; r.stdout = "1 failed"; r.stderr = ""
        return r
    r = fleet.eval_pytest_criterion("C9", Path("."), ["tests/t.py::x"], run=run)
    assert r.status == "FAIL"


def test_pytest_pass_is_PASS():
    def run(argv, **kw):
        class R: pass
        r = R(); r.returncode = 0; r.stdout = "1 passed"; r.stderr = ""
        return r
    r = fleet.eval_pytest_criterion("C9", Path("."), ["tests/t.py::x"], run=run)
    assert r.status == "PASS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k "criterion or pytest_" -v`
Expected: FAIL — `AttributeError: ... 'eval_files_criterion'`

- [ ] **Step 3: Write minimal implementation**

```python
CriterionResult = collections.namedtuple("CriterionResult", "id status detail")


def _path_matches_any(path: str, patterns) -> bool:
    return any(fnmatch.fnmatch(path, p) or
               (p.endswith("/**") and (path == p[:-3] or path.startswith(p[:-3] + "/")))
               or p == "**"
               for p in patterns)


def eval_files_criterion(cid, touched, allow, deny) -> CriterionResult:
    bad = []
    for path in sorted(touched):
        if deny and _path_matches_any(path, deny):
            bad.append(f"{path} (denied)")
        elif allow and not _path_matches_any(path, allow):
            bad.append(f"{path} (out of scope)")
    if bad:
        return CriterionResult(cid, "FAIL", "out-of-scope paths: " + ", ".join(bad))
    return CriterionResult(cid, "PASS", f"{len(touched)} touched path(s) in scope")


def eval_pytest_criterion(cid, cwd, nodes, run=None) -> CriterionResult:
    run = run or subprocess.run
    if not nodes:
        return CriterionResult(cid, "FAIL", "no test nodes declared (under-delivery)")
    for node in nodes:
        try:
            r = run([sys.executable, "-m", "pytest", node, "-q"],
                    cwd=str(cwd), capture_output=True, text=True, timeout=900)
        except Exception as exc:
            return CriterionResult(cid, "INFRA", f"runner unavailable: {exc}")
        rc = getattr(r, "returncode", 1)
        blob = f"{getattr(r, 'stdout', '')}{getattr(r, 'stderr', '')}"
        if rc == 0:
            continue
        # rc 5 == no tests collected. That is a MISSING deliverable, not a broken
        # harness: classing it INFRA would let a worker dodge a real FAIL by
        # deleting or renaming the target test (round-2 F4).
        if rc == 5 or "collected 0 items" in blob or "no tests ran" in blob.lower():
            return CriterionResult(cid, "FAIL", f"{node}: collected 0 tests (under-delivery)")
        if rc == 4 or "usage error" in blob.lower():
            return CriterionResult(cid, "INFRA", f"{node}: pytest usage error")
        return CriterionResult(cid, "FAIL", f"{node}: pytest rc={rc}")
    return CriterionResult(cid, "PASS", f"{len(nodes)} node(s) passed")


def eval_criterion(crit, cwd, touched, allow, deny, run=None) -> CriterionResult:
    cid = crit.get("id") or "<no-id>"
    kind = crit.get("kind")
    if kind == "files":
        return eval_files_criterion(cid, touched, allow, deny)
    if kind == "pytest":
        return eval_pytest_criterion(cid, cwd, crit.get("nodes") or [], run=run)
    return CriterionResult(cid, "FAIL", f"unknown kind {kind!r} (fail-closed)")
```

Ensure `import collections, fnmatch, sys, subprocess` are present at the top of `fleet.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k "criterion or pytest_" -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): files + pytest criteria, fail-closed, zero-collect is FAIL"
```

---

### Task 7: `spec new` and `spec accept` (durable-actor promotion guard)

**Files:**
- Modify: `bin/fleet.py` (add subcommands to the arg parser — `grep -n "add_parser(" bin/fleet.py` to find the parser block)
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: `spec_path`, `parse_spec`, `spec_digest`, `check_slice_scopes`, `sdd_enabled`.
- Produces: `cmd_spec_new(args) -> int`, `cmd_spec_accept(args) -> int`, `write_spec(campaign, data, body) -> None`, `spec_actor() -> str`.

`spec accept` refuses when `accepted_by == author` and when `reviewed_by` is empty or equals the author. Identity is the **durable actor** (operator/claim-holder), never a rotating incarnation id.

- [ ] **Step 1: Write the failing test**

```python
def _mk(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_SDD", "1")
    fleet.campaign_specs_dir().mkdir(parents=True, exist_ok=True)
    data = fleet.parse_spec(GOOD_SPEC); data.update(over)
    fleet.write_spec("md-demo", data, "## Context\nbody\n")
    return data


def test_accept_refuses_self_promotion(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md")
    monkeypatch.setenv("FLEET_ACTOR", "altai")
    rc = fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    assert rc != 0
    assert fleet.load_spec("md-demo")["status"] == "proposed"


def test_accept_refuses_without_review_receipt(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="")
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    rc = fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    assert rc != 0


def test_accept_succeeds_and_stamps_digest(tmp_path, monkeypatch):
    data = _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md")
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    rc = fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    assert rc == 0
    got = fleet.load_spec("md-demo")
    assert got["status"] == "accepted"
    assert got["accepted_by"] == "maga"
    assert got["accepted_digest"] == fleet.spec_digest(data)


def test_accept_refuses_a_widening_slice(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md",
        slices={"w1": {"scope_allow": ["docs/**"], "criteria": []}})
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    rc = fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    assert rc != 0


def test_spec_verbs_are_inert_when_flag_off(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md")
    monkeypatch.setenv("FLEET_SDD", "0")
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    rc = fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    assert rc != 0
    assert fleet.load_spec("md-demo")["status"] == "proposed"
```

Add `import types` at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k accept -v`
Expected: FAIL — `AttributeError: ... 'write_spec'`

- [ ] **Step 3: Write minimal implementation**

```python
def spec_actor() -> str:
    """The DURABLE actor -- operator identity, never a rotating incarnation id
    (a per-session id makes the no-self-promotion check trivially defeatable)."""
    return (os.environ.get("FLEET_ACTOR") or "").strip() or "unknown"


def write_spec(campaign: str, data: dict, body: str) -> None:
    path = spec_path(campaign)
    path.parent.mkdir(parents=True, exist_ok=True)
    block = json.dumps(data, indent=2, sort_keys=False)
    path.write_text(f"# Campaign {campaign}\n\n```json\n{block}\n```\n\n{body}", encoding="utf-8")


def _spec_body(campaign: str) -> str:
    text = spec_path(campaign).read_text(encoding="utf-8")
    m = _SPEC_JSON_FENCE_RE.search(text)
    return text[m.end():].lstrip("\n") if m else ""


def cmd_spec_new(args) -> int:
    if not sdd_enabled():
        print("sdd is disabled (set FLEET_SDD=1 or state/config.json)", file=sys.stderr)
        return 1
    if spec_path(args.campaign).exists():
        print(f"spec already exists: {spec_path(args.campaign)}", file=sys.stderr)
        return 1
    data = {"spec": args.campaign, "status": "proposed", "author": spec_actor(),
            "accepted_by": "", "reviewed_by": "", "accepted_digest": "",
            "links": [], "scope_allow": [], "scope_deny": ["state/**", "logs/**", "mailbox/**"],
            "slices": {}, "criteria": []}
    write_spec(args.campaign, data, "## Context\n\n## Decision\n\n## Consequences\n\n"
                                    "## Requirements (EARS)\n")
    print(f"created {spec_path(args.campaign)} (status=proposed)")
    return 0


def cmd_spec_accept(args) -> int:
    if not sdd_enabled():
        print("sdd is disabled", file=sys.stderr)
        return 1
    try:
        data = load_spec(args.campaign)
    except SpecFormatError as exc:
        print(f"cannot accept: {exc}", file=sys.stderr)
        return 2
    actor = spec_actor()
    author = (data.get("author") or "").strip()
    reviewed = (data.get("reviewed_by") or "").strip()
    if data.get("status") != "proposed":
        print(f"spec is {data.get('status')!r}, not 'proposed'", file=sys.stderr)
        return 1
    if actor == "unknown":
        print("set FLEET_ACTOR to the accepting operator", file=sys.stderr)
        return 1
    if actor == author:
        print("refusing: an author may not promote its own spec", file=sys.stderr)
        return 1
    if not reviewed or reviewed == author:
        print("refusing: reviewed_by must name a review doc from a reviewer != author",
              file=sys.stderr)
        return 1
    problems = check_slice_scopes(data)
    if problems:
        for p in problems:
            print(f"slice problem: {p}", file=sys.stderr)
        return 2
    body = _spec_body(args.campaign)
    data["status"] = "accepted"
    data["accepted_by"] = actor
    data["accepted_digest"] = spec_digest(data)
    write_spec(args.campaign, data, body)
    append_event("spec_accepted", spec=args.campaign, accepted_by=actor)
    print(f"accepted {args.campaign} (digest {data['accepted_digest'][:12]})")
    return 0
```

`append_event` already exists — `grep -n "def append_event" bin/fleet.py` and match its real signature; if it takes a dict, adapt the call.

- [ ] **Step 4: Wire the subcommands**

Find the parser block (`grep -n "add_parser(" bin/fleet.py`) and register a `spec` subparser with `new` and `accept` actions dispatching to `cmd_spec_new` / `cmd_spec_accept`, following the file's existing parser style exactly.

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k accept -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): spec new/accept with durable-actor no-self-promotion guard"
```

---

### Task 8: `spec verify` — the gate, with tamper check and atomic stamp

**Files:**
- Modify: `bin/fleet.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `verify_stamp_path(campaign) -> Path`, `cmd_spec_verify(args) -> int`.

Exit contract: **0** all-pass · **1** any criterion FAIL · **2** harness failure (unparseable spec, digest tamper, INFRA criterion, slice problems). Ambiguity resolves toward 1.

- [ ] **Step 1: Write the failing test**

```python
def test_verify_refuses_on_digest_tamper(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md")
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    data = fleet.load_spec("md-demo")
    data["criteria"][0]["nodes"] = ["tests/test_x.py::test_EVIL"]   # post-accept tamper
    fleet.write_spec("md-demo", data, "body")
    rc = fleet.cmd_spec_verify(types.SimpleNamespace(campaign="md-demo", worker=None))
    assert rc == 2


def test_verify_stamp_is_written_and_readable(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md", criteria=[])
    monkeypatch.setenv("FLEET_ACTOR", "maga")
    fleet.cmd_spec_accept(types.SimpleNamespace(campaign="md-demo"))
    fleet.cmd_spec_verify(types.SimpleNamespace(campaign="md-demo", worker=None))
    stamp = json.loads(fleet.verify_stamp_path("md-demo").read_text(encoding="utf-8"))
    assert stamp["spec_status"] == "accepted" and "overall" in stamp


def test_verify_on_proposed_spec_is_exit_2(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="altai", reviewed_by="docs/reviews/r.md")
    rc = fleet.cmd_spec_verify(types.SimpleNamespace(campaign="md-demo", worker=None))
    assert rc == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k verify -v`
Expected: FAIL — `AttributeError: ... 'cmd_spec_verify'`

- [ ] **Step 3: Write minimal implementation**

```python
def verify_stamp_path(campaign: str) -> Path:
    """Runtime, gitignored -- derived and regenerated by every verify."""
    return state_dir() / "spec-verify" / f"{campaign}.json"


def cmd_spec_verify(args) -> int:
    if not sdd_enabled():
        print("sdd is disabled", file=sys.stderr)
        return 2
    try:
        data = load_spec(args.campaign)
    except SpecFormatError as exc:
        print(f"cannot verify: {exc}", file=sys.stderr)
        return 2
    if data.get("status") != "accepted":
        print(f"spec is {data.get('status')!r}; only an accepted spec is verifiable",
              file=sys.stderr)
        return 2
    recorded = (data.get("accepted_digest") or "").strip()
    if not recorded or recorded != spec_digest(data):
        print("TAMPER: executable fields changed since accept -- refusing", file=sys.stderr)
        return 2
    problems = check_slice_scopes(data)
    if problems:
        for p in problems:
            print(f"slice problem: {p}", file=sys.stderr)
        return 2

    slice_name = None
    cwd = Path.cwd()
    if getattr(args, "worker", None):
        reg = load_registry()
        rec = (reg.get("workers") or {}).get(args.worker) or {}
        slice_name = rec.get("spec_slice")
        if rec.get("cwd"):
            cwd = Path(rec["cwd"])
    allow, deny = effective_scope(data, slice_name)
    base = None
    if getattr(args, "worker", None):
        base = ((load_registry().get("workers") or {})
                .get(args.worker, {}).get("spec_baseline_sha"))
    touched = touched_paths(cwd, base)

    wanted = None
    if slice_name:
        wanted = set((data.get("slices") or {}).get(slice_name, {}).get("criteria") or [])
    results = []
    for crit in data.get("criteria") or []:
        if wanted is not None and crit.get("id") not in wanted:
            continue
        results.append(eval_criterion(crit, cwd, touched, allow, deny))
    results.append(eval_files_criterion("_scope", touched, allow, deny))

    overall = "PASS"
    if any(r.status == "FAIL" for r in results):
        overall = "FAIL"
    elif any(r.status == "INFRA" for r in results):
        overall = "INFRA"

    stamp = {"ts": now_iso(), "spec": args.campaign, "spec_status": data.get("status"),
             "digest": recorded, "slice": slice_name, "overall": overall,
             "per_criterion": [{"id": r.id, "status": r.status, "detail": r.detail}
                               for r in results]}
    verify_stamp_path(args.campaign).parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(verify_stamp_path(args.campaign), stamp)

    for r in results:
        print(f"{r.status:5} {r.id}: {r.detail}")
    print(f"overall: {overall}")
    return {"PASS": 0, "FAIL": 1, "INFRA": 2}[overall]
```

Confirm the real names of `load_registry`, `now_iso`, and `_write_json_atomic` by grep before writing; adapt if they differ.

- [ ] **Step 4: Wire `spec verify` into the parser** (same style as Task 7 step 4), with `--worker`.

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.13 -m pytest tests/test_spec.py -k verify -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): spec verify gate -- tamper check, criteria, atomic stamp"
```

---

### Task 9: Binding — registry fields, `spawn --spec`, refuse-proposed, respawn carry

**Files:**
- Modify: `bin/fleet.py` (`new_worker_record`, `dispatch_bg`, `compose_prompt`, `cmd_respawn`)
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces: registry fields `spec`, `spec_slice`, `spec_baseline_sha`; `spec_section_for(campaign, slice_name) -> str`; `current_head_sha(cwd) -> str | None`.

Respawn rebuilds the record through `new_worker_record`, which has a **fixed key set and no `**kwargs`** — any field not explicitly copied is LOST. The binding must be copied by hand and the baseline **re-stamped** (round-2 F2/A2/A3).

- [ ] **Step 1: Write the failing test**

```python
def test_new_worker_record_has_spec_fields_defaulting_null():
    rec = fleet.new_worker_record(None, "C:/tmp", "task", "bypass")
    assert rec["spec"] is None and rec["spec_slice"] is None
    assert rec["spec_baseline_sha"] is None


def test_pre_sdd_record_loads_unchanged():
    old = {"session_id": "s", "cwd": "C:/tmp", "status": "idle"}
    assert old.get("spec") is None          # readers must .get() -- no KeyError


def test_spec_section_names_scope_and_criteria(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="a", reviewed_by="r",
        slices={"w1": {"scope_allow": ["src/**"], "criteria": ["C1"]}})
    sec = fleet.spec_section_for("md-demo", "w1")
    assert "BINDING SPEC" in sec and "src/**" in sec
    assert "re-read" in sec.lower()


def test_respawn_carries_binding_and_restamps_baseline(tmp_path, monkeypatch):
    before = {"spec": "md-demo", "spec_slice": "w1", "spec_baseline_sha": "OLDSHA",
              "cwd": str(tmp_path)}
    after = fleet.new_worker_record(None, str(tmp_path), "task", "bypass")
    fleet.carry_spec_binding(before, after, new_baseline="NEWSHA")
    assert after["spec"] == "md-demo" and after["spec_slice"] == "w1"
    assert after["spec_baseline_sha"] == "NEWSHA", \
        "a carried-over stale baseline diffs already-merged work and false-blocks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k "record or binding or section" -v`
Expected: FAIL — `KeyError: 'spec'`

- [ ] **Step 3: Add the fields and helpers**

In `new_worker_record`'s returned dict add (additive — never rename/remove existing keys):

```python
        "spec": None,
        "spec_slice": None,
        "spec_baseline_sha": None,
```

Then add:

```python
def current_head_sha(cwd) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    return (r.stdout or "").strip() or None if r.returncode == 0 else None


def carry_spec_binding(before: dict, after: dict, new_baseline: str | None) -> None:
    """new_worker_record has a FIXED key set -- anything not copied here is lost."""
    after["spec"] = before.get("spec")
    after["spec_slice"] = before.get("spec_slice")
    after["spec_baseline_sha"] = new_baseline


def spec_section_for(campaign: str, slice_name: str | None) -> str:
    data = load_spec(campaign)
    allow, deny = effective_scope(data, slice_name)
    wanted = None
    if slice_name:
        wanted = set((data.get("slices") or {}).get(slice_name, {}).get("criteria") or [])
    lines = ["## BINDING SPEC",
             f"Contract: docs/specs/campaigns/{campaign}.md (slice: {slice_name or 'whole-spec'})",
             "**Re-read this file at the start of every turn.** It is the contract you are",
             "bound to; your work is verified against it deterministically.",
             f"Allowed paths: {', '.join(allow) or '(none declared)'}",
             f"Forbidden paths: {', '.join(deny) or '(none)'}",
             "Criteria you own:"]
    for c in data.get("criteria") or []:
        if wanted is not None and c.get("id") not in wanted:
            continue
        lines.append(f"- {c.get('id')}: {c.get('ears', '')}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Thread the binding through dispatch**

1. `compose_prompt` — add a `spec_section: str | None = None` keyword param; when set, append it to the composed body (it is the *composer*; `dispatch_bg` only writes the finished body).
2. `dispatch_bg` — add a `spec: str | None = None` param; when set and `sdd_enabled()`, append a second `--add-dir` for `campaign_specs_dir()` next to the existing `tasks_dir()` one.
3. In `dispatch_bg`, before launching: if `spec` is set, `load_spec(spec)` and **refuse (raise / return non-zero, no launch)** unless `status == "accepted"`.
4. `cmd_spawn` — accept `--spec` / `--slice`, stamp `spec`, `spec_slice`, and `spec_baseline_sha = current_head_sha(cwd)` on the pre-claim record.
5. `cmd_respawn` — where it hand-copies `cost_usd`/`retired_sids`, also call
   `carry_spec_binding(before, new_record, new_baseline=current_head_sha(cwd))`.

Every one of these paths must be a no-op when `sdd_enabled()` is false.

- [ ] **Step 5: Add the refuse-proposed test**

```python
def test_dispatch_refuses_a_proposed_spec(tmp_path, monkeypatch):
    _mk(tmp_path, monkeypatch, author="a", reviewed_by="r")   # status == proposed
    with pytest.raises(Exception):
        fleet.assert_spec_bindable("md-demo")
```

Implement:

```python
def assert_spec_bindable(campaign: str) -> dict:
    data = load_spec(campaign)
    if data.get("status") != "accepted":
        raise SpecFormatError(
            f"refusing to bind: spec {campaign!r} is {data.get('status')!r}, not accepted")
    return data
```

- [ ] **Step 6: Run the tests**

Run: `py -3.13 -m pytest tests/test_spec.py -v`
Expected: all pass

- [ ] **Step 7: Full suite — no regressions**

Run: `py -3.13 -m pytest -q`
Expected: every pre-existing test still passes (the flag is off in their environment)

- [ ] **Step 8: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): bind workers to specs; respawn carries binding, re-stamps baseline"
```

---

### Task 10: Surfacing — status flag + doctor check (stamp-read only)

**Files:**
- Modify: `bin/fleet.py` (`status_snapshot` / the status table renderer; add `_doctor_check_spec_drift`)
- Test: `tests/test_spec.py`, `tests/test_terminal_surface.py`

**Interfaces:**
- Produces: `read_verify_stamp(campaign) -> dict | None`, `_doctor_check_spec_drift() -> tuple[str, bool, str]`.

Views must never run verify, take `fleet.lock`, or parse the spec file — they read the stamp only, and tolerate a partial/missing stamp without raising.

- [ ] **Step 1: Write the failing test**

```python
def test_read_stamp_tolerates_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert fleet.read_verify_stamp("nope") is None


def test_read_stamp_tolerates_torn_write(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    p = fleet.verify_stamp_path("md-demo")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"ts": "partial', encoding="utf-8")
    assert fleet.read_verify_stamp("md-demo") is None   # must not raise


def test_doctor_spec_check_is_note_only(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_SDD", "1")
    name, ok, _ = fleet._doctor_check_spec_drift()
    assert ok is True     # note-only: it informs, it never turns doctor red
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.13 -m pytest tests/test_spec.py -k "stamp or doctor" -v`
Expected: FAIL — `AttributeError: ... 'read_verify_stamp'`

- [ ] **Step 3: Write minimal implementation**

```python
def read_verify_stamp(campaign: str):
    """View-legal: no lock, no subprocess, no spec parse. Tolerate-and-ignore."""
    try:
        return json.loads(verify_stamp_path(campaign).read_text(encoding="utf-8"))
    except Exception:
        return None


def _doctor_check_spec_drift():
    name = "spec_drift"
    if not sdd_enabled():
        return (name, True, "sdd disabled")
    notes = []
    try:
        reg = load_registry()
    except Exception:
        return (name, True, "registry unavailable")
    for wname, rec in sorted((reg.get("workers") or {}).items()):
        campaign = rec.get("spec")
        if not campaign:
            continue
        stamp = read_verify_stamp(campaign)
        if stamp is None:
            notes.append(f"{wname}: bound to {campaign}, never verified")
        elif stamp.get("overall") != "PASS":
            notes.append(f"{wname}: {campaign} last verify {stamp.get('overall')}")
        if stamp and stamp.get("spec_status") in ("proposed", "superseded"):
            notes.append(f"{wname}: bound to a {stamp.get('spec_status')} spec")
    return (name, True, "; ".join(notes) if notes else "no spec drift")
```

Register it in the doctor runner list beside the other `_doctor_check_*` entries, and add the `drift` flag to the status table sourced from `read_verify_stamp` only.

- [ ] **Step 4: Run the tests**

Run: `py -3.13 -m pytest tests/test_spec.py -k "stamp or doctor" -v`
Expected: 3 passed

- [ ] **Step 5: Confirm the view lint still passes**

Run: `py -3.13 -m pytest tests/test_terminal_surface.py -q`
Expected: PASS — no view path gained a lock, probe, or write

- [ ] **Step 6: Full suite + doctor smoke**

Run: `py -3.13 -m pytest -q` then `py -3.13 bin/fleet.py doctor`
Expected: tests green; doctor all-PASS with a `spec_drift: sdd disabled` note

- [ ] **Step 7: Commit**

```bash
git add bin/fleet.py tests/test_spec.py
git commit -m "feat(sdd): status drift flag + note-only doctor check, stamp-read only"
```

---

## Done criteria for Phase 1

- `py -3.13 -m pytest -q` green, including the pre-existing suite with the flag off.
- `py -3.13 bin/fleet.py doctor` all-PASS.
- With `FLEET_SDD=1`: `spec new` → edit → `spec accept` (as a different `FLEET_ACTOR`) → `spawn --spec` → `spec verify --worker <name>` produces a stamp and a correct exit code.
- With the flag off: dispatch argv is byte-identical to pre-SDD.

## Deferred to the Phase-2 plan (do NOT build here)

`--judge` auto-dispatch (R3); the live `stop_specfence.py` Stop-hook fence with its `has_fresh_outcome` amendment and fail-open surfacing; `spec supersede`; the SPEC.md fold (R4). Phase 2 is gated on Phase 1 proving out in one real flagged-on campaign.
