# Native Codex durable-result rereview — 368d5ea

DONE means: exact-head verdict, focused evidence, and remaining boundary are recorded.

**Verdict: GREEN.** Reviewed `368d5ea8c0428ad0047a93af604428f5a9de7905` atop `e5d1610`, closing RED `fe3c844`.

Successful completed results now require durable `result_text`, nonempty `result_item_id`, explicit `result_truncated=false`, full matching public item history, and complete usage. Output and stored result fields come from durable evidence. Missing/live-only/missing-marker cases return incomplete with no result text/item persisted; explicit truncation does likewise while preserving lifecycle and usage. Text or item disagreement raises ambiguity before any registry write. Claim/thread/turn/generation revalidation remains under lock.

Restart evidence, usage, lifecycle classification, no-duplicate resume/turn behavior, owner/path guards, and default-off provider launch remain intact. Fleet/PM/tap explicit homes and ambient-home fallback still refuse Interface registration before provider access or mutation because the protocol has no caller credential.

Checks: Python 3.10 **31 passed**; Python 3.12 **31 passed**; adversarial truncation/mismatch **2 passed** on each; fake harness **18 passed**, zero provider processes (overall `BLOCKED` only for the intentional Interface boundary); `git diff --check` clean.
