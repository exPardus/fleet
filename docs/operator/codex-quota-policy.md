# Codex quota and message policy

**Current operator ruling (2026-09-20).** Subscription tokens are scarce even
when incremental API spend is zero. This policy applies to current Codex fleet
work and survives interface and supervisor handoff.

## Admission and routing

- Run at most two implementation or research workers plus one focused reviewer
  under the supervisor. The interface and supervisor are separate roles.
- A worker may not spawn descendants without the supervisor approving a bounded,
  independent task. Do not create recursive reviewer chains.
- Use Luna for routine inventory, documentation, and glue; Sol for substantive
  research, implementation, and review. Terra is prohibited. Astra remains
  restricted to separately authorized money or VPS operations; the completed
  bounded reasoning pass does not authorize another one.
- Use one focused independent review per change. After two unsuccessful review
  rounds, stop and rebrief from the concrete blockers instead of adding reviewers.
- Before a batch, record any supported quota or token counters plus its model,
  effort, and context plan. After it, record supported deltas and the delivered
  artifact. State unavailable counters and conversions as unavailable.

## Message and context limits

- Inter-agent messages default to at most 120 words.
- Final worker receipts are at most 200 words: verdict, head, tests, blockers,
  next action, and exact artifact paths.
- Store full evidence in artifacts. Link exact files or commits; do not paste
  reports, JSON, test logs, or full roster dumps between agents.
- Send the smallest complete brief with exact file pointers. Do not fork full
  conversation history by default. Bound tool output and avoid repeated polling.

## What is measurable

The supported collaboration roster exposes identity, hierarchy, and current
status. It does not expose subscription-token totals, cache charges, historical
peak concurrency, or a conversion from provider tokens to weekly plan quota.
OpenRouter credit and API-price records are separate and must not be presented as
Codex subscription usage.

The 2026-09-20 exhaustion followed many Sol/high bodies, nested evidence and
review fan-out, repeated RED/fix/rereview turns, one Astra/xhigh reasoning pass,
interrupted Terra turns, four accidental Luna fixture launches, and verbose
cross-agent receipts. These are evidenced demand mechanisms, not an allocation
of the weekly quota. Exact attribution is unavailable. OpenAI's current plan
documentation says model, context, reasoning, tool use, and caching affect quota:
<https://learn.chatgpt.com/docs/pricing>.

DONE means this policy is linked from the active skill, tier policy, campaign,
and current interface handovers, and its focused documentation checks pass.
