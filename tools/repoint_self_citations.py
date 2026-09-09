"""Deterministic, idempotent re-pointing of bin/fleet.py's SELF line-citations.

Takes the citation VALUES from the base commit (where they are known correct),
maps each through the base->working line map, and writes them into the working
file positionally. Re-running is a no-op because the source of truth is always
the base commit, never the working file's current numbers."""
import sys, io, re, difflib, subprocess, tokenize, pathlib

NUMBER_RE = re.compile(r":(\d+)")
NAMED_RE = re.compile(r"`(\w+):(\d+)(?:-(\d+))?`")
PLAIN_STRING_RE = re.compile(r"^[rRbBuU]*['\"]")
DOC_TAIL_RE = re.compile(r"(?:[\w./-]*\.md|[A-Z]{2,}|three-tier[\w.-]*)$")
TAIL_PUNCT = "`( ,[-"
LOOKBEHIND = 60

def prose_spans(raw):
    starts, pos = [], 0
    for line in raw.split("\n"):
        starts.append(pos); pos += len(line) + 1
    off = lambda rc: starts[rc[0]-1] + rc[1]
    spans = []
    for tok in tokenize.generate_tokens(io.StringIO(raw).readline):
        if tok.type == tokenize.COMMENT or (
                tok.type == tokenize.STRING and PLAIN_STRING_RE.match(tok.string)):
            spans.append((off(tok.start), off(tok.end)))
    return spans

def self_cites(raw):
    """[(kind, start, end, value)] in file order: kind 'num' or 'end'."""
    spans = prose_spans(raw)
    inp = lambda o: any(a <= o < b for a, b in spans)
    out = []
    for m in NUMBER_RE.finditer(raw):
        if not inp(m.start()): continue
        before = raw[:m.start()]
        if before and before[-1].isdigit(): continue
        window = re.sub(r"\s*\n\s*#?\s*", " ", before[-LOOKBEHIND:]).rstrip(TAIL_PUNCT)
        if DOC_TAIL_RE.search(window): continue
        out.append(("num", m.start()+1, m.end(), int(m.group(1))))
    for m in NAMED_RE.finditer(raw):
        if not inp(m.start()) or m.group(3) is None: continue
        out.append(("end", m.start(3), m.end(3), int(m.group(3))))
    out.sort(key=lambda t: t[1])
    return out

base = sys.argv[1]
old = subprocess.run(["git","show",f"{base}:bin/fleet.py"],
                     capture_output=True, text=True, check=True).stdout
p = pathlib.Path("bin/fleet.py"); raw = p.read_text(encoding="utf-8")
m = {}
for tag,i1,i2,j1,j2 in difflib.SequenceMatcher(
        None, old.splitlines(), raw.splitlines(), autojunk=False).get_opcodes():
    if tag == "equal":
        for k in range(i2-i1): m[i1+k+1] = j1+k+1

want = self_cites(old); have = self_cites(raw)
assert len(want) == len(have), (
    f"citation count moved: base {len(want)} vs working {len(have)} -- this "
    f"script maps POSITIONALLY and cannot be used once a citation is added or "
    f"removed")
edits = []
for (kw, _, _, vold), (kh, s, e, vnow) in zip(want, have):
    assert kw == kh, "citation kinds diverged"
    tgt = m.get(vold)
    assert tgt is not None, f"base line {vold} has no counterpart in the working file"
    if tgt != vnow:
        edits.append((s, e, str(tgt)))
for s, e, r in sorted(edits, key=lambda t: -t[0]):
    raw = raw[:s] + r + raw[e:]
p.write_text(raw, encoding="utf-8")
print(f"re-pointed {len(edits)} of {len(have)} self-citations against {base}")
