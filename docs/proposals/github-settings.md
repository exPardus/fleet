# Proposal: GitHub repo settings for discoverability

Status: PROPOSAL — nothing here has been applied. Every command below is for the
operator/manager to run by hand; this branch mutates no repo settings.

Measured baseline (2026-07-24, `gh repo view exPardus/fleet`): the repo is PUBLIC with
**no description, no topics, no homepage**, Discussions off, Issues on, Wiki on. GitHub
search and topic pages index description + topics, so today the repo is effectively
invisible to anyone not handed a direct link.

## 1. Description (highest impact, one command)

GitHub truncates around 350 chars; this is 315. It front-loads the search phrases people
actually type ("Claude Code", "orchestration", "agents", "parallel") while staying
literally true of the code:

```
gh repo edit exPardus/fleet --description "Fleet manager for Claude Code: one manager session spawns, steers, and monitors many durable headless Claude Code agent sessions in parallel across projects. Mid-turn steering, token budgets, usage-limit park/resume, journals + respawn, git-tracked knowledge loop. Single-file stdlib-only Python CLI. No daemon, no deps."
```

## 2. Topics (second highest impact, one command)

GitHub topic pages are a real discovery channel (`github.com/topics/claude-code` etc.).
15 topics, all lowercase/hyphenated per GitHub rules, ordered core → generic:

```
gh repo edit exPardus/fleet --add-topic claude --add-topic claude-code --add-topic anthropic --add-topic ai-agents --add-topic llm --add-topic llm-agents --add-topic agent-orchestration --add-topic multi-agent --add-topic multi-agent-systems --add-topic autonomous-agents --add-topic coding-agents --add-topic agentic-workflow --add-topic developer-tools --add-topic cli --add-topic python
```

Judgment calls: `agentic-workflow` and `coding-agents` are where the 2026 search
traffic is; `windows` was cut (platform topics attract little browse traffic and the
README badges already carry it).

## 3. Homepage

No docs site exists yet (see §6), so point the homepage at the reader-facing entry doc
rather than leaving it blank:

```
gh repo edit exPardus/fleet --homepage "https://github.com/exPardus/fleet/blob/main/docs/concepts.md"
```

Swap this for the Pages URL if/when §6 ships.

## 4. Community surfaces

```
gh repo edit exPardus/fleet --enable-discussions
gh repo edit exPardus/fleet --enable-wiki=false
```

- **Discussions on**: README + CONTRIBUTING invite community; issues are for bugs/features,
  Discussions gives "how do I / show-and-tell" a home that isn't a dead issue.
- **Wiki off**: it is empty, and an empty Wiki tab reads as abandonment. All docs live in
  `docs/` under review discipline; a second, unreviewed docs surface would drift (this
  repo's docs already drift one direction — see `knowledge/lessons.md` 2026-07-23 doc-pass-2).

## 5. Social preview (manual — no CLI)

Settings → General → Social preview. Until someone makes an image, GitHub renders the
repo name + description, so §1 already improves link cards. Suggested text if an image
gets made (1280×640):

> **claude-fleet** — run a whole team of Claude Code agents from one seat.
> Durable sessions · mid-turn steering · survives reboots and usage limits · zero deps.

## 6. GitHub Pages docs site: recommend LATER, not now

Recommendation: **not yet.**

- The reader path (README → concepts → getting-started) is 3 files of GitHub-rendered
  markdown with working mermaid — a Pages build adds CI, a theme, and a second rendering
  target to keep honest, for near-zero reach gain at the current audience size.
- The receipts discipline (`tools/verify_receipts.py`) targets the repo's markdown;
  a transformed site is one more place for claims to rot.
- Revisit when: topics/description have been live for a while, and traffic or issue volume
  suggests strangers are actually landing (say, ≥50 stars or recurring "how do I" issues).
  Then a `mkdocs-material` site over the existing `docs/` tree is a weekend, not a project.

## Top 3 by impact

1. §1 description — repo currently has none; this is the search index entry.
2. §2 topics — repo currently has none; this is the browse/discovery channel.
3. §4 discussions+wiki — makes "community welcome" true at the settings layer, not just in prose.
