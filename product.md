# fleet — product

## Who
Anyone who wants software built by a team of agents, not helped by one. First
user: its author, running several projects on a small remote box with limited
Claude and Codex plans. Open source on GitHub; other people are meant to run it.

## What
Fleet is another software developer on the team: its own agent. Give it an
idea, a bug, a product, or a job, and it works the way a good developer does:
understands the intent, proposes the shape, makes reasonable choices, keeps the
big picture, delivers, learns from what breaks, and keeps going for days without
supervision. It reports honestly, asks only what is the operator's to decide,
and survives limits, crashes and context bands without anyone noticing.

## How it works
- Interface: the conversation. Turns a seed into a product brief with the
  operator, holds the vision, rules on the irreversible. Any session, any repo.
- Supervisor: the manager. Splits a job into departments, writes charters,
  lands and integrates, hands off to its successor at its context band.
- Workers: departments. As independent as the task allows; long tasks get
  long-lived workers with their own branch, subagents and tests. QA and security
  are departments with the same standing as feature work.
- Substrates: Claude sessions and Codex. Native Codex support is the target;
  mcx is the stopgap until it exists.
- Rituals are code. Models decide; scripts boot, guard, reap, land, close waves.

## Good enough
Fleet is never done. It is good enough when a real project ships through it
from one sentence to a usable release, the operator only answering questions
and ruling, and a second project runs the same way without new fleet work.

## Quality bar
Tests pass from a clean clone. Nothing is done until someone other than its
author has used it and said so. Reports are short and structured. Docs say what
a thing is for and how to use it, once; code is the authority. Spend is
measured per landed line.

## Never
- Never build a fleet feature no downstream job asked for.
- Never write prose that restates code or history.
- Never let a worker mark its own milestone done.
- Never spend the operator's attention on governance of fleet itself.
- Never a second live supervisor over one home.
