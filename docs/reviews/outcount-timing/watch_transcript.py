"""External high-resolution watcher for a session transcript.

Samples os.stat() on every *.jsonl under a projects dir every 2 ms and logs,
with time.time_ns() on the same clock base the probe hook uses, every observed
size change together with what the new bytes contain (record type, message id,
output_tokens). Gives the arrival time of each transcript record independent of
the hook.

usage: watch_transcript.py <projects-dir-glob> <out.jsonl> <seconds>
"""
import glob
import json
import os
import sys
import time
from pathlib import Path


def parse_tail(raw, from_line):
    """Records after index from_line, summarised."""
    out = []
    lines = raw.splitlines()
    for i in range(from_line, len(lines)):
        line = lines[i].strip()
        if not line:
            out.append({"i": i, "type": "<blank>"})
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            out.append({"i": i, "type": "<unparsed>", "len": len(line)})
            continue
        if not isinstance(rec, dict):
            out.append({"i": i, "type": "<nondict>"})
            continue
        item = {"i": i, "type": rec.get("type")}
        msg = rec.get("message")
        if isinstance(msg, dict):
            item["msg_id"] = msg.get("id")
            usage = msg.get("usage")
            if isinstance(usage, dict):
                item["out_tokens"] = usage.get("output_tokens")
            blocks = [c.get("type") for c in msg.get("content") or []
                      if isinstance(c, dict)]
            item["blocks"] = blocks
            texts = [c.get("text") for c in msg.get("content") or []
                     if isinstance(c, dict) and c.get("type") == "text"]
            if texts:
                item["text_head"] = ("\n".join(t for t in texts if t))[:60]
        out.append(item)
    return out, len(lines)


def main():
    pattern, out_path, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
    fh = open(out_path, "a", encoding="utf-8")
    state = {}  # path -> (size, n_lines)
    end = time.monotonic() + secs
    fh.write(json.dumps({"t_ns": time.time_ns(), "ev": "watch_start",
                         "pattern": pattern}) + "\n")
    fh.flush()
    while time.monotonic() < end:
        for p in glob.glob(pattern):
            try:
                st = os.stat(p)
            except OSError:
                continue
            prev = state.get(p)
            if prev is not None and prev[0] == st.st_size:
                continue
            t_ns = time.time_ns()
            try:
                raw = Path(p).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                fh.write(json.dumps({"t_ns": t_ns, "ev": "read_err",
                                     "path": p, "err": repr(exc)}) + "\n")
                fh.flush()
                continue
            from_line = prev[1] if prev else 0
            new, n_lines = parse_tail(raw, from_line)
            state[p] = (st.st_size, n_lines)
            fh.write(json.dumps({"t_ns": t_ns, "ev": "grow", "path": p,
                                 "size": st.st_size,
                                 "mtime_ns": st.st_mtime_ns,
                                 "new": new}, ensure_ascii=False) + "\n")
            fh.flush()
        time.sleep(0.002)
    fh.write(json.dumps({"t_ns": time.time_ns(), "ev": "watch_end"}) + "\n")
    fh.close()


if __name__ == "__main__":
    main()
