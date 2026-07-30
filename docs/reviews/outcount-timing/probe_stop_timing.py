"""INSTRUMENTATION ONLY -- experiment `outcount2`, not shipped code.

Extra Stop hook that answers: when does the transcript record carrying the
FINAL assistant message's usage land, relative to this hook's read?

It reproduces stop_outcome.py's read exactly (same grouping by message.id,
same payload-vs-transcript text comparison), then POLLS the transcript file
until the comparison passes or the budget runs out, logging every observed
change of the file with a wall-clock timestamp on the same time base
(time.time_ns()) the external watcher uses.

Writes one JSON object per invocation to $PROBE_LOG (JSONL).
Never blocks the turn beyond POLL_BUDGET_MS, always exits 0.
"""
import json
import os
import sys
import time
from pathlib import Path

POLL_BUDGET_MS = float(os.environ.get("PROBE_POLL_BUDGET_MS", "8000"))
POLL_INTERVAL_S = 0.002


def _read_payload():
    buf = getattr(sys.stdin, "buffer", None)
    raw = buf.read() if buf is not None else sys.stdin.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw or "{}")


def _last_assistant(raw_text):
    """stop_outcome._transcript_result's logic, reduced to what we compare:
    (text, output_tokens, message_id, n_assistant_records, n_lines)."""
    text = out = msg_id_last = None
    n_asst = 0
    last_id = _NO = object()
    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        n_asst += 1
        mid = msg.get("id")
        if last_id is _NO or mid is None or mid != last_id:
            last_id = mid
            text = None
        parts = [c.get("text") for c in msg.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if parts:
            text = "\n".join(parts)
        usage = msg.get("usage")
        if isinstance(usage, dict):
            out = usage.get("output_tokens")
        msg_id_last = mid
    return text, out, msg_id_last, n_asst, len(lines)


def main() -> int:
    t_entry = time.time_ns()
    log_path = Path(os.environ.get(
        "PROBE_LOG", str(Path(__file__).resolve().parent / "probe.jsonl")))
    rec = {"t_entry_ns": t_entry, "poll_budget_ms": POLL_BUDGET_MS}
    try:
        payload = _read_payload()
        tp = payload.get("transcript_path")
        want = payload.get("last_assistant_message")
        rec["session_id"] = payload.get("session_id")
        rec["transcript_path"] = tp
        rec["payload_has_last_msg"] = isinstance(want, str)
        rec["payload_last_msg_len"] = len(want) if isinstance(want, str) else None
        rec["t_payload_read_ns"] = time.time_ns()
        samples = []
        matched_at = None
        first_size = None
        prev_sig = None
        deadline = time.monotonic() + POLL_BUDGET_MS / 1000.0
        first_pass = True
        while True:
            now_ns = time.time_ns()
            try:
                st = os.stat(tp)
                sig = (st.st_size, st.st_mtime_ns)
            except OSError as exc:
                sig = ("ERR", repr(exc))
                st = None
            if sig != prev_sig:
                prev_sig = sig
                entry = {"t_ns": now_ns,
                         "dt_ms": (now_ns - t_entry) / 1e6,
                         "size": st.st_size if st else None,
                         "mtime_ns": st.st_mtime_ns if st else None}
                try:
                    raw = Path(tp).read_text(encoding="utf-8", errors="replace")
                    t_text, out, mid, n_asst, n_lines = _last_assistant(raw)
                    entry.update({"n_lines": n_lines, "n_assistant": n_asst,
                                  "last_msg_id": mid, "last_out_tokens": out,
                                  "match": isinstance(want, str)
                                           and isinstance(t_text, str)
                                           and want == t_text})
                except OSError as exc:
                    entry["read_err"] = repr(exc)
                samples.append(entry)
                if first_size is None:
                    first_size = entry.get("size")
                if entry.get("match") and matched_at is None:
                    matched_at = entry["dt_ms"]
                    rec["matched_dt_ms"] = matched_at
                    rec["matched_out_tokens"] = entry.get("last_out_tokens")
                    break
            if first_pass:
                first_pass = False
                rec["match_on_first_read"] = bool(samples and samples[0].get("match"))
            if time.monotonic() >= deadline:
                break
            time.sleep(POLL_INTERVAL_S)
        rec["samples"] = samples
        rec["n_samples"] = len(samples)
        rec["matched"] = matched_at is not None
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
    rec["t_exit_ns"] = time.time_ns()
    rec["hook_duration_ms"] = (rec["t_exit_ns"] - t_entry) / 1e6
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
