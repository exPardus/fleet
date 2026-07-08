export const meta = {
  name: 'fleet-idea-forge',
  description: 'Multi-round idea foundry for claude-fleet: research → ideate (5 lenses) → refine → adversarial attack → 4-personality judge panel → synthesize; repeats with feedback',
  whenToUse: 'When hunting for new claude-fleet features/ideas with heavy vetting. Expensive (~90-110 agents at defaults).',
  phases: [
    { title: 'Context', detail: 'one haiku digest of fleet docs', model: 'haiku' },
    { title: 'Research', detail: '4 web sweeps per round, angle varies by round', model: 'sonnet' },
    { title: 'Ideate', detail: '5 personality lenses per round', model: 'sonnet' },
    { title: 'Refine', detail: 'merge, dedup, top-N mini-specs', model: 'opus' },
    { title: 'Attack', detail: 'adversarial red-team per idea', model: 'opus' },
    { title: 'Judge', detail: '3 opus judges + 1 fable cynic per idea', model: 'opus' },
    { title: 'Synthesize', detail: 'final ranked report written to repo', model: 'fable' },
  ],
}

// ---- knobs ----
const ROUNDS = 2
const TOP_N = 5            // mini-specs per round that reach attack+judging
const PASS_SCORE = 6.5     // avg judge score to survive
const FLEET = 'C:/proga/claude-fleet'

// ---- schemas ----
const IDEAS = { type: 'object', required: ['ideas'], properties: { ideas: { type: 'array', items: {
  type: 'object', required: ['title', 'pitch', 'phase', 'novelty'],
  properties: { title: { type: 'string' }, pitch: { type: 'string' },
    phase: { type: 'string', description: 'which roadmap phase it belongs to, or NEW' },
    novelty: { type: 'number', description: '1-10 self-rated: does anything in PRIOR-ART already do this' } } } } } }

const SPECS = { type: 'object', required: ['specs'], properties: { specs: { type: 'array', items: {
  type: 'object', required: ['title', 'spec', 'phase', 'effort'],
  properties: { title: { type: 'string' }, spec: { type: 'string', description: '10-20 line mini-spec: what, how, principle-fit' },
    phase: { type: 'string' }, effort: { type: 'string', description: 'S/M/L' } } } } } }

const ATTACK = { type: 'object', required: ['fatal', 'wounds'], properties: {
  fatal: { type: 'boolean', description: 'true = idea is unworkable or violates a fixed principle' },
  wounds: { type: 'array', items: { type: 'string' }, description: 'concrete non-fatal problems' } } }

const VERDICT = { type: 'object', required: ['score', 'oneLiner'], properties: {
  score: { type: 'number', description: '1-10' }, oneLiner: { type: 'string' } } }

const JUDGES = [
  { name: 'greybeard-cynic', model: 'fable', persona: 'A staff engineer who has watched every orchestration framework of the last 15 years die of its own complexity. You despise features that exist to be impressive. You have seen "one state many views" promised and betrayed a dozen times. Score harshly; a 7 from you means you would actually build it.' },
  { name: 'shipit-pragmatist', model: 'opus', persona: 'A solo developer with 5 hours a week for this tool. You only value what saves you time within two weeks of building it. Maintenance burden is a first-class cost: every daemon, dependency, and config file loses points.' },
  { name: 'product-visionary', model: 'opus', persona: 'You judge whether this idea makes claude-fleet the tool people abandon Vibe Kanban / Claude Squad / Conductor for. Incremental parity bores you; you reward ideas that exploit fleet\'s unique durable-sessions + manager-knowledge architecture in ways competitors structurally cannot copy.' },
  { name: 'ops-auditor', model: 'opus', persona: 'A paranoid SRE/security reviewer. You score on failure modes, silent-death risk, attack surface (this tool can spawn processes with --dangerously-skip-permissions), cross-platform fragility, and what happens at 3am when it breaks.' },
]

const LENSES = [
  { key: 'power-user', prompt: 'ideas a heavy daily user of multi-session Claude Code would beg for after a month of real use' },
  { key: 'reliability', prompt: 'ideas that eliminate silent failure, lost work, and babysitting — boring, sturdy, ops-grade' },
  { key: 'minimalist', prompt: 'ideas that DELETE or collapse complexity — fewer commands, fewer concepts, same power; also flag existing planned features that should die' },
  { key: 'moat', prompt: 'ideas only possible because fleet has durable resumable sessions + a git-tracked manager knowledge loop — things Vibe Kanban/Agent-View/Conductor structurally cannot do' },
  { key: 'contrarian', prompt: 'ideas that challenge the roadmap\'s assumptions — where is the spec/roadmap wrong, what would you bet is the actual killer feature nobody listed' },
]

const RESEARCH_ANGLES = [
  ['deep-dive the top competitors (Vibe Kanban, Claude Squad, Conductor, Crystal/Nimbalyst, claude-flow, Citadel): changelogs, issues, roadmaps — what did they ship recently and what do their users complain about',
   'search HN, Reddit, X for pain points people report running multiple coding agents in parallel (lost work, steering, context, cost) — collect verbatim complaints',
   'multi-agent orchestration patterns from research and industry (2025-2026): supervision trees, checkpointing, agent memory systems — what transfers to CLI session orchestration',
   'adjacent domains: incident-management tools (PagerDuty), CI orchestrators, tmux/terminal-multiplexer power workflows, fleet/device management — UX patterns worth porting'],
  ['Claude Code native features landing 2026 (agent view, agent teams, hooks, SDK): what is newly possible or newly obsolete for a session orchestrator',
   'how people actually use Telegram/Slack/Discord bots to control long-running dev processes — command grammars, threading, notification fatigue solutions',
   'context management techniques for long-running LLM agents: journaling, compaction, handoff protocols — published patterns and their failure modes',
   'what makes internal developer tools get abandoned vs adopted — post-mortems, essays, studies'],
  ['newest multi-agent coding tools launched in the last 6 months that PRIOR-ART.md might have missed — verify each exists',
   'observability/dashboard patterns for autonomous agents: what do people actually look at, what is vanity',
   'cost control and budgeting patterns for heavy LLM agent usage — per-task budgets, trust-based routing, model tiering in the wild',
   'human-in-the-loop approval patterns: plan gates, definition-of-done contracts, review queues — implementations and lessons'],
]

// ---- phase 0: context pack (haiku, once) ----
phase('Context')
const brief = await agent(
  `Read these files and produce a dense 60-line brief for other agents: ${FLEET}/docs/SPEC.md, ${FLEET}/docs/ROADMAP.md, ${FLEET}/docs/PRIOR-ART.md, and every file in ${FLEET}/docs/specs/. Cover: architecture (sessions-not-processes, mailbox+hooks, journals, knowledge loop), the 5 design principles VERBATIM, the 6 roadmap phases, existing planned features per phase, and the steal-ideas already listed. Return only the brief.`,
  { label: 'docs-brief', model: 'haiku' })

const seen = new Set()
const survivors = []
const graveyard = []
let feedback = 'none yet — first round'

for (let round = 1; round <= ROUNDS; round++) {
  log(`=== round ${round}/${ROUNDS} ===`)

  // ---- research (sonnet, 4 angles, varies by round) ----
  const angles = RESEARCH_ANGLES[(round - 1) % RESEARCH_ANGLES.length]
  const research = (await parallel(angles.map((a, i) => () =>
    agent(`Web research for the claude-fleet project (context brief below). Load WebSearch/WebFetch via ToolSearch first. Angle: ${a}. Return a compact digest: findings as bullets with sources, max 40 lines, no padding.\n\nCONTEXT:\n${brief}`,
      { label: `research:r${round}a${i}`, phase: 'Research', model: 'sonnet' })
  ))).filter(Boolean).join('\n\n---\n\n')

  // ---- ideate (sonnet, 5 lenses) ----
  const rawIdeas = (await parallel(LENSES.map(l => () =>
    agent(`You are an ideation agent for claude-fleet. Your lens: ${l.prompt}.\n\nCONTEXT BRIEF:\n${brief}\n\nFRESH RESEARCH:\n${research}\n\nALREADY-SEEN IDEA TITLES (do not repeat or trivially rephrase):\n${[...seen].join('; ') || 'none'}\n\nPRIOR JUDGE FEEDBACK (learn what dies and why):\n${feedback}\n\nPropose 4-6 ideas. Each must fit the 5 design principles in the brief. Be specific, not thematic.`,
      { label: `ideate:${l.key}:r${round}`, phase: 'Ideate', model: 'sonnet', schema: IDEAS })
  ))).filter(Boolean).flatMap(r => r.ideas)

  // dedup vs everything ever seen (plain code — barrier above is justified: dedup needs all lenses)
  const fresh = rawIdeas.filter(i => {
    const k = i.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  log(`round ${round}: ${rawIdeas.length} raw → ${fresh.length} fresh ideas`)
  if (!fresh.length) continue

  // ---- refine (opus, one merger) ----
  const refined = await agent(
    `You are the refiner. From the candidate ideas below, select the ${TOP_N} strongest (merge overlapping ones), and write each up as a 10-20 line mini-spec: what it is, how it works within fleet's architecture, which roadmap phase it belongs to, effort S/M/L, and explicitly how it satisfies (or tensions with) the 5 design principles.\n\nCONTEXT BRIEF:\n${brief}\n\nCANDIDATES:\n${JSON.stringify(fresh, null, 1)}`,
    { label: `refine:r${round}`, phase: 'Refine', model: 'opus', schema: SPECS })
  if (!refined) continue

  // ---- attack + judge pipeline (per idea, no barrier between ideas) ----
  const judged = await pipeline(
    refined.specs,
    (s) => agent(
      `Adversarial red-team. Try to KILL this claude-fleet idea: technical infeasibility, race conditions, cross-platform breakage, violation of the design principles (in brief), YAGNI, "native Claude Code will ship this next month", maintenance trap. Default skeptical.\n\nCONTEXT BRIEF:\n${brief}\n\nIDEA:\n${s.title}\n${s.spec}`,
      { label: `attack:${s.title.slice(0, 30)}`, phase: 'Attack', model: 'opus', schema: ATTACK }
    ).then(a => ({ spec: s, attack: a })),
    (r) => {
      if (!r || r.attack?.fatal) return r  // fatally wounded — skip judging, record below
      return parallel(JUDGES.map(j => () =>
        agent(`${j.persona}\n\nJudge this claude-fleet idea (context brief + red-team findings below). Score 1-10 and one line of reasoning.\n\nCONTEXT BRIEF:\n${brief}\n\nIDEA:\n${r.spec.title}\n${r.spec.spec}\n\nRED-TEAM WOUNDS:\n${(r.attack.wounds || []).join('\n')}`,
          { label: `judge:${j.name}:${r.spec.title.slice(0, 20)}`, phase: 'Judge', model: j.model, schema: VERDICT })
      )).then(vs => ({ ...r, verdicts: vs.filter(Boolean) }))
    }
  )

  // ---- tally (plain code) ----
  const crits = []
  for (const r of judged.filter(Boolean)) {
    if (r.attack?.fatal) {
      graveyard.push({ title: r.spec.title, cause: 'red-team fatal', wounds: r.attack.wounds })
      crits.push(`KILLED (fatal): ${r.spec.title} — ${(r.attack.wounds || []).join('; ')}`)
      continue
    }
    const avg = r.verdicts.reduce((s, v) => s + v.score, 0) / (r.verdicts.length || 1)
    const entry = { round, title: r.spec.title, spec: r.spec.spec, phase: r.spec.phase,
      effort: r.spec.effort, avg: Math.round(avg * 10) / 10,
      verdicts: r.verdicts.map((v, i) => `${JUDGES[i]?.name}: ${v.score} — ${v.oneLiner}`),
      wounds: r.attack.wounds }
    if (avg >= PASS_SCORE) { survivors.push(entry) } else {
      graveyard.push({ title: entry.title, cause: `avg ${entry.avg} < ${PASS_SCORE}`, verdicts: entry.verdicts })
    }
    crits.push(`${entry.title}: avg ${entry.avg} — ${entry.verdicts.join(' | ')}`)
  }
  feedback = crits.join('\n')
  log(`round ${round} done: ${survivors.length} total survivors, ${graveyard.length} in graveyard`)
}

// ---- synthesis (fable) ----
phase('Synthesize')
const report = await agent(
  `You are the final synthesizer for the claude-fleet idea forge. Below: context brief, ${survivors.length} judge-approved ideas (with scores, per-judge one-liners, red-team wounds), and the graveyard of killed ideas.\n\nWrite ${FLEET}/docs/IDEA-FORGE-REPORT.md: (1) executive summary, (2) ranked survivor table (score, phase, effort), (3) full mini-specs for the top ideas ordered by score with judge quotes and remaining wounds to address, (4) roadmap-integration recommendations (which phase/spec-stub each idea should be folded into), (5) graveyard appendix — one line each with cause of death, so future speccing sessions don't re-propose them. Also RETURN the executive summary + ranked table as your final text.\n\nCONTEXT BRIEF:\n${brief}\n\nSURVIVORS:\n${JSON.stringify(survivors, null, 1)}\n\nGRAVEYARD:\n${JSON.stringify(graveyard, null, 1)}`,
  { label: 'synthesize', model: 'fable' })

return { survivors: survivors.length, killed: graveyard.length, report }
