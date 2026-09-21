# Native acceptance blocker disposition
DONE means: deterministic protocol tests close supported usage and leave unsupported Interface authentication fail-closed.

## Receipt

Native `interface-register --codex-thread` requires an explicit Fleet home, but
remains blocked. The public protocol exposes readable thread ID, session ID, and
source membership; official documentation does not define the ambient Codex IDs
as caller credentials. Treating replayable environment values as authentication
would let a known UUID grant mutation. Fleet, PM, and tap therefore each refuse
without provider access or state change. No resume, turn, or second writer occurs.

The per-home host now durably records bounded `item/completed`,
`turn/completed`, and `thread/tokenUsage/updated` evidence. Supervisor result
reconciliation binds it to the exact claimed thread/turn. Result text persists
only from matching durable item text/ID with an explicit untruncated marker;
completed status, usage, or live history alone stays incomplete. A fresh store
instance recovers the same evidence after restart.

Fake harness: 18 probes passed with no provider process; Interface remains
BLOCKED. No real
provider lifecycle was retried. Native remains opt-in; worker paging, permissions,
bridge control, and default cutover remain out of scope.

## WHERE THIS BRIEF WAS WRONG

The requested genuine Interface authentication is absent from the reviewed
public protocol. Thread/session/source membership cannot substitute for it.
