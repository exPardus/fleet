#!/usr/bin/env bash
# Bench cheap OpenRouter models on the inventory task through finger.py.
B=/home/altai/proga/fleet/tools/fingers
OUT=$B/bench-out; mkdir -p "$OUT"
one() {
  m="$1"; safe=$(echo "$m" | tr '/:' '__'); d="$OUT/$safe"
  rm -rf "$d"; cp -r "$B/bench-template" "$d"
  r=$(timeout 600 python3 "$B/finger.py" --model "$m" --dir "$d" --task "@$B/bench-task.md" --json 2>&1 | tail -1)
  pass=$(cd "$d" && uv run --no-project --python 3.12 --with pytest python -m pytest -q 2>&1 | tail -1)
  echo "{\"pytest\":\"$(echo "$pass" | tr -d '"' | tail -c 40)\",\"run\":$r}" >> "$OUT/results.jsonl"
}
export -f one; export B OUT
: > "$OUT/results.jsonl"
printf '%s\n' "$@" | xargs -P 4 -I{} bash -c 'one "$@"' _ {}
echo DONE >> "$OUT/results.jsonl"
