#!/usr/bin/env python3
"""A minimal agent harness for cheap models -- "fingers", not brains.

Four tools (list_dir, read_file, write_file, run_cmd), one loop, no plugins,
no MCP, no hooks. It exists because Claude Code's per-turn overhead is larger
than a mechanical edit deserves, and because a model too weak for Claude Code
can still rename a symbol or add a docstring correctly.

Usage: finger.py --model <openrouter-slug> --dir <workdir> --task <text|@file>
Env: OPENROUTER_API_KEY (or --key-file, default ~/.config/openrouter/env).
"""
import argparse, json, os, pathlib, re, subprocess, sys, time, urllib.request

API = "https://openrouter.ai/api/v1/chat/completions"
TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "description": "List files under a path relative to the working directory.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 text file relative to the working directory.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write a UTF-8 text file relative to the working directory, creating or replacing it.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_cmd", "description": "Run a shell command in the working directory and return its output.",
      "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
]
SYSTEM = ("You are a careful engineer doing one mechanical task in a working directory. "
          "Use the tools; do not describe what you would do. Read before you write. "
          "Verify with run_cmd when a check exists. When the task is done and verified, "
          "reply with one short line and no tool call.")


def _safe(workdir: pathlib.Path, path: str) -> pathlib.Path:
    p = (workdir / (path or ".")).resolve()
    if not str(p).startswith(str(workdir.resolve())):
        raise ValueError("path escapes the working directory")
    return p


def call_tool(workdir: pathlib.Path, name: str, args: dict, timeout: int) -> str:
    try:
        if name == "list_dir":
            p = _safe(workdir, args.get("path", "."))
            return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir()))[:4000]
        if name == "read_file":
            return _safe(workdir, args["path"]).read_text(encoding="utf-8", errors="replace")[:20000]
        if name == "write_file":
            p = _safe(workdir, args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return f"wrote {len(args.get('content',''))} bytes to {args['path']}"
        if name == "run_cmd":
            r = subprocess.run(args["cmd"], shell=True, cwd=workdir, capture_output=True,
                               text=True, timeout=timeout)
            out = (r.stdout + r.stderr)[-6000:]
            return f"exit={r.returncode}\n{out}"
        return f"unknown tool {name}"
    except Exception as exc:  # a tool error is data for the model, not a crash
        return f"ERROR: {type(exc).__name__}: {exc}"


def post(body: dict, key: str, timeout: int) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read())


def read_key(path: pathlib.Path) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    text = path.read_text(encoding="utf-8")
    match = re.search(r"OPENROUTER_API_KEY=(\S+)", text)
    if not match:
        raise SystemExit(f"no OPENROUTER_API_KEY in {path}")
    return match.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--task", required=True, help="task text, or @path to a file")
    ap.add_argument("--max-steps", type=int, default=24)
    ap.add_argument("--cmd-timeout", type=int, default=120)
    ap.add_argument("--http-timeout", type=int, default=300)
    ap.add_argument("--key-file", default=os.path.expanduser("~/.config/openrouter/env"))
    ap.add_argument("--json", action="store_true", help="print one JSON line instead of prose")
    args = ap.parse_args()

    workdir = pathlib.Path(args.dir).resolve()
    task = args.task
    if task.startswith("@"):
        task = pathlib.Path(task[1:]).read_text(encoding="utf-8")
    key = read_key(pathlib.Path(args.key_file))

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    started, usage, steps, final = time.time(), {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}, 0, ""
    while steps < args.max_steps:
        steps += 1
        try:
            data = post({"model": args.model, "messages": messages, "tools": TOOLS,
                         "tool_choice": "auto", "max_tokens": 4000}, key, args.http_timeout)
        except Exception as exc:
            final = f"HARNESS ERROR: {type(exc).__name__}: {exc}"
            break
        if "choices" not in data:
            final = f"API ERROR: {json.dumps(data)[:300]}"
            break
        for field in ("prompt_tokens", "completion_tokens"):
            usage[field] += (data.get("usage") or {}).get(field, 0) or 0
        usage["cost"] += (data.get("usage") or {}).get("cost", 0) or 0
        msg = data["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            final = (msg.get("content") or "").strip()
            break
        for call in calls:
            fn = call["function"]
            try:
                fn_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            result = call_tool(workdir, fn["name"], fn_args, args.cmd_timeout)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "name": fn["name"], "content": result[:20000]})
    else:
        final = f"STOPPED: hit --max-steps {args.max_steps}"

    record = {"model": args.model, "steps": steps, "seconds": round(time.time() - started, 1),
              "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
              "usd": round(usage["cost"], 5), "final": final[:400]}
    print(json.dumps(record) if args.json else
          f"{record['model']}: {record['steps']} steps, {record['seconds']}s, "
          f"{record['usd']} USD\n{record['final']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
