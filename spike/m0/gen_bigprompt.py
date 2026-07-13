"""Generate a >32k-char prompt whose successful delivery is provable:
the needle sits at the END, so truncation is detectable."""
from pathlib import Path

body = ("FILLER " * 6000) + "\nIf you can read this, reply with exactly: NEEDLE-9317"
assert len(body) > 40_000
Path(__file__).parent.joinpath("out", "bigprompt.txt").write_text(body, encoding="utf-8")
print(len(body))
