"""The boot bundle's SECOND durable plaintext nonce copy (measured 2026-09-09).

THE DEFECT. `_render_sup_spawn_task` redirects `sup-boot` to a bundle FILE so the
minted nonce is never read off a stream tail (class-4 doctrine), and step 3 orders
`rm <bundle>` so the file does not persist (claim-nonce 5.8/5.9). That is a complete
defence against the STREAM and an incomplete defence against the READER: step 3 said
only "Read the REST of the bundle file now" and did not say HOW. The bundle measured on
the supervisor host that morning was ~35KB, and a harness that persists large tool
output writes it to durable storage of its own -- so one `cat` re-created, outside the
fleet's reach, exactly the artifact the redirect exists to avoid. The ritual's `rm` then
deleted ONE of TWO plaintext copies.

  The generalisation, which is the part worth keeping: A REDIRECT PROTECTS THE STREAM,
  NOT THE READER. Any tool that persists large output re-creates the artifact the
  redirect exists to avoid. Same shape as the wave-38 `| tail -8` lesson -- the
  TRANSPORT, not the command, is where the evidence goes wrong.

THE SECOND HALF, confirmed by reading the code rather than taken on faith:
`_render_successor_task` rendered step 1's `sup-boot --handoff-inc ... --handoff-token ...`
with NO REDIRECT AT ALL and then told the successor to "read your boot bundle output",
i.e. off the stream tail -- the very act the gen-0 renderer's docstring calls the
doctrine violation it was fixed for. Two dispatch paths, one ratified doctrine, and only
one of them had ever been repaired. So every property here is held over BOTH renders,
parametrized: a fix applied to one path and not its sibling is this repo's named
recurring defect.

WHY THE PIN IS A WHITELIST AND NOT A `cat` BAN. The defect is "read it all at once",
which is a property of the READ, not of a spelling. A pin forbidding the word `cat`
passes over `head -n 99999`, over a file-reading tool named in prose, and over
`python -c "print(open(...).read())"`. So every rendered line that names the bundle path
must match one of four sanctioned forms (redirect / anchored grep / bounded slice / rm);
anything else -- including a form nobody has written yet -- is an unbounded read.
`TestTheDetectorCanSeeAWholeFileRead` exercises that discriminating power on synthetic
bodies with known answers, because an empty-offender list is green for the same reason a
correct render is green.
"""
import json
import re
from types import SimpleNamespace

import pytest

import fleet


SUP_PIPE = "sup|inc-1|boot"
SUCC_INC = "inc-20260909T101112Z-abcd"

# A slice wide enough to be one sensible read, narrow enough that it cannot be a
# whole-file read wearing a range. NOT a measured spill threshold -- the 35.1KB
# observation behind this work is one data point, not a boundary, and the code
# deliberately states the SHAPE rather than a number. This ceiling exists so that
# `sed -n '1,999999p'` cannot pass as a slice.
MAX_SLICE_LINES = 200

_SLICE_RE = re.compile(r"^sed -n '(\d+),(\d+)p' \"(?P<b>.+)\"$")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# The two renders, and the bundle path each one is responsible for.
# ---------------------------------------------------------------------------
def render_gen0():
    return SUP_PIPE, fleet._render_sup_spawn_task(SUP_PIPE, "inc-1", "campaign brief")


def render_successor():
    name = fleet._successor_worker_name(SUCC_INC)
    return name, fleet._render_successor_task(SUCC_INC, "inc-old", "tok-x")


RENDERS = {"gen0": render_gen0, "successor": render_successor}


def _body_and_bundle(kind):
    name, body = RENDERS[kind]()
    return body, fleet.boot_bundle_path(name).as_posix()


def bundle_naming_lines(body, bundle):
    """Every rendered line that names the bundle path."""
    return [ln.strip() for ln in body.splitlines() if bundle in ln]


def classify_bundle_line(line, bundle):
    """One of the four sanctioned forms, or None -- and None means the render
    orders something to happen to the whole bundle that nobody has justified.

    The classifier is deliberately positive. It does not enumerate the bad
    forms (there is no end to them); it enumerates the four the doctrine
    sanctions and calls everything else an unbounded read."""
    q = f'"{bundle}"'
    if "sup-boot" in line and f"> {q} 2>&1" in line:
        return "redirect"
    if line == f'grep -E "^(VERDICT|INCARNATION|NONCE):" {q}':
        return "grep"
    m = _SLICE_RE.match(line)
    if m is not None and m.group("b") == bundle:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < lo <= hi and (hi - lo + 1) <= MAX_SLICE_LINES:
            return "slice"
        return None
    if line == f"rm {q}":
        return "rm"
    return None


def unbounded_reads(body, bundle):
    return [ln for ln in bundle_naming_lines(body, bundle)
            if classify_bundle_line(ln, bundle) is None]


def slices_ordered(body, bundle):
    return [ln for ln in bundle_naming_lines(body, bundle)
            if classify_bundle_line(ln, bundle) == "slice"]


# ---------------------------------------------------------------------------
# The property, over BOTH dispatch paths.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["gen0", "successor"])
class TestTheBundleReadIsChunked:
    def test_a_bounded_slice_of_the_bundle_is_ordered(self, kind, native_home):
        """POSITIVE, and that is the point: the ritual must NAME the chunked
        form. A render that merely stopped saying `cat` would still leave an
        agent to invent its own whole-file read."""
        body, bundle = _body_and_bundle(kind)
        got = slices_ordered(body, bundle)
        assert got, (
            f"{kind}: no bounded `sed -n '<a>,<b>p' \"{bundle}\"` slice is ordered; "
            f"lines naming the bundle were {bundle_naming_lines(body, bundle)}")

    def test_no_line_naming_the_bundle_orders_an_unbounded_read(self, kind, native_home):
        """HONESTY ABOUT WHAT CAUGHT WHAT: run against the UNPATCHED tree this
        was GREEN for `gen0`, because the defective instruction ("Read the REST
        of the bundle file now") was PROSE and named no path -- there was no
        line for the whitelist to reject. The test that went red on today's code
        is the positive one above. This one is the guard going FORWARD, against
        the editor who answers "how?" with `cat "<bundle>"`; it is not evidence
        of the original defect and must not be cited as such."""
        body, bundle = _body_and_bundle(kind)
        offenders = unbounded_reads(body, bundle)
        assert not offenders, (
            f"{kind}: rendered line(s) do something unsanctioned to the whole bundle: "
            f"{offenders}. A redirect protects the stream, not the reader.")

    def test_the_render_states_why_the_read_is_sliced(self, kind, native_home):
        """The WHY travels with the instruction or the next editor deletes it as
        noise. One clause naming the mechanism: a tool that persists large output
        makes a second durable copy."""
        body, _ = _body_and_bundle(kind)
        low = body.lower()
        assert "second durable" in low, f"{kind}: the reason is not stated"
        assert "in slices" in low or "in chunks" in low


@pytest.mark.parametrize("kind", ["gen0", "successor"])
class TestBothDispatchPathsRedirectTheBoot:
    """Follows the form of the existing gen-0 pin
    (`tests/test_supspawn_fixwave2.py::TestRenderedCommandQuoting::
    test_bundle_quoted_in_redirect_grep_and_rm`) rather than inventing a second
    one -- but parametrized, so the successor path can no longer diverge from
    the gen-0 path on a doctrine both are subject to."""

    def test_sup_boot_output_is_redirected_to_the_bundle_file(self, kind, native_home):
        body, bundle = _body_and_bundle(kind)
        assert f'> "{bundle}" 2>&1' in body
        assert f"> {bundle} " not in body          # unquoted form absent

    def test_the_nonce_is_grepped_from_the_file_not_read_off_the_stream(self, kind,
                                                                        native_home):
        body, bundle = _body_and_bundle(kind)
        assert f'grep -E "^(VERDICT|INCARNATION|NONCE):" "{bundle}"' in body

    def test_the_bundle_is_deleted(self, kind, native_home):
        body, bundle = _body_and_bundle(kind)
        assert f'rm "{bundle}"' in body


# ---------------------------------------------------------------------------
# The seeds. Every discriminating power claimed above, on a known answer.
# ---------------------------------------------------------------------------
BUNDLE = "/home/x/fleet/state/tasks/sup~inc-1~boot.boot-bundle.txt"


class TestTheDetectorCanSeeAWholeFileRead:
    def test_it_accepts_the_four_sanctioned_forms(self):
        body = (f'   "/py" "/f.py" --fleet-home "/h" sup-boot > "{BUNDLE}" 2>&1\n'
                f'   grep -E "^(VERDICT|INCARNATION|NONCE):" "{BUNDLE}"\n'
                f"   sed -n '1,120p' \"{BUNDLE}\"\n"
                f'   rm "{BUNDLE}"\n')
        assert unbounded_reads(body, BUNDLE) == []
        assert len(slices_ordered(body, BUNDLE)) == 1

    def test_it_sees_a_cat(self):
        assert unbounded_reads(f'   cat "{BUNDLE}"\n', BUNDLE)

    def test_it_sees_a_huge_head(self):
        """The mutant that defeats a `cat` ban."""
        assert unbounded_reads(f'   head -n 99999 "{BUNDLE}"\n', BUNDLE)

    def test_it_sees_a_file_reading_tool_named_in_prose(self):
        """The mutant that defeats every shell-shaped ban: no shell at all."""
        assert unbounded_reads(f'   Read the file {BUNDLE} with the Read tool.\n', BUNDLE)

    def test_it_sees_a_one_line_python_script(self):
        assert unbounded_reads(
            f'   python -c "print(open(\'{BUNDLE}\').read())"\n', BUNDLE)

    def test_an_unbounded_range_is_not_a_slice(self):
        """`sed` with the range opened out is a whole-file read wearing a slice's
        clothes, and so is a slice wider than any one read should be."""
        assert unbounded_reads(f"   sed -n '1,$p' \"{BUNDLE}\"\n", BUNDLE)
        assert unbounded_reads(f"   sed -n '1,999999p' \"{BUNDLE}\"\n", BUNDLE)
        assert slices_ordered(f"   sed -n '1,999999p' \"{BUNDLE}\"\n", BUNDLE) == []


class TestTheSuccessorsRedirectTargetHasADirectory:
    """The successor dispatch is the ONE `--bg` launch that does not go through
    `dispatch_bg` (see `cmd_sup_handoff_begin`'s docstring), and `dispatch_bg`
    is the only other place `tasks_dir()` is created. A redirect into a missing
    directory fails the successor's FIRST ACT and strands the whole handoff, so
    the directory is made at begin rather than assumed.

    DRIVEN, not restated: the verb is run for real against a home that has never
    dispatched a worker, which is precisely the state in which the assumption is
    false. A test that called `mkdir` itself and then asserted the directory
    exists would be green over the hole."""

    def _sup_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        sup = tmp_path / "supervisor"
        sup.mkdir()
        (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                      encoding="utf-8")
        (tmp_path / "knowledge").mkdir()
        (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- e\n",
                                                         encoding="utf-8")
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                                 encoding="utf-8")
        return tmp_path

    def _dispatch_then_roster(self, successor_sid="succ0001-full", short_id="succ0001"):
        state = {"dispatched": False}
        def run(argv, **kw):
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0,
                                       stdout=f"backgrounded \u00b7 {short_id} \u00b7 sup\n",
                                       stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["dispatched"]:
                entries.append({"sessionId": successor_sid, "status": "busy"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        return run

    def test_begin_creates_the_parent_of_the_successors_bundle(self, tmp_path,
                                                               monkeypatch, capsys):
        home = self._sup_home(tmp_path, monkeypatch)
        assert not fleet.tasks_dir().exists(), \
            "the fixture must start WITHOUT state/tasks or this proves nothing"
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-20260724T000000Z-0old",
                                 "session_id": "sid-old", "claimed_at": beat,
                                 "heartbeat_at": beat, "claimed_via": "fresh"})
        rc = fleet.cmd_sup_handoff_begin(
            SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None),
            which=lambda _n: "C:/fake/claude.cmd",
            run=self._dispatch_then_roster(), sleep=lambda _s: None)
        capsys.readouterr()
        assert rc == 0
        entries = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert entries, "begin recorded no pending successor"
        succ = fleet._successor_worker_name(entries[-1]["successor_inc"])
        bundle = fleet.boot_bundle_path(succ)
        assert bundle.parent.is_dir(), (
            f"begin left no directory for the successor's redirect target "
            f"{bundle}; its FIRST ACT would fail and strand the handoff")
        # and the body it wrote really does redirect into that path
        body = fleet.handoff_task_file_path(
            entries[-1]["successor_inc"]).read_text(encoding="utf-8")
        assert f'> "{bundle.as_posix()}" 2>&1' in body
        assert str(home) in str(bundle)
