# Documentation index

Fleet's tracked documentation is generic public product and design material.
Operational records belong to each user's local fleet home and are ignored by
Git; `fleet init` creates those paths without replacing existing content.

## Start here

- [`getting-started.md`](getting-started.md) — install and initialize a home.
- [`concepts.md`](concepts.md) — architecture and lifecycle overview.
- [`SPEC.md`](SPEC.md) — behavioral specification and invariants.
- [`ROADMAP.md`](ROADMAP.md) — future product direction.
- [`PRIOR-ART.md`](PRIOR-ART.md) — generic ecosystem comparison.
- [`specs/`](specs/) — topic-specific public designs and executable receipts.
- [`plans/`](plans/) — generic implementation plans that remain current.

## Repository surfaces

- [`../README.md`](../README.md) and [`../product.md`](../product.md) define the
  public product.
- [`../skills/fleet/SKILL.md`](../skills/fleet/SKILL.md) is the operating manual.
- [`../knowledge/INDEX.md`](../knowledge/INDEX.md) and
  [`../knowledge/playbooks/`](../knowledge/playbooks/) are generic knowledge.
- [`../tests/`](../tests/) and [`../bin/`](../bin/) are the executable contract
  and implementation.

## Local operator data

`supervisor/`, `state/`, `logs/`, `mailbox/`, `docs/lanes/`,
`knowledge/projects/`, and `local operator lessons` are per-home local storage.
They may contain goals, identities, journals, briefs, lane receipts, project
facts, and operator decisions, so they are never public source.
