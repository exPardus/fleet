"""A lane's report cannot be left where only a disposable directory holds it.

THE DEFECT THIS FILE EXISTS FOR. `state/` is gitignored (`.gitignore:1`) and a
git worktree gets its **own** `state/`, so a lane told to write its report to
`state/journals/<name>.md` writes it into a directory that is in no commit and
that dies with the worktree. The path is *relative* in the briefs that caused
this, so which `state/` it lands in is decided by the lane's cwd rather than by
the instruction. Three reports were lost that way in the wave-44 -> 47 campaign:
the `w44-ceil` report carrying the prepared `supervisor/GOALS.md` replacement
text (an operator ruling is still blocked on it -- `docs/OPERATOR-GATES.md`,
gate opened 2026-08-08); slice a3's self-report, lost outright, so its
adversarial gate had to audit the branch from the code; and the a2 gate's
38,815-byte verdict, which survived only because a supervisor noticed and
hand-copied it to the main tree. Measured on this machine at the time of
writing: 55 briefs under `state/tasks/` order a *relative* `state/journals/`
report, 84 order the absolute form. Both are gitignored. The fix and its
reasoning: `docs/lanes/README.md`.

WHAT THIS PIN CAN AND CANNOT ASSERT -- read this before trusting the name.

  CANNOT: that a future lane obeyed the convention. No test can. A lane is a
  session, its report is a file it may or may not write, and by the time
  anything could check, the evidence being protected is the thing that is
  missing.

  CAN, and does: that the durable location is real and tracked; that the
  premise of the whole doctrine (`state/` is ignored) still holds; and that the
  surfaces which INSTRUCT lanes and brief-writers do not point a report at a
  disposable path. Instructions are what the defect actually travelled through
  -- the deliverables line is hand-authored fresh per lane -- so instructions
  are what is pinned.

DISPOSABILITY IS ASKED OF GIT, NOT HARDCODED. Every verdict below about whether
a path is disposable comes from `git check-ignore` against the repo's live
ignore rules. Nothing here carries a list of "bad paths". Add `reports/` to
`.gitignore` tomorrow and a surface pointing reports there goes RED without a
line of this file changing; that is the property, where a literal-string
allowlist would only ever have been a spelling.

NON-VACUITY, which this repo has measured the need for repeatedly. A pin gated
behind a magic substring pins the substring: delete the substring and it passes
green over a broken world. Four seeds stop that here:

  * `test_the_declaration_is_present_and_parses` -- the root is READ from
    `docs/lanes/README.md`, so deleting the declaration is RED, not a skip.
  * `test_every_surface_names_the_declared_report_root` -- a surface that
    simply drops the instruction is RED. This is the seed that catches a
    silent revert, because a reverted surface has no bad string left to find.
  * `test_the_detector_can_tell_a_disposable_path_from_a_durable_one` -- proves
    `check-ignore` discriminates at all, so the suite cannot go green because
    the detector is broken, absent, or answering "not ignored" to everything.
  * `test_state_is_gitignored_so_the_premise_of_this_file_holds` -- if `state/`
    stops being ignored, this file's whole argument needs re-deriving and the
    RED is the notification.

SCOPE OF `SURFACES`, stated because the omission is deliberate.
`docs/lanes/README.md` is NOT in it. README is the rationale document: it
quotes the disposable path repeatedly *in order to explain why it is wrong*,
and a rule that forbids naming the defect would force the explanation out of
the file that exists to give it. README is pinned instead by the declaration
tests below, which is the part of it that other code depends on.

BLOCK SCOPING, not line scoping. These surfaces are Markdown with hard-wrapped
bullets, so a single instruction spans several physical lines and a line-scoped
rule is evaded by wrapping -- accidentally, most likely, which is worse. Text
is folded into logical blocks (a bullet and its continuations; a paragraph; a
fenced stanza) and the rule applies per block.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The rationale document, which is also where the canonical root is DECLARED.
README = "docs/lanes/README.md"

#: Files that instruct a lane, or instruct whoever writes a lane's brief.
#: A file belongs here when a reader could take an action from it about where a
#: report goes. See the scope note in the module docstring for why README is not
#: a member.
#:
#: `bin/fleet.py` IS NOT A MEMBER, AND SHOULD BECOME ONE. Its
#: `_PREAMBLE_TEMPLATE` is the only instruction that reaches EVERY lane
#: unconditionally -- machine-rendered at spawn, no supervisor in the loop --
#: which makes it the highest-coverage instructing surface in the system. Today
#: it names only the JOURNAL target (`journals_dir()`, correctly absolute and
#: correctly disposable) and says nothing about a report, so there is no report
#: destination in it for this pin to grade. It was also fenced to another lane
#: when this file was written (w47, `w47-a3fix` held it). When someone adds a
#: report line to that template, add `"bin/fleet.py"` here in the same commit:
#: the surface that reaches every lane is the one most worth pinning.
SURFACES = (
    "skills/fleet/SKILL.md",
    "skills/fleet/supervisor.md",
    "docs/lanes/BRIEF-TEMPLATE.md",
)

#: The declaration `docs/lanes/README.md` carries, and the only place the
#: canonical path is written down for a machine.
_DECLARATION = re.compile(r"<!--\s*lane-report-root:\s*(\S+?)\s*-->")

#: A backticked token is the only thing considered a candidate path. Prose that
#: names a path without backticks is out of scope by construction -- these
#: surfaces backtick every path they mean.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A path token counts as a REPORT DESTINATION only when a report word appears
#: in the text shortly before it. `verdict` is here because a gate's verdict is
#: a report under another name and was one of the three losses.
#:
#: Proximity, not mere co-occurrence in the block, and the difference is
#: measured rather than theoretical. Scoped to the whole block this fired on
#: three innocent passages on its first run: the `fleet archive` and `fleet
#: doctor` rows of SKILL.md's command table, and supervisor.md's boot-bundle
#: paragraph. All three name a gitignored runtime path -- correctly, it is
#: where those commands really write -- and all three use "report" elsewhere in
#: the row as a VERB about what a command prints. A rule that cannot tell "the
#: verb reports" from "your report goes here" would have had to be relaxed or
#: allowlisted, and an allowlist is how a pin stops being evidence.
_REPORT_WORD = re.compile(r"\b(report|reports|deliverable|deliverables|verdict|verdicts)\b",
                          re.IGNORECASE)

#: How far back from a path token a report word still governs it. One clause,
#: roughly -- long enough for "your report **committed on that branch** at
#: `docs/lanes/<name>.md`", short enough not to reach the previous sentence.
_PROXIMITY = 120

#: Prefixes that disguise a fleet-home-relative path. `$FLEET_HOME/state/...`
#: and `state/...` name the same disposable directory, and a pin that could not
#: see through the prefix would grade the absolute spelling as durable -- which
#: is exactly the half-fix this lane rejected (README, "Why not just always use
#: the absolute path").
_HOME_PREFIXES = (
    "$(fleet home)/",
    "$FLEET_HOME/",
    "${FLEET_HOME}/",
    "<fleet home>/",
    "$(fleet home)\\",
    "$FLEET_HOME\\",
)


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _normalise(token: str) -> str:
    """Strip a fleet-home prefix and normalise separators.

    Returns "" for a token that is not a candidate repo-relative path."""
    t = token.strip()
    for prefix in _HOME_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    t = t.replace("\\", "/")
    if "/" not in t:
        return ""
    if any(c.isspace() for c in t):
        return ""
    if t.startswith(("http://", "https://", "-", "/")):
        return ""
    if re.match(r"^[A-Za-z]:", t):          # an absolute Windows path
        return ""
    return t.lstrip("./")


def _ignored(paths):
    """The subset of `paths` git considers ignored. One subprocess, not N.

    NUL-delimited in BOTH directions, and both halves are load-bearing:

      * `-z` makes git read NUL-separated input, so a newline-separated feed
        arrives as ONE giant path and every answer is wrong-but-plausible.
      * Bytes, never `text=True`. Text mode translates `\\n` to `os.linesep` on
        the way into the pipe, so on Windows git received `path\\r` and reported
        back the c-quoted `"state/journals/x.md\\r"` -- a path that matched
        nothing the caller had asked about. Measured on the first run of this
        file: every membership test failed while the repo was entirely correct.
      * `-z` also suppresses c-quoting on output, so a path containing `<`, `>`
        or a quote comes back exactly as it went in."""
    paths = [p for p in dict.fromkeys(paths) if p]
    if not paths:
        return set()
    payload = b"\0".join(p.encode("utf-8") for p in paths) + b"\0"
    out = subprocess.run(["git", "check-ignore", "--stdin", "-z"],
                         cwd=REPO, input=payload, capture_output=True)
    if out.returncode not in (0, 1):
        raise AssertionError("git check-ignore failed "
                             f"(rc={out.returncode}): {out.stderr.decode('utf-8', 'replace').strip()}")
    return {chunk.decode("utf-8", "replace")
            for chunk in out.stdout.split(b"\0") if chunk}


def _blocks(text: str):
    """Fold Markdown into logical blocks: a bullet plus its continuations, a
    paragraph, a fenced stanza. See the module docstring on block scoping."""
    blocks, current, in_fence = [], [], False
    for line in text.splitlines():
        fence = line.lstrip().startswith("```")
        if fence:
            in_fence = not in_fence
            current.append(line)
            continue
        if in_fence:
            current.append(line)
            continue
        starts_item = re.match(r"^\s{0,3}([-*+]|\d+\.|\|)\s", line) is not None
        if not line.strip() or starts_item:
            if current:
                blocks.append("\n".join(current))
            current = [line] if line.strip() else []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b for b in blocks if b.strip()]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _declared_root() -> str:
    m = _DECLARATION.search(_read(README))
    assert m, (
        f"{README} no longer carries its `<!-- lane-report-root: ... -->` "
        f"declaration. That declaration is what every assertion in "
        f"tests/test_lane_report_durability.py reads the canonical path from; "
        f"without it this pin would have nothing to check and would pass "
        f"vacuously. Restore it, or re-point it deliberately.")
    return m.group(1).replace("\\", "/").rstrip("/")


@pytest.mark.unit
class TestTheDetectorWorks:
    """Seeds. Without these the whole file could go green over a broken world."""

    def test_the_detector_can_tell_a_disposable_path_from_a_durable_one(self):
        # Both answers, from one call, so a check-ignore that has stopped
        # discriminating -- broken, absent, or answering one way to everything
        # -- cannot be mistaken for a clean repo.
        ignored = _ignored(["state/journals/probe.md", "docs/SPEC.md"])
        assert "state/journals/probe.md" in ignored, (
            "git check-ignore does not report a path under state/ as ignored. "
            "Either .gitignore changed (see the premise test) or the detector "
            "this file depends on is not working -- do not relax this.")
        assert "docs/SPEC.md" not in ignored, (
            "git check-ignore reports a tracked spec file as ignored, so it is "
            "answering 'ignored' indiscriminately and every durability verdict "
            "below is worthless.")

    def test_state_is_gitignored_so_the_premise_of_this_file_holds(self):
        # `# live:` in the receipts sense -- a deliberate claim about the
        # working repo, not about a commit. If state/ ever stops being ignored,
        # the argument in docs/lanes/README.md needs re-deriving from scratch
        # and this RED is how anyone finds out.
        ignored = _ignored(["state/journals/x.md", "state/verdicts/x.md", "state/tasks/x.md"])
        assert ignored == {"state/journals/x.md", "state/verdicts/x.md", "state/tasks/x.md"}, (
            "state/ is no longer fully gitignored. docs/lanes/README.md argues "
            "from the premise that it is; re-derive that argument before "
            "changing this assertion.")

    def test_the_declaration_is_present_and_parses(self):
        root = _declared_root()
        assert root, f"{README} declares an empty lane-report-root"
        assert "/" in root, (
            f"{README} declares {root!r} as the lane-report-root; a bare "
            f"top-level name is almost certainly a mistake")


@pytest.mark.unit
class TestTheDurableLocationIsReal:

    def test_the_declared_root_is_not_disposable(self):
        root = _declared_root()
        assert not _ignored([f"{root}/probe.md"]), (
            f"the declared lane-report root {root!r} is GITIGNORED, so a report "
            f"committed there would not be committed at all. This is the exact "
            f"defect the directory exists to prevent, one level up.")

    def test_the_declared_root_is_tracked_by_git(self):
        root = _declared_root()
        out = _git("ls-files", "--", root)
        assert out.returncode == 0, out.stderr
        tracked = [line for line in out.stdout.splitlines() if line.strip()]
        assert tracked, (
            f"nothing under {root!r} is tracked by git. An untracked directory "
            f"is exactly as durable as state/ was -- existing on disk is not "
            f"the property, being in a commit is.")

    def test_the_rationale_document_is_itself_tracked(self):
        # The one document that explains why reports live where they do must
        # not be the one document that dies with the worktree.
        out = _git("ls-files", "--", README)
        assert out.stdout.strip(), f"{README} is not tracked by git"


@pytest.mark.unit
class TestTheInstructingSurfaces:

    @pytest.mark.parametrize("rel", SURFACES)
    def test_the_surface_exists(self, rel):
        assert (REPO / rel).is_file(), (
            f"{rel} is listed in SURFACES but does not exist. Membership is "
            f"declared, so a surface that is renamed or deleted must be "
            f"re-declared here rather than silently dropping out of coverage.")

    @pytest.mark.parametrize("rel", SURFACES)
    def test_every_surface_names_the_declared_report_root(self, rel):
        """The non-vacuity seed for this class.

        A surface that is quietly reverted to the old convention has no
        offending string left for a scan to find -- the deliverables line just
        goes back to naming a state/ path, or stops naming a path at all. What
        catches that is requiring the durable root to be PRESENT, which a
        revert removes."""
        root = _declared_root()
        assert root in _read(rel), (
            f"{rel} never names the declared lane-report root {root!r}. Either "
            f"the instruction was removed or it was re-pointed somewhere else; "
            f"both are the regression this pin exists for.")

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_surface_points_a_report_at_a_disposable_path(self, rel):
        """The rule itself.

        A backticked path preceded within `_PROXIMITY` characters by a report
        word is a REPORT DESTINATION. If any such destination is gitignored,
        the surrounding block must also name the durable root -- which permits
        the deliberate contrast a teaching surface needs ("the journal is
        disposable, the report is not") and forbids the shape that lost three
        reports: a deliverables line whose only named destination is inside
        `state/`.

        The proximity window is what separates a destination from the word
        "reports" used as a verb in a command table; see `_REPORT_WORD` for the
        three passages that proved the distinction is needed."""
        root = _declared_root()
        offenders = []
        for block in _blocks(_read(rel)):
            candidates = [_normalise(m.group(1)) for m in _BACKTICKED.finditer(block)
                          if _REPORT_WORD.search(
                              block[max(0, m.start() - _PROXIMITY):m.start()])]
            bad = sorted(_ignored(candidates))
            if bad and root not in block:
                offenders.append((bad, " ".join(block.split())[:200]))
        assert not offenders, (
            f"{rel} instructs about a report while naming a gitignored "
            f"destination, without naming the durable root {root!r} in the "
            f"same block:\n" + "\n".join(
                f"  ignored: {bad}\n  block:   {snippet}" for bad, snippet in offenders))
