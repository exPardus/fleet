"""SDD acceptance gate: campaign spec parsing, digest, scope and criteria."""
from __future__ import annotations

import collections
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


CAMPAIGN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
JSON_FENCE_RE = re.compile(r"```json[ \t]*\n(.*?)\n```", re.DOTALL)
REQUIRED_KEYS = ("spec", "status", "author", "criteria")
STATUSES = ("proposed", "accepted", "superseded")
EXIT_FOR = {"PASS": 0, "FAIL": 1, "INFRA": 2}

CriterionResult = collections.namedtuple("CriterionResult", "id status detail")


class SpecFormatError(Exception):
    pass


class TouchedPathsError(Exception):
    pass


def check_campaign_name(campaign: str) -> str:
    if not isinstance(campaign, str) or not CAMPAIGN_RE.match(campaign):
        raise SpecFormatError(
            f"invalid campaign name {campaign!r} (must match {CAMPAIGN_RE.pattern})")
    return campaign


def _str_list(value, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise SpecFormatError(f"{label} must be a list of non-empty strings")
    return value


def _safe_relative(value: str, label: str) -> None:
    # Inside the bound cwd; a leading "-" would reach pytest as an option (-p imports code).
    path = value.split("::", 1)[0].replace("\\", "/")
    parts = PurePosixPath(path).parts
    if (value.startswith("-") or path.startswith("/") or re.match(r"^[A-Za-z]:", path)
            or ".." in parts):
        raise SpecFormatError(f"{label} {value!r} must be a relative path inside the worker cwd")


def validate_spec(data) -> dict:
    if not isinstance(data, dict):
        raise SpecFormatError("machine block must be a JSON object")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise SpecFormatError(f"machine block missing required key(s): {', '.join(missing)}")
    if data.get("status") not in STATUSES:
        raise SpecFormatError(f"status {data.get('status')!r} is not one of {', '.join(STATUSES)}")
    for key in ("scope_allow", "scope_deny"):
        for pat in _str_list(data.get(key), key):
            _safe_relative(pat, key)
    slices = data.get("slices") or {}
    if not isinstance(slices, dict):
        raise SpecFormatError("'slices' must be an object")
    for name, sl in slices.items():
        if not isinstance(sl, dict):
            raise SpecFormatError(f"slice {name!r} must be an object")
        for key in ("scope_allow", "scope_deny"):
            for pat in _str_list(sl.get(key), f"slice {name!r} {key}"):
                _safe_relative(pat, f"slice {name!r} {key}")
        _str_list(sl.get("criteria"), f"slice {name!r} criteria")
    criteria = data.get("criteria")
    if not isinstance(criteria, list):
        raise SpecFormatError("'criteria' must be a list")
    seen = set()
    for crit in criteria:
        if not isinstance(crit, dict) or not isinstance(crit.get("id"), str) or not crit["id"]:
            raise SpecFormatError("every criterion needs a non-empty string 'id'")
        if crit["id"] in seen:
            raise SpecFormatError(f"duplicate criterion id {crit['id']!r}")
        seen.add(crit["id"])
        for key in ("nodes", "scope_allow", "scope_deny"):
            for value in _str_list(crit.get(key), f"criterion {crit['id']!r} {key}"):
                _safe_relative(value, f"criterion {crit['id']!r} {key}")
    for name, sl in slices.items():
        unknown = sorted(set(sl.get("criteria") or []) - seen)
        if unknown:
            raise SpecFormatError(f"slice {name!r} names unknown criteria: {', '.join(unknown)}")
    return data


def parse_spec(text: str) -> dict:
    m = JSON_FENCE_RE.search(text)
    if not m:
        raise SpecFormatError("no fenced ```json machine block found")
    try:
        data = json.loads(m.group(1))
    except ValueError as exc:
        raise SpecFormatError(f"machine block is not valid JSON: {exc}") from exc
    return validate_spec(data)


def spec_body(text: str) -> str:
    m = JSON_FENCE_RE.search(text)
    return text[m.end():].lstrip("\n") if m else ""


def render_spec(campaign: str, data: dict, body: str) -> str:
    block = json.dumps(data, indent=2)
    return f"# Campaign {campaign}\n\n```json\n{block}\n```\n\n{body}"


def executable_fields(data: dict) -> dict:
    crit = [{"id": c.get("id"), "kind": c.get("kind"),
             "nodes": sorted(c.get("nodes") or []),
             "scope_allow": sorted(c.get("scope_allow") or []),
             "scope_deny": sorted(c.get("scope_deny") or [])}
            for c in data.get("criteria") or []]
    crit.sort(key=lambda c: str(c["id"]))
    slices = {name: {"scope_allow": sorted(sl.get("scope_allow") or []),
                     "scope_deny": sorted(sl.get("scope_deny") or []),
                     "criteria": sorted(sl.get("criteria") or [])}
              for name, sl in sorted((data.get("slices") or {}).items())}
    return {"scope_allow": sorted(data.get("scope_allow") or []),
            "scope_deny": sorted(data.get("scope_deny") or []),
            "slices": slices, "criteria": crit}


def spec_digest(data: dict) -> str:
    canon = json.dumps(executable_fields(data), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _glob_prefix(pattern: str):
    if pattern == "**":
        return ""
    if pattern.endswith("/**"):
        head = pattern[:-3]
        if not any(ch in head for ch in "*?["):
            return head
    return None


def glob_contains(outer: str, inner: str) -> bool:
    # Pattern domain, never a filesystem match; unknown shapes answer False.
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


def _literal_head(pattern: str) -> str:
    head = []
    for part in pattern.split("/"):
        if any(ch in part for ch in "*?["):
            break
        head.append(part)
    return "/".join(head)


def globs_may_intersect(a: str, b: str) -> bool:
    if glob_contains(a, b) or glob_contains(b, a):
        return True
    ha, hb = _literal_head(a), _literal_head(b)
    if not ha or not hb:
        return True
    return ha == hb or ha.startswith(hb + "/") or hb.startswith(ha + "/")


def effective_scope(data: dict, slice_name):
    allow = list(data.get("scope_allow") or [])
    deny = list(data.get("scope_deny") or [])
    sl = (data.get("slices") or {}).get(slice_name) if slice_name else None
    if sl:
        allow = list(sl.get("scope_allow") or allow)
        deny = deny + [p for p in sl.get("scope_deny") or [] if p not in deny]
    return allow, deny


def check_slice_scopes(data: dict) -> list:
    problems = []
    whole = list(data.get("scope_allow") or [])
    slices = data.get("slices") or {}
    for name, sl in sorted(slices.items()):
        for pat in sl.get("scope_allow") or []:
            if whole and not any(glob_contains(w, pat) for w in whole):
                problems.append(f"slice '{name}' pattern '{pat}' would widen beyond the whole-spec scope")
    names = sorted(slices)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for pa in slices[a].get("scope_allow") or []:
                for pb in slices[b].get("scope_allow") or []:
                    if globs_may_intersect(pa, pb):
                        problems.append(f"slices '{a}' and '{b}' overlap on '{pa}' / '{pb}'")
    return problems


def criteria_for(data: dict, slice_name) -> list:
    crits = list(data.get("criteria") or [])
    if not slice_name:
        return crits
    wanted = set(((data.get("slices") or {}).get(slice_name) or {}).get("criteria") or [])
    return [c for c in crits if c.get("id") in wanted]


def _git_paths(cwd: Path, query: list, run) -> set:
    argv = ["git", "-C", str(cwd), *query]
    try:
        r = run(argv, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise TouchedPathsError(f"git {' '.join(query)}: {exc}") from exc
    if getattr(r, "returncode", 1) != 0:
        detail = (getattr(r, "stderr", "") or "").strip().splitlines()
        raise TouchedPathsError(f"git {' '.join(query)} failed: {detail[-1] if detail else 'rc != 0'}")
    return {p.replace("\\", "/") for p in (getattr(r, "stdout", "") or "").split("\0") if p.strip()}


def touched_paths(cwd: Path, base, run=None):
    # The ignored query is mandatory (--exclude-standard hides gitignored deny targets);
    # ignored paths are fenced by deny only: git cannot attribute them to a turn.
    run = run or subprocess.run
    try:
        r = run(["git", "-C", str(cwd), "rev-parse", "--show-prefix"],
                capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise TouchedPathsError(f"git rev-parse: {exc}") from exc
    if getattr(r, "returncode", 1) != 0:
        raise TouchedPathsError(f"{cwd} is not a git work tree")
    if (getattr(r, "stdout", "") or "").strip():
        raise TouchedPathsError(f"{cwd} must be the repository top level")
    base_args = [base, "--"] if base else ["--"]
    changed = set()
    changed |= _git_paths(cwd, ["diff", "--name-only", "--no-renames", "-z", *base_args], run)
    changed |= _git_paths(cwd, ["diff", "--cached", "--name-only", "--no-renames", "-z", *base_args], run)
    changed |= _git_paths(cwd, ["ls-files", "--others", "--exclude-standard", "-z"], run)
    ignored = _git_paths(cwd, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"], run)
    return changed, ignored - changed


def path_matches_any(path: str, patterns) -> bool:
    for p in patterns:
        if p == "**" or fnmatch.fnmatchcase(path, p):
            return True
        if p.endswith("/**") and (path == p[:-3] or path.startswith(p[:-3] + "/")):
            return True
    return False


def eval_files_criterion(cid, changed, allow, deny, ignored=()) -> CriterionResult:
    bad = []
    for path in sorted(changed):
        if deny and path_matches_any(path, deny):
            bad.append(f"{path} (denied)")
        elif allow and not path_matches_any(path, allow):
            bad.append(f"{path} (out of scope)")
    for path in sorted(ignored):
        if deny and path_matches_any(path, deny):
            bad.append(f"{path} (denied, ignored)")
    if bad:
        return CriterionResult(cid, "FAIL", "out-of-scope paths: " + ", ".join(bad[:20])
                               + (f" (+{len(bad) - 20} more)" if len(bad) > 20 else ""))
    return CriterionResult(cid, "PASS", f"{len(changed)} touched path(s) in scope")


def eval_pytest_criterion(cid, cwd, nodes, run=None) -> CriterionResult:
    # Ambiguity is FAIL (a missing or empty target is under-delivery); INFRA = no runner.
    run = run or subprocess.run
    if not nodes:
        return CriterionResult(cid, "FAIL", "no test nodes declared (under-delivery)")
    for node in nodes:
        try:
            r = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--", node],
                    cwd=str(cwd), capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return CriterionResult(cid, "FAIL", f"{node}: timed out")
        except Exception as exc:
            return CriterionResult(cid, "INFRA", f"runner unavailable: {exc}")
        rc = getattr(r, "returncode", 1)
        blob = re.sub(r"\x1b\[[0-9;]*m", "",
                      (getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or ""))
        if rc == 0 and re.search(r"\b[1-9][0-9]* passed", blob):
            continue
        if "No module named pytest" in blob:
            return CriterionResult(cid, "INFRA", f"{node}: pytest is not installed for {sys.executable}")
        if rc in (0, 5) or "collected 0 items" in blob or "no tests ran" in blob.lower():
            return CriterionResult(cid, "FAIL", f"{node}: no test passed (under-delivery)")
        return CriterionResult(cid, "FAIL", f"{node}: pytest rc={rc}")
    return CriterionResult(cid, "PASS", f"{len(nodes)} node(s) passed")


def eval_criterion(crit, cwd, changed, allow, deny, ignored=(), run=None) -> CriterionResult:
    cid = crit.get("id") or "<no-id>"
    kind = crit.get("kind")
    if kind == "files":
        own_allow = list(crit.get("scope_allow") or [])
        own_deny = deny + [p for p in crit.get("scope_deny") or [] if p not in deny]
        in_scope = [p for p in changed if not own_allow or path_matches_any(p, own_allow)]
        if own_allow and len(in_scope) != len(changed):
            outside = sorted(set(changed) - set(in_scope))
            return CriterionResult(cid, "FAIL", "out-of-scope paths: " + ", ".join(
                f"{p} (outside criterion scope)" for p in outside[:20]))
        return eval_files_criterion(cid, changed, allow, own_deny, ignored)
    if kind == "pytest":
        return eval_pytest_criterion(cid, cwd, crit.get("nodes") or [], run=run)
    return CriterionResult(cid, "FAIL", f"unknown kind {kind!r} (fail-closed)")


def overall_status(results) -> str:
    if any(r.status == "FAIL" for r in results):
        return "FAIL"
    if any(r.status == "INFRA" for r in results):
        return "INFRA"
    return "PASS"


def run_criteria(data, slice_name, cwd, base, run=None, git_run=None):
    allow, deny = effective_scope(data, slice_name)
    results = []
    try:
        changed, ignored = touched_paths(cwd, base, run=git_run)
    except TouchedPathsError as exc:
        changed = ignored = None
        results.append(CriterionResult("_scope", "INFRA", str(exc)))
    else:
        results.append(eval_files_criterion("_scope", changed, allow, deny, ignored))
    for crit in criteria_for(data, slice_name):
        if crit.get("kind") == "files" and changed is None:
            results.append(CriterionResult(crit.get("id"), "INFRA", "touched paths unavailable"))
            continue
        results.append(eval_criterion(crit, cwd, changed or set(), allow, deny,
                                      ignored or set(), run=run))
    return results
