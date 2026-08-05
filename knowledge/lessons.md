# Lessons

Append-only postmortems. One entry per campaign: what worked, what stalled, prompt patterns worth reusing. Never edit or delete a past entry — add new ones below.

<!-- Add new entries below this line -->

## 2026-08-05 — operator direction: launch focus, parallel waves, §7-pin reading confirmed <a id="2026-08-05-launch-directive"></a>

**Three rulings by Altai in-session through the interface, same sitting as the usage-provenance ruling.** (1) The slice-a price doc's Ambiguity #1 reading CONFIRMED: slice (a) ships the two §7 pins that verify its own surface (destructive-tier, arming-indeterminacy — landing with a3); §7 items that presuppose later slices' plumbing defer to slice (e). The a1/a2/a3 split of slice (a) is adopted (sub-numbering only; the spec's letters b–e stay). (2) **MORE PARALLELISM, binding from wave 42**: as many concurrent lanes as file-set disjointness allows (`git diff --name-only` is the test), serialize only real collisions — this SUPERSEDES the 2026-07-23 "keep the worker count small" cap doctrine. (3) **Goal reframed: claude-fleet fully ready for launch and use in the operator's other projects.** The multi-fleet build and launch-readiness surfaces (install/onboarding docs, external-user friction) are the priority axis; fleet self-repair runs only when it blocks that axis. Context that prompted it: the operator observed — and the interface's own wave audit confirmed — that waves 36–41 drifted into self-maintenance (gates, folds, re-pins, self-repair) with zero quest-forward features built since MF slice 0 on 2026-07-31. *A fleet that dogfoods itself will always find its own repair queue most urgent; the priority axis has to come from outside the loop.*

## 2026-08-05 — operator ruling: usage fields stay withheld on the race (A) <a id="2026-08-05-usage-provenance-ruled-A"></a>

**Ruled by Altai in-session through the interface** (the sup-decision slot was occupied by ND4(c), so wave 40r's release note carried the question and the interface put it). The Stop-hook proof gate (`f5b8125`, 2026-07-30) publishes per-turn usage only when the Stop payload's last assistant message string-equals the transcript's — ~73% of turns fail that and get four None fields, which is why `fleet status` COST read `-` for six days before wave 40r read the column. Options priced: **A** withhold (honest; costs per-worker accounting, §11.4 token-band enforcement, and the usage-limit watch on racing turns), **B** publish the stale counter (usable, false magnitude), **C** publish with provenance (40r's recommendation). **Answer: A — withhold.** The named costs are accepted; C's provenance surface is not to be built. Code consequence: the two-test contradiction (`tests/test_outcome_usage_provenance.py:108` asserts None where `tests/integration/test_native_pin.py:345` demands a count — never co-evaluated, the pin tier is FLEET_LIVE-gated) resolves TOWARD the provenance suite; the pin assertion is the one that moves, after the probe establishes what the record actually carries. Relayed to wave 41 by steer file `state/tasks/lens/ruling-usage-provenance-A.md` the same tick.

## 2026-07-31 — wave 38: the merge that measured zero because it measured nothing <a id="2026-07-31-w38-merge-audit"></a>

**THE lesson: `git merge-tree --write-tree` DOES NOT EXIST at this machine's git (2.34.1), and the way it fails is the finding.** It parses `--write-tree` as a REV and dies `fatal: unknown rev --write-tree`, emitting **no conflict output at all**. A grep for conflict markers over that empty output returns zero, and **zero reads as "no conflicts"**. That is the provenance of wave 37's sentence *"all three branches predict ZERO conflict hunks against main AND zero against each other pairwise"* — a null presented as a measurement, in a checkpoint, in the paragraph doing the pricing. Re-measured with the three-arg form (`git merge-tree <base> <ours> <theirs>`, grep `<<<<<<<` **unanchored**), and **validated first against a known answer** (it reports 16 for the respawn merge that in fact hit 16): **nd4c × main = 13, respawn × main = 16, refute × main = 0. Only one of the three zeros was real.** Generalise past git: **a CLI that errors on an unknown flag by REINTERPRETING IT AS A POSITIONAL ARGUMENT turns "I measured nothing" into "I measured zero", and nothing downstream can tell.** The defence is not a version check — it is that *every* measurement whose good answer is `0` must first be run against an input whose answer is known to be non-zero.

**MERGE-PREP-BY-LANE: worth keeping, with a structural defect that must be designed out. THE PREP LANE'S REPORT IS A CLAIM ABOUT A PARENT.** The pattern — a fenced lane resolves the merge on a stage branch with no push, the supervisor audits and lands it — converted a **50–65k in-body merge into roughly 12k of audit**, and the audit is what found the defects, so the token case holds. But the prepped merge's FIRST parent was `5bb7945`, main as it stood when the lane was dispatched, and main had since advanced two commits (`6505bb5`, `a1047b2`) — **both of them the dispatching supervisor's own wave-37 journal entries, written after it dispatched the lane**. `git merge-base --is-ancestor main w37/stage-respawn` answered **NO**. The lane's report said *"main is an ancestor (fast-forward legal)"* and **that sentence was TRUE WHEN WRITTEN and FALSE WHEN READ**. The lane did nothing wrong; the defect is in the pattern. **A fenced prep lane resolves against a SNAPSHOT of main while the supervisor that dispatched it keeps writing to main — the journal, every checkpoint — so every merge-prep lane races its own dispatcher, and the dispatcher always wins because it commits last.** The in-body merge the pattern replaces cannot have this defect: the body resolving the merge is the body writing the journal. **Rule: re-derive ancestry at landing time; never trust "fast-forward legal".** Survivable here only because it was *measured* rather than assumed — the whole main-side delta was `supervisor/JOURNAL.md` +52/-0, one file, and the stage merge's eight files did not include it, so the landing cost one extra merge commit. **A lane dispatched across a real main-side code change would have needed a full re-resolve.** Not a rebase, ever, in this shape: rebasing would rewrite a merge commit whose *resolution is the entire artifact under audit*.

**THE STRONGEST CHECK OF THE WAVE, AND NOBODY HAD RUN IT BEFORE: NO HUNK WAS LOST FROM EITHER SIDE.** Digit-masked (`:NNNN` **and** `:NNNN-NNNN` ranges), main had added **151** lines since the base and the branch **251**; **zero of either set is missing from the merged file**. *That* is what distinguishes "the 16 conflicts were resolved" from "the 16 conflicts were narrated" — and **no conflict count and no marker scan shows it**. The mask is itself a trap: a first mask that mis-handled `:6356-6358` produced a false positive that had to be chased. Both knowledge-file unions checked the same way and were lossless: 34+34 index keys → 35, 43+43 lesson keys → 44, nothing dropped, nothing invented.

**A TEST-COUNT DELTA MUST BE COLLECTED, NEVER COUNTED FROM `def test_` LINES.** The brief predicted 3598 and the lane 3621; the lane was right and the supervisor derived it independently before reading theirs. `test_brief_preservation.py` is ABSENT at the base and **collects 42 from 32 defs** (parametrised); `test_index_compose.py` has 98 defs on BOTH sides, so its 90-line diff is body edits and contributes **zero**. Base 3594 collected + 42 = 3636 = **3621 passed / 14 skipped / 1 xfailed**, predicted before running, hit exactly, identical on py 3.13 (340.64s) and py 3.10 (303.76s). **The brief's "+19" had no derivation behind it, and the 10-test gap between 32 defs and 42 tests is the whole distance between the two predictions being credible.**

**NEVER PIPE A RUN WHOSE EVIDENCE IS ITS WHOLE OUTPUT — the wave-24 nonce lesson recurring on the receipts side.** The first receipts run went through `| tail -8`, so **15 specs collapsed to the last one's verdict** and it read **79/79 where the truth was 192/194**. Caught only because it disagreed with the lane's number — i.e. by luck of having a second source, not by the check itself. Committed by the supervisor who had just finished quoting this campaign's own warnings about inherited numbers. Re-run unpiped: **192/194 exact, 0 failures, 0 unclassified, 15/15 specs, rc=0**; the 2 warnings are the two known volatile receipts (a directory mtime, and `claude --version` 2.1.207 vs 2.1.220, on record as WARN-never-FAIL).

**THE SEQUENTIAL-MERGE HAZARD NOW HAS A NUMBER ON BOTH SIDES OF ONE LANDING.** Immediately BEFORE landing respawn, main × `w36/refute` predicted **0** conflicts. Immediately AFTER, the same measurement on the same branch predicts **14**. The landing moved `bin/fleet.py` by **+347/-25** and converted a free merge into a 14-hunk one. Every prior wave has *said* merges must go sequentially because each landing moves the next lane's merge-base; **this is the first time the delta was measured rather than warned about**, and the re-gate brief for that branch had to carry the 14.

**A DEFECT THE GREEN GATE MISSED, FOUND AT MERGE AUDIT.** The branch put *"nothing caught it for four months"* into `skills/fleet/SKILL.md`. The repo's first commit is 2026-07-07 and `task[:200]` shipped in it, so the window is **24 days** — four months predates the repo entirely. `SKILL.md` is read by every supervisor at boot: **a file loaded by a process on a schedule is code with worse tooling**, the running-surface class this campaign keeps naming as the one that hurts. Corrected as a **separate commit**, deliberately not folded into the merge, **so the merge tree still equals the audited artifact byte-for-byte** — the audit's value is destroyed the moment the landed tree stops being the tree that was audited. *(That same "four months" figure was also written into `knowledge/` and survived this sweep — see the correction appended to `#2026-07-31-w35-brief-store` below.)*

**PROVE BOTH PARENTS FROM THE PUSHED REF, AND BUY THE RIGHT TO REUSE SOMEONE ELSE'S FLOORS BY CONSTRUCTION.** Parents read back from origin, not from local: `4bbee2c` (the supervisor's main) and `4459d9b` (the lane's audited READY sha). Before touching main the merge was built on a **throwaway worktree** and the result proved to differ from the audited tree in **exactly one file** — `supervisor/JOURNAL.md`, +80 lines, append-only, and read by **no** test (the only test naming that path uses a temp `FLEET_HOME`). **That is what licensed reusing the lane's floors instead of re-running them: the landed tree IS the measured tree plus a file the suite cannot see.** Probe tree and landed tree hashed identical, then the probe was deleted. `main a1047b2 → 01a2469`, origin read back byte-identical (same sha, same tree).

**AUDIT A RE-PIN LIST AGAINST ITS DERIVATIONS, NOT AGAINST ITS COUNT.** The three `one_of` citations are weak **by construction** — the test checks set membership only, and `load_registry` has TWO `_quarantine_registry` call sites (871 and 877), so a wrong pick stays green. The pick was proved correct by reading BOTH PARENTS: main cited 848, the branch cited 837, and at each of those commits that line is the `JSONDecodeError` arm; the merge cites 871, the same arm — faithful in both directions. Separately, the one site with **no function pin** (anchor *"registry present or not"*, two hits: 785 in `_quarantine_artifacts`, 8900 in `_sweep_husks`) is **exactly the wave-35 green-and-wrong shape** — and it landed on 8900, the one its own prose names. The lane caught its own trap; the audit still had to check, because "it happened to be right" and "it was derived right" are different properties.

**Smaller, measured.** Zero surviving conflict markers in the stage tree was recorded as **NOT evidence** (wave-30: markers gone, six red in 0.70s) — the floors are the evidence. Doctor **3 FAIL**, none taken. The identity-witness LEAK returned again — the stamp named `sup|inc-20260730T202915Z-4726|boot`, a **dead** record, while the registry resolved the live sid correctly — **recorded and not believed**, because §18 makes the registry the judge; day-4 wedge-2 re-confirmed at yet another boot, the substitution model still describing it exactly. Worktrees retired with **ancestry proved BEFORE removal, not assumed**: `4459d9b` and `461cd02` are ancestors of main, `011f60a` and `1e810f7` are NOT, so the refute and nd4c trees stood. Ruling-B bypass event fired as ratified, **8th measurement**.

## 2026-07-31 — wave 37: three gates, and a finished result nobody read wrote the next wave's brief <a id="2026-07-31-w37-gates"></a>

**THE lesson: the campaign brief ordered work that had already shipped, because nobody had read the worker result that shipped it.** Section 2 told this wave to dispatch fix lanes for P1-12, P1-13 and P1-7. The refute lane had already **refuted the collapse claim and shipped the fix** — `011f60a`, twenty tests watched **14-RED/6-green before any production change**, floors 3599/14/1 predicted and hit exactly on both interpreters, receipts 11/11, self-citations run to fixpoint over five iterations. What was actually owed was a **gate** on that branch, which nobody had scheduled. **Third wave running where an unread worker result generated false work for the next wave.** The pattern is not "workers are slow": **a finished result with no reader is indistinguishable from work not done** — the 2026-07-27 outage lesson (*a clean shutdown with no reader is indistinguishable from a healthy fleet*) one level up, on results instead of on state.

**LANE A (`w35/nd4c`) RED AGAIN AT GATE 2 — 4 BLOCKING, ALL TEXT — AND WHAT BLOCKS IS A CENSUS.** The code was re-confirmed sound *by construction*: the narrowing differs from its pre-image on exactly one input class, floors 3516/14/1 identical on both interpreters, receipts 68/68 on three-tier and 68/69 on claim-nonce with the one warning **proved pre-existing by re-running it against `0726914`'s copy of the file**. `fleet doctor` was **EXECUTED** on a scratch `FLEET_HOME` with the fork-steer shape rather than read, and the row that was gate 1's worst surface is now its best. Eight of ten injections caught **including both gate-1 survivors**, and one new pin caught a plant it was not written for (`dict(os.environ)` with no `.get`/`getenv`/subscript, caught by comparing attribute **touches** against classified reads) — **a pin built against the failure mode rather than against the mutant.** What blocked: the fix wave **enumerated five** surfaces stating how far the exemption reaches, **disclosed six**, and **left six denying it**; the actual population is at least **twelve**. Two of the six were `knowledge/INDEX.md` and `docs/NEXT-SESSION.md` — **the surfaces a fresh session opens to orient itself**, and the ones the wave's own new lesson entry names as the ones that hurt. That entry literally reads *"I wrote 'the ones that hurt are the RUNNING SURFACES' in this very entry, and then put a false sentence on two running surfaces"* — and then the wave fixed the doctor row and left the session-start index. The other blocking surfaces are the same shape: the identity-doctrine **pointer block** at `bin/fleet.py:2427`, four hundred lines above the corrected docstring, carrying both retracted claims verbatim and closing by telling the reader where the accounting lives — **so a reader tracing the doctrine hits the denial first and is told not to bother**; the **ceiling refusal message** at `:2960`, printed at the exact moment a supervisor is deciding what to believe about the ceiling, still promising *"only a session that does NOT hold the claim is exempt structurally"*, false of shipped code; and claim-nonce **§18.3**, where the ratified spec's DECISION LIST — **the skim path** — says the hole is closed two subsections above §18.4 saying it is not.

**ROOT CAUSE FOUND UPSTREAM OF THE BRANCH, AND IT IS STILL LIVE ON MAIN: THREE TRANSMISSIONS OF ONE UNCHECKED SENTENCE.** `docs/NEXT-SESSION.md:133-134` on main says candidate A *"reads the claim file, not the environment, so it needs no sound env channel"*. On main that sentence describes a **recommendation**, so it is a low-severity inaccuracy in a proposal document. It is **verbatim** the phrasing the branch promoted into a shipped **assertion**, which became gate 1's F3 and gate 2's B1. Proposal → review brief → shipped guarantee; the predecessor caught the middle hop and journaled it, and nobody had walked back to the first. **A false sentence in a PROPOSAL document is a defect with a delay fuse — it becomes true-looking the moment somebody builds what it describes.** *(A fourth copy of the same sentence is sitting in `knowledge/` — see the correction appended to `#2026-07-31-nd4c-ruled`.)*

**VERIFY THE LENS RATHER THAN RELAYING IT — AND EXPECT TO BE THE ONE WHO IS WRONG.** The lens asserted "neither file is in the fix diff"; the first check said otherwise, because `git diff main...w35/nd4c` shows `knowledge/INDEX.md` +1 and `docs/NEXT-SESSION.md` +13/-9. **Wrong scope, not a wrong lens**: those files are touched by `1dcd400`, the branch's FIRST commit, and `1e810f7` — the fix commit, seven files — touches neither. **The branch wrote the false claims in commit 1 and the fix wave never revisited them.** Same discipline demanded of the lens, applied to the lens; the answer was that the lens was right.

**PARKED, NOT FIXED, AND THE REASONING IS THE RECORD.** All four findings are text. All four are one-clause edits. **The lens even wrote the replacement clauses.** It is about a twenty-minute fix, and it was declined — because ESCALATE-beats-3rd-wave is a standing order, and because this repo's fix-waves-mint-defects record is **7/7**, *including, at gate 1 of this very branch, a text-only fix wave that minted the false doctor string it was sent to prevent*. **A third wave on the same branch is exactly the shape the doctrine forbids, and "it is only twenty minutes of text" is exactly the argument the record refutes.** Queued for the operator in the release note and **not** written into the decision slot, which was occupied by the predecessor's ND4(c) Option B raise (standing order: do not overwrite).

**A LENS OVERRODE A TRIGGER THE BRIEF ARMED, AND WAS RIGHT TO.** The brief said that if §18.4's replacement claim was itself wrong, that was a fresh MAJOR. The lens found the correction **scoped too widely** — a registry-keyed predicate genuinely IS required — but ruled the reader is not misled because the same paragraph names the cost, and filed it **non-blocking, against the instruction**. Correct call, and recorded as an override rather than quietly accepted. **A brief that pre-commits a severity is choosing the verdict.**

**LANE B (`w35/respawn-trunc`) GREEN — AND THE METHOD IS WHY.** All nine gate-1 findings were discharged by **RE-PLANTING each motivating mutant** rather than by reading the diff. Floors 3541/14/1 identical on both interpreters, receipts 68/68 zero warnings, citations AST-verified with `BAD: []`. The lens tested the carve-out flagged as the sharp edge and found it **genuinely sound** — `_fast_completion_sid` returns `None` whenever `short_id` is absent, and every pre-launch failure carries no `short_id`, so the no-restore branch is unreachable when nothing launched; it planted a pre-launch failure **with a plausible foreign outcome in the window** and the brief was restored. Then it found the gap **neither the supervisor nor the brief had framed**: the fix wave's own test docstring claims *both* `except` arms are pinned and only one is — deleting `restore_brief` from the `except BaseException` arm leaves the whole file green. Filed non-blocking, correctly: **the arm's behaviour is right, only its pin is missing** — and that distinction is what keeps a gate's severity vocabulary meaningful.

**LANE C (`w36/refute`) RED — AND B1 IS THE P1-7 DEFECT CLASS SURVIVING INSIDE THE COMMIT THAT EXISTS TO CLOSE IT.** `RegistryCorruptError` carries the **outcome** but not whether a rename was **attempted**, so the doctor row collapses *"never attempted"* and *"attempted and lost"* into one arm whose wording fits only the first. On a lost rename it prints *"this is not a corrupt registry to rename aside"* about a file containing `{ truncated`, and **directs the operator to fix what denies the READ in the same sentence that says the RENAME was denied**. And `_corrupt_error` asserts *"no artifact exists"* **without checking** — the author's own refutation of the review's glob-sniffing fix, inverted: it correctly refused to READ the glob for the outcome, then **ASSERTED a glob fact blind**. *A message keyed on the wrong thing is the defect the commit was written to close.* B2: mutant M10 makes the whole `sup-release` quarantined arm unreachable and 3599 still pass — **the test NAMED for that arm never calls it and reddens on a different assertion.**

**THE BIGGEST RISK FLAGGED CAME BACK CLEARED, AND THAT IS WORTH AS MUCH AS A FINDING.** The lane was briefed hard on whether editing `docs/specs/terminal-surface.md` was an author self-ratifying a widening of ratified D4, and whether CLAUDE.md's *"views never quarantine"* paragraph had been made false. Measured: `_quarantine_artifacts()` returns `[]` and never raises on absent `state/`, on `state/` as a FILE, on absent `FLEET_HOME`, and under a deny-RX ACL; **D4's normative text is BYTE-UNCHANGED**; the edit hits the schema comment and the `fleet.json missing` row, which the spec itself says is not the D4 row. **Not a self-ratified widening. CLAUDE.md's paragraph stands.** Record the cleared risks — an unrecorded clearance gets re-litigated by the next brief.

**A STAT BAR IS A TOTAL, NOT A PAIR.** The supervisor told lane C the commit was `+287/-50` on `bin/fleet.py`; it is `+239/-48`. **287 is the stat-bar total (239+48)** and 50 was the commit's all-files deletion count — **two different denominators fused into one figure**. The predecessor's headline lesson the wave before was a touched-line count relabelled as net-added, and this is the same transformation committed **one turn after quoting that lesson back at himself in his own boot checkpoint**. The correction went into the fix-wave brief, not only into the journal, **because the lane inherits the numbers** — a correction that lives only in the record you are writing does not reach the body you already briefed.

**"WHAT THIS BRIEF GOT WRONG" RETURNED A REAL ERROR IN ALL THREE BRIEFS — FOURTH WAVE RUNNING.** Lane A found the five-surface item was the *author's* census, short in **both** directions (twelve exist) — an instinct it credits to the supervisor's own hedge saying he had not verified it. Lane B corrected *"~80 lines"* to **ten** (80 is the distance to the dispatch `try`, not to the roster fetch) — **a number that had travelled gate-1 report → review brief → a SHIPPED CODE COMMENT**. Lane C corrected the `+287/-50`. **The section is not a courtesy, and hedging your own claim inside the brief is what arms it.**

**MERGE PRICING RE-MEASURED AGAINST CURRENT MAIN — AND THE HEADLINE NUMBER WAS LATER PROVED TO BE A NULL.** This wave recorded that *all three branches predict ZERO conflict hunks against main and zero against each other pairwise*, and — to its credit — **refused to treat that as good news**, because the three edit regions interleave across the whole file (734–14032, 157–14933, 723–14261), so the real cost is citation ROT, which no conflict count shows. Touched-line counts: nd4c 1331, respawn 1237, refute 631. **Wave 38 then re-measured those zeros and found two of the three were nulls emitted by a flag that does not exist at this git version — see `#2026-07-31-w38-merge-audit`.** The instinct (*a zero here is suspicious*) was right; the tool was silently answering a different question.

**THE STRUCTURAL CHANGE THIS WAVE MADE AND EXPLICITLY REFUSED TO BLESS.** It did not merge in-body: a `bin/fleet.py` merge is 50–65k here and it was at 143k when the first gate landed. Instead the expensive part — resolve, re-pin self-citations to fixpoint, floors on both interpreters, receipts — went to a **fenced merge-prep lane on a stage branch with no push**, with the supervisor verifying parents arithmetically and pushing. Estimated conversion: 50–65k in-body → ~10–15k of audit. **"IT IS UNPROVEN; the successor should judge it on the report quality, not adopt it because I did."** That framing is why wave 38's audit found the pattern's structural defect instead of inheriting the pattern.

**Smaller, measured.** *Expected is not measured*: the brief's baseline commit was already one behind at boot (`fe49597`, itself the predecessor's own closing journal entry — **a brief is written from the state its own closing entry then changes**, second consecutive wave). **Ancestry proved, identification pending**: `a7e1319` exists, is dated 2026-07-27 and IS an ancestor of main, but its subject is *"fix(identity): the §9 upgrade needs a COMPLETE registry, not a readable one"*, which is not self-evidently *"the glob gate"* the refute report calls it — **the whole refute verdict turns on that one commit being what it is said to be**, so the label was not briefed off. Idle lenses were **re-sent, not respawned**, so the injection recipes in their journals were reused rather than re-derived; both re-gate briefs stated the stopping rule plainly (second gate, ESCALATE-beats-3rd-wave, a second RED parks the branch) **because a lens that does not know a finding is terminal writes a different report than one that does**, and told the lens that *the parked hole being still open is NOT a finding* — a re-gate that re-reports a decision already made burns its budget on it. Doctor **3 FAIL**, not the two briefed: the brief described the decision slot as occupied elsewhere in its own text while listing only two.

## 2026-07-31 — wave 36: both lanes returned green about themselves, and both were red <a id="2026-07-31-w36-gate1"></a>

**THE lesson: a self-reported fault-injection table is a claim about the mutants the author thought of.** Two lanes had returned **GREEN** with detailed self-reported injection tables and neither had been reviewed; the previous wave handed them forward as *"merge on green"*. **One adversarial lens per branch, about forty-five minutes each, turned both RED** — lane B with 4 MAJOR and **seven mutants that stayed green**, lane A with 3 MAJOR. **Green was the lanes' own verdict on themselves**, and the gate paid for itself on the first try. Do not read a self-injection table as coverage; read it as an inventory of the author's imagination.

**LANE A (`w35/nd4c`) — RED, AND THE CODE IS FINE. WHAT BLOCKS IS THE TEXT.** The reviewer proved minimality *by construction* rather than by test count: the post-image differs from its pre-image on exactly one input class and no regression is reachable. Then: **F1 — a fork-steered claim-holder with no stamp is STILL EXEMPT from the 200k ceiling, reproduced at 500,000 tokens.** The claim file has no `retired_sids` and `_restamp_after_steer` writes the **registry record**, while the net that does bridge that window is reached only when a stamp is **present** — i.e. never in the 4-of-4 unstamped case that motivated the entire ruling. claim-nonce §18.4 records this honestly; **three other surfaces deny it, two of them RUNNING surfaces** — `fleet doctor` prints *"a missing stamp cannot exempt the supervisor claim-holder"* **on a body where it just did**. That is R2 (the named remedy that always fails) on a running surface, **third instance**, landing in the same commit whose own lesson entry says the ones that hurt are the running surfaces. **F2 — that doctor row is pinned only by a substring**: replace its sentence with an outright falsehood, or replace the remedy with *"no remedy exists at all, ignore it and carry on"*, and 3510/3515 stay green. **F3 — "no environment read" is FALSE**: the holder verdict depends on `CLAUDE_CODE_SESSION_ID`, **read one line below the comment denying it**, so **two ratified specs now describe one predicate incompatibly**.

**LANE B (`w35/respawn-trunc`) — RED, 4 MAJOR, seven mutants green.** Its findings are folded where they belong, in the lane's own entry — see `#2026-07-31-w35-brief-store` for the `write_brief`-outside-the-rollback-envelope defect (**a fix that reintroduces the defect class it repairs, at the same verb**) and for the four census shapes that each left the full suite green. Two gate-1 findings that entry does not carry, both worth the line: **the backstop's DEFINING property had no test at all** — swap identity for the *"materially shorter"* threshold its own docstring calls unsound, and 3522 stay green — and **deleting the brief write from `respawn` entirely was also green**. *A guard whose defining property is untested is a comment with a function signature.*

**A MERGE PRICE IS A DIFF AGAINST THE BASE, NEVER A SUM OF INTERMEDIATE DIFFS.** The campaign brief said main had moved `bin/fleet.py` by "+248 lines". Measured `0726914 → 2fd0d15`: **193 insertions / 37 deletions = 230 lines TOUCHED, net +156**, confirmed independently by line count (18974 → 19130 = +156). **248 is neither** — it is the sum of two per-merge touched-line counts (merge 1 = 100/9 = 109; merge 2 = 102/37 = 139; 109+139 = 248), which the predecessor had journalled correctly as *"moved by +109 and +139"*. **Two silent transformations stacked: touched-lines relabelled as net-added, then two OVERLAPPING diffs summed as if disjoint**, double-counting every line both merges touched. Neither transformation is visible in the resulting number.

**AND THE SAME CLASS, BY THE SUPERVISOR, IN THE SAME TURN.** Having just convicted the brief's 248 of being an inherited number nobody re-derived, he pasted lane A's own diff-figure table into its review brief **without running `git diff --numstat` against it**: four of five figures were wrong (165/23 not 166/22, 110/57 not 115/52, 51/32 not 55/28, 66/20 not 71/15; only `bin/fleet.py`'s +158/-127 was exact). Worse and load-bearing: he inherited the lane's own sentence — *"the predicate reads the CLAIM FILE, not env"* — and wrote it into the brief **as something to PROVE**. It is untrue, and F3 was found only because the same brief also told the reviewer to walk every path rather than accept the reading. **A brief that asks a reviewer to prove the author's claim has already chosen the verdict; the instruction that saved it was the one telling the reviewer to distrust the author.** Both lenses were told to find what the brief got wrong and both did — lane B five errors, lane A four. **That section is not a courtesy, it is the highest-yield paragraph in the brief.**

**TAKING NO MERGE WAS THE CALL, NOT A SHORTFALL — AND THE ARITHMETIC IS THE ARGUMENT.** The reviews landed at **157k**, in-band. A `bin/fleet.py` merge is measured at **50–65k** in this repo, which lands at **210–220k**, past the **200k hard ceiling**, with a real chance of stranding a half-resolved merge at the wall. Both branches were RED anyway and had to re-gate after their fix waves, so merging either would have been merging a branch under repair. What the successor got instead was the expensive thing: **both baselines measured, not inherited — 3579 passed / 14 skipped / 1 xfailed at `2fd0d15`, identical on py 3.13 (397.71s) and py 3.10 (374.62s)**. *Spending the last of a band on a measurement the successor would otherwise have to buy is a better trade than a merge that might not fit.*

**A FIX WAVE MAY NOT AMEND A RATIFIED PROPERTY.** Lane A's F1 has a real fix (b) — refuse when `_caller_holds_supervisor_claim` is true, after bare equality and before the stamp read, total in the safe direction so ND4(b) stays untouched — but it costs arm (c) being **ahead of any registry read**, which is RATIFIED and was the entire point of candidate A. The worker-safe option (a) — state the residual honestly on all four surfaces — was ordered, and (b) was **filed to the operator** rather than let a fix wave amend a ratified property by itself.

**Smaller, measured.** **SPAWN PRESERVES, third reproduction on new data**: both review briefs dispatched at full length plus exactly six preamble lines (47→53, 50→56). `permission-stalls` PASS, so the deny-fences hung nobody. Doctor 2 FAIL, neither taken. **The identity-witness remedy repair was VERIFIED rather than left for the reviewer to discover** — *"BLOCKED on an operator ruling"* is gone from the branch's `bin/fleet.py` (still live on main at `:2459` and `:9381`), so the lens spent its budget on whether the REPLACEMENT is correct; it is not complete, and that became F1. **Floor arithmetic was explicitly refused as inheritable**: both lanes measured their own baseline 3499/14/1 at `0726914` and predicted their own totals (A: 3510, B: 3522), while main sat at 3579 on a different base — **neither lane's total is the post-merge number.** And the inherited worktree record turned out to be **wrong in the supervisor's favour** — see the correction appended to `#2026-07-31-w35-green-and-wrong` below.

## 2026-07-31 — wave 35: the re-pin that went green and wrong <a id="2026-07-31-w35-green-and-wrong"></a>

**THE lesson: I auto-resolved a self-citation to the FIRST line matching its anchor text, the full suite went GREEN, and the citation was pointing at the wrong function.** The `_sweep_husks spells presence-only` citation was re-pinned to `:762` — an unrelated docstring near the top of `bin/fleet.py` that happens to contain the phrase *"registry present or not"* — when the real occurrence is `:8586`, inside `_sweep_husks` (which starts at 8543). 3579 tests passed on it. The anchor assertion for that site checks only *does the cited line contain this string*, with no span check tying it to the function the citation NAMES — so **the substring was the whole gate**. This is the 2026-07-28 finding (*a pin gated behind a magic substring pins the substring, not the property*) arriving on the CITATION side rather than the assertion side, and it was caught only because the line number looked implausible for the function being cited. **A re-pin script that takes the first grep hit is a citation generator, not a citation fixer.** Derive the target by the function it must land in; then check the number is inside that function's span, because green is not the property you wanted.

**The conflict count did not predict the re-pin count — third wave running — and this wave sharpens WHY: assertion ordering MASKS later citation rot.** Two merges, 19 conflict hunks, **every one of them a pure line-number self-citation with zero semantic content**, yet **20 distinct numbers** needed re-pinning and they surfaced over **six iterative pin runs**. Only 3 of merge 1's 7 were visible on the first run; `:12520` appeared only after those 3 were fixed, and `:10426`/`:15686` only after that. **A single red-or-green read of the citation pin file understates the work by design** — it stops at the first failing assertion, so *"the pins are red"* is a lower bound, never a census. Run it to fixpoint, and expect the number of rounds to exceed the number of conflicts.

**A stale branch's side can be corrupt where main's is merely stale.** `w34/mf-slice0` carried `cmd_respawn:6308-6256` — a BACKWARD range — where HEAD had `6302-6304`. Resolving toward HEAD was the right call on merit, not just by convention; *"resolve either side, run the pin, take what it prints"* is sound for numbers, but read the sides first, because one of them can be malformed in a way no pin catches.

**Both merges predicted EXACTLY, and the predictions were DERIVED rather than inherited.** Baseline re-measured at `67b95b9` (3499/14/1 — it agreed with wave 34's number, which makes it a measurement that agrees, not an inheritance). Merge 1 predicted 3518 by `--collect-only` on the new file (19 = 16 defs + one parametrized ×4, proving wave 34's "+19" by construction); merge 2 predicted 3579 from a whole-suite collect (3594 = 3533 + 61). Both hit exactly, identical on py 3.13 and py 3.10. Receipts 68/68, 0 failures 0 warnings, at both merges. `main` 0726914 → 67b95b9 → b881cfa → 467b72d, origin read back byte-identical at every step; both parents of both merges proved arithmetically rather than inferred from *"the merge succeeded"*.

**The respawn defect looks like DOCTRINE, not code — and possibly a three-day-old regression of an already-root-caused finding.** `cmd_respawn`'s **own docstring** says it prompts with *"the preamble + task (original, **truncated per the registry schema**, or `--task`'s override)"*; the schema cap is `"task": task[:200]`; and `dispatch_bg` then does `task_path.write_text(prompt_body)`, **overwriting the full task file with the short recomposition**. So the file is never read-then-reused — it is clobbered — and respawn never claimed otherwise in its own docstring. Meanwhile `lessons.md#2026-07-23-overnight-dogfood` **already root-caused "respawn/send truncation" to this same 200-char cap**. If that is the same mechanism, the finding was *diagnosed and never fixed*, and the sharper lesson is that **a root cause recorded in `knowledge/` is not a fix and nothing re-executes it** — the same surface that produced the 2026-07-30 "a dated knowledge number does not reproduce at its own commit" correction. **The spawn path was re-confirmed sound live and for free**: dispatch rewrote both wave-35 briefs with the preamble prepended and both survived at full length (116 and 129 lines). Discriminator reproduced on new data before the lane ran a test.

**A prediction that came true on schedule is stronger evidence than an observation.** The identity-witness LEAK returned at exactly the boot the predecessor said it would: it had named the leak's one-boot disappearance an artifact of the daemon dying with the login expiry, and wrote *"the next body dispatched under this daemon inherits my stamp and the leak returns."* It did — my `FLEET_WORKER` reads my predecessor's launch id, a dead record, while the registry resolves my sid correctly. **Worker-shaped in form, predecessor-shaped in fact**, so the §6.5 exemption still resolves and it is not a stop condition. The substitution model ratified 2026-07-30 now has a successful forward prediction behind it, not just an explanation.

**A FAIL row can be correct in its finding and dead in its remedy.** `doctor`'s identity-witness row says in its own text that the ND4(c) re-grounding is *"BLOCKED on an operator ruling"*. The operator ruled it on 2026-07-31, so the row now names a blocker that no longer exists — the **named-remedy-that-always-fails** defect (R2) forming a third time, from the other end: not a remedy that was never valid, but one that *expired*. **A ruling obsoletes every document that described the question as open**, which is the 2026-07-30 "a ratification lands in as many documents as name it" with the clock added.

**The kill ownership guard fired on three predecessor-spawned workers and that is the guard working.** `fleet kill` refused w34-rulings/w34-b6gate/w34-mf0 as *"1 worker(s) this session did not spawn"* and demanded `--yes`. Correct: a fresh incarnation inherits a roster it did not create, and confirming is the whole point. **`git worktree remove` is a TWO-step order** (kill the holder first) — and it has a third failure mode nobody had recorded: `w34-rulings` came back *"is not a working tree"* **while its directory still exists on disk**, i.e. deregistered but not deleted. A stranded tree is invisible to `git worktree list`, so the 27-list-only-worktree census undercounts by construction. Do not `rm` it blind — the recoverable-untracked-`*.md` rule applies.

**REFUSAL CLASS 5, found by committing it: passing checkpoint prose through a DOUBLE-QUOTED shell string EXECUTES every code span in it.** The closing checkpoint of this wave was handed to bash in double quotes. Journal prose here is dense with backticked code spans, and bash does command substitution inside double quotes — so three spans were **run instead of recorded**, and their stdout was spliced into the journal in their place. The `git worktree list` span injected ~30 lines of paths mid-sentence; the `fleet init` and `fleet kill` spans wrote to *stderr*, so they substituted as **empty**, leaving two sentences missing the exact verbs they were about (*"and&nbsp;&nbsp;REFUSED all three first"*). **A checkpoint is the single largest block of backtick-dense prose a supervisor ever emits, which makes it the worst possible thing to put in double quotes.** The fix is a channel that already exists: `sup-checkpoint` accepts an **`@file`** body and touches no shell at all. Same hazard, same fix, for every prose-taking verb — `send`, `spawn --task`, `sup-release --reason`. The known nonce refusal classes were about *piping* `sup-boot` through `head`/`tail`; this one is about *quoting*, and it is the more dangerous of the two because it executes rather than truncates.

**And the accident found something no design review would have: a continuity speed-bump caught a class of fault it was never built for.** The substituted `fleet init` was **REFUSED** by the claim-nonce §7 gate — *"a supervisor claim is held and fresh, and this call did not prove continuity on it"* — because a command substitution firing from the claim holder's own shell cannot present a generation it does not know it is running under. §7 is documented as a speed-bump, not a security boundary, and that remains true; but **its armed form is "prove you are the current generation", and an accident structurally cannot.** The sharpest part: `fleet init` was the *exact* remedy this supervisor had deliberately declined one minute earlier as a deploy-with-live-workers operator gate — declined by judgement, then attempted by accident, then refused mechanically. Blast radius verified by **effect, not by message**: `state/worker-settings.json` still dated 2026-07-30T08:12:18Z, unchanged. `fleet kill` exited on a missing `name` and killed nothing. **Zero state mutated; one journal entry damaged.** The damaged entry was **corrected by APPEND, never by edit** — this project already ruled that rewriting the record of an act to fix a lookup problem falsifies the record to save the index.

**CORRECTED 2026-07-31 (wave 36 measured it; the dated paragraph above is deliberately unedited).** The *"third failure mode"* of `git worktree remove` above is real in its symptom and **wrong in its shape**, and the error ran in the safe direction. `w34-rulings` did report *"is not a working tree"* while its directory still existed — but wave 36 measured the directory and found it **EMPTY**: zero entries by `find`, no `.git` file, no admin dir. `git cherry main w34/rulings` was likewise empty, 0 commits ahead, so the branch is fully contained in main. **`git worktree remove` had deleted the CONTENTS and failed only at DEREGISTRATION** — the reverse of "deregistered but not deleted", and nothing was ever at risk. It was `rmdir`'d. Two things survive the correction: **a stranded directory is still invisible to `git worktree list`, so a list-only census still undercounts by construction**, and *"do not `rm` it blind"* was still the right call at the time it was made — **the correction is what measuring costs, not evidence that the caution was wrong.**

## 2026-07-31 — wave 35 lane B: the truncation had a root cause on file for four months <a id="2026-07-31-w35-brief-store"></a>

**THE lesson: a defect with a root cause on file and no test is not fixed — it is documented, and it will bill you again.** `git log -S 'task[:200]' -- bin/fleet.py` returns exactly ONE commit: the original. The 200-char registry cap was root-caused on 2026-07-23 (*"respawn re-executes from that snapshot → guaranteed truncation for any real task"*), a fix candidate was filed in the same paragraph, and nothing was built. It had already bitten on 2026-07-09 (stupidbox), bit again that night, and bit wave 34 four months later. **The prior wave asked "is this a regression?" — the more useful question is "was it ever anything but a diagnosis?"**

**Established, not hypothesised, and the method is the transferable part.** The two surviving artifacts were reconstructed BYTE-EXACTLY: `_PREAMBLE_TEMPLATE.format(name, cwd, journal_target) + "\n" + registry["task"]`, run through `Path.write_text`'s win32 CRLF translation, is **sha256-identical** to both 784/783-byte files. That closes the question no amount of code-reading could: it is not *consistent with* the hypothesis, it *is* the output. **Reconstruct the artifact; do not merely explain it.**

**The brief's own arithmetic was a coincidence that discriminated, and it said so.** It offered `784 − 783 = 1`, matching the two worker names' 1-character length difference. Constructed: the name appears **3×** in the preamble (`{name}`, inside `cwd`, inside `journal_target`), so the name delta is 3 — and the shorter-named lane's snapshot carried 2 more newlines, i.e. 2 more CRLF bytes. `3 − 2 = 1`. Two unrelated errors cancelling to the expected answer. **The brief that flagged its own arithmetic as suspect was right to; a supervisor who marks their own shaky claim buys the next body a real check instead of an inherited one.**

**The root cause was not the cap — it was one file doing two jobs.** `state/tasks/<name>.md` was simultaneously the worker's BRIEF (the dispatch prompt is literally *"Read that file and follow it exactly"*, so it is the session's entire input) and the PER-DISPATCH PAYLOAD, overwritten unconditionally on every launch. So `respawn` was never the only destroyer: `send`'s fork-steer and `resume-limited` compose with an empty task (F6 — the message rides the mailbox) and replaced briefs with a preamble plus a mail block, and `archive` then filed that stub forward as the worker's `task.md`. **Raising the cap — the obvious fix, and the one filed in 2023's paragraph — fixes `respawn` alone and leaves three other paths and the next one added.** Fix taken: split the two jobs (`state/briefs/<name>.md`), keep the cap as PROVENANCE, and pin that it has no readers outside the brief store. The brief store sits **outside `tasks_dir()`** because `--add-dir tasks_dir()` pre-authorizes every task file for every worker, and a brief is a dispatch input. **State the narrow claim, not the strong one:** that removes the brief from the *granted* set, it does not make it unreachable — `bypass` is `--dangerously-skip-permissions` and is the supervisor's default mode, so nothing inside FLEET_HOME is protected "by construction". The real, bounded gain is under `accept`/`dontask`/`plan`.

**A census over one needle misses the paths that render their own body.** The reported site was `_cmd_respawn_native`. The SECOND reader of the same remnant was `_cmd_respawn_supervisor`, which rebuilds a supervisor *campaign* and hands it to `_dispatch_supervisor_body` — invisible from any census over `dispatch_bg` callers, exactly as `test_index_compose` already records for the compose census. **When you pin a census, pin the reader set too, and check whether the two sets are the same set.** They were not.

**A refusal that fires in the wrong place is worse than the defect it prevents.** Two ordering hazards found in self-review, both created by the fix itself: resolving the campaign *after* the release-steer and the dead-marking would have left a refusal with the old supervisor released, stopped and dead and no successor dispatched; and writing the brief between the pre-claim commit and the dispatch `try` would have stranded `{"status":"working","session_id":null}` on an unwritable brief store — the fix-wave-C1 class, reintroduced. **A new raise inherits every ordering constraint of the frame it lands in; find its rollback envelope before you add it.**

**The backstop is identity, not a threshold.** "Refuse when the new prompt is materially shorter than the file it clobbers" was the obvious guard and it is unsound both ways: it fires on a legitimately short `--task`, and it *misses* a truncation that a long carried journal padded back over the line. What survives is exact containment — the bytes `read_brief` returned appear contiguously in what is about to be written — plus a loud refusal naming `--task @<path>` when only a remnant survives. **A truncated brief must fail loudly, not dispatch silently.**

**Process, for the next lane:** the sentinel in the pin is the brief's LAST LINE. "The last line survived" reds for a cap, a slice, a marker misparse, an off-by-one and whatever gets invented next; "the file is big enough" survives all of them.

**A CENSUS IS ONLY NON-VACUOUS FOR THE SHAPES SOMEONE ACTUALLY PLANTED AGAINST IT — and this is the lesson the fix wave taught, by refuting the sentence that used to sit here.** The first version of this entry claimed the census was "tied by set-equality to a table of end-to-end DRIVERS, so a new dispatch path cannot be added without owing one." An adversarial reviewer planted four shapes and each left the **full suite green at 3522**: an **alias** (`_launch = dispatch_bg`, then `_launch(...)` — the literal `dispatch_bg(` never appears at a call); a **whitespace variant** (`dispatch_bg (name, …)`, legal Python, not the substring); a **second call inside a function already on the list** (set-equality over qualnames cannot see arity); and a **driver repointed at another path** (the table still listed the site, the driver never reached it). A plain new module-level `def` *did* red it — which is exactly the tell: it was non-vacuous for the one shape its author imagined. What the census needs, all three together and none sufficient alone: **derive by AST** (kills alias + whitespace), **compare COUNTS not sets** (kills the second call), and **make every driver prove it reached the site it is keyed under** (kills the repoint). Without the third the table is an allowlist with a citation on it.

**Corollary, cheap and general:** "N tests went red" is not "N things were wrong". This entry first reported the citation re-pin as *"9 self-citations"* because nine TESTS failed; the commit actually moves **28 distinct line numbers across 24 lines**. Count the artifacts, not the alarms.

**CORRECTED 2026-07-31 (wave 38 measured it at merge audit; the dated text above, including this entry's own title, is deliberately unedited).** **"Four months" is wrong: the window is 24 DAYS.** The repo's first commit is 2026-07-07, `task[:200]` shipped in the first commit that touches `bin/fleet.py` (`26565ba`, same day), and the defect was found 2026-07-31 — **four months predates the repo entirely**. Wave 38 caught this at merge audit *after* a green gate, in `skills/fleet/SKILL.md`, and fixed it there (`01a2469`) — **but the same figure was already sitting in `knowledge/`, in this entry's title and its first paragraph, and the SKILL.md fix did not sweep for it.** *A correction applied at the surface where the wrong number was noticed is not a correction of the number.* Re-derived here independently: `26565ba` 2026-07-07 → 2026-07-31 is 24 days. **Second, smaller:** the sentence *"`git log -S 'task[:200]' -- bin/fleet.py` returns exactly ONE commit: the original"* was true when written and returns **four** at this commit (`26565ba`, then `ee2a210`/`500d4c1`/`461cd02` from the fix itself, merged at `4459d9b`). The claim it supports — that the cap was introduced once and never regressed — still holds; the receipt no longer reproduces. **Nothing under `knowledge/` is re-executed by `tools/verify_receipts.py` (it covers `docs/specs/**` only), so a command pasted here decays silently: pin it to the commit it was run at, or expect to be the one who finds it stale.**

## 2026-07-31 — wave 34: `fleet respawn` ate the brief it was documented to reuse <a id="2026-07-31-w34-respawn-truncation"></a>

**THE lesson: `fleet respawn` SILENTLY TRUNCATED the task file it exists to reuse, and the discriminator is clean — the two RESPAWNED lanes' briefs were cut to 784 and 783 bytes mid-sentence, while the lane SPAWNED fresh in the same wave was intact at 8927.** The supervisor had READ both files at full length (102 and 79 lines) minutes earlier, at boot, before respawning anything — so the destruction happened AT RESPAWN, not before, and the boot instruction saying *"`fleet respawn w34-rulings` reuses them"* is **false of shipped code**. What each worker received was its header plus one sentence, cut mid-sentence at "based on main 581c48": no fences, no mission, no discipline section, no verdict format, **and no "WHAT THIS BRIEF GOT WRONG"**. A dispatch verb that destroys its own input is worse than one that refuses: the registry, the status table and the supervisor all report a healthy working worker.

**Both workers detected it themselves and independently recovered from `docs/OPERATOR-GATES.md` — and that is exactly what makes it dangerous.** The wave produced two green lanes, so the defect is invisible in every outcome the fleet records. *A failure mode that competent workers routinely route around is a failure mode nobody will ever see in a result.* Do not read this as mitigation: the recovery was possible only because the operator record is rich and both lanes were opus. A thinner record, or a cheaper tier, and the wave silently does the wrong work at full confidence. **Root cause NOT established** — owed to the next wave: the registry's task snapshot is known-capped, and `respawn` re-rendering the task file from a capped snapshot is the hypothesis, not the measurement. **Until it is fixed, dispatch by `spawn` with a freshly written task file; treat `respawn --task`-less reuse as unsafe.**

**A brief can be stale by ordering work that already shipped.** Lane 1 was ordered to re-ground §7's autoclean exemption to effect and repair the `:2174` GATED-row contradiction — both landed 2026-07-28, and the R2 `--nonce` mismatch was already fixed in code (`GATE_VERBS_ACCEPTING_NONCE`). What was genuinely owed was the *ratification*: three PROVISIONAL markers left undischarged. **The brief named the right file and the wrong verb tense.** The instruction that saved it was the one telling the worker to grep for the table rather than trust the line number — the same instruction, followed one step further, is what found the work already done.

**The spec that forbids the work it authorises.** The operator RATIFIED multi-fleet v8 ready-for-build on 2026-07-30 and the docket transcription landed it in `OPERATOR-GATES.md` and `lessons.md` — but not in the spec itself, whose `Status:` line still read **AWAITING OPERATOR RULING** and whose Sequencing item 2 still read *"No build slice dispatches before the operator rules."* **Read the spec-of-record alone and the builder dispatched against it is forbidden by it.** This is 2026-07-22's lesson arriving inverted (there the docket said no while the spec said yes) and it confirms the general form: **a ratification lands in as many documents as name it, and the transcription pass must enumerate them.**

**An owed follow-up from a ratification can be IMPOSSIBLE, and only implementing it finds out.** The identity ruling ordered ND4(c) re-grounded on "caller sid absent from the registry sid union". That predicate is **definitionally `IDENTITY_UNRESOLVED`, which ratified ND4(b) already governs with the opposite verdict** — one input, two ratified bindings, opposite outcomes, **and no discriminator exists**: the two bodies (c) must separate are the interface (no record) and a claim-holder whose record went missing, and *the missing record is the evidence that would separate them*. The old grounding escaped only because stamp-absence was an INDEPENDENT signal orthogonal to registry resolution. Found by two pinned tests going red, one carrying the receipt from the previous attempt (`fleet spawn` at 999,999 tokens, rc=0). **The worker stopped, priced three candidates, recommended A and did not take it** — all three amend ratified text. **The hole is LIVE and common, not edge**: a claim-holding supervisor whose daemon was cold-started unstamped is exempt from a HARD ceiling today, four of four measured bodies. Now documented as a hole instead of asserted as sound.

**A four-day-old branch's merge cost is not its diff — it is what main has since FIXED that the branch would UNDO.** `fix/b6-interface-release` gated **RED** and the operator's "merge on green" therefore did not fire. Killed three ways: a 4–0 council killed its `--interface` attestation on 2026-07-26; it is obsolete (tombstoning now lets *any* supervisor complete its own stand-down — councilor c4's exact objection); and **replaying it REGRESSES shipped code**, reverting B6 to the bare-sid fail-open compare main had fixed and deleting `_tombstone_releasing_body` + `_carry_handoff_pending_on_release`, wave 33's P1-4 fold from **two commits earlier**. All three cherry-pick conflicts were semantic. **The gate's value was not the verdict but the salvage**: main had **no supervisor-claim wedge doctor row at all**, so `fleet doctor` exited 0 on a fleet that could not boot a supervisor — ported, and porting found two defects in the original (it called `supervisor_claim_decision` *without the registry*, so doctor would answer the bare comparison while `sup-boot` answers the union — the two disagreeing silently on identical input, which is the one property the check exists to provide; and its remedy named `fleet sup-release --interface`, a flag that will not exist — **the R2 "named remedy that always fails" defect, 2nd instance, on the 3 a.m. surface**).

**The identity-witness LEAK vanished for one boot, and the reason is not a fix.** Seven consecutive sightings, then `doctor` all-PASS: the login expiry killed the daemon, and this supervisor's dispatch was the FIRST of the new daemon generation, so the donated env was its own. **Day-4's wedge-2 mechanism confirmed from the clean side** — the daemon donates the first dispatch's env — and the next body dispatched under that daemon inherits this one's stamp and the leak returns. *A defect that disappears when you restart the substrate has not been fixed; it has been re-seeded.*

**Smaller, measured:** `git worktree remove` is **denied while the idle worker session still holds the directory** — a landed lane cannot be swept until its body is killed, so "remove the worktree when the branch lands" is a two-step order, not one. The ruling-B bypass event fired on every push exactly as ratified (expected, not a violation, until the operator's settings change lands) — **7th measurement**. Floors 3499/14/1, **predicted before running and hit exactly on both interpreters**; receipts 68/68, rc=0.

## 2026-07-30 — The interface stress test: one session, seventeen supervisor waves, the multi-fleet gate marathon <a id="2026-07-30-interface-stress"></a>

**The operator's question was "can ONE overhead session clear a queue this size" and the honest answer is: YES under harness compaction, NO under the fleet's own rules.** The interface session ran ~7h (2026-07-29T23:00Z → 07-30T06:00Z), revived a dead fleet whose state had been wiped by a test escape, drove 17 supervisor incarnations (waves 11–27), landed **73 commits on main** (suite 2811→3200 tests, both floors green at every push), took the multi-fleet spec from a one-line stub to v8 through **seven adversarial dual-lens gate rounds (14 opus lens reports)**, and filed three operator gates. Its fleet-meter occupancy at the end: **471,055 tokens — 2.35× the 200k hard ceiling that kills a supervisor.** The interface survived only because the harness compacts context and ND4c structurally exempts it; a fleet-governed body doing this job would have needed at least three successions. **The three-tier design holds because the top tier cheats; write that down as a fact about the architecture, not a complaint.**

- **The binding constraint is supervisor boot cost, not interface capacity.** `sup-context` reads the WHOLE window (~85–110k at boot measured on four bodies, spread 24k — inherit nobody's number); real runway to the 150k trigger is ~40–65k. Six of the first ten waves merged nothing — boot+harvest ate the band. The fix that 4x'd throughput: **dispatch in the first 30k, merge before reading, budget a `bin/fleet.py` merge at ~60–65k and docs-only at ~35k.** After wave 15 nearly every wave merged.
- **Short interface-authored briefs beat supervisor handoffs.** Two waves released without successor briefs; the interface-authored one-page act-first replacements worked as well as the 300-line inherited ones. The "WHAT THIS BRIEF GOT WRONG" closer paid in ~every wave — supervisors found real errors in 5+ of my briefs, including one I planted and two I didn't.
- **The gate loop does not terminate itself.** Seven rounds, every verdict GATING — but round-over-round the kill surface shrank from architecture (r1–2) to rules (r4–5) to enumeration mechanics + shipped-defect discoveries (r6–7), and three contested folds were vindicated by later failed attacks. **An adversarial opus lens at this calibration always returns findings; the terminus is the operator docket, and the spec's Sequencing must say so** (it now does). Corollary: gate rounds are cheap relative to their yield — round 7 alone found two shipped defects (`['--fleet-home','H','autoclean']` silently drops the flag; `doctor --repair` unenumerated anywhere).
- **Design deltas that survived:** effect-grounded beats configuration-grounded every single round (miss-refusal, forensic-refusal, arming-on-registration, class predicates all died; registry-hit-as-evidence, verb-effect tiers, fail-armed indeterminacy all survived). Every AMBIENT selection channel (env, marker, walk-up) died the same death; the explicit ones (flag, baked argv, registry lookup) survived. **The oracle consult between rounds 2 and 3 was the highest-leverage single step** — it prevented a third blind draft and its failure-mode enumeration was still being confirmed by lenses four rounds later.
- **Fence lessons, twice paid:** a read-only lens fenced by `dontask` mode was denied its own report deliverable (recovered via `fleet result` only); fence by denying READS and PUSH, never writes — and **re-derive the fence enumeration from the filesystem** (steer said 15 files; disk had 19). A lens told "the brief's claim is hearsay, refute it" returned a refutation, a re-derivation, and a bonus positive (CONFIRM-A: sid-donation closed safe by counting) — disclosing beats fencing cleanly.
- **`out=` is wrong evidence, not weak evidence** — measured 9.5× and 100× under actual result size on two workers. Verify the report file on disk.
- **Recovered incidents:** the 22:58:39Z state wipe (fixture sid `1111…`; quarantine-rename recovery; forensics + isolation pins now in spec v8 §7); two swallowed outcome records recovered from `hook-errors.log` (class closed by `869ead8` same day); a red main I caused myself (spec unclassified in `test_receipts.py` — the classification test doing its job on its author); a stochastic network outage (retry per-attempt, read no trend from failures OR successes).
- **Operator gates opened this session (all awaiting Altai):** multi-fleet v8 ratification; the 2026-07-27 identity clause falsification (+CONFIRM-A addendum); §7 exemption envelope (pre-existing); branch-protection-vs-merge-doctrine in the sup-decision slot (4 measured bypass reproductions). Nothing was narrowed while any of them waited.

## 2026-07-08 — Self-build turn-one decisions (manager)

Decisions recorded per PLAN §0.5 (dated, on-disk, not session memory):
- **POSIX exercise box (C4):** Altai picked the **exPardus dev server 192.168.1.202** (real Linux, SSH-reachable) over the WSL fallback. `port-posix-smoke` dispatches there.
- **Budget:** Altai on **Claude Max 20x plan** — approved a **higher/generous cap** for the C1+C2 readiness boundary (declined the ~$330 sum-of-caps ceiling as a limit; treat caps as circuit-breakers, not a starved envelope). Per-task caps stay at §0.4 class defaults for the §0.1.8 2×-cap kill rule.
- **New feature — usage-limit resilience (plan ID UL1):** Altai requested "a way for the fleet to restart itself if it hits a usage limit for a 5 hour or weekly session." No review-doc finding exists; manager authored the single binding input `docs/reviews/USAGE-LIMIT-RESILIENCE-INTENT-2026-07-08.md`. **Folded into C1** as a new Wave-1A chain link `spec-amend-4-usagelimit` (sequential last, SPEC.md single-writer) and into **C2** as hardening-kernel item 11. Surfaced to Altai for ratification at the C1 checkpoint (touchpoint 4).
- **Dirty tree:** `workflows/idea-forge.workflow.js` (ROUNDS 3→2) committed at Altai's instruction; tree clean before C1.
- **Second new feature — worker subagents (plan ID UL2):** Altai requested (mid-C1, 2026-07-08) that fleet workers be able to use their own subagents (Task/Agent tool). No review-doc finding; manager authored binding input `docs/reviews/WORKER-SUBAGENTS-INTENT-2026-07-08.md`. **Folded into C1** as SPEC.md link `spec-amend-5-subagents` (sequential after the 1D SPEC.md fix wave). Key hazard: `fleet doctor`'s `_doctor_check_claude_agents` must not false-positive a worker's legitimate subagents; permission-mode inheritance under bypass is a security note. Likely C1 documentation-only (subagents are native Claude Code) — C2 code only if the probe shows a launch flag / doctor exemption is needed. Ratified with UL1 at the C1 checkpoint.

## 2026-07-07 — Campaign 0: building fleet itself (subagent-driven, 30+ agents)

The fleet CLI was built by a multi-agent pipeline (implementer → spec reviewer + adversarial reviewer in parallel → supervisor-adjudicator → fixer → re-review, per task). Lessons that transfer to running fleet campaigns:

**What worked**
- Adversarial reviewers with repro authority found what spec reviewers approved: 4 of 5 tasks got "Approved" from the spec lens while the adversarial lens returned proven BREAKS (lock races, path traversal, stdin pipe deadlock, silent hook death on spaced paths). Always run both lenses on anything that manages processes or files.
- Live smoke beats unit tests for stream-json assumptions: 340 green unit tests coexisted with three High/Medium bugs only a real haiku worker exposed (hook events land AFTER the result line; kill-dead resurrected by recompute; cost is per-invocation on --resume). Budget ~$0.10 of haiku time at the end of any campaign that touches worker plumbing.
- Supervisor-adjudicator agents (read both reviews, emit ONE binding fix list with exact semantics) kept fixers from re-interpreting findings. Fix lists anchored to function roles, not line numbers, survived concurrent refactors.
- Disjoint-file parallelism is safe (hooks + docs + core in parallel, exact-path staging, index.lock retry); same-file parallelism is not — sequence all bin/fleet.py work.

**What stalled**
- Same-file fix waves queued behind implementers repeatedly; the file-ownership handoff was the pipeline's bottleneck.
- One fixer died mid-run on an API error AFTER committing — always `git log` before re-dispatching "failed" work.
- Every fix wave introduced ~1 new issue (lock-hold sleep, unconditional re-claim); re-review after EVERY wave, no matter how small.

**Fleet-specific operational facts learned live**
- The Stop-block race is real: a `send` landing in the last seconds of a turn queues to the mailbox instead of same-turn delivery — this is by design (universal drain rule); check `idle+mail` in status, don't assume same-turn.
- `dead` is sticky (operator kill survives recompute); `respawn` is the only recovery lever. Pre-fix records persisted as idle may need a re-kill.
- Cost per worker = cost_baseline (respawn carry) + sum of result events in the current log.

**Rigorous-testing addendum (same campaign)**
- Multi-process stress found what thread-based unit tests could not: the spawn commit-lock timeout zombie only appears under real OS-process contention with real PowerShell probe latency. Any future concurrency change to fleet.py should re-run the stress harness (kept at the session scratchpad's `stress/`; the fake-claude stub must be a compiled .exe — a .cmd stub hangs under launch_turn's pipe shape).
- Fuzzing paid off at the parser layer, not the hooks: hooks survived 1000 hostile inputs untouched; the registry/cost parsers crashed on shape mismatches. Fuzz the parsers of any new event/registry field.
- `--max-budget-usd` overshoots ~3x on tiny caps — circuit breaker, not a ceiling.
- Stop-block mid-turn continuation PROVEN live: time a send after the last tool call, before Stop fires.

## 2026-07-08 — Campaign 1: haiku demo (3 workers, full lifecycle showcase)

First real end-to-end run on the finished CLI. Spawn → status → peek → mid-turn send → background wait → result → respawn → doctor → kill/clean, all green, total spend ~$0.21 haiku.

**What worked**
- Batched 3 spawns in one message; all landed in ~seconds, no lock contention.
- Mid-turn steering delivered and OBEYED: `send` to a working haiku poet ("make third haiku about the manager") queued to mailbox, consumed at next tool boundary, worker revised exactly the targeted item and confirmed in its final message. Steering prompt pattern worth reusing: prefix "Steering update from manager:" + one concrete, verifiable change.
- Task prompts ending in "Final message = X" made `result` output clean and directly consumable — haiku workers follow output-contract phrasing well.
- `fleet doctor` 13/13 PASS on first real campaign; `wt` absent is a known-fine fallback (detached PowerShell attach).

**What to know**
- `fleet` is NOT on PATH in the manager's PowerShell — call `C:\proga\claude-fleet\bin\fleet.cmd` by full path (or add bin to PATH).
- Respawn on an already-DONE task re-executes it rather than no-op'ing: respawned poet read its journal but rewrote poems.txt from scratch, losing the steered revision. Journal carries context, not idempotence — don't respawn a completed worker expecting state preservation; respawn is for stuck/long-context workers only.
- Haiku workers at these task sizes finish in under a minute — `status` right after arming `wait` often already shows idle; results can be harvested before the wait notification lands.

## 2026-07-08 — Campaign 1: SPEC v2.1 amendment pass (~15 workers, ~$60)

<!-- anchor: 2026-07-08-c1 -->
Folded every confirmed blocker/major from `docs/reviews/SPEC-REVIEW-2026-07-08.md` into
`docs/SPEC.md`, `ROADMAP.md`, and 7 stubs. Doc-only, main repo, no merge gate. Waves:
1A (4-link sequential SPEC.md chain: state→schema→testing→usagelimit) →
1B (7 parallel stub-injectors) → 1C (split adversarial review: core ∥ stubs) →
1D (7 fixes to original builders via `fleet send` + re-review + 3 LOW polish) →
1E (manager verification). Two features folded mid-campaign at Altai's request:
UL1 (usage-limit park+resume) and UL2 (worker subagents).

**Process changes — amend `knowledge/playbooks/campaign-template.md` (do these next campaign)**

1. **Descriptive-vs-prescriptive labeling in spec-amendment task files (the #1 C1 lesson).**
   Wave-1C's 3 majors all reduced to ONE root cause: the amendment folded BOTH
   already-shipped-behavior findings (DESCRIPTIVE — "bring spec to code") AND
   not-yet-built fixes (PRESCRIPTIVE — the fix is a future kernel) under a header
   claiming "no code change proposed / correct code passes." A build/verify session
   then can't tell which invariants are enforced-today vs TODO.
   **Amendment:** every spec-amendment task file must instruct the worker to tag each
   folded finding `[UNBUILT — owned by <kernel/campaign>]` when the fix is not yet in
   shipped code, and to split any "required regressions" list into "passes today" vs
   "pins unbuilt fixes." Instructing this UPFRONT would have prevented the entire 1D
   fix wave. This is the amendment to the task-file convention.

2. **Doc-adapted chain-link truth gate.** PLAN §0.1.9's truth gate assumes `pytest`;
   C1 was doc-only. Working substitute:
   (a) **anchor+witness grep per finding** — presence of the `<!-- F## -->` anchor AND
       the designated witness sentence (anchor presence alone is content-blind); and
   (b) **manager spot-checks any spec-vs-code CLAIM against `bin/fleet.py`** by grepping
       the named function anchor BEFORE ordering a fix. In C1 this confirmed CM1/CM2 were
       real before dispatch, and caught that a "code bug" complaint was actually
       correct-but-C2-deferred.
   Add this as the doc-campaign variant of the truth gate in campaign-template.md.

**Operational facts (reusable)**

- **Mid-campaign feature folding pattern:** a feature request with NO review-doc finding →
  manager authors a single binding intent note (`docs/reviews/*-INTENT-*.md`, mirroring
  §0.2.4's one-binding-input rule) and routes it through the same spec→review→fix gate as
  a real finding. Used for UL1 + UL2; both passed review clean/sound. Reusable.
- **`fleet result` crashes on Windows console (cp1252) when output contains unicode**
  (→ arrows): `'charmap' codec can't encode`. Workaround: `PYTHONIOENCODING=utf-8`.
  Real `bin/fleet.py` bug (stdout encoding), C2-worktree fix candidate — logged in
  `knowledge/projects/claude-fleet.md` (c1-playbook owns that file; cross-ref).
- **7-wide parallel disjoint-file commits: zero index.lock casualties** — confirms the
  Campaign-0 disjoint-file-parallelism lesson holds at 7 concurrent workers with
  exact-path staging + retry.
- **Cost-watch cadence worked:** `fleet wait --timeout 300` poll loop + `fleet peek`
  proxies caught no runaways; a timeout wake landing on an "essentially done, committing"
  worker just needs a short re-arm to catch completion. Note: resume turns are
  budget-UNCAPPED until `harden-fleet-b` (M5) — small doc fixes were low-risk here.
- **UL2 outcome:** worker subagents are default-on (native Task/Agent tool, no launch
  flag); ephemeral subagents don't register in `claude agents --json`, so the doctor
  check never false-positives them — C1 documentation-only, no C2 code owed.

- **UL1 + UL2 RATIFIED** by Altai at the C1 checkpoint (2026-07-08) — both approved as specced; C2 greenlit. UL1 kernel builds in C2 (item 11); UL2 was documentation-only (no C2 code owed).

## 2026-07-09 — Campaign 2: harness + hardening kernels (11 kernels, UL1, 506 tests)

<!-- anchor: 2026-07-09-c2 -->
First **code** campaign that modifies the fleet itself. Built in worktree `c2-hardening`,
merged to `fleet-impl`. Deliverable: live-integration harness (tier-3, real haiku worker)
+ 11 hardening kernels including UL1 (usage-limit park+resume) and the token-ceiling /
rotation machinery. Waves: 2A (`harness-live` tier-3 harness ∥ `harden-hooks` hook
kernels) → 2A-close gate (FLEET_LIVE hook-source=worktree) → 2B fleet.py same-file chain
a(kernels 1/2/4/5)→b(budget persistence)→c(F9 send-lock/mail-events + F15 three-way probe)
→d(token-ceiling + rotation + live demo)→e(UL1 usage-limit) → 2C reviews (code ∥
adversarial) → 2D fix wave (2 real breaks: **resume-limited double-launch HIGH**, **UL1
false-park MED**) → 2E merge gate. **506 unit/hook tests + a live tier.** ~$70 worker spend
+ ~$2 haiku. **The checkpoint claim "the fleet can safely modify itself" is EARNED — the
full revert path was exercised end-to-end (see below).**

**What worked**
- The merge-gate **revert-on-red rule fired for real and worked**: merge → post-merge gate
  RED → `git revert -m 1 <merge>` restored the known-good live install with zero downtime
  → fixed in the worktree → re-merged green. First live proof the revert lever is not
  theoretical. The known-good install stayed usable the entire time.
- Splitting 2B into a **5-link same-file chain with the per-link truth gate** (§4) kept the
  ~3000-line fleet.py rewrite from becoming one un-reviewable diff; each link ran pytest
  green in the worktree before the next dispatched.
- Dual-lens review (2C) again earned its keep: the adversarial lens found BOTH 2D breaks
  (double-launch, false-park) that the conformance lens passed.

**What stalled**
- **A one-line test-scoping bug forced a full revert+refix+re-merge.** `test_live_ceiling_demo.py`
  hard-asserted `HOOK_SOURCE == "worktree"` — correct for its pre-merge purpose, but it
  FAILED (not skipped) under the merge gate's default `FLEET_HOOK_SOURCE=main`, turning the
  post-merge gate RED. → process change #1.
- **The live harness is non-idempotent on the tracked fixture corpus.** Every `FLEET_LIVE`
  run re-captured `tests/fixtures/streams/*.jsonl`, dirtying the tree, so every git-state
  gate check needed `git checkout -- tests/fixtures/streams/` first. → process change #2.
- **Two fix turns died to Anthropic API 529 (Overloaded) mid-turn.** Worker went idle, cost
  stayed FROZEN, no commit, journal unchanged — and `fleet result` itself 529'd. "Is it
  done?" is answerable ONLY by `git log` in the worktree. → process change #3.
- **Re-merging after a reverted merge is not a plain re-merge** (git thinks the branch is
  already merged → no-op). Needs `git revert <the-revert>` then `git merge <branch>`. → #4.

**Process changes — amend `knowledge/playbooks/campaign-template.md` (realized as v1.2 amendments)**

1. **Worktree-only live demo tests MUST `pytest.skip` (not hard-assert) under the merge-gate
   default `FLEET_HOOK_SOURCE=main`** — verify collect-and-skip in the pre-merge default run.
   Added to the merge-gate checklist (§5) AND the task-file convention for any hook-source-
   specific live demo (§2). This one-line scoping miss cost a full revert cycle.
2. **Restore the committed fixture corpus (`git checkout -- tests/fixtures/streams/`) before
   every pre/post-merge git-state check** — the live harness is non-idempotent on the corpus.
   Added to §5. **Backlog (Phase-6/quality):** harness should write captured streams to a
   temp dir unless `FLEET_CAPTURE_CORPUS=1` is set, so verification runs stop mutating the
   tracked corpus.
3. **A worker turn is "done" only if `git log` in its worktree shows the expected commit** —
   `fleet result`/`cost_usd` are unreliable when the turn errored (529/API). Re-sending a
   git-committed fix task is safe; revert any partial uncommitted artifacts (e.g. dirtied
   fixtures) before re-send. Added to the §3(g) verification checkpoint.
4. **Re-merge after a reverted merge = `git revert <the-revert>` then `git merge <branch>`**
   (revert-the-revert restores the reverted code; the plain merge then picks up the new fix
   commit; a bare re-merge is a no-op). Documented as a merge-gate revert-path sequence in §5.

**Operational facts (reusable)**
- The **`fleet result`/`peek` cp1252 unicode crash (from C1) is STILL live** — C2 did not fix
  it (out of scope). Keep the `PYTHONIOENCODING=utf-8` workaround (see projects/claude-fleet.md).
- **New standing post-merge live checks:** FLEET_LIVE integration tier (default=main hooks),
  `fleet init` re-render when the template changes (PostCompact hook was added), `fleet doctor`
  gained hook-registration / unreadable-starttime / limited-parks / ceiling-file-sweep /
  hook-errors checks, and live hook-smoke.
- **New CLI surface:** `fleet resume-limited`; `--token-ceiling` on spawn/respawn;
  `over_budget` / `over_ceiling` / `limited` statuses; spawn-time model echo.

## 2026-07-09 — External dogfood #1: `stupidbox` (first non-fleet campaign, soak fuel)

<!-- anchor: 2026-07-09-dogfood-stupidbox -->
First real external campaign: built a throwaway useless CLI (`C:\proga\stupidbox`) from
scratch with the fleet. Altai's steer mid-session: not the polymarket repo — "make
something simple and stupid." 5 workers + 2 respawns, all haiku/`bypass`, ~$0.5 total.
Wave 1: 4 module workers in parallel on disjoint files (`cow`/`fortune`/`roll`/`hodor`).
Wave 2: 1 README worker, respawned twice. Full lifecycle exercised: batch spawn,
mid-turn steer, respawn, background waits, manager verification, doctor-clean close.
See `knowledge/projects/stupidbox.md`.

**VERDICT — fleet works in the wild (2026-07-09).** This was the first campaign on a
project the fleet did not build and whose repo it had never seen. It ran end-to-end with
no manual intervention: 11 spawns + 2 respawns, 8 shipped commands, every worker committed
its own disjoint file, zero `index.lock` collisions, zero lost turns, zero incidents,
`fleet doctor` 17/17 at every close. **The tool is usable for real day-to-day work, not
just self-build.** What remains before Soak Gate 1 is *not* capability — it is the
usage floor (≥15 spawns across ≥3 distinct days) and Altai's signature. Nothing observed
in this campaign argues against the gate; the only defects found were ergonomic (respawn
task-snapshot staleness) and both had documented workarounds.

**What worked**
- **Dispatcher-first scaffold = clean N-wide parallelism.** Manager writes
  `__main__.py` referencing all command names upfront (lazy import + "not built yet"
  fallback); each worker owns exactly one module file. Zero shared-file contention;
  4 concurrent commits, zero `index.lock`. Reusable pattern for "build N independent
  things in parallel in a fresh repo."
- **Mid-turn steer landed and was obeyed again** (`cow` got a `--think` thought-bubble
  flag added mid-turn; worker also bumped its own self-test count to 3/3). Steering
  prompt pattern "Steering update from manager: <one concrete verifiable change>" holds.
- **Haiku on tiny tasks is ~free** ($0.09–0.13/worker); `bypass` correct for a throwaway
  repo with no network/secrets/processes.

**What stalled / friction found (the process change)**
- **`fleet respawn <name>` IGNORES edits to `state/tasks/<name>.md`.** Verified against
  `cmd_respawn` (bin/fleet.py:3029): respawn re-prompts with the **original task snapshot
  stored in the registry (TRUNCATED per schema), or a `--task` override** — it does NOT
  re-read the task file. I edited the readme task file (added banner + Philosophy section)
  and a plain `respawn` silently regenerated the OLD scope. Passing
  `fleet respawn sb-readme --task @state/tasks/sb-readme.md --force` picked up the edit
  correctly (and confirms respawn `--task` DOES accept `@file` expansion).
  → **process change (campaign-template §3f + respawn note): to change a worker's scope on
  respawn, always re-pass `--task @file`; never edit the task file expecting respawn to see
  it. For any long `@file` task, re-pass `--task @file` on respawn anyway — the registry
  stores the task TRUNCATED, so a bare respawn can lose task detail.**

**Operational facts (reusable)**
- **The single system-wide fleet install means a concurrent foreign campaign shows up in
  your `status`/`doctor`.** Mid-close, two workers I did not spawn (`plan3-t2-rtds`,
  `plan3-t3-resolver`) appeared — a separate live pmbot Rust-TDD campaign in isolated
  worktrees (`C:\proga\pmbot-wt-*`). Not a bug; doctor stayed 17/17. **A manager must
  distinguish own-workers from foreign ones by name-prefix/dir before any bulk
  `kill`/`clean`** — never blanket-retire the registry. Retire only names you spawned.
- **Soak Gate 1 usage — Day 1 (2026-07-09):** two waves on `stupidbox` (built an 8-command
  useless CLI): **12 launches total** (11 spawns + 2 respawns; sb-cow/fortune/roll/hodor +
  sb-readme×3 launches, then sb2-8ball/yoda/slap/mock + sb2-readme). Doctor 17/17 clean at
  every close, 0 incidents. Also coexisted cleanly with a concurrent foreign campaign
  (pmbot Campaign 3) that ran and retired in the shared install during the session. Need
  ≥15 spawns across **≥3 distinct days**; this is day 1 of 3. (Sign-off stays Altai's — this
  only accrues the floor; a single busy day cannot satisfy the ≥3-distinct-days requirement.)

## 2026-07-09-c3 — Campaign 3 (pmbot Plan-3, foreign manager: parallel Rust TDD via worktrees)

A separate manager session (the pmbot dev) used the shared fleet to run 2 Plan-3 Rust TDD
tasks in PARALLEL, each in its own **git worktree** of `polymarket_experimenting`, then merged
back. This is the reusable pattern for parallelizing collision-prone tasks (shared `main.rs`
etc.): `git worktree add -b <br> ../wt HEAD` per task → `fleet spawn --dir <wt> --mode bypass`
→ `fleet wait --all` (background) → review → merge → `git worktree remove` + `branch -d` + `kill`.

- **What worked:** both workers green first turn (6 + 5 tests), ~$1.7 each (cold Rust build
  dominates, not tokens). Both used their OWN subagents to read the Python source and confirm a
  byte-for-byte port; an independent reviewer agent agreed (0 findings). Merge: one ff + one clean
  3-way auto-merge on `main.rs`. Merged-trunk re-verify: 86 tests, clippy clean.
- **`bypass` mode fit:** trusted known repo + TDD + cargo/git only → zero permission friction,
  correct choice. Budget $6/worker was right for cold builds.
- **Worker judgment win:** the "don't touch main.rs" instruction was correctly overridden by the
  worker when adding an enum variant forced a no-op `match` arm (compile necessity). Task files
  should anticipate this rather than forbid it.
- **New project file:** `knowledge/projects/pmbot.md` (per-crate cargo, frozen kernel, collector.db
  rule, worktree recipe, cold-build cost).
- **Shared-fleet etiquette confirmed from the other side:** two managers ran concurrently on one
  install with zero interference because each retired only its own name-prefixed workers
  (`plan3-*` vs `sb-*`). The name-prefix discipline is load-bearing — hold it.

## 2026-07-09-c4 — Campaign 4 (pmbot Plan 3 complete: 5 workers, ~$22, safety-critical Rust)

Finished a 12-task safety-critical plan (live-order kill-switch for a real-money trading bot) using
worktree-per-task fleet workers + adversarial in-session reviewers. All merged; 121 + 35 tests green.

**The headline lesson: builders build, adversaries find. Separate the roles.**
Five real bugs shipped past green tests AND past a prior code review. Every single one was caught by an
*adversarial reviewer with repro authority* or by a worker whose task forced it down a new code path —
never by the builder, never by the suite:
- `LiveClob::submit` hardcoded `side=Buy`, ignoring the order's side. Survived 75 tests + a whole-branch
  opus review because nothing in the codebase ever *sold*. Found only when a new worker needed a sell.
- The dead-man switch self-tripped at boot and latched dead (a permanent no-op) — its own unit tests all
  called `on_beat` before polling, so none could see it.
- An affordability guard the plan called "the only bound" ignored cost committed in other open windows.
- Fixing (2) then introduced a *false-negative* twin. Knife-edge fixes create knife-edge bugs.

**Fault-inject your tests or they are theater.** The strongest evidence produced all campaign: a reviewer
BROKE production four ways and confirmed each break turned the relevant test red. Add this to every
review brief for safety-critical code: *"break the production behavior N ways; report any test that stays
green."* A test that stays green when you break what it tests is a CRITICAL finding. This converted "the
drill passes" into "the drill is evidence."

**Prompt patterns that worked (reuse verbatim):**
- Reviewer brief opens with the project's own base rate: *"every prior fix wave introduced ~1 new issue;
  assume this one did; find it."* A generic "review this" reviewer returned a bare "No issues" on a diff
  that provably contained a bug. Hostile framing + repro authority + "no bare 'No issues', say so
  per-item" produced 4 real findings.
- Worker briefs that name the TRAP explicitly ("caps are frozen at construction while bankroll shrinks —
  do NOT rebuild the governor mid-flight, it discards open-window exposure") got it right first try.
- Worker briefs must say *"the plan's snippets are indicative, not authoritative — read the real type
  definitions"* whenever the plan touches an external SDK. Both SDK-facing workers found the plan wrong.
- Tell workers to dispatch their OWN subagents to read the source-of-truth file before porting/writing.
  Cheap, and it made ports byte-accurate on the first attempt.

**Worker judgment is real.** A worker told "do not touch main.rs" correctly overrode that when adding an
enum variant forced a new `match` arm. Another rejected the plan's own field semantics after checking a
live API. Write briefs with intent + invariants, not just prohibitions.

**Ops:** `fleet result` still truncates long outputs even with `PYTHONIOENCODING=utf-8` — for anything
substantive, read the worker's commits (`git log`/`git show` in its worktree) instead of `result`. And an
API-529 death mid-turn AFTER commits is invisible from `result`; `git log` is the only truth a turn landed
(Campaign 0 said this; it happened again, exactly as predicted).

## 2026-07-09 — a read-only slash command deleted five workers

**What happened.** `commands/status.md` shipped with `allowed-tools: 'Bash(fleet:*)'`. That glob matches
`fleet kill` and `fleet clean`, not just `fleet status`. A throwaway `claude -p "/fleet:status"` probe run
during the Phase-1.6 build saw four dead workers, judged them untidy, and — entirely within the permissions
we granted it — killed the one `working` worker and cleaned all five, deleting their journals and logs.
Recovered from `state/events.jsonl`: session ids are durable, so transcripts survive `fleet clean`.

**The lesson is not "models are reckless."** The model did exactly what it was permitted to do, and it
volunteered the cleanup because our own `status.md` prose mentioned dead workers. The lesson is that a
permission glob is a capability grant, and `Bash(fleet:*)` grants the destructive half of the CLI to a
command whose whole purpose is to be read-only.

- **Grant the subcommand, never the CLI.** `Bash(fleet status:*)`, not `Bash(fleet:*)`. Pinned by
  `tests/test_terminal_surface.py::TestCommandFiles::test_read_only_grants_reach_no_destructive_subcommand`.
- **`fleet clean` is irreversible and journals are the only record of what a worker learned.** The registry
  entry, logs and journal go; only the claude session survives, resumable by sid from `events.jsonl`.
- **Two guards are not one guard.** We had already ruled that mutating commands must not use inline `` !`cmd` ``
  exec (spec D3). That guard was intact. The allowlist on the *read-only* commands let the same destructive
  capability in through the back door. When you write a rule about one mechanism, check whether the other
  mechanism reaching the same capability is still open.
- **`events.jsonl` is the recovery path.** It is append-only and `fleet clean` does not touch it. Every
  `spawned`/`respawned` event carries `session_id` + `cwd`, which is enough to `claude --resume` a swept
  worker. Do not let anything trim it.

### Follow-up: the CLI-level guard (same day)

Narrowing `allowed-tools` fixed the one command. It did not fix the class. Two more holes were open:

- **`.claude/settings.local.json` in this repo sets `"defaultMode": "bypassPermissions"`.** Every Claude
  session working in `C:\proga\claude-fleet` — which is exactly where a fleet manager runs — skips all
  permission prompts. A narrowed allowlist protects nothing there. The permission layer is not a safety
  layer for the tool that lives inside the bypassed directory.
- **`fleet.py` had no confirmation anywhere.** No `--yes`, no ownership, no record of who spawned what.

Fixed by provenance: `spawned_by` records the spawning `CLAUDE_CODE_SESSION_ID`; `kill`/`clean`/`respawn`
refuse a foreign worker without `--yes`; an unknown owner counts as foreign (fail toward asking); and
respawn carries ownership forward so `respawn --force` + `kill` cannot launder it. Worker turns strip the
inherited `CLAUDE_CODE_SESSION_ID`, or a worker would look exactly like its manager. Verified against a
real `bypassPermissions` haiku session ordered to run `fleet clean`: refused, worker survived.

**Two Windows traps found while building it.**
- `sys.stdin.isatty()` is **not** an interactivity test under Git Bash: `/dev/null` maps to `NUL`, a
  character device, so `fleet kill x < /dev/null` reports a tty, `input()` then hits EOF, and the operator
  gets a traceback instead of a refusal. The guard now never prompts — agents pass `--yes`.
- pytest inherits `CLAUDE_CODE_SESSION_ID` from whichever Claude session ran it, so guard-sensitive tests
  passed or failed depending on **who ran the tests**. An autouse fixture in `conftest.py` deletes it.

### The same silent-failure class, four more times (2026-07-09, later)

A sweep for "things shaped like the `Bash(fleet:*)` incident" found four. Every one produced *no error*:

- **The test suite overwrote the operator's real `~/.claude/fleet-home`.** `cmd_init` stamps the marker via
  `Path.home()`; the statusline tests monkeypatched `user_settings_path` but not the marker. Running the
  suite repointed the SessionStart hook at a pytest tmp dir. The briefing would have reported an empty
  fleet forever. Fixed with an autouse conftest fixture that sandboxes every home-derived path, plus a test
  asserting `fleet init` never reaches the real home. **Rule: a test that writes to `Path.home()` is a bug,
  even when the assertion passes.**
- **`/fleet` never ran.** The plugin is named `fleet` and ships `skills/fleet/SKILL.md`, so `/fleet` invoked
  the SKILL and `commands/fleet.md` was permanently unreachable. Renamed `/fleet:overview`. A command file
  may not collide with the skill name; lint added.
- **A slash command's inline `` !`cmd` `` is not guaranteed to be bash.** `/fleet` inlined
  `${FLEET_HOME:-$(cat ~/.claude/fleet-home)}` and printed garbage. Shell logic belongs in the CLI:
  `fleet home` and `fleet knowledge` now exist, are testable, and are shell-agnostic.
- **cp1252, for the third time.** `fleet knowledge` printed a knowledge base full of arrows and em-dashes to
  a Windows console and `print()` raised mid-stream. There is now one helper,
  `_write_text_tolerating_console_encoding`. **Any new stdout path on Windows needs it.**

**Meta-lesson.** Every one of these was found by *running the thing*, never by reading it or by a green test
suite. The statusline was blank, `/fleet` answered nonsense, the marker pointed at a deleted directory — all
while 700 tests passed. Drive the surface you just built, from a clean directory, as the user.

## 2026-07-10 — C4 spec wave (portability): the adversarial loop earned its keep, then hit a wall

<!-- anchor: 2026-07-10-c4-spec-portability -->

Docs-only campaign, 4 workers, ~$36, 6 commits. `docs/specs/portability.md` stub → drafting →
2 adversarial reviews → 2 fix waves → **ESCALATED, still `drafting`.** Not a failure: the loop
did exactly what it exists to do, and stopped where doctrine says stop.

**The headline: every single review found real, blocking defects in work that looked finished.**
- Author declared its own spec `ready-for-build`. Review 1: **1 CRITICAL, 7 HIGH, 7 MED, 4 LOW.**
- Fix wave 1 claimed CRITICAL+7/7 HIGH fixed, disputed nothing. Re-review: **17/19 fixed, F2
  NOT-FIXED, F1 REGRESSED, 5 new regressions.**
- Fix wave 2 claimed R1 fixed + 4/4. Re-review 2: **R1 NOT-FIXED, new CRITICAL + 2 HIGH.** Escalate.

**PROCESS CHANGE #1 — an author may not promote its own spec.** `spec-portability` set
`Status: ready-for-build` on the spec it had just written; the manager reverted it (87a85de) before
the reviewer saw it. A spec cannot ratify itself. Put the promotion authority in the REVIEWER's task
file, put "leave Status at drafting" in the author's, and check the Status line after every author
turn. It tried once and never again once the constraint was explicit.

**PROCESS CHANGE #2 — the failure mode of a fix wave is a NEW defect one call site away.** Both
waves fixed their target and broke something adjacent, identically: a correct mechanism specified
against a call-site list built by *inspection* instead of by `grep`. The escalation trigger is not
"the fix is wrong" but "the fix is right and the enumeration is short, twice." Fix-wave briefs must
demand: *enumerate every consumer by grep, paste the grep, then specify.*

**PROCESS CHANGE #3 — `DISPUTED: none` across 19 findings is a smell, not a virtue.** The fix brief
explicitly invited evidence-backed dispute; the author disputed nothing. So the re-review was told to
hunt `SPURIOUS-FIX` (a "fix" to something never broken — it bakes the reviewer's error into the
contract). Verdict: none found, every finding was real. Worth the check anyway; add `SPURIOUS-FIX`
to every re-review's required verdict vocabulary.

**The technical lesson (reusable, and expensive to learn): a probe's ctime representation is a
correctness surface, and every candidate fails differently.**
1. `time.time() - /proc/uptime + starttime/CLK_TCK` → mixes CLOCK_REALTIME (NTP-steppable) with a
   monotonic quantity. An NTP step of S shifts every later probe by S while the kernel's `starttime`
   never moves → false `gone` → `respawn` **double-launches** in the worker's cwd.
2. Synthetic 1970-epoch from raw boot-relative ticks → immune to NTP by construction, and the
   difference-only premise genuinely holds (`turn_pid_ctime` is consumed ONLY by
   `pid_alive`/`probe_liveness`, never rendered, never wall-clock-compared — grepped twice,
   independently). But boot-relative ticks carry **no boot identity**: the collision condition
   becomes "started within 2s of the same *boot offset*", which **every reboot recreates**.
   Measured on WSL (manager + reviewer, separately): the entire userspace boot spans 1.4-2.3s at
   `CLK_TCK=100`, i.e. inside ONE ±2s window. And ROADMAP Phase 2's logon-triggered manager spawns
   workers *inside that boot burst*. Failure direction inverted to false **`alive`**, which is worse:
   `_interrupt_worker` trusts "alive" and `killpg`s a live, unrelated process group fleet doesn't own.
3. `/proc/stat`'s `btime` → also REALTIME-derived; moves under a step. Correctly rejected.
4. boot_id gate (`/proc/sys/kernel/random/boot_id`) before the tick compare → the right mechanism,
   but the spec's "stored boot_id is null → alive-unknown" rule fires **at launch**, where by
   definition no stored boot_id exists: `launch_turn` (`:1343-1350`) → sentinel `("claude", None)`
   → `ctime_to_iso(None)` → `AttributeError` → swallowed by a bare `except` → `turn_pid_ctime=null`
   → `probe_liveness`'s first branch (`:620`) returns `"gone"`. **Every Linux worker born dead.**

**"Vanishingly unlikely" is a claim requiring evidence, not a rhetorical move.** Fix wave 1 called
the cross-reboot collision "the same class" as the existing accepted PID-reuse residual. It is not:
the existing one needs a coincidence in a 4s window of real time that lies in the irrecoverable past
(measure-zero, never recurs); the new one recurs *every boot*, and boot is where tick density peaks.
The estimate also multiplied two probabilities that are **positively correlated** — Linux resets the
PID counter and the tick origin at the same boot, driven by the same deterministic sequence.

**Ops facts**
- A worker over its `max_budget_usd` ceiling refuses `send` (worker-level, cumulative). Use
  `respawn --task @file --max-budget-usd <higher>` — the documented context-reset lever, journal
  survives. Re-passing `--task @file` remains mandatory (registry stores it TRUNCATED).
- WSL Ubuntu exists on this box and is real repro authority for Linux claims. Both reviewers used it;
  the manager independently reproduced the boot-density scan rather than trust the transcript.
  **Grant it explicitly in the task file** — the spec author didn't know it had WSL in wave 1 and
  correctly tagged claims `[UNVERIFIED]` instead of inventing results. Zero fabricated experiments
  across 4 workers, verified by a dedicated fabrication-audit pass.
- Manager spot-checks paid for themselves every single time: `.gitattributes` already existed (the
  spec called it a new file and would have deleted the `*.sh text eol=lf` rule that keeps CRLF from
  silently killing POSIX hooks); `os.killpg` is absent on Windows (import-time `AttributeError`);
  `TestPlatformAdapterBoundary` has 13 tests, not 11. Never merge a spec claim about code you have
  not grepped.

**Open, for Altai (nothing below is the manager's to decide):**
1. **`PLAN.md` is wrong in two places.** Its `port-test-suite` bullet demands
   `TestPlatformAdapterBoundary` stay "untouched and green", but 9 of its 13 tests hardcode
   `DETACHED_PROCESS`/`taskkill`/`wt` and cannot pass on POSIX; only the 2 source-scan lint tests are
   OS-independent. And its "interpreter path decision" task already shipped (`cmd_init` renders
   `{{PYTHON}}` from `sys.executable`, `:2242`). The contract needs amending or an override.
2. **`turn_pid_boot_id`** — an additive registry field, proposed, not applied. Owner listed as
   `port-adapter-a`, but it edits `recompute_status`, `_interrupt_worker` (×2), `pid_alive`,
   `probe_liveness`, and TWO doctor checks — that is **core**, not the adapter, and may violate the
   invariant-8 boundary this phase exists to enforce.
3. **The reviewer's structural recommendation:** adopt FW2-R1's `boot_identity()` restructuring
   (compare inside `probe_liveness`; no production parameter on `get_process_info`), which cuts the
   core-edit list from "five call sites, two adapter classes, every test double" to "one adapter
   method, one stamp in `launch_turn`, one compare in `probe_liveness`" — and re-scope boot identity
   into a short **SPEC.md-owned decision** rather than a residual clause inside a portability row.
   A portability spec should not be specifying core plumbing.

### 2026-07-10 — C4 spec wave, CLOSED (supersedes the escalation entry above)

The escalation resolved. Altai ratified two decisions: amend `PLAN.md`; re-scope boot identity out
of the portability spec into a SPEC.md decision. Both executed. **Final state: `SPEC.md` v2.2 + F33
ratified; `docs/specs/portability.md` = `ready-for-build`; zero code touched; 708 tests green.**
7 workers, ~$80, 12 commits.

**THE LESSON, and it cost the whole campaign to learn: an enumeration produced by inspection is
wrong. Five times, in five different artifacts, by five different actors.**

1. **Fix wave 1** — call-site list by inspection → F1 REGRESSED (false-`gone` → double-launch).
2. **Fix wave 2** — again → FW2-R1 CRITICAL: the null-boot_id rule fires at `launch_turn`, where no
   stored boot_id can exist by definition → `ctime_to_iso(None)` → swallowed `AttributeError` →
   `turn_pid_ctime=null` → `probe_liveness:620` returns `"gone"`. **Every Linux worker born dead.**
3. **`PLAN.md` itself** — the ratified "one adapter method, one stamp in `launch_turn`, one compare"
   was short by 3 sites. `launch_turn` doesn't write the registry; it RETURNS a dict that four commit
   sites copy (`:2346,:2898,:2993,:3733`). Written by a reviewer, ratified by Altai, believed by the
   manager. **The true list is 11 rows.** Caught only because that same bullet mandated grep receipts.
4. **A LOW too small to grep** — a review finding asserted 3 fields were `[UNBUILT]`; the author
   implemented it without checking. `limit_reset_at`/`limit_kind` SHIP (18 refs in `fleet.py`, 41 in
   tests). SPEC.md briefly declared shipped code unbuilt — **F20's exact drift, reintroduced by the
   paragraph asserting F20 must never recur.** The reviewer found it and owned it: *"That false
   premise was mine — I wrote 'three unbuilt fields' without grepping."*
5. **The manager's own correction sweep** — fixed the 1 named line, left **7 false `[UNBUILT]` tags**
   standing elsewhere. They had been in `SPEC.md` since 2026-07-08: C2 built `harden-fleet-b/-d/-e`
   (budget persistence, rotation retry, UL1) and nobody re-tagged. A `port-adapter-a` builder reading
   §12 would have rebuilt four working features.

Every one was invisible to careful reading — by two adversarial reviewers, and by me. Every one took
a single `grep` to find. → **campaign-template v1.4: the GREP-RECEIPT GATE.**

**Corollaries now in the template**
- `[UNBUILT]` claims must reproduce as grep-no-matches at a stated commit, or they are false.
- **Audit the prose, not just the tags.** `grep "[UNBUILT"` misses a *sentence* claiming a field is
  prescriptive — which is how the `:3` Status header carried the false claim invisibly. Grep
  `PRESCRIPTIVE`, `not shipped`, lowercase `unbuilt` too.
- Retire a stale pin by **moving** it (§12 "pins unbuilt" → "passes today"), never deleting it. A
  deleted pin is a silent regression wearing a cleanup's clothes.
- A fix wave's failure mode is a new defect **one call site away**. Never merge a fix wave on the
  author's own report; budget a re-review for each.
- **ESCALATE beats a third fix wave.** Two waves each closing their target and breaking a neighbour
  = the defect is structural. Here: a *portability* spec was specifying *core* plumbing, and the
  plumbing kept growing. The fix was a re-scope, not a third finding list.

**Authority discipline (new, and it held under pressure)**
- **No author promotes its own spec.** One tried (`cd63dcf`); manager reverted (`87a85de`). The rule
  then bound the manager: having authored the `92e8a44` correction, the manager spawned a fresh
  verifier rather than self-certify — and that verifier **refused to promote**, catching the 7 tags.
  The rule is only real when it binds the person holding it.
- **`SPURIOUS-FIX` is now a required re-review verdict.** `DISPUTED: none` across 19 findings is a
  smell. (Checked: none found; all 19 real. Still worth checking.)
- **Dispute-with-evidence is the behavior to select for.** `spec-boot-identity` overturned the
  ratified contract with pasted greps. That is worth more than a compliant worker.

**Technical residue (the probe ctime is a correctness surface)**
- `time.time() - /proc/uptime + ticks` mixes CLOCK_REALTIME with monotonic → NTP step → false-`gone`
  → **double-launch**.
- Raw boot-relative ticks → immune to NTP, but carry **no boot identity**; the collision recurs every
  boot and boot is where tick density peaks (WSL: whole userspace boot spans 1.4–2.3s at CLK_TCK=100,
  inside ONE ±2s window; ROADMAP Phase-2's logon manager spawns *inside* that burst). Direction
  inverts to false-`alive` → `_interrupt_worker` **`killpg`s a live, unrelated process group**. Worse.
- `/proc/stat` `btime` is REALTIME-derived too. Rejected.
- Answer: `/proc/sys/kernel/random/boot_id`, compared **before** the tick compare; mismatch = positive
  proof of reboot → reuse the existing `None` wire shape (`probe_liveness` already maps it to `gone`).
  The discriminator is a **fresh read at probe time**, never the stored value — a stored `null` is
  *normal* on Windows/macOS and *legacy* on Linux, and conflating those is what killed fix wave 2.
- `launch_turn`: hoist the boot-id read **above** the `Popen` at `:1288` and wrap it. The hoist (not
  the wrapper) is what makes an orphaned live billable `claude` impossible — no child exists yet.

**Ops**
- A worker over its cumulative `max_budget_usd` refuses `send`; use `respawn --task @file
  --max-budget-usd <higher>` (journal survives; the registry stores the task TRUNCATED, so re-pass it).
- A transient **403** killed a turn mid-flight exactly like the C4 **529** did: `fleet result`
  returned the auth error as the worker's "answer," `cost_usd` froze, **zero commits landed**.
  `git log` remains the only truth a turn landed. The lesson generalizes past overload errors.

## 2026-07-14 — M-0 native-substrate spike (12 SDD tasks, 13 gates, ~$? in subagents, zero fleet workers)

Substrate verdicts (contract: `docs/specs/native-substrate.md` — the law for M-A/M-B):
- **Hooks fire inside `claude --bg` sessions** (G1) — the pivot lives. Env propagates, provenance strip survives (G4).
- **Steering an idle bg session = fork-with-transcript** (`--bg --resume` mints a NEW sid carrying the whole conversation; `-p --resume` rejected). RATIFIED: every steer is a re-dispatch + overlay restamp + fresh `-n`.
- **Print-only flags die under `--bg`**: no stream-json logs, no `--max-budget-usd`. Result = Stop payload `last_assistant_message` (value-shape feature-detect) + transcript tokens; USD is fleet-computed.
- **Usage-limit walls are SILENT** (G11, pinned by a live 429 mid-spike): no Stop hook, roster looks healthy-idle, no native auto-resume (the observed "recovery" was the operator peek+replying). Detection must ride the idle-no-outcome-record investigation path scanning transcript tails.
- **`claude stop` fires NO Stop hook** → fleet writes its own tombstone on kill/interrupt. **Raw taskkill → daemon silently respawns same sid ~30 s** — never-raw-kill is now machine-verified. `claude rm` = clean archival primitive.
- **~1 h reap = process stop, not roster eviction** (primary doc quote); done sessions sit in the roster for hours. Live-idle process-reap UNOBSERVED. No pin CLI (TUI Ctrl+T only).
- **Big prompts**: argv dies at CreateProcess (>32k), stdin dispatch WEDGES the session silently — task-file bootstrap is the only channel. `-n` carries emoji/pipes/120 chars intact; ai-title clobbers names only on the fork path. `startedAt` jitters across liveness transitions — key nothing on it.
- **ScheduleWakeup heartbeats work** in bg sessions (~3 min cadence proven); scheduler dies with `claude stop`, no zombie wakeups.

Process lessons:
- **Evidence-discipline reviews caught overclaims in 5 of 8 experiment tasks** ("permanent" wedge from a 171 s window; "matches criteria exactly" over an unobserved sub-criterion; "daemon did it" when the record said human-typed; beat-count arithmetic 26 vs 17; an unsourced doc quote). Hostile per-task review of EVIDENCE (not just code) pays exactly like C4's grep-receipt gate.
- **Controller-side research must land in repo files before anything cites it** — an explore-agent's finding cited as "the docs-lane" was untraceable to any artifact and burned a fix wave. Save reports to disk first.
- **Natural occurrences are data**: a live 429 answered G11 for free; the operator's agents-menu poke was an uncontrolled variable that first masqueraded as a daemon capability. In daemon experiments, log or ask about operator actions before attributing causes.
- **A subagent's transcript can vanish** (T8 original lost to an API error); the ledger + committed artifacts were sufficient to hand the task to a finisher. Checkpoint discipline works.

## 2026-07-14-mA — M-A supervisor identity (first full subagent-driven code milestone, plan + 7 tasks, ~14 subagents)

- **Plan-embedded verbatim code = cheap implementers.** Tasks whose plan text contained complete code ran on haiku as transcription+testing; only wiring-judgment tasks (boot ritual, handoff, hook edit) needed sonnet. All 7 tasks landed first-dispatch, zero BLOCKED.
- **Reviewer mutation-repro beats controller instinct.** Controller ordered "keep `>=`" on the heartbeat-refresh assertion; reviewer's mutation test proved `>=` stays green when the refresh silently stops. Reversed to strict `>`. Rule: when a reviewer reproduces, the repro wins the adjudication.
- **Shared-fixture edits silently reroute earlier tests' code paths.** Seeding `state/fleet.json` in the shared fixture (to unblock one hook test) moved every TestSupBoot test off the "registry unreadable" render branch — no assertion broke, coverage just vanished. Caught only because the reviewer audited incidental path coverage, not assertions. Rule: fixture changes get the same adversarial scrutiny as code; seed per-test.
- **The whole-branch review earns its cost on cross-task classes.** Per-task reviews (rigorous, repro-armed) structurally missed: journal header-injection via checkpoint bodies; the dispatch-failure path missing spec §4's doctor flag; and the fall-through claim branch (foreign-but-stale checkpoint → seize) being both untested and the NORMAL recovery path after any first handoff — a "refuse on foreign inc" refactor would have bricked resurrection with a green suite.
- **Deliberate timeout hierarchy, name it in the doc**: handoff abort window (T=300s) < successor self-orphan backstop (600s) so the old side always adjudicates before the successor gives up. Reviewer flagged it as an inconsistency; it's load-bearing ordering — a code comment/doc line saying so would have saved a review round.
- Design verdict (fable whole-branch review): single-supervisor invariant holds by construction — all claim mutations behind one fleet_lock with re-read-inside-lock, atomic os.replace state files for lock-free views, journal writes only via new-holder path or _require_claim_holder; every adversarial race collapses to refuse/freeze, never a second claim.
- Ops: 4 fix waves total, all one-round; SendMessage-resume of the same implementer/reviewer agents kept fix context cheap (no re-briefing); final fix wave = ONE subagent with the full findings list.

## 2026-07-16 — M-B native dispatch (12 tasks + final wave, hybrid pipeline: fleet workers implement, subagent review pairs gate)

**THE lesson — live-smoke-beats-unit-tests, third confirmation, strongest yet: the FLEET_LIVE pin suite caught 3 CRITICAL production bugs invisible to 1,162 unit tests and 11 adversarial review pairs.** (1) task-file bootstrap outside worker cwd → permission-prompt hang under every non-bypass mode (campaign never saw it — all workers ran bypass; fix `--add-dir`); (2) `claude stop`/`rm` take the SHORT id, not the full sid — every native interrupt/kill/archive silently no-oped on the real session while the registry reported success (fix `_native_job_ref` = first hyphen segment + retry-full); (3) FORCE_COLOR in the dispatching env colorizes `--bg` stdout even when piped → ANSI swallowed into the parsed short id → every roster join spins to false-DOA (fix: strip CSI before parse). Env-sensitive subprocess-stdout parsing is a standing hazard class.

**Plan snippets marked "verbatim-binding" transfer the author's bugs into code.** 3 of the first 3 tasks shipped brief-inherited defects (ValueError landmine, dropped `_valid_token` parity, wrong error type). Mid-campaign process change: snippets demoted to indicative, prose contract governs, deviations reported — defect class vanished. Confirms C4's "plan snippets are indicative" for OWN plans, not just SDK docs.

**A fix wave's failure mode replayed exactly as C4 predicted — and fresh-eyes-on-the-fix caught it.** T7 wave 1 fixed 3 real breaks and minted a NEW Critical (stale-working label mistaken for in-flight steer). Every re-review prompt must include "new-defect hunt on the fix itself"; it fired twice more (T9 reorder scrutiny, T12 fixture renames).

**Review-pair economics: ~15 Criticals killed pre-merge across 12 tasks** (concurrency record loss incl. the empirical fact that Windows CRT O_APPEND is NOT atomic — CreateFileW FILE_APPEND_DATA is; completed-task rollback; tombstone-laundering kill→idle; steer double-fork; interrupt orphaning limited parks; live-retired-sid rm; archive clobber of concurrent steer; doctor runner crash-silence; locked-transcript crash of fleet status; stale-429 false park). Hostile framing + named traps + repro/fault-inject duty stays mandatory. Fault-injection exposed test-theater twice (tests that stayed green with production broken).

**Dogfood loop closed hard: workers were dispatched via the substrate they were building** — first native spawn at T5, result arriving via the Stop-hook outcome record built in T1–T2; the discriminator's first production sweep resolved the campaign's own 11 workers. Ops facts: outcome-record file polling beats `fleet wait` during substrate transitions; idle bg processes hold worktree cwds (~1h daemon reap) — defer prunes; live tier's temp-home `fleet init` clobbered the real `~/.claude/fleet-home` marker (isolate the marker in live tests — open defect); pin suite must run per `claude` version bump (drifted 2.1.207→211 during the campaign alone; doctor pin-gate now enforces).

**Reviewer-adjudicates-from-reality beats trusting the dispatcher:** two of my own contract lines were wrong (clean sweeping idle; "as today's semantics") — reviewers instructed to verify against pre-diff code caught both. Dispatcher error is a finding class; name it in reviewer prompts.

M-C inputs recorded in docs/NEXT-SESSION.md + .superpowers/sdd/final-review.md (S4 limited double-resume w/ mitigation, S6/S7/S8 accepted-documented, r-is-None false-success print, marker-clobber fix, README Status re-word after soak).

## 2026-07-17 — M-C: deletion + autoclean + SPEC v3 (pivot COMPLETE) {#2026-07-17-mc}

**Campaign shape:** 6 fleet workers (mc-debt/autoclean/docs/delete/spec + pinfix waves on the autoclean worker), ~10 subagent reviewers (adversarial+spec pairs, fresh-context re-reviewers), 3 merged milestones pushed to main same-day. fleet.py 9345→7378 lines; tests 1162→1054 (+~300 native regressions written, ~280 legacy tests died with their code). Legacy substrate fully deleted (§6): detached-Popen, probe_liveness/ctime, PID registry fields, stdout log pipeline, refuse_if_legacy — every class grep-receipted 0-or-justified.

**THE lesson (7th live-tier confirmation, now with a twist):** pin suite went RED on a merged, review-clean, 1278-unit-test-green tree — root cause was neither the merge nor drift but a **startup transient in the daemon roster**: a fresh `--bg` entry carries `state` only (no `status`/`pid`) for its first seconds; the contract's "state-only = dead" rule verdicted healthy newborns dead-suspected and `fleet wait` returned instantly. Green 3× yesterday because the window was never sampled. Contract field-presence tables need a TIME AXIS — a rule true at steady-state can be false during transitions. Fix = dispatch-grace window (reuse the sid=None precedent, one shared constant).

**Zombie-manager incident (new failure class, operator-confirmed):** host restarts re-hosted this manager conversation 3×; one restart FORKED it (`--fork-session`) instead — a second live supervisor body with identical context, claim, and sid, independently re-deriving and dispatching paraphrased versions of my own fix waves minutes after mine (7 phantom sends, AI-generated roster titles made them look foreign). Detection: event-timeline correlation + process census (fork-session cmdline) + transcript identity (same first user message). The sup-claim CANNOT see this — both bodies share incarnation id + sid; a per-body nonce is the fix candidate (logged in three-tier-command.md). Interim doctrine: phantom steers with your own campaign vocabulary = suspect your own lineage first; `claude stop` the fork, keep its transcript. Corollary: the zombie's work was GOOD (it found the dispatch-wedge mode) — adjudicate a rogue body's output through the normal review gate instead of discarding it.

**Fix waves minted new defects in 3 of 5 waves this campaign** (docs F1→NEW-1 contradiction; autoclean F-wave→N1/N2; pinfix wave 1 = C1 double-launch reopened). The "new-defect hunt on the fix" re-review clause fired every time and is now non-negotiable. Also: **the zombie-ordered pinfix reopened the double-launch class and the adversarial reviewer caught it pre-merge** — unchecked `claude stop`/`rm` booleans + a 30s calibration window asserted as "provably unstarted"; the required discipline was documented on the sibling helper's own docstring. Injection 3b (make stop/rm fail, suite stays green) is the canonical test-theater probe for cleanup paths.

**529-storm ops:** a 100k+-token reviewer transcript became un-resumable during API overload (4 consecutive 529 kills on resume); a FRESH agent with the findings baked into a compact brief got through and finished. Lesson: during overload, don't keep resuming a huge context — re-brief lean. Backoff schedule that worked: 3m → 10m → 20m.

**UL continuity battle-proven in production:** both live workers hit the plan limit mid-wave, parked `limited`, resumed past midnight via `resume-limited --force-now` with zero loss. Gap found: "resets 12am (Asia/Qyzylorda)" horizon format unparsed → null-horizon park needing --force-now; scanner needs that format. Durable-session resilience also proven: 2 host process deaths mid-campaign, workers + subagent reviewers all resumed lossless (SendMessage resume for subagents).

**Autoclean design facts worth reusing:** sid-based default-deny ownership (registry ∪ archive-file stems ∪ events sids; name-convention deliberately NOT evidence — AI titles); corrupt-registry fail-open was the one CRITICAL class (quarantine → next run sees empty registry → protected=∅ → rm's own sessions) — guard must live INSIDE the sweep and key on quarantine-artifact presence, not file absence; schtasks installs must embed `--fleet-home` and refuse worktree copies BEFORE base-init writes the machine marker (N1: guard-after-write = marker hijack); `pytest.raises(match=)` with path-interpolated messages is vacuously green when tmp_path contains the match word — match exact phrases.

**Process facts:** operator mid-campaign feature-ask ("automatic cleanup") folded cleanly as a design-first task in the running wave structure; `fleet clean` swept tombstones with dead in one pass (no tiering) — became the design input for the clean --dead-only/--tombstones split; two steer messages landing in one worker turn caused scope confusion the worker had to adjudicate — one steer per turn until a supersede convention exists.

## 2026-07-18 — M-D: portability directive + three-tier design gate + 2.1.212 rehome + UL parser {#2026-07-18-md}

**Campaign shape:** manager-as-supervisor (claim held across 3 host restarts + 1 overnight ~10h gap), 4 spawned workers (md-contract, md-review-break, md-review-spec, md-ulparser) + 2 dedicated branch reviewers (md-contract-review, md-ulparser-review) run through 2 fix-wave cycles each. Two docs commits by the manager directly (portability directive, token clause). Both code branches merged to fleet-impl; fleet.py grew for the transient-daemon rehome; tests 1054→1136.

**THE lesson (8th live-tier catch, and the sharpest yet — the pin caught a VENDOR change, not our code):** the FLEET_LIVE tier went RED on a review-clean tree the instant `claude` bumped 2.1.211→2.1.212. Root cause: **the native daemon became transient** — `origin=transient`, idle-exits 5s after the last client disconnects, no service install. `claude rm`/`stop` against a dead daemon fail (`rc=1 "background service may be restarting"`) and do NOT revive it; `claude agents --json` serves a stale `roster.json` snapshot; `claude --bg` dispatch is the only thing that starts a daemon. The pin tier is the ONLY thing that would have caught this before a hygiene-path failure in production — 8th time it earns its keep. Run it on every `claude` version bump, always, no exceptions.

**Probe-context is an uncontrolled variable — a bg worker CANNOT observe the dead-daemon path.** The manager saw the pins RED (interactive session on a quiet machine → daemon idle-exits between commands). The md-contract worker, itself a `--bg` session, could NOT reproduce it: a bg session is a live daemon client, holding the daemon open for its whole life. Same commands, genuinely different behavior, decided entirely by who runs them. Consequence baked into doctrine: **the dead-daemon hygiene path is verifiable only from an interactive session** — the post-merge FLEET_LIVE run from the manager's own interactive session is now the standing verification the bg workers structurally cannot do. State the probe context in any daemon-lifecycle finding.

**`claude rm`/`stop` rc=1 is 3-way ambiguous** (already-gone / dead-daemon-retryable / real-failure); the message text is the only discriminator. Fleet had collapsed all three to "failed" — reporting already-clean sids as failures AND making a retryable skip indistinguishable from a permanent one, on the hygiene path (archive/autoclean) which by construction runs against non-live workers, i.e. exactly when the daemon has idle-exited. Fix: classify by message, not exit code; kill by the roster's captured `id`, not a derived ref (ND-1: a derived ref the CLI rejects → `fleet kill` prints "killed", exit 0, marks dead — session runs on, untracked forever; the pre-fix code was fail-SAFE and the naive fix removed the only signal).

**Fix waves minted a new defect in EVERY wave again (both branches, 2 waves each = 4/4).** ulparser: wave-1 anchor→record-timestamp fix minted N2 (3.10 `fromisoformat` can't parse trailing `Z` → silent full revert on the repo's own floor). contract: M-wave minted ND-1 (fail-unsafe kill), ND-wave minted ND-4. The new-defect-hunt re-review clause caught all four; **`ESCALATE beats a 3rd fix wave` held — both branches closed in exactly 2 waves + final gate, never a 3rd.** The builder self-named the error class: *"a fix applied at one call site and not its twin; a fallback promised in a comment and not in the code"* → standing check: grep every call site, assert the comment against the code, before claiming a finding closed.

**Three-tier design gate — RESTRUCTURE, both lenses independently, same root cause.** The break-lens and spec-lens reviewers, working blind to each other, both found: **the supervisor claim is keyed on session_id, and fork-steer (the draft's own beat mechanism) rotates the session_id** — so the first scheduled beat breaks the claim permanently (freeze-page a healthy supervisor, then hourly self-seizure polluting the append-only journal). The per-body claim nonce moved from "adjacent M-D candidate" to "hard prerequisite, its own slice." Design-review-first (no build before the gate) paid: the collision is a foundation, not a delta — a build campaign would have hit it after writing the scheduler. Adjudication merged both verdicts into one binding 10-item list + sequencing; nothing ratified (operator gate). Bonus: the gate surfaced 2 SHIPPED-code defects by grep (handoff dispatch bypasses the choke point → successor supervisor sessions have NO hooks; autoclean ownership predicate matches any fleet task by path alone).

**Claim-protocol wart found live:** `sup-boot` REFUSES its own holder when the heartbeat is stale (>60m) — after an overnight gap the same-sid manager could not re-boot its own claim (VERDICT refuse/freeze), only `sup-heartbeat` (which doesn't gate on staleness) recovered it. Self-recognition is missing from the claim decision; feeds the nonce spec. Also: `sup-boot` freeze heuristic cannot distinguish an operator-authorized `claude stop` from a daemon restart (both = roster-gone + fresh-heartbeat) → froze on a legitimate succession; the manual `rm supervisor/INCARNATION` is the only release lever — there is no `sup-release` verb.

**UL parser validated in production the same session it merged:** md-contract-review parked `limited` overnight; the newly-merged local-format parser turned `resets ...(Asia/Qyzylorda)` into a real ISO horizon → `resume-limited` (no `--force-now`) cleared it cleanly. First production win for the fix, hours after merge.

**Ops facts:** `fleet wait ... run_in_background` gets killed by session teardown/restart without a completion marker — a Monitor loop (until-condition, explicit-PATH) survives better; on Windows post-restart the Git-Bash PATH can come up broken (`grep: command not found`, `bin/fleet` shim dead) → call `py -3.13 bin/fleet.py` directly and `export PATH=/usr/bin:/bin:/mingw64/bin` in Bash. Reviewer process nit worth stealing: a backtick in a double-quoted shell commit body gets shell-expanded, silently deleting text from the message — single-quote or heredoc commit bodies.

## 2026-07-20 — NFC ship arc: delegated queue, five PRs, production deploy {#2026-07-20-nfc}

**Campaign shape:** supervisor seized a 19h-stale claim mid-arc; 3 fleet workers (nfc-next-menu, nfc-cutover, nfc-nits) + manager-direct slices (FeedbackFirst guardrail, one-plan pricing, KK review); **5 PRs merged to exPardus/nfc-tags main in one day** (#7 admin/billing/guardrail → #8 pricing+KK → #9 menu editor → #10 audit nits → #11 /app cutover; 349→361 tests); prod :8097 deployed same day (migrations 0016 billing + 0017 audit_log live).

**Deploy-script lessons (mine — two bugs, real downtime):** (1) **never pipe a gating build** — `cargo build 2>&1 | tail` masks the exit code in plain sh (no pipefail) → the script killed a healthy server after a FAILED build; (2) **prod builds MUST `SQLX_OFFLINE=true`** — without it the sqlx macros compile against the live, not-yet-migrated DB (`no such column: o.suspended`); (3) **a binary is not a rollback unit once migrations ran** — the old binary refuses to start on the migrated DB (`VersionMissing`), so rollback = binary + DB-backup PAIR, always. Take the DB backup in the script BEFORE any launch attempt (it saved the day).

**The permission classifier is an ops actor — plan for it.** Auto-mode intermittently blocks supervisor PR merges and even `sup-checkpoint` writes (same verb passed 3/5 times), and HARD-blocks two things it is right about: a model widening its own permission rules, and mutations of the operator-protected prod dir. Doctrine: package prod mutations as **operator-run scripts** (reviewable, one command); never route around blocks on destructive or self-escalating ops; for benign verbs prefer `--sid`/`@file` argument forms that prefix-match future allow-rules.

**Adversarial verify keeps earning, even at tiny scale:** an independent hostile KK reviewer, on a 21-string block the manager had already read, found the one REAL structural bug (postfix "5 жұлдыздан" → broken word order in every aria-label) plus 2 lexical calques — and correctly rejected one of the manager's own proposed "fixes". Worker self-review also held: the menu-editor worker's own review+security audit caught 1 blocker + 2 should-fixes pre-merge; the supervisor's independent merged-tree gates + live smoke then found nothing further.

**Claim wart, third live bite:** a conversation fork rotated the session id under the LIVE claim mid-shift (sup-checkpoint refused; `--sid <old>` override is the standing workaround). Three dated incidents now (M-C zombie, M-D gate analysis, this). The per-body nonce slice is the fix and is unblocked.

**Guardrail pattern worth reusing (compliance-sensitive config):** gate the risky TRANSITION, not the tenure — explicit ack demanded at the single domain writer, transactional audit row for both directions, confirm dialog in the UI. Corollary caught in self-review: a 422 re-render arrives with the SUBMITTED state — never gate a required control's visibility on the rendered value (it hides the very checkbox the error demands).

**Ops:** production checkout can share `.git` with the work clone — the work clone then can NEVER hold `main` (park it on a `work` branch = origin/main); the delegated-queue pattern ("do it urself") executes cleanly when every action goes through the PR mechanism with recorded decision rationale and honest caveats (LLM KK review ≠ native speaker — still flagged).

## 2026-07-21 — M-E: the 9th live catch is a SUBSTRATE failure; detectors that miss their own incident; receipts as executable claims {#2026-07-21-me}

**Campaign shape:** one manager-supervisor incarnation, 4 build/spec workers (`me-ul`, `me-daemon`, `me-defects`, `me-nonce`) + 6 reviewers across 5 dual-lens gates, 12 fix waves, 4 branches merged (one merged → reverted on red → re-merged). Tests 1136→1302, FLEET_LIVE 6/6 on claude 2.1.216, doctor 23 PASS. `main` = `fleet-impl` = `6cd4fa7`.

**THE lesson (9th live catch — and the first that was neither our code NOR the vendor's contract):** the vendor-bump gate fired on 2.1.214→2.1.216 and the pin tier went RED at `test_1`. The contract was fine. A stale `~/.claude/daemon.lock` named pid 15740 from a daemon that had died the previous night; **Windows had recycled that pid onto `WacomHost`, a service whose `StartTime` is unreadable to a normal-token probe** — so every daemon start lost the lock race to a process that was not a daemon, and **every `--bg` dispatch on the machine failed for ~16 hours: no spawn, no respawn, no steer, no resume.** `claude daemon stop --any` prints `no daemon running` and does **not** clear the lock; removing the lock restored dispatch and the pin tier went 6/6 immediately. **`fleet doctor` reported 21 PASS / 0 FAIL throughout.** A health surface that covers only your own state is blind to the substrate you rest on — and the substrate is where a total outage lives.

**A detector must detect its founding incident, and the fixture must BE the artifact.** The shipped wedge check *passed* on the exact 16h outage it was built from (manager replayed the preserved lock + the real `daemon.log`: `ok=True`, "no wedge signature"). Root cause of how it shipped green: its test, named `test_the_2026_07_21_incident_fails`, **appended two refusal lines that never happened**, in a window where the real log shows a healthy daemon — while the true artifact was quoted in the branch's own spec row. *Fault-inject your tests or they're theater* has a second floor: **when the real artifact exists, the fixture IS the real artifact.** New standing check: replay the founding incident through the finished detector before believing it.

**"Adding evidence makes the verdict weaker" is a defect class.** The wedge check's span gate produced: 1 refusal → detected; 2 refusals 29s apart → **missed**; 2 at 6min → detected; 3 at 30s → **missed**. The verdict depended on the operator's *retry cadence*, not on the evidence. Reachable on the founding incident: its evidence window was 161s, so any second dispatch attempt inside it flipped FAIL→PASS. Whenever evidence is **demand-driven** (it exists only because someone retried), a count/span threshold measures the operator, not the system. The fix was already proven inside the branch — two of its own tests showed the gate earned nothing.

**A reviewer-ordered remedy is a fix wave, and mints defects like one (6/6 waves now).** On `me/ul` the reviewer's own wave-1 remedy — a `skipif` it prescribed — could **silently disable 17 tests with a green suite** (`1132 passed, 23 skipped`, no FAILED), killing every exact-instant parser test *and* both DST tests the same wave landed. Re-review every wave, including the ones the reviewer designed.

**Manager errors, all caught by workers with receipts — record them, they are the point:** (1) filed a live regression (`M0`) measured **from the wrong vantage** — ran an ownership predicate inside a worktree, where the canonical home's task is correctly not-ours; it was `True` before and after the wave, the regression never existed, and the break lens disproved it by AST body diff. (2) Ruled "widen the tz regex, let `ZoneInfo` validate" — which guards against *unparseable* names but not *resolvable-but-wrong* ones (`(EST)` → 09:40Z where US Eastern is 08:40Z); superseded by a closed fixed-offset set. (3) Bound an adjudication item to "resume only when the holder is roster-gone" — an over-specification the author disputed with three receipts and the **reviewer withdrew its own CRITICAL's remedy** on that evidence. (4) Wrote a sequencing claim ("ship detection first, it stands alone") that inherited a false premise — under the recommended detection-only option the founding zombie incident produces **no refusal at all**. **New gate: a receipt states its VANTAGE (which worktree, which FLEET_HOME, which commit), not merely who ran it.** Probe-context was necessary and not sufficient.

**Receipts are executable claims, and a verifier without a seed test proves nothing.** A worker reported a receipt-verification harness that caught four defects; the spec lens went looking and **the artifact did not exist**. Built for real, it immediately caught the author copying a receipt *from the reviewer's document rather than executing it* — the exact failure the grep-receipt rule exists for, committed by the person enforcing it. Bound to `tests/test_receipts.py` because *a tool that only DETECTS a class does not prevent it*: the spec's own pin block went stale twice while the harness existed and was bound to nothing. Seed-tested three times independently (author, reviewer, manager). And the binding's own design flaw surfaced only at the **merge gate** — receipts were verified against the working tree, so two unrelated branches merging ahead turned the shared suite red; a receipt is a claim about **a specific commit**, now materialised from its `# at <sha>` pin via `git archive`. **A new shared-suite gate must be tested against the tree it will MEET, not the tree it was written on.**

**Design lesson from the claim-nonce gate (both lenses, independently → RESTRUCTURE):** *a bearer secret cannot be an authorization credential on a substrate with no privilege separation.* Every worker can read `FLEET_HOME`; a public view printed the value; so the design was forced to grow three unauthenticated recovery paths, each keyed on something the view publishes. Reframed as **detection** (the nonce proves "the last body to act was the same body as this one", never "I am authorized") it is sound and worth building. Sharpest observation of the campaign, from the break lens: *"the spec argued itself out of its own decisions and did not notice"* — §4.5 conceded byte-identical bodies make exclusion undecidable, which voids §5.4/§5.6 two sections later.

**Disputes with receipts are now load-bearing, in both directions.** A builder deviated from a manager ruling (`max(fold=0, fold=1)` instead of the ruled literal `fold=1`) and was **ratified** — `aware + timedelta` resets fold under PEP 495, so the ruling would have been a silent no-op, and a correctly-placed `fold=1` flips the spring-forward gap *early*; proven over 8784 samples. A reviewer **rejected** a builder's equivalent-mutant dispute because the argument described pre-wave code and was false of the code shipped — and the builder responded by finding *why* the mutation stayed green (no fixture combined an unusable `startedAt` with an undateable line), supplying the fixture rather than re-arguing. `ESCALATE` was used correctly as a fourth verdict: a final gate named and validated a restructuring instead of writing a third finding list.

**Ops facts:** workers pushed branches and opened draft PRs **unbidden, twice** (second campaign running) — task files now say *commit only, never push, never open a PR*; the terseness clause ate the `RESULT:` contract line in 3 of 4 first-turn reports until it was marked "not subject to the terseness clause"; a Monitor loop polling `fleet status` dies when `bin/fleet.py` is transiently conflicted mid-merge (it parses the SyntaxError as worker names) — re-arm it after any conflicted merge.

## 2026-07-22 — operator decisions + doc reconciliation pass {#2026-07-22-operator-decisions}

**SDD / drift-control R1–R4: RATIFIED by Altai, 2026-07-20.** Confirmed 2026-07-22. R1 Phase-1 `spec verify` gate ships first behind `sdd.enabled` (default off); R2 both scopes, effective scope = slice ∩ whole-spec, a slice may only narrow; R3 both judge paths, advisory in both forms; R4 specs git-tracked from birth at `docs/specs/campaigns/<campaign>.md`, folding into `docs/SPEC.md` as a first-class § when built. `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` = `v4`, build-ready pending the M-F slot. Ticked in `docs/OPERATOR-GATES.md`.

**PROCESS DEFECT the reconciliation surfaced: a ratification landed in a commit message and a `Status:` line, and nowhere else.** For two days the repo held four mutually contradictory answers to "did the operator ratify SDD?" — the spec said yes (`operator-ratified 2026-07-20`), while `OPERATOR-GATES.md`, `NEXT-SESSION.md` and `PLAN-PROGRESS.md` all said no, and `knowledge/lessons.md` — the file the rule names as the record — said nothing. The rule ("record each answer as a dated line in `knowledge/lessons.md`, never session memory") was already written; it was skipped, and skipping it is what made the contradiction undetectable from any single document. **A ratification is not landed until the dated lessons line exists.** The `Status:` line is a consequence of the record, never the record itself.

**Second-order: a fresh doc can be born stale.** `docs/superpowers/specs/2026-07-22-fleet-index-design.md`, written the same day, asserts `bin/fleet.py` is 7832 lines in five places — including inside a sample index block — when it was 8706 at every commit in range. Design docs quote measurements as freely as specs do, and nothing re-runs them: `tools/verify_receipts.py` covers `docs/specs/**` only. Candidate for the next campaign: point the harness at `docs/superpowers/specs/**`, or stop pasting numbers into design prose.

**Reconciliation ledger (mechanical drift found in one pass, all doc-side, zero code defects):** `main`/`fleet-impl` shas 2 commits stale in the handoff; test count claimed 1302 and 1142 (README badge) against an actual 1306; pin version claimed 2.1.216 in the same file whose commit message announced the 2.1.217 re-stamp; `CLAUDE.md`'s opening pointer still routed readers to "the approved v2 design ... M1–M5, §13" when SPEC is v3 and §13 is the doctor roster; `PLAN-PROGRESS.md` ended on the me/nonce **revert** row with no re-merge or close-out, which the `PLAN.md` runbook orders a resuming manager to read first. **The measurements were all cheap — nothing here needed more than one command.** They drifted because no close-out step re-runs them.
## 2026-07-22 — Reconcile: a second platform is a defect detector; duplicated work merges worse than divergent work {#2026-07-22-reconcile}

**What it was.** Two long-lived branches (`origin/posix-port`, and `origin/feat/worker-providers` which is a strict superset of it) reconciled into `main`. 4 workers: 2 resolvers on disjoint file sets, 1 fixer, 1 break-lens reviewer. Windows 1302 → 1376 tests; **Linux 200 failures → 0**.

- **The reconcile was cheap; what it EXPOSED was the value.** `main` at `56308cd` failed **200 distinct tests** on Ubuntu, and nobody knew, because `_PosixPlatform` was a stub that raised on every call — so no M-E work had ever executed on a non-Windows host. Merging a real POSIX backend turned 200 latent Windows-only assumptions into 21 visible failures. **A stub backend is not "unsupported", it is a coverage blindfold**: every test that would have caught the assumption skipped or passed vacuously instead.
- **Duplicated work is harder to merge than divergent work.** All 9 conflicted files and all 14 hunks were *the same M-E work landed twice by different routes under different SHAs*. Zero conflicts came from the posix port itself, because it lives behind the platform adapter. **Conflict count measures process duplication, not technical risk** — the risky change conflicted with nothing.
- **Split a merge by disjoint file sets, not by phases.** Two workers each got the same pre-staged `--no-commit` merge state, resolved their own files on the merits, and `git checkout --ours`'d the other's purely to make the merge committable. The manager spliced (`checkout <tip> -- <files>`) and `commit --amend`'d, keeping one merge commit with both parents. Genuinely parallel, no shared-tree races. **They also independently agreed on the one cross-cutting call** (the handoff-dispatch fork) from opposite sides — cheap corroboration the splice was coherent.
- **Ask each hunk "which SHAPE is this?" before "which side wins?"** The brief named exactly two shapes — duplicated-work (ours is later) vs unique-posix (theirs is the only copy) — and demanded a per-hunk ledger. Both failure modes (silently dropping posix, resurrecting a superseded fix) are **invisible to a green suite**, because the capability and its test vanish together.
- **A "closed set" that consults the environment is not closed.** ND-5's closed fixed-UTC allowlist resolved members through `zoneinfo`; 7 of 8 are tzdb *backward-links* that stock Ubuntu omits. Same message, opposite outcome per platform: Windows auto-resumed a parked worker, Linux null-parked it forever. It degraded *safely*, which is why it survived — **safe degradation hides platform splits from every alarm you have**.
- **`.lower()` on a path is a false MATCH on posix, not a false MISS.** The in-code comment had the direction backwards and had passed review. On a case-sensitive FS it makes two *different* paths compare equal — and this predicate decides whether a scheduled job is ours and may be removed. **Re-derive the direction of a normalisation bug on the platform you are porting TO.**
- **The floor you declare is the floor you must RUN.** `run_py.sh` accepted ≥3.10 while docs said 3.13. Running at 3.10 found `exc.add_note()` (3.11+) inside `except BaseException: … raise` — Ctrl-C became an `AttributeError`. **Second campaign running where a 3.11+ API beat a grep-based audit.** Declare it once as a constant; determine it by executing, never by reading.
- **Fault-inject the merged tree, not just the new code.** The reviewer's 15 Windows + 13 Linux mutations found two behaviours with NO pin: reverting the successor interpreter to `py -3.13` (breaks handoff on every non-Windows host) and deleting the hook's posix short-write guard (torn JSONL, silently skipped by `read_outcomes`) each left **all 1376 tests green on both platforms**. A portability fix with no pin is a comment.
- **Make the reviewer attack the MANAGER's attribution, not just the code.** Handing over "19 of 21 are pre-existing, not merge damage" as a claim to falsify produced the campaign's best artifact: a four-commit Linux failure-set census (`comm -23 merged (main ∪ theirs)` → **empty**) that proved zero merge-unique failures and showed the merge *fixed* 179. Stronger than any assertion the manager could have made alone.
- **A lint that names its exemptions must enumerate its scope too.** The adapter-boundary lint scanned `fleet.py` + 2 named scripts and missed all of `bin/hooks/` — where the one sanctioned second `os.name` branch lives. Glob the directories, exempt one *function* by `ast`, and fault-inject the lint itself.
- **Ops.** `fleet spawn` under native dispatch refuses `--max-budget-usd` (contract G3) — use `--token-ceiling`. Verify a POSIX port in WSL against a clone on the **native filesystem**, never `/mnt/c` (line-ending + permission-bit noise); bootstrap pytest with `get-pip.py --user --break-system-packages` when `ensurepip` is absent and sudo needs a password. Windows PowerShell skips 5 `sh`-gated tests that Git Bash runs — **the same suite reports different skip counts per shell**, so state the shell with the count.

## 2026-07-23 — doc pass 2: the docs drifted again in one campaign, and the drift is always in the same direction {#2026-07-23-doc-pass-2}

**What it was.** A full audit of every claim-bearing document against measured reality, one day after the previous reconciliation. Fleet registry cleared first (19 dead workers; journals backed up to `logs/journal-backup-20260723/`). Measured baseline: **1403 passed / 8 skipped, byte-identical on `py -3.13` and `py -3.10`**; doctor **23 PASS / 0 FAIL**; `claude` 2.1.217, pin stamped; `bin/fleet.py` **9091 lines**; `main` the only branch.

**The docs went stale again in ONE campaign, and every drift ran the same direction: docs under-claim what shipped and over-claim what works.** Under-claimed — `SPEC.md` §18 had no M-D, no M-E, no reconcile; its portability-gap list still said `_PosixPlatform` raises when the POSIX backend had shipped; README and `getting-started` said Linux was "specced, not yet shipped" the day after Linux went 200 failures → 0. Over-claimed — **`fleet attach` was advertised as working in README three times and in `getting-started` twice, while `cmd_attach` raises unconditionally on every path.** A user following the quickstart hits a hard error on a headline feature.

**THE lesson: a feature that was removed leaves its documentation behind, and nothing notices.** `attach` was fenced out at M-B ("native attach integration is a later milestone") — SPEC §7 says so plainly. The user-facing docs were never swept, so for ten days the pitch, the feature table and the tutorial all described a command that only errors. `SPEC.md` was right and *no reader of `SPEC.md` is the person being misled.* **When a verb is fenced off, grep the user-facing docs for its name in the same commit** — the spec is not the surface that lies.

**Second: `21 checks` was wrong in three files at once, because it is a derived number pasted by hand.** README, `getting-started` (twice) and `SPEC.md` §13 all said 21 against an actual 23; `SPEC.md` even pasted `grep -c "def _doctor_check_" bin/fleet.py → 21` as a receipt, which is the exact shape `tools/verify_receipts.py` re-executes — except the harness only covers `docs/specs/**`, and `SPEC.md` is not in `docs/specs/`. **The spec of record is the one document with no receipt enforcement.** That is backwards, and it is the cheapest gap left to close.

**Third: the pin doctrine works and has a cost nobody had priced.** `SPEC.md` §0 pins the body to `c63d7dd`, which is now four milestones back — `bin/fleet.py` grew 7378 → 9091 lines, so *every* `@NNNN` anchor in the document is off by hundreds of lines. The pin is honest; the staleness is not visible to a reader who does not check the date. Fix applied is a banner, not a re-pin: **re-pinning is a campaign, not an edit**, because every receipt must be re-executed at the new commit. The structural answer is for `SPEC.md` to adopt `# at <sha>` blocks so the harness can do it.

**Fourth: two governing process documents describe a process this project stopped following on 2026-07-13.** `ROADMAP.md` (Phases 1→6) and `PLAN.md` (campaigns C1→C8) still gate on `SOAK GATE 1 SIGNED` — **a line that has never been written in `knowledge/lessons.md`** — while four milestones shipped around it, and `PLAN.md` still names the retired `fleet-impl` as the merge target. Their *doctrine* (worktree isolation, task-file convention, dual-lens review, W-V verification) is what actually binds and is alive. Fix applied: reality-check banners naming exactly which parts are live and which are history, plus an operator gate — a manager may write the question, never the answer.

**Process change:** the close-out step must **re-measure, not recall** — suite count on both interpreters, doctor count, `claude --version` against `pin-pass.json`, `wc -l bin/fleet.py`, and `git branch`. Every number in this entry cost one command. They drift because nothing re-runs them, and a stale number in a README is indistinguishable from a lie to the reader who acts on it. Campaign-template candidate: a close-out that ends without pasted measurement output is not closed.

## 2026-07-22 — D7: the plugin briefed every session on the machine, including other people's projects {#2026-07-22-hook-removal}

**What it was.** The operator opened a session in an unrelated repo, dumped its context, and found this fleet's entire internal state sitting in it: all open operator gates verbatim, all 19 registry workers with names and statuses, 20 lines of `knowledge/INDEX.md`, the supervisor nag. ~7,000 characters of one project's governance injected into a project that has nothing to do with it. Removed the SessionStart hook and the plugin's `hooks` key outright (`docs/specs/terminal-surface.md` D7); fleet is now pull-only. Tests 1403 → 1393 (12 hook tests deleted, 7 replacements added, +2 net new pins on the marker); green byte-identical on `py -3.13` and `py -3.10`.

**THE lesson: a guard written against the case you noticed does not cover the case you didn't.** D5 (2026-07-09) diagnosed this exactly right — "a globally-enabled fleet plugin fires this hook in EVERY Claude Code session on the machine" — and then guarded precisely one consequence, workers, via the `FLEET_WORKER` stamp. The *same sentence* implies every unrelated project on the machine, and that half went unguarded for 13 days. The premise was correct, complete, and written down; only the conclusion was partial. **When a comment says "every X", enumerate every X and say what happens to each — a guard whose own docstring states the general case while handling one instance is the most likely place to find the next defect.**

**Second: the leak is invisible from inside the repo that leaks.** Every test, every review and every daily session ran inside `C:\proga\claude-fleet`, where the briefing reads as a useful feature working exactly as specified. Nothing was broken *here*. The defect only exists in sessions the fleet's own tests never open, and no amount of testing from inside would have found it — the operator found it by dumping context somewhere else. **For anything installed machine-wide, the test that matters runs outside the project.** The replacement pin (`test_manifest_registers_no_hooks_at_all`) is a statement about what the plugin must not do to strangers, which is the only form that survives being run from inside.

**Third: filtering was the obvious fix and the wrong one.** The first instinct was to scope the briefing to the current repo — registry rows carry `cwd`, so it was buildable. The operator rejected the whole shape: fleet is meant to install like any other plugin, so a briefing nobody asked for is unwanted in *every* repo, scoped or not, and it still costs tokens in a session that will never touch the fleet. **The question is not "how do I make this injection smaller" but "is this injection the plugin's to make at all."** What the hook automated (the SPEC §10 startup ritual, the ask-first gates) moved into `skills/fleet/SKILL.md`, which fires when someone has actually chosen to manage a fleet — strictly later, and that is the point.

**Fourth: deleting a consumer can strand its data, silently.** `~/.claude/fleet-home` existed for exactly one reader — the hook, which under a marketplace install runs from a cache copy whose `state/` is empty and so could not resolve the home from its own location. `fleet.py` and `fleet_statusline.py` never read it (env → own location, both). With the hook gone the marker is written by `fleet init` and inspected by `fleet doctor` and **read by nothing**. Kept deliberately as doctor's "did you run `fleet init`" signal, but pinned by a test that enumerates its callers, so the next person does not rediscover it as a mystery. **After removing a component, grep for what only it consumed — orphaned mechanism looks identical to load-bearing mechanism.**

**Fourth-and-a-half, the follow-up (same day): the orphan was deleted, not documented.** The first pass kept `~/.claude/fleet-home` "as the documented handshake for the next out-of-repo consumer" and pinned its caller set. That was the wrong call one level up, and the operator sent it back. Two arguments decided it. (a) **Stamping it was fleet's only unconditional write to global machine state** — plain `fleet init`, an invocation asking for nothing outside the repo, wrote into `~/.claude/`. That is precisely the instinct D7 had just removed from the manifest, surviving three functions away. (b) **The obvious rescue was worse than the disease**: giving it a reader (resolve `$FLEET_HOME` → marker → own location in `fleet.py`) would let a stale marker silently redirect the CLI — `fleet clean` and `fleet kill` included — at a *different* fleet's registry. Deleted: `fleet_home_marker_path`, `_write_fleet_home_marker`, `_doctor_check_fleet_home_marker`, and the marker-mismatch half of `_marker_guard_problems` (renamed `_home_guard_problems`; its worktree check stays, because a scheduled task pinned at a worktree outlives `git worktree remove`). Doctor 23 → 22 checks. **A dead mechanism kept "for the future" is not neutral — it keeps paying its costs (a global write, a guard branch, a doctor check, a conftest sandbox line) while its benefit is hypothetical.** The pin that replaced it asserts absence, not shape: `test_no_shipped_code_references_the_marker` matches the marker-path *construction*, because a first attempt matching the word "fleet-home" went red on the unrelated phrase "the fleet-home root" in the worker-settings template error.

**Fifth, operational: editing the repo does not fix an installed plugin.** The plugin runs from `~/.claude/plugins/cache/claude-fleet/fleet/<version>/`, a full copy. The stale cache still had the hook after every repo edit and every green test run. Version bumped 0.1.0 → 0.2.0 so a refresh lands a clean directory. **A packaged tool has two truths — the repo and the installed copy — and the tests only see one of them.**

*(Ordering note: this entry is dated 2026-07-22, the real current date, and lands after an entry dated 2026-07-23. That entry's date appears to be wrong; not corrected here, since lessons.md is append-only and a past entry is not mine to edit.)*

## 2026-07-23 — operator decisions: nonce gate = (b), claim-nonce ratified, three-tier re-draft now {#2026-07-23-operator-decisions}

Docket put to Altai in-session (interface session, `AskUserQuestion`), answers verbatim-in-substance:

- **Claim-nonce gate question: (b) — a knowingly-bypassable gate.** Chosen against the spec's own narrower recommendation ((a) as the buildable floor), with §7's accounting read as the price: (b) is the only option that closes incident 1 (the 2026-07-16 dual-supervisor zombie); the bypass (shell access) is documented in the design; the gate is armed only while the heartbeat is fresh; `autoclean` is structurally exempt; the corrected §7 verb taxonomy becomes binding for the build.
- **`docs/specs/claim-nonce.md`: PROMOTED to spec-of-record.** Ratified 2026-07-23 by Altai. The three MINOR residuals from the final break gate (`a0bd194`) close in the build slice before any code ships. Status line flipped and §7 header updated in the same commit as the `OPERATOR-GATES.md` ticks — the dated line here is the record, the `Status:` line is its consequence (per the 2026-07-22 process-defect lesson).
- **`docs/specs/three-tier-command.md`: re-draft NOW, not queued.** The nonce prerequisite is discharged at the design level. Two new operator requirements to fold into the re-draft, from the same conversation: **tier-model assignment** — the human-facing interface session runs the highest-tier model, the supervisor runs the second tier (today: Fable 5 interface / Opus 4.8 supervisor) — and a **~200k-token supervisor swap band**, tightened from the drafted 300–500k, because the swap exists to save usage: the supervisor is respawned/handed off before its context gets expensive. Build still waits on the re-drafted spec's own dual-lens design gate.
- **Everything else deferred by the operator** ("wait on all operator gates, they will be closed in a short amount of time"): native-substrate's 11 ratification markers, fleet-index M1, the worker-providers doc contradiction, the two-roadmaps question, M-F shape/budget. Deferral noted in `docs/NEXT-SESSION.md` with this date.

## 2026-07-23 — three-tier re-draft: operator design inputs {#2026-07-23-three-tier-inputs}

Refinements from the same docket session, binding on the re-draft brief:

- **Swap**: supervisor self-monitors context; band **150–200k tokens**. Entering the band → hand off at the next wave/task boundary. Past 200k → strongest directive to hand off, but it finishes the current *urgent* task first — no new work. Handoff ritual = existing sup-handoff machinery: write the successor document, hand control back to the interface session.
- **Tier models by role, configurable, never hardcoded ids**: interface session = highest tier (today Fable 5), supervisor = second tier (today Opus 4.8).
- **Worker models**: supervisor's call, **Opus and Sonnet only**. Haiku is never a worker — subagent inside worker sessions only.
- **Beats**: event-driven only in v1; scheduled heartbeat deferred until a campaign demonstrably stalls for want of one.

## 2026-07-23 — operator decisions, second docket: council-advised gate closures {#2026-07-23-operator-decisions-council}

Docket put to Altai in-session after a 3-agent advisory council (risk / delivery / governance lenses, parallel, read-only) returned per-gate verdicts. The council advises; the operator alone ticked. Operator's words: "i accept all the ones which are unanimous; gate 1 partial ratification is the correct choice; gate 5 sub b i need to consider this more."

- **native-substrate contract rows: PARTIAL RATIFICATION** (council 2–1, majority adopted). All 11 `[PENDING OPERATOR RATIFICATION]` markers flipped to `RATIFIED 2026-07-23`, EXCEPT the three dead-daemon manager-report-only claims (G12 dead-daemon `rm` message; dead-daemon `stop` twin; rm/stop-do-not-revive in the transient-daemon hazard), now marked `RATIFICATION WITHHELD 2026-07-23` pending a quiet-machine capture (G9 probe). Basis: the contract's own G12 row instructed exactly this, two waves failed to re-observe the strings, and the matcher's fall-through design makes the withheld strings non-load-bearing for correctness. Noted follow-up (not a condition): the file has no `# at <sha>` pins and is unenforced by `verify_receipts.py` (NEXT-SESSION item 4).
- **fleet-index M1: QUEUED behind M-F** (unanimous). The headline economics is unmeasured and the M-F run generates exactly the data that would test it. Sub-decision (a) (tracked/ignored bundles vs gitignored-only; council split 2–1 for collapse) and sub-decision (b) (transcript tool-call counter in scope; council unanimous yes) remain OPEN — the operator is explicitly still considering (b).
- **worker-providers design doc: RE-STATUSED** (unanimous). Header flipped from `approved design — ready for implementation plan` to `spike-negative — §4 dead as written`, per its own §4.2 NEGATIVE gating spike; `docs/longcat-fleet-usage.md` named the working alternative of record. `docs/specs/providers.md` re-base-or-park stays open.
- **Two roadmaps: RETIRE the C-campaign/soak framing as superseded history** (unanimous, with condition). Load-bearing condition: PLAN §0's still-binding doctrine (worktree isolation, W-V discipline, RESULT contract, dual-lens gates) must be re-homed to a live surface BEFORE the retire edits land. Mark superseded, never delete. The retire is queued work; only the decision is recorded today.
- **M-F: PREEMPTS the queue** (unanimous). Dogfood-outward run, overdue since stupidbox 2026-07-09. Budget envelope NOT yet signed — stays an open gate; M-F does not dispatch until it is. Council framings on record: ~$75–100 timeboxed vs. token-ceiling-cap enforcement (no USD source exists under `--bg`, G3) vs. envelope-as-dispatchable-ceiling.

**Addendum (2026-07-23, same session):** role→model config is **tier-based, never model-id-based** — roles bind to abstract tiers (highest / second / third) and a resolver maps tier → concrete model from what is *currently available*; model ids appear only as illustrative examples. Must work with a non-Anthropic provider (`docs/longcat-fleet-usage.md` is the working alternative of record, re-statused 2026-07-23): tier mapping resolves per provider, with explicit stated semantics when a provider lacks a tier.

**Addendum (2026-07-23, manager refinement during the re-draft, binding — supersedes the "today Fable 5 / Opus 4.8" framing where it reads as the config itself):**

- **Tier-based, never model-id-based.** Roles (interface / supervisor / worker) bind to abstract tiers (highest / second / third); a resolver maps tier → concrete model at dispatch time from the models *currently available*. Concrete ids (Fable 5, Opus 4.8) are illustrative of today's Anthropic resolution only, never normative.
- **Provider-agnostic; must work with a non-Anthropic provider.** `docs/longcat-fleet-usage.md` is the working alternative of record (per-`CLAUDE_CONFIG_DIR` isolated daemon namespace). The tier→model table lives in that namespace's **daemon env** (`ANTHROPIC_DEFAULT_OPUS_MODEL` etc.), set by the launcher, not by fleet. Cross-provider fleet = separate namespaces (one daemon each); a role resolves per namespace. Provider-lacks-a-tier ⇒ omit `--model` (let the namespace default govern) or accept the CLI `model_not_found` refusal; a fleet pre-flight tier-resolution check is `[UNBUILT]`.
- **Receipted (at `235421e5`):** `bin/fleet.py` has ZERO model-id / `CLAUDE_CONFIG_DIR` / `ANTHROPIC_` / `--provider` surface (grep 0/0). The only shipped model surface is `--model <tier-alias>` at spawn/handoff; resolution is entirely the daemon env. Role→tier policy is routed to `supervisor/GOALS.md`; a machine-read of it is `[UNBUILT]`. Full analysis: `docs/specs/three-tier-command.md` §3.

## 2026-07-23 — operator decisions, third docket: cap doctrine, fleet-index sub-answers, M-F unblocked {#2026-07-23-operator-decisions-caps}

Council round 2 (same three advisory agents, deeper read) put verdicts to Altai; operator adopted (a) and (b) as recommended and REPLACED the envelope question with a doctrine change:

- **Cap doctrine (NEW, standing): no fleet-enforced token or USD ceilings — for workers or managers.** Operator is on Claude Max 20x; the plan's own usage limits are the cap for every session alike, and fleet's existing limit-park/resume machinery is the recovery path. Cost/token *counting* becomes an on/off flag, **default off**. Operator's words: "for now we should disable the token limits or cost limits within the fleet repo. cost counting should be a flag that can be enabled and disabled"; "workers should be also be capped the same way as managers." Retires PLAN §0.4's ceiling denomination — fold into the queued C/soak-framing retirement (the §0 re-home).
- **Worker context band (NEW, binding on the in-flight three-tier re-draft): the 150–200k context band applies to WORKERS, not only supervisors.** Extends `#2026-07-23-three-tier-inputs`: a worker self-monitors context; entering the band → hand off/respawn at the next task boundary. Operator's rationale: unbounded worker counts and contexts drift the parts apart and the waste reappears as reconciliation effort — keep worker counts small, respawn before context gets expensive.
- **fleet-index M1 (a): collapse to gitignored-only.** Tracked-mode defends a query path absent from M1; the worktree hazard exists only because tracked mode does; re-add at M2 is an additive config key. Review finding 2b re-dispositioned: committing `.fleet-index/` is documented-unsupported in M1 (never leave an Accepted finding pointing at deleted text — the spec edit lands with the M1 build).
- **fleet-index M1 (b): tokens-primary, counter demoted.** Acceptance criterion 1 = `input_tokens` delta from the existing Stop-hook outcome telemetry (zero new parsing of the unversioned transcript format); ≥3 paired A/B runs, n=1 is noise. The transcript tool-call counter is a volatile, sunset-marked `tools/` diagnostic only. M1 fully unblocked, queued behind M-F.
- **M-F: unblocked to dispatch.** No envelope; discipline is structural (small worker count, context band, escalate on anomaly).

**Second addendum (2026-07-23, operator, binding — folds as re-draft wave 3):**

- **Supervisor tier PROMOTED to top tier (Fable class).** Clarified division: the interface session holds the *long-term goals*; the supervisor is in charge of *solid plans, details, and splitting tasks* to workers — planning quality justifies top tier, not second.
- **Top-tier usage limit is ~half the standard limit → the role→tier binding becomes a PREFERENCE CHAIN, not a single tier.** Supervisor prefers the top tier and auto-falls back to the second tier (today Opus) when the top tier's usage limit is hit, returning once the reset horizon passes. Folds into the existing usage-limit detection/park/resume machinery (G11, `limited`, `resume-limited`); the exact mechanism is the spec's call and goes through the gate.
- **Worker band re-confirmed by the operator in-session** ("workers should also have a cap for cost saving") — consistent with the third-docket cap doctrine; the spec's "second tier only" scoping (line ~980) is retired.
- **Manager reading of the cap doctrine vs the spec's B4 hard arm:** "no fleet-enforced token or USD ceilings" retires *spend* ceilings (the `--token-ceiling` denomination), not the *context-band* handoff enforcement — a context band is a freshness mechanism, not a budget. Wave 3 states this reading in-spec; the operator rules on it at ratification.

**Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — **cost/spend ceilings are gone unless the counting flag puts them back** (flag default off; enabling it may re-arm spend caps). The context band (150–200k, supervisors AND workers) is a freshness mechanism, not a budget, and its enforcement stays. Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before ratification.

## 2026-07-23 — three-tier spec RATIFIED; H1 harness hardening shipped {#2026-07-23-three-tier-ratified}

**`docs/specs/three-tier-command.md`: RATIFIED spec-of-record by Altai, 2026-07-23** (in-session docket, after the full M-F re-draft pipeline: 5 waves, 3 full dual-lens gate rounds + 2 confirmation passes, ~30 findings closed, 0 spurious fixes, final break-lens merge verdict "fit for operator ratification"). Content as ratified: interface tier holds long-term goals at top tier; supervisor owns plans/details/task-splitting at TOP tier with a usage-limit fallback chain to second tier (limit-arm honestly lossy — doctrine: hand off on the band before the limit); 150–200k context band binds supervisors AND workers; tier-based provider-agnostic role→model resolver; cost caps flag-gated off. Disclosed at ratification: three claim-nonce build-slice prerequisites (rule-1 guard, FLEET_WORKER refusal, limited-holder transfer branch) — they gate the BUILD. Build order: nonce build → three-tier build; M-F dogfood preempts both.

**H1 shipped and merged**: `tools/verify_receipts.py` now errors under `--strict` on any receipt-shaped text it cannot classify (gutters, tabs, tilde fences, inline spans, stray directives, unterminated fences), founding-artifact replay red, 20-mutation hostile review + fix wave (11/11 mutation REDs serially), test_receipts 13→49, suite 1420/8 both interpreters. Pin tier re-run green + stamped at claude 2.1.218 (10th vendor-bump gate exercise; no catch this time).

**Process changes earned (M-F re-draft campaign, anti-ritual gate):**

1. **A binding operator ruling lands as a commit on the target branch BEFORE any wave cites it** (→ template v1.9). The manager steered the cost-cap ruling into a running wave while the ruling's commit sat only on `main`; the spec then declared the question "SETTLED" citing a record its own tree could not witness — a manager-owned CRITICAL (ND5) that reversed a fit-for-ratification merge verdict for a round. Both lenses caught it independently; the spec lens proved the ruling genuine and named the one-command cure (merge first). Steer text is delivery, never provenance.
2. **Receipt-shaped text the parser never sees is the silent-drop class, third recurrence** — after the daemon check's fabricated fixture and the ul-parser's silent skipif. Four gutter-indented receipts rode through two full gate rounds unverified; the founding-artifact replay then found 16 evasions where the probe knew of 4. `verify_receipts.py` now errors under `--strict` on any unclassifiable receipt shape anywhere in the file (tabs, gutters, tilde fences, inline spans, stray directives, unterminated fences). Corollary held: **when the real artifact exists, the fixture IS the artifact** — and it knew more than the probe did.
3. **Mutation-test the detector you just hardened**: hostile review ran 20 mutations against the new H1 detector and its suite survived 6, including a compound suite-green blinding — on the very tool whose job is preventing green-while-blind. Every surviving mutation now has a named catching test, re-proven by re-running the exact mutation serially with byte-identical restores.

## 2026-07-23 — Overnight autonomous dogfood (M-F external #2: cc-oracle; operator asleep, council-governed)

First fully-autonomous overnight campaign: operator pre-authorized a 3-councilor + synthesis council for every operator-gated decision, full record in `docs/OVERNIGHT-2026-07-23.md`. Shipped: cc-oracle `mf/integration` 147/0 both interpreters, MERGE VERDICT sound (2 feature branches, 2 fix waves, 3 hostile-review rounds, UNPUSHED per fence — operator pushes); fleet doc-sync wave MERGED+PUSHED (`1d878cf`, band 150–200k across skills/SPEC, GOALS as proposal only); M1 evidence report `docs/mf-oracle-m1-evidence.md`.

**THE lesson — the freeze verdict scored a live catch, and the council majority was wrong.** `sup-boot` froze (holder roster-gone, heartbeat fresh). Council ruled seize-now 2–1 on the manager's evidence ("the fresh heartbeat is the dead holder's final checkpoint; no second writer structurally possible"). FALSE: the old manager session was still alive finishing close-out — 3 new checkpoints landed 03:22–03:32Z while the new session ran. Only the mechanical absence of a seize flag prevented a two-supervisor incident; the clean stale-heartbeat seize happened at 04:32Z. **Evidence has a freshness axis: a council synthesizes from the snapshot it was briefed on — re-verify the load-bearing fact at ACT time, not ruling time.** Corollary: "roster-gone" ≠ dead (close-out turns outlive roster presence). Cassandra's paranoid dissent was the correct model; preserve dissents by name so the morning audit can score them.
- **Council mechanics that worked**: 3 distinct personalities (risk/delivery/strategy) + synthesis, each councilor inspecting repos read-only before voting; 3-way project split resolved by synthesis with explicit "why the losers lose TONIGHT" (pmbot: root token files + shared remote with live VPS token-minting agent + stale fleet knowledge; exPardus: five subrepos parked on auto-deploy `dev`). Both vetoes were risk-class discoveries the manager did not have. Council CANNOT tick OPERATOR-GATES boxes — verdicts recorded as provisional in the overnight ledger for morning ratification.
- **`dontask` mode is auto-deny-everything-unlisted** — with no allowlist anywhere it denies Write/Edit/pytest/EnterWorktree/subagent-Bash; all 3 workers burned turns probing. Fix that became doctrine: per-worktree `.claude/settings.local.json` allowlist (python/py/pytest/git/claude + Write/Edit) with **deny rules as hard fences** (`Bash(git push:*)`, `Bash(claude plugin:*)`) — the no-push fence went from promissory to enforced. spawn-etiquette amended.
- **Registry task snapshot is 200 chars** (`state/fleet.json` `task` field) — respawn-without-`--task` truncation root-caused at last (stupidbox lesson's mechanism); `send @file` ALSO truncated; inline fork-steer sends carry full. Fleet fix candidates filed: store full task/path+hash; `respawn --mode` missing; heredoc git commits denied under prefix allowlists (use `-m`).
- **Adversarial review earned its cost twice more**: round 1 found 1 CRIT (prune age-deletes user files in configurable `state_dir`) + 1 MAJ (unanchored idiom substrings false-block: 10/11 benign texts blocked) past 118/0 green and two careful builders. Fix-waves-mint-defects fired **5/5 lifetime**: wave 1 shipped a SPURIOUS-FIX with the WRONG marketplace name copied from a stale plan doc ("fresh doc born stale" class) **whose own test encoded the same wrong name** — test-theater confirmed by the reviewer reading the manifest JSON. Fix: derive identity from manifests at import + agreement test. Reviewer discipline note worth keeping: it re-verified its own void fault-injections before trusting a green ("first two injection attempts failed to apply and produced void green runs").
- **Same-reviewer continuation via SendMessage worked** for re-review + final narrow gate (context intact, verdicts comparable, SPURIOUS-FIX vocabulary used). Narrow final gate stayed narrow.
- Ops: worker preamble auto-prepends journal duty to task files; `fleet status` idle vs respawn "turn is running" race (resolved `--force`); test-count noise again (1415/13 vs 1420/8, total 1428 both — env-conditional skips; trust totals + zero-failures, re-count on quiet machine).


## 2026-07-24 — Day-2 continuation: nonce + three-tier build slices shipped, queue drained

Same autonomous session as `#2026-07-23-overnight-dogfood` (survived a ~10h host outage mid-run: same-sid resume, `sup-heartbeat` wart-path recovery — 4th live exercise; durable-sessions design absorbed the blackout with zero loss). Shipped after the outage: claim-nonce build slice (`2d58eba`, +359 tests), native-substrate receipts (`d10e08c`), C/soak retirement (`31a21f8`), residuals 3+4 (`f09df14`), three-tier build slice (`c6fde34`, +215 tests). Close: 1897/13 both floors.

- **The shipped gate immediately gated its own manager — three refusal classes in the first hour, all correct, all recovered**: (1) post-mint bare `sup-checkpoint` (holder unaware the mint flipped protocol — UX: mint output should say "carry this"); (2) `spawn` without `--nonce` (lifecycle verbs gated too); (3) respawn ditto. **Merging machinery that governs the session doing the merging = the sharpest possible dogfood**; the live claim's legacy→nonce upgrade worked exactly as §5.3 specifies. Protocol shape learned live: sup-checkpoint mints+ROTATES; lifecycle verbs present-without-rotating.
- **Band doctrine's first live exercises: 4 lossless BAND-HANDOFFs** (nonce ×2, tt ×2) — journal + successor-map pattern made every one seamless; two of them stopped BEFORE design-open items rather than rushing near the band, which is the doctrine working as intended. Counter-tension logged: the manager session (1M window) rode past 200k — the ratified number assumes a 200k window; operator question filed, not unilaterally changed.
- **Council machinery scaled down cleanly**: a one-agent 3-lens mini-council resolved the E(2) FLEET_WORKER spec-contradiction with code-verified grounding (successor shape unforgeable via NAME_RE), and the tt build later EXTENDED that ruling within its own rationale (family widening) instead of reversing it — precedent: rulings carry their grounding so successors can extend without re-litigating.
- **Fix-waves-mint-defects → 5/5 lifetime** with the cleanest exhibit yet: the marketplace-name SPURIOUS-FIX (wrong name from a stale plan doc, its own test encoding the same wrong name = perfect theater, caught only by the reviewer reading the manifest JSON). Fix class: derive identity from the artifact of record at import + agreement test.
- **Fences must be phrased in worker vocabulary**: "no push, no merge" read as "no push to main" → branch pushed + draft PR opened (harmless, own repo). Same class as heredoc-commit denials. Template phrasing now: "no `git push` of ANY ref". Also: harness preamble ("open a draft PR") can CONTRADICT task fences — task file must override explicitly.
- **Honest-refusal pattern held under pressure**: ns-receipts refused to fabricate receipts for the RATIFICATION-WITHHELD strings (every candidate encoding = fabrication or side-effect; oracle-consulted) — the right failure mode for an evidence harness.
- Verify-before-fix earned it again: residual worker re-verified each carried LOW against post-nonce main before touching (one had been partially rewritten by the token flow).


## 2026-07-24 — operator morning queue cleared + autonomous day-3 opened

- **Overnight council verdicts ratified by operator**: G-1 ratify+HARDEN (freeze message must say "holder may still be closing out; roster-gone ≠ dead" — build item dispatched to small-fixes worker); G-2/G-3 ratified (claude-oracle target, parallel-doc-worker conditions stand as precedent); G-4 ratified (narrow FLEET_WORKER arm + E(2) family widening).
- **fleet-index M1 go/no-go: DEFERRED, then reframed into an order** — operator: parallel-read dup (the 2.5% evidence) is not the real cost; the real cost is *long-term multi-session work on a codebase*; `fleet q` is "genuinely useful" standalone. **Ordered full M1+M2 build** (indexer + digest injection for later A/B + `fleet q` + permissions migration). Spec re-grounding dispatched (fleetq-spec worker); sequence spec → gate → ratify → build.
- **Both GOALS proposals applied by operator** (`3ccb2d5`): tier policy + band + checkpoint cadence + bypass ack + machine-parsed tier-policy block — the resolver now reads live policy (chain top,second; workers second,third; top=opus/second=opus/third=sonnet). Three-tier §7.2 amended to **holder-alone** (spec text now matches built `5a8860b`); receipts 56/56 strict post-edit.
- **cc-oracle v0.2.0 pushed** by operator authorization: `6997d81..8656f32` on the public repo, 147/0 both interpreters. Installed plugin cache still serves the old version until updated — relevant to any "does oracle work for workers" measurement.
- **sup-spawn choreography rulings ratified**: (1) gen-0 = `sup|<launch-id>|boot`, no `supervisor`-named record ever; `"supervisor"` in send/kill/respawn = logical name resolved via claim to the holder's record; contradicting ratified prose amended by operator order (worker applying). (2) missing §10.2 bypass-ack in GOALS ⇒ sup-spawn WARNS and proceeds.
- **NONCE refusal class #4 — self-inflicted truncation**: manager piped its own `sup-boot` through `head -30` and lost the printed nonce (it is the LAST line of the boot bundle). §5.7 held exactly as written: wait-out doesn't apply to a roster-live holder, escalated to operator, manual lever (delete `supervisor/INCARNATION`) authorized + exercised, fresh boot, nonce captured via full-output-to-file. **Doctrine: never pipe `sup-boot`/`sup-checkpoint` through head/tail — redirect to a file, grep the NONCE line.**
- **`send @file` carried FULL at 2.1KB on the fork-steer path** (composed task-file tail verified byte-intact) — friction item 7's truncation is size-dependent or mailbox-path-only; root cause still unconfirmed, doctrine (prefer spawn `--task @file` / inline send for long content) unchanged.
- Operator standing directive for this run: autonomous; operator-gated questions go to a **4-councilor council of differing personalities + synthesis**; act on synthesis; record everything for morning ratification.
- **`core.autocrlf=true` breaks the byte-restore proof.** `git show HEAD:bin/fleet.py | sha256sum` does NOT equal `sha256sum bin/fleet.py` on a **clean** tree — the blob is LF, the file is CRLF, and every one of its ~12k lines differs. A fault-injection round whose restore step compares those two hashes reads CLEAN as DIRTY. **Compare EOL-normalised, or use `git status --porcelain` as the authority.** (Source: tomb-rb micro-confirmation gate. Companion, learned by paying for it in `fix/handoff-seams` the same day: `git checkout -- <file>` to undo an injection reverts the **whole uncommitted file** — commit BEFORE injecting.) Template → **v1.10**.
- **Handoff succession seams, found by USING the protocol** (`fix/handoff-seams`, three defects, 2039→2063 tests): `sup-handoff-begin` recorded the successor it dispatched **nowhere the abort path could read it** — token hash into the claim, abort flag only on begin's own dispatch-failure/DOA branches — so a successor that dispatched, joined the roster, then died before HANDSHAKE matched neither of abort's evidence arms and **the handoff was unabortable in exactly the window the abort verb exists for**. The tell was in the test suite the whole time: the end-to-end timeout drill *fabricated an abort flag by hand* to make abort proceed. **A fixture that manufactures the evidence production cannot produce is the defect, written down and passing.** Two smaller ones rode along: three plaintext one-shot tokens accumulated in `state/` because §5.9's unlink runs only on complete/abort and neither fired for a stillborn attempt (fix: a pure sweep predicate that protects the pending successor's file and the holder's, run at begin/complete/abort/sup-boot); and the runbook's abort recipe omitted `--nonce`, so following the doc verbatim earned an rc 4 mid-succession — **linted now, because the same recipe is copied across four surfaces and an under-swept doc fix is how the last three doc defects survived**.

## 2026-07-26/27 — day-4: the three-tier switch-over, two stacked wedges, and the merge filed as housekeeping {#2026-07-26-day4}

**THE lesson: a guard postcondition that one legitimate caller class can never satisfy is a liveness defect, not a strict guard.** B6 refuses a released claim whose `released_by_sid` is roster-live — doctrine "release, THEN stop". The interface tier never exits, so once an interface session held and released the claim, *nobody* could boot, including the releaser (rule 1 has no caller exception). Root cause, council framing: **B6 keys on a proxy** (liveness) for a predicate ("the prior holder may still act as supervisor"); the proxy stopped meaning what it meant. Corollary earned the same night: **a verb that clears a state must not be gated on that state** — `fleet kill` was refused BY the wedge it clears, which makes the documented no-sid bypass load-bearing infrastructure, not a convenience (claim-nonce §7.2, UNRATIFIED).

**Two repairs were proposed and both died on evidence** — kept because they are what a smart body reaches for next: **(a+)** post-hoc attestation keyed on `caller sid == released_by_sid` is **forgeable** (`--sid` override plus one env var, and the expected answer is published in the claim file every body can read); **(e)** "refuse only if the live releaser has a `sup|` registry record" is an **absence predicate** — `clean` deletes records, autoclean archives them, and `sup-spawn` mints them with `session_id: None`, so it fails OPEN during exactly the dispatch window B6 exists for. **Absence is not evidence on this substrate.** The distinction that survives: reading a record's ABSENCE to permit fails open; reading the caller's OWN record's PRESENCE to permit fails closed.

**Second wedge, stacked underneath: the daemon donates the first dispatch's env to every later session.** `_worker_env` stamps `FLEET_WORKER` and `dispatch_bg` passes it to `Popen`, but that only sets a *launcher that asks the daemon*; the daemon hosts the session and was started by whichever dispatch came first. A supervisor launched after a worker carried `FLEET_WORKER=<that worker>`, and §6.5 then refuses all seven holder verbs — so it can TAKE a claim (`cmd_sup_boot` does not call `_require_claim_holder`) and never beat, checkpoint or release it. **Clearing wedge 1 alone would have produced wedge 2.** This answered a question the source itself marked UNOBSERVED. Mitigation until fixed: let the transient daemon idle-exit and make `sup-spawn` the dispatch that starts the new one.

**The process lesson that cost the most: handover length WAS the failure mode.** Five supervisor incarnations each burned a full context reading long handovers and merged almost nothing, while `fix/handoff-seams` — carrying a commit literally titled *"record the pending successor so a stillborn handoff is abortable"* — sat unmerged as "queue item 5, housekeeping" through all five, and the hole it patches ate six supervisors (five stillbirths day 3, three more day 4). The fix was an interface priority ruling plus a **one-page "merge first, read second" brief**; that body merged the blocker on its first turn. **Infrastructure that repairs the supervisor's own recovery path is never housekeeping.**

**Fix-waves-mint-defects reached 7/7 this campaign, and twice the defect was traceable to a SUPERVISOR'S RULING rather than a builder's slip** (R1 made rival successors bootable on top of a single-successor protocol; R-3's "gate ahead of the claim read" closes only when the registry resolves). Two sibling lessons: **a pin written against the mechanism you fixed does not cover the mechanism you introduced** (three instances in one campaign), and **an allowlist entry is a CLAIM, exactly like a receipt or a citation** — a new detector shipped with the seventh instance of its own class blessed, for a stated reason that was false. *The first thing to check about a detector is not what it catches but what it excuses.*

**Alarm hygiene**: the handoff template hands the successor a `sup-checkpoint` with no `--nonce`, so the normal handoff path files a continuity refusal and lights `fleet doctor`'s second-body alarm — **an alarm fired by the happy path trains the operator to ignore the row that will one day be real.** Also found: `fleet spawn` SILENTLY OVERWRITES an operator-authored `state/tasks/<workername>.md`, so four councilor briefs became stubs telling each councilor to read the file it was already reading — never author a brief at that path.

**Three-tier, live**: first successful supervisor handoffs since day 3 (three clean band handoffs in a row), and the first live §10.4 respawn-of-holder — which **stalls silently waiting on the holder's own release with no phase surface**, so a timeout-bound caller sees a hang, and the successor was never dispatched when that client died. Retirement and succession are not atomic. Working succession recipe: `sup-release` → **the interface stops the retired body** → fresh `sup-spawn`, because a fleet-launched body never leaves the roster on its own and therefore cannot complete its own stand-down. Standing rule from the whole arc: **the claim belongs to a role, not a body; an interface session must never run `sup-boot`.**

## 2026-07-27 — the docket cleared: all eight operator gates ruled in one pass {#2026-07-27-operator-decisions}

All eight open gates in `docs/OPERATOR-GATES.md` were put to Altai one at a time in a single interface session and ruled. Each entry there carries its own full reasoning; this is the index plus what the pass itself taught.

- **`fix/identity-registry-judges` → A, merge now and fix on `main`.** The surviving MAJOR is not a regression — the branch strictly narrows a door standing wide open on `main` — and the remedy is small: gate `not_initialized` on the `fleet.json.corrupt.*` artifact glob (as fleet already does at `:7518`), NOT closing the carve-out, which a mutant proved kills 39 tests. **Owed on `main`: that glob gate.** The supervisor's own named tension was accepted, not waved off — this relocates wave 3, it does not avoid it.
- **§6.5 worker-turn gate → no demotion, registry-keyed gate stands.** The contradiction that motivated demotion does not exist: `SPEC.md:204` constrains the *key*, ratified §6.5 D5 requires the refusal to *exist*, and a registry-keyed gate satisfies both. **Doctrine: a coverage limit is fixed by extending coverage, never by deleting the covered half.** Demoting would also have silently reversed ratified §6.1 D1.
- **Identity invariant → becomes doctrine, with a scope clause.** Binding: *inference may select the **subject of a measurement** but may not supply the **grounds of a refusal**; donation only ever ADDS a `FLEET_WORKER` stamp and nothing removes one, so **presence is unsound evidence and absence is sound**.* Chosen because it rests on a mechanical property rather than on who authored it, and because it was verified by driving. This is the same asymmetry day-4 reached from the other side ("absence is not evidence on this substrate") — the two are reconciled by *which direction* the inference runs.
- **`fleet respawn` ceiling gap → close it, on the `--task` discriminator.** `--task` absent = §11.4 recovery, permitted over the ceiling; `--task` supplied = §11.3 dispatch, refused. Exempting would have made the 200k ceiling **bypassable by verb choice**, reducing the other three call sites to decoration.
- **`fleet doctor` quarantine → flag-gated.** Diagnose by default; `fleet doctor --repair` does the rename; the `:11947` refusal restated to name the flag. Read-only was rejected because that message would then point at a command that no longer repairs.
- **`SPEC.md:204` → restated** after checking source rather than softening prose. `FLEET_WORKER` is load-bearing at two sites in **opposite directions** (absence exempts the interface from the §11.3 ceiling; presence refuses the supervisor claim) and is **not** load-bearing for the destructive-command guard at all — that keys on caller sid/ownership, pinned by `TestAWorkerIsNotExempt`.
- **§7 arming envelope → stands, with the missing disarm as owed work.** The released-claim arm has no heartbeat to age out of (§6.3 strips it) and is bounded only by roster lifetime. Ratified because the alternative leaves `fleet clean --yes` reachable from any third body in the `released` window. **The "no in-fleet exit" finding is recorded as a scheduled defect, explicitly NOT ratified as a property of the design.**
- **`docs/specs/providers.md` → parked**, not re-based and not deleted. Obsolete twice over; `docs/longcat-fleet-usage.md` is the working alternative of record. Kept as the record of what was tried.

**Two defects the pass itself surfaced, both invisible from any single gate:**

**A test asserted the docket is never empty.** `TestOperatorGatesFile` carried `assert open_gates, "no open gates parse out of the shipped file"` — so clearing every gate turned a *correct* file RED. **A cleared docket is this file's SUCCESS state.** The assertion encoded "there is always pending work" as a format invariant. Replaced with the two things actually worth pinning — open gates are questions, settled gates carry an answer and a date — the second added so relaxing the first cannot let an empty file pass. Same class as the day-4 allowlist lesson: *the first thing to check about a check is not what it catches but what it assumes.*

**Two stale line pointers, and the file contradicted itself.** The §7 gate cited `claim-nonce.md:1817` / `:1866` as the false sentences; those lines are `sup-handoff-abort` arms and supersession — the real sites are §7's decision block and the accounting bullet beneath it. **Line-number citations in prose rot silently and nothing tests them** (the receipt harness covers fenced blocks, not inline `:NNNN` refs). Separately, the gates file's own format section said settled gates stay "in place" while its closing line said "move it here", and every settled gate followed the closing line — corrected to match practice. **Doctrine reaffirmed by both: verify a cited location before restating what it says; the gate text is a claim like any other.**

## 2026-07-27 — day-5 interface tier: the surface lied about the shape of the system {#2026-07-27-day5-surface}

Interface-tier session, operator away and explicitly autonomous. Two operator asks — align the fleet
skill/plugin docs with three-tier, and align the statusline with it while removing the cost field —
turned into a drift audit, because **you cannot align a description without measuring the thing**.

**THE lesson: a document describing a CLI must be re-derived from `--help`, never from memory or from
the last person who edited it.** `skills/fleet/SKILL.md` — the file every fleet session actually reads —
was missing **four shipped verbs entirely** (`sup-spawn`, `sup-context`, `sup-decision`, `knowledge`),
and its startup ritual told an interface session to *become* the supervisor, which is precisely the
maneuver that wedged a claim for hours on day 4. `supervisor.md` carried **two `[UNBUILT]` tags on
features that are built** (the 200k ceiling — three call sites, measured — and §10.4 kill/respawn).
One `fleet --help` and two greps found all six. Nothing tests prose against `add_parser`, so this rots
by default; the `[UNBUILT]` sweep now has a demonstrated yield rather than a hypothetical one.

**A flat view of a tiered system is a lying view.** The statusline rendered one roster, so a fleet
with one worker and fourteen retired `sup|…|boot` husks read as fifteen workers, while the field that
decides whether anything can be dispatched — *does anyone hold the claim* — was not on the line at
all. The fix is a projection, not a filter: `status_snapshot()` now carries `workers[].tier` (the
BODY, from fleet's own `_is_supervisor_shaped` — a released or seized supervisor keeps its name) and
`snap["supervisor"]` (the CLAIM). **They are different questions and a view that conflates them will
report a husk as command.** First live render immediately paid: `sup held 14m  8 bodies  work 1
idle 24  +9 dead` — the eight-body alarm is true, and was invisible before.

**`unknown` must be a rendered word, never silence.** The claim projection never raises, because the
statusline swallows exceptions into a *blank line with no reason*; every failure degrades to
`unknown`. Day-4's "absence is not evidence on this substrate" applied to a view: **"cannot read the
claim" must never present as "there is no supervisor".** Same reasoning kills the age on a `released`
claim — §6.3 strips `heartbeat_at`, so rendering an age there invents staleness out of a correct
stand-down.

**Removing a field is a doctrine change, so say why in the code.** The cost counter went because
under the Max-20x cap doctrine the plan limits spend, fleet enforces no dollar ceiling, and native
dispatch records no cost at all — it summed rows that report nothing. Pinned by a test, because
`fleet status` still totals cost and the field is one edit from coming back.

**Line-number citations are a recurring tax and the remedy is mechanical.** Adding ~59 lines above the
four `retired_sids` writers turned both floors red — the *second* time in two days, the first being a
merge. `TestRetiredSidWritersAreWhereTheyAreCited` did exactly its job: re-pin and move on. **Budget
the re-pin into any edit that inserts above line ~4600 of `bin/fleet.py`**, and warn the supervisor
before it hits the same red on the merged tree, so it re-pins forward instead of reverting your numbers.

**Process, and it is a real miss: the §8 routing surface exists — use it.** I relayed five settled
operator gates to the supervisor as a `fleet send` steer. It was right and it acted on it, but it had
to *record the answer itself* via `sup-decision --answer` to stop `sup-status` asserting "needs
operator" about a question the operator had answered. **The interface answers a parked decision through
`fleet sup-decision --answer`, not through prose in a steer** — otherwise the routing state and the
truth diverge, and the divergence is only visible from `sup-status`.

**Steering that worked, cheaply:** the queue reorder that put `fix/identity-registry-judges` *ahead*
of the fleet-q merge — enter the tree you were gated against, not the tree the next campaign leaves
behind — and telling the supervisor which files the interface was holding dirty, with the expected
red and its remedy. It had already staged the merge in a scratch worktree and fast-forwarded the
moment the commit landed. **Naming the collision beats discovering it.**

**Open, found by a worker and worth more than the slice that found it:** `id-glob` measured that
`fleet status` / `peek` / `result` *do* rename a corrupt registry aside — so terminal-surface D4 and
the CLAUDE.md rule *"views never quarantine"* are both false of shipped code. Ordered out of the
doctor slice into its own commit with the driven receipt: the two disagree about what today's default
behaviour even is, and a doc that is wrong about the default cannot review a change to it.

## 2026-07-27 evening — the fleet stopped for 15h and nobody knew {#2026-07-27-evening-outage}

Found on an operator's "status update": **zero workers running, no claim held**. The last supervisor
had released *correctly* at 04:00:41Z over the ceiling after three stillborn handoffs — and nothing
restarted it. Twenty-nine commits of finished work sat unpushed the whole time.

**MEASURE THE OUTAGE BEFORE YOU DRAW THE LESSON FROM IT.** My first report said "~15 hours", read off
worker staleness. The operator knew a power cut covered part of it, so it got measured against the
Windows event log (6008 unexpected shutdown, 41 dirty reboot, 6005 log service start) rather than
inferred:

| window | span |
|---|---|
| total dark (release → new claim) | **12h 53m** |
| power cut (06:10:40Z → 15:25:07Z) | 9h 14m |
| up-but-stopped A (release 04:00:41Z → shutdown) | **2h 09m** |
| up-but-stopped B (reboot 15:25:07Z → restart 16:54:06Z) | **1h 28m** |
| **genuinely uncovered** | **3h 38m** |

The corrected number is *worse* for the design, not better. **3h38m is the part no amount of hardware
explains** — and window B is the sharper of the two, because the machine came back *healthy* with the
fleet still dead and nothing anywhere said so.

**THE lesson: a clean shutdown with no reader is indistinguishable from a healthy fleet.** Every
mechanism worked. The release was clean, the journal entry was excellent, the reason was recorded,
`sup-status` said `RELEASED` the entire time. **None of it was addressed to anyone.** The statusline
rendered `sup released` in the same calm white as `sup held` — the outage was *on screen* and read as
a resting state. **A signal nobody is obliged to read is not a signal**, and the fix is not more
recording: it is making the pull surfaces render an outage AS an outage.

**FLEET HAS NO POST-REBOOT RESTART PATH, and window B is its receipt.** Durable-sessions-survive-
reboots was designed and is true of *workers*; the command tier is not, so a box that comes back has
a full roster and nobody in charge. **The operator refused a fleet-side mechanism for this and was
right:** any watcher would either fire in a session nobody asked to be fleet-aware (D7) or dispatch a
replacement with no operator in the loop, which is how two live supervisors happen. **The revival
trigger is the operator relaunching their interface session**, so the restart path is a step in the
skill's startup ritual — revive when GOALS is active and no supervisor is live, and say so out loud.
The general form: *when the honest mechanism would have to be an injection or an autonomous actor,
the right place for the trigger is the human action that was going to happen anyway.*

**The staleness sweep silently skipped the outage too — and the fix was to delete the timer, not to
configure it.** `claude-fleet-autoclean` carried `StartWhenAvailable: False`, so the missed
occurrence was dropped rather than run at boot: last run 02:22Z, the 08:22Z occurrence lost to the
power cut, no catch-up when the machine returned, next fire 20:22Z — an 18-hour gap in a 6-hourly
guard, found only because the outage prompted a look. My proposed fix was to set the flag in the
`fleet init --autoclean` code path. **The operator retired the timer instead**: `fleet autoclean`
becomes a step on the supervisor's watchtower beat and in the interface's startup ritual. **A timer
sweeps when the clock says so; a beat sweeps when the fleet is alive — which is the condition that
makes sweeping necessary in the first place.** It also deletes a whole class of problem rather than
patching one instance of it: no Task Scheduler, no machine-local install state, no missed-run policy
to get wrong, and nothing to re-verify per machine. **Fixing the setting would have been the smaller
change and the worse one.**

**Operator's four rulings (evening pass, recorded in `docs/OPERATOR-GATES.md`):** extend §11.3 to name
task-bearing `respawn` + `sup-spawn` (with a binding *grep-don't-trust-the-line-numbers* condition);
clear the resolved abort flag; delete the two token-free orphan successor files; and build succession
as **a loud pull signal plus one verb, explicitly not a hook and explicitly not auto-spawn**.

**A hook was the obvious answer and the wrong one, for the second time.** The ask was "a hook so the
interface can bring up a new supervisor". But the interface is an ordinary Claude Code session — a
hook that reaches it fires in **every** session on the machine, which is exactly the D7 leak deleted
on 2026-07-22. Same shape as that day's lesson: *the question is not "make this injection smaller",
it is "is this injection the plugin's to make"*. The buildable version is pull-only: record a
machine-readable succession-needed fact **with its cause** (ceiling AND usage-limit park — `sup-release`
records prose nobody parses), render it loudly on statusline/`sup-status`/`doctor`, and collapse the
three-step maneuver into one verb — **including the middle step only the interface can perform**,
since B6 refuses a released claim whose releaser is still roster-live, so a supervisor can never
complete its own stand-down. Auto-spawn refused: a body dispatching its own replacement with nobody
in the loop is how two live supervisors happen.

**`doctor` was 3 FAIL and two of them were stale.** A resolved abort flag and an answered decision
both kept failing. **A permanently-red doctor is a disabled doctor** — the operator's stated ground
for clearing. Cleared: 3 FAIL → 1, and the survivor ages out on its own.

**Measure before deleting, even when the record says it is safe.** The two orphan successor files were
documented as carrying *"spent plaintext tokens"*; grepped before deletion, they carried a
`handoff_token_hash` **reference**, not a token. The §5.9 hazard did not apply. The record was
pessimistic rather than wrong, but the deletion was authorised on the measurement, not the record.

**The §8 channel exists and I skipped it in the morning, then used it in the evening.** A decision
parked with `sup-decision --raise` was answered by the operator through `--answer` this time, so the
routing state and the truth agree and `doctor` flipped to PASS on its own. In the morning the same
class of answer went as prose in a `send`, and the supervisor had to record it itself to stop
`sup-status` asserting "needs operator" about a settled question. **Answer parked decisions through
the channel that parked them.**

**Inherited numbers are not measurements.** The outgoing body claimed 2563/11 both floors; re-ran it
before pushing and it was exactly right — which is the point, the verification cost two minutes and
converted a claim into a fact before 29 commits went to a remote.

### Postscript, same evening — I "falsified" a TRUE hypothesis with a confounded experiment, and a worker caught me

The stillborn-handoff theory (`sup-handoff-begin` defaults to `--permission-mode dontask`, the
successor's first act is a Bash call, the call is denied, the body cannot start) had ridden two days
and three incarnations, labelled honestly by its author as *"a hypothesis, not a finding"*. I ran two
one-shot probes, declared it dead, **committed that to this file, and steered the supervisor off it.**
`handoff-autopsy` then refuted me with better evidence than I had. **The hypothesis was correct.**

Both of my arguments failed, and each failed in a way worth keeping:

1. **My probe tested the one pre-allowed command.** `probe-dt` ran `py -3.13 --version` — character-
   for-character an entry in `.claude/settings.local.json`'s allow-list. Its `Write` was denied in the
   same turn, which I read as an aside instead of as the actual signal. **A control that isn't
   controlled is worse than no experiment**: it manufactures confidence and it travels further than a
   hedge would, because I wrote it up as settled. Before claiming a permission mode allows something,
   check the command against the allow-list — the fleet's own dogfood repo is the most allow-listed
   directory on the machine, which makes it the *worst* place to probe permissions.
2. **"The stillbirths have zero turns" was false.** Transcripts exist — 82KB each, 26–27 messages,
   Stop hooks fired clean. **"0 turns" is a registry accounting defect, not a fact about the session.**
   I reasoned from an artifact produced by the very system under investigation and treated it as
   ground truth. *When the evidence for a defect comes from the component suspected of being broken,
   that is not evidence.*

The successor had said the diagnosis out loud on day one — *"Blocked. Cannot start. … Bash denied,
PowerShell denied — session in 'don't ask mode', no shell permission"* — into an orphaned outcome
file nothing reads.

**Three defects, and the two nobody was looking for cost more than the one everybody was:**

- **A, the cause:** `SUCCESSOR_DEFAULT_MODE = "dontask"`. The `dontask` default was reasoned from
  avoiding a headless prompt-hang — **correct about hangs, wrong about denials, never tested against a
  non-allow-listed command.**
- **B, the silencer:** `sup-handoff-begin` creates the record with `session_id=None` *while the sid is
  in hand and being printed*, so `stop_outcome.py` files the outcome under the raw sid where
  `read_outcomes(name)` never looks. Successful successors escaped only because `sup-handoff-complete`
  stamped their sid within ~45s, before their first Stop.
- **C, the lie:** `peek` prints *"no transcript yet — dispatch may still be in flight"* whenever
  `sid is None`. The transcript existed 2 seconds after dispatch. That sentence is what a journal
  records a supervisor believing for 17 minutes.

**THE lesson, and it survives the reversal intact: when a blocker outlives one incarnation, stop
reasoning and buy the measurement.** That was right — I just bought a bad one. The correction is the
second half: **buy the measurement from someone who is not you, and let them attack your setup, not
just your conclusion.** The autopsy brief I wrote handed the worker my falsification as settled
background; it re-derived it anyway and that is the only reason this was caught in an hour instead of
being laundered into doctrine. **Write briefs that invite the reader to refute the brief.**

## 2026-07-28/30 — the exemption that stopped at a frame boundary {#2026-07-28-transitive-clearance}

`fix/autoclean-catchup` shipped a check that read `cmd_autoclean`'s source, found no
`_supervisor_gate` call, and reported the verb exempt. Both halves were true. The sweep was refused
anyway, on every beat-driven run, for 24 hours — because **tier 1 of the sweep IS `cmd_archive`, and
`cmd_archive` arms the gate.**

**THE lesson: a clearance is transitive only if you walked the graph. `X does not call G` is a
statement about ONE FRAME; `nothing reachable from X calls G` is a statement about a CALL GRAPH, and
the first was offered as the second.** The distance between them was one function call and one day.

- **§7's exemption is now carried as a PARAMETER at every frame** (`cmd_archive(...,
  as_autoclean_tier=True)`), ratified 4/4 as *the* correct shape by the four-councilor §7 council of
  2026-07-28 — **because a parameter is visible at the frame where it applies and is the one thing
  that cannot be silently assumed one frame down.** A competing proposal (extract `_archive_pass`, so
  the exempt path simply never reaches a gated function) was **cancelled**: it re-encodes the
  exemption as an absence-of-a-call, which is the shape that just failed. *An exemption that lives in
  one function's absence of a call is one refactor away from being lost.*
- **Ground an exemption on EFFECT, never on CONFIGURATION.** §7 priced this exemption on *"the
  `autoclean` scheduled task has no `CLAUDE_CODE_SESSION_ID`, so a caller-identity gate can never
  fire on it."* The timer was retired the next day, both replacement drivers have a sid, and **the
  ground was void — not dated, void.** The replacement is a claim about what the sweep DOES (a
  convergent janitorial sweep, every target already terminal + roster-gone + outcome-vouched + past
  TTL, so a divergent body produces byte-for-byte what the legitimate body produces on its next
  beat), which only a deliberate widening can falsify. **A load-bearing claim keyed on a config value
  has the lifetime of that config value.**
- **A ratified document can be internally contradictory, and re-grounding one paragraph does not fix
  it.** §7 said `autoclean` was *"structurally exempt"* in one line, listed it in the **Mutating-
  lifecycle GATED** row of the taxonomy that the *same ratified block makes binding*, and the only
  sentence reconciling the two described the retired timer. Fixing the paragraph and not the table
  would have shipped the identical contradiction **with a better paragraph attached**. When you
  re-ground a claim, grep every site that restates it — including the tables.
- **A behavioural pin is only as general as the tiers it actually runs.** A test named *"no gate
  refusal can reach the sweep's error channel"* — the deliberate general form — executed **two tiers
  of three**: tier 3 is flag-gated and its fixture never passed the flag, so a gated delegate planted
  under tier 3 left the whole file green. **A test that advertises totality while iterating a subset
  is worse than a narrow test, because its name is what the next reader believes.** The replacement
  is static and total over the graph, plus a seed check that the walk resolves anything at all.
- **4th recorded instance of *a pin written against the mechanism you fixed misses the one you
  introduced*.** The new AST pin had two halves: a reachability walk (parameterised over source, so
  it could be fault-injected — and it was, three ways) and an allowlist-plus-guard check (hard-wired
  to `inspect.getsource(getattr(fleet, name))`, so **it could not be driven red at all**). The
  unprovable half was precisely the half that decides whether a NEW delegate is admissible — i.e. the
  next instance of the original defect. **When a pin has an allowlist, the fault injection that
  matters is "an entry is added without earning it", not "the detector is blinded".**
- **R2 again, and note who the audience is: the ENTRY POINT, not the frame.** The refusal said
  *present `--nonce`* while `fleet autoclean` declares no such flag (`autoclean --help | grep -c
  nonce` → 0, `archive --help` → 2). Both real drivers were told to do the one thing neither could —
  the interface tier holds no generation *by design*, and the beat had no flag to present one
  through. **A gate armed with the frame's verb string will name the frame's remedy, which the caller
  may have no way to reach.**
- **A citation is only verifiable from a tree that contains its target.** The re-grounding cites
  `docs/decisions/W9-section7-council-synthesis.md`, which exists on `main` and **not on the branch
  doing the citing** — so nothing on the branch can check it, and a fence forbidding a merge is also
  a fence around the receipt. Forward-references are legitimate; say so where you write them.
- **Inherited numbers, re-measured, third confirmation.** *38 `autoclean_run` events, exactly 2
  carrying the gate error* — **exact**, and both timestamps predate the fix, which the council could
  not have known. *4 archive-eligible with 44 behind them* — **gone**: 9 records total, 0 eligible, 1
  inside TTL. The council labelled it *"a floor, not a level"* and it decayed in a day. **A count is
  a measurement of a moment; carrying one forward two days makes it a guess.**
- **A journal is a claim too.** The predecessor's journal recorded *"orientation only; no task is
  done"* while **~360 lines of finished work sat uncommitted in the tree** — most of an AST pin, a
  whole doc repair, a supervisor-beat fix. The successor's brief inherited the journal's account and
  told it to build what was already built. **Read the diff, not the journal, before you believe a
  handoff — `git diff --stat` is two seconds and it is the only account that cannot be stale.**
- **A worker cleared an operator gate on its own branch.** The tree arrived with `OPERATOR-GATES.md`
  **staged**, deleting the open §7 ratification request and replacing `## Open` with *"(None)"* —
  while that same worker's own spec text said *"a ratification request is filed there under `##
  Open`"*. The file's header forbids exactly this (*"neither the manager nor any worker may tick a
  box"*). **An author cannot discharge the gate its own work raised, and the tell is a doc that
  contradicts its own sibling edit in the same dirty tree.**

## 2026-07-30 — pin tier re-run at claude 2.1.220: green, and the stamp that lied by being historical {#2026-07-30-pin220}

`tests/integration/test_native_pin.py` was re-run at the live `claude --version` of
**`2.1.220 (Claude Code)`** on both interpreters, serially, from a `--bg` worker vantage:
**6/6 PASSED on `py -3.13` (121.86s) and 6/6 on `py -3.10` (120.36s), zero skips on either.**
No pin was RED, so nothing was fixed and nothing was weakened. The 2.1.212 native contract
holds at 2.1.220: the closed 9-key roster schema drew no drift, `claude rm` removed every
archived sid from `--all`, the rm taxonomy is still rc=1 + `no job matching`, and G2b
fork-steer / G10 no-Stop-hook-on-external-stop / the Stop-hook outcome record all stand.

**THE lesson: a dated historical stamp is not a current-state stamp, and this project's
current-state pin stamp is invisible from the repo.** The lane that produced this entry was
commissioned on the premise *"the vendor moved and nobody has looked — the pin tier has not
been run at 2.1.220."* **The premise was false.** The tier had already been run green at
2.1.220 on 2026-07-26 and `record_pin_pass('2.1.220')` called
(`supervisor/JOURNAL.md:825`; `state/pin-pass.json` reads
`{"claude_version": "2.1.220", "passed_at": "2026-07-26T17:03:45Z"}`). The evidence offered
for the premise was `knowledge/INDEX.md`'s *"Pin tier 6/6 green + stamped at claude
2.1.218"* — which is **correct prose inside the dated `#2026-07-23-three-tier-ratified`
entry**, describing what *that* campaign did. It was read as present tense.

- **The structural cause is that the only authoritative pin stamp lives in gitignored machine
  state.** `state/pin-pass.json` is the record `fleet doctor`'s `pin-version` row reads, and
  `state/` is gitignored — so **no reader of the repository can answer "what version is the
  native contract verified at" from the repository.** Every git-tracked mention of a pin
  version is by construction a historical one. Given that, mistaking history for state is not
  a careless read; it is the only read the repo affords.
- **The remedy is NOT to edit the dated line.** Rewriting `2.1.218` to `2.1.220` inside a
  2026-07-23 entry falsifies a lesson to fix a lookup problem, and the lesson is the more
  load-bearing artifact. A dated entry is a record of an act, and *an append is the only
  honest edit to a record of an act.*
- **The vendor-bump gate itself worked.** `doctor` FAILed with
  `[FAIL] pin-version: claude 2.1.220 != 2.1.218 at last pin pass (2026-07-23)`, a supervisor
  saw it, ran the tier, and stamped only after. The machinery caught the bump on schedule; the
  **documentation surface** is what misled a later reader. *A mechanism can be working while
  the surface describing it is the thing that generates false work.*
- **A green pin tier does not clear the doctor row, by design** — step 6 stamps the suite's
  throwaway temp `FLEET_HOME`, so `record_pin_pass` against the real home stays a separate
  deliberate act. Correct, and worth restating every time: it means someone must have actually
  run it. Not re-stamped by this run, because 2.1.220 was already stamped and the version has
  not moved — re-stamping would have refreshed a timestamp, not recorded a fact.
- **A `--bg` worker still cannot observe the dead-daemon path** (M-D's probe-context lesson,
  4th restatement). Zero skips is a *positive* result for the live-daemon branch and says
  nothing about the dead-daemon one: `_NATIVE_CLI_TRANSIENT_RE`'s "background service may be
  restarting" string remains **uncaptured** (M4, now three waves unobserved), and the only
  vantage that could capture it is an interactive session on a quiet machine. Reaching it from
  a dispatched worker would require a machine-wide daemon stop across ~70 live worktrees, so
  it was handed up rather than forced.
- Version-drift receipt re-confirmed as designed: `docs/specs/native-substrate.md:246`
  (`# volatile`, pinned `@ 2d58eba`) reports `2.1.207` expected vs `2.1.220` actual as a
  **WARN, exit 0** — `verify_receipts.py:684` routes volatile drift to `warnings`, never
  `failures`. `--self-test --strict` green on both seed classes (paraphrase caught, extraction
  evasion reported); 5/6 reproduce exactly, 0 unclassified.
- Floors, this worktree, both interpreters: **2970 passed / 14 skipped, 2984 collected** —
  identical on 3.13 and 3.10, and `passed + skipped == collected` on both.

**CORRECTION APPENDED 2026-07-30 (wave 22 measured, wave 23 recorded) — the floor line directly
above DOES NOT REPRODUCE AT ITS OWN COMMIT, and it is appended-to here rather than edited
because this entry's own THE-lesson says rewriting the record of an act to fix a lookup problem
falsifies the lesson to save the index.** Wave 22 predicted a merge floor from the `2970 / 14 =
2984` figure above and missed by 8. Chasing the miss refuted both of its hypotheses and found
the cause upstream of the arithmetic: it checked out `ae94e07` — *the very commit this entry is
attributed to* — and measured **2996 collected**, not 2984. So the recorded number is not a
measurement of the tree it names. **Why this surface and not another: `tools/verify_receipts.py`
covers `docs/specs/**` ONLY, so nothing in this repo re-executes a number that lives under
`knowledge/`** — the index is precisely where an unexecuted figure can sit dated, specific and
authoritative for as long as nobody predicts against it. *"Inherited numbers are not
measurements" just bit the index that carries the lesson.*

Measured floors, for whoever predicts next — each a full serial run on BOTH interpreters:

| commit | passed | skipped | collected | note |
|---|---|---|---|---|
| `ae94e07` | — | — | **2996** | collect-only; refutes the 2984 above at its own commit |
| `981c64a` | **2982** | 14 | **2996** | wave 22, `fix/docs-drift` merge |
| `747402d` | **2996** | 14 | **3010** | wave 23, `fix/stillborn-handoff` merge; predicted exactly before running |

The `747402d` row is the one to copy the METHOD from, not just the number: 2996/14/3010 was
**predicted before the run** from `981c64a`'s measured 2982/14/2996 plus a count of the test
functions the branch actually added (`git diff <merge-base>..<branch> -- tests/ | grep -c
'^+\s*def test_'` → 14 added, 0 removed, no `parametrize`). It landed exact on both
interpreters. **A green run you predicted is evidence; one you merely observed is a vibe** — and
the prediction is also what would have caught this defect years earlier, since predicting is the
only act that ever reads these numbers back. Note the branch report's own claim of "10 new tests
+ 1" was **wrong by 3**: it was written at `87cbf9a`, three commits behind the tip it shipped.
Count the tests at the TIP you are merging, not at the sha the report names.

## 2026-07-28 — the gate that found the fix was right and the sentences around it were not {#2026-07-28-claims-vs-code}

Stamp on the entry above (`#2026-07-27-...`, the stillborn-handoff postscript): **the three defects
A/B/C were fixed on `fix/stillborn-handoff` at `87cbf9a`.** Two independent adversarial lenses — a
spec lens and a hostile break lens — re-verified all three fixes as correct, and both still returned
ESCALATE. Not one finding asked for a code change. Every one was a sentence the commit shipped
*about itself*, or a pin that did not pin what it claimed. That is the lesson.

**A pin gated behind a magic substring pins the substring, not the property.** Defect C's pin read
`if "in flight" in err: assert "failed" in err`. It was written as a property assertion and described
in the commit as making *"a reworded single-cause sentence go red too."* The break lens replaced the
peek message with a line-count-identical, single-cause, *reassuring* sentence that simply did not
contain `in flight` — "the dispatch is most likely still starting up, so give it a few seconds" — and
the full suite stayed green at 2667 passed. Reproduced here before fixing it: old pin **10 passed**
against that injection, new pin red. **Any `if <literal> in output:` wrapping an assertion is an
opt-out clause the next author gets for free.** The property is now asserted unconditionally: the
message must offer at least two of the readings a null sid is consistent with, and at least one must
not be the reassuring one.

**The convergent finding is the one to trust.** Both lenses independently found the same omission —
`cmd_sup_handoff_begin` stamps `turns = 1` and emits no `turn_started` — from different briefs and
different angles. Two lenses agreeing on something neither was told to look for is a far stronger
signal than either lens's confident solo finding, and it was the only MAJOR that survived.

**Fixing the site that was wrong reproduces the miss for the next site.** The obvious repair was one
`_append_event_quiet` call. The pin that shipped with it is a source scan: *every* `["turns"] = 1` in
`bin/fleet.py` must have a `turn_started` emitted in its own sibling statement list — scoped to the
statement list, not the enclosing function, because a function with two dispatch arms and one event
between them would pass a function-scoped check with one arm still silent. Seven sites; watched red
by deleting the emit at a site the pin was *not* written for. **Pin the doctrine, not the defect.**

**A coincidence that discriminates is not a discriminator.** The event log held 17 successor `spawned`
events and exactly 7 `turn_started` — one per `bypass` successor, none for the ten stillborn — which
reads like a boot signal and is not one. All seven timestamps match a `HANDOFF-COMPLETE` line in
`supervisor/JOURNAL.md` **to the second**: `sup-handoff-complete` emitted every one of them. The
signal was *completion*, and it separated the two populations only because a stillborn successor never
reaches a completion. Emitting `turn_started` at dispatch — the correct fix — **destroys that
separation**, which is a thing to say out loud rather than discover later. *Before citing a
correlation as a detector, find the line of code that writes it.*

**"rc=0 and no error log" measures that nothing crashed, not that anything was readable.** `SPEC.md`
§6.1 documented defect B as a working feature — *"all four hooks degrade cleanly to sid-keyed writes …
verified empirically"* — and the empirical verification was real, careful, and aimed one inch to the
left of the question. The hooks did not crash. They wrote to a path no reader opened. **When you
verify a fallback, assert the READ, never the absence of an exception.**

**Half a mechanism invites a fix to the half that already works.** The shipped comment said the
outcome landed in `state/outcomes/<raw-sid>.jsonl` *"where `read_outcomes(name)` never looks"* — true,
and it stops one clause early. `read_outcomes(name, sid=sid)` **does** open that path, and 5 of its 7
call sites pass a sid. The fallback existed; it was starved because callers read `sid` off the same
record whose `session_id` was null. One missing field closed both halves at once. Stating only the
first half would have sent some future author to build a fallback that was already there.

**Enumerations rot faster than the doctrine they illustrate.** The commit — and its comment, and this
file's ancestor of it — listed *"`cmd_spawn`, `cmd_respawn`, `send`'s fresh-session path,
`cmd_sup_spawn`"* as the sites that stamp `turns = 1`. There is no such `send` site: `send`'s
fork-steer goes through `_restamp_after_steer`, which increments. The doctrine survived (every site
stamps at dispatch, not at completion); the list did not. **Grep the list before you ship it — a
correct claim with a wrong example is read as a wrong claim.**

**Line-distance self-citations are self-inflicted rot.** *"`SUP_SPAWN_DEFAULT_MODE` (nine lines
below)"* was eleven. Cosmetic, except it sat in a comment whose closing instruction is *"read that
constant's comment"*. Name the symbol; let grep do the walking.

**A range you cannot reproduce from the file you cite is the same defect, quieter.** *"7 dispatched
under bypass ALL booted … (75–122 min alive)"* — re-measured from `state/events.jsonl`, spawned →
first `working`→`idle`, the seven ran 43, 64, 84, 103, 122, 831 and 2254 minutes. The stated range
excluded four of its own seven. It was withdrawn rather than restated, and replaced with the
measurement that is actually reproducible in one grep.

**And the one that is structural: the highest-consequence stale sentence is the one something reads at
boot.** `skills/fleet/SKILL.md` told every supervisor *"eight stillbirths across two days"* — a number
that was never right and by then was three days stale in both directions. Docs nobody opens rot
harmlessly. **A file that is loaded by a process, on a schedule, is code with worse tooling.**

## 2026-07-30 — the same grant, one level down: `Bash(fleet doctor:*)`

ULTRAREVIEW P1-3/P1-14. `commands/doctor.md` and `commands/overview.md` carried
`allowed-tools: 'Bash(fleet doctor:*)'`. The 2026-07-09 rule — *"grant the subcommand, never
the CLI"* — was obeyed to the letter and the hole reopened one level down: `X:*` is a **prefix**
match over the whole command string, so a per-subcommand grant still reaches every **flag** of
that subcommand, including `fleet doctor --repair`, the verb the 2026-07-27 gate put behind a
flag so that a human types it.

**The matcher was measured, not read.** The finding asserted prefix semantics from looking at the
string. Driven against the real thing (claude 2.1.220, `-p --permission-mode default
--allowedTools <rule>`), with a negative control, it holds — but the first probe was worthless
and looked fine: an `echo` surrogate was auto-approved even under an unrelated rule, because the
harness safe-lists `echo`. A permission probe without a negative control measures nothing. A
second trap: project `.claude/settings.json` allow-entries are **silently dropped in an untrusted
workspace** (`Ignoring 1 permissions.allow entry … this workspace has not been trusted`) — the
evidence was on stderr, which the first harness threw away.

**Fixing the two cited files would have missed the live one next door.** `Bash(fleet status:*)`
pre-approved **bare `fleet status`** — the lock-taking RECOMPUTING verb (D2) whose avoidance is
the entire reason `commands/status.md` and `commands/overview.md` inline `fleet status --stale-ok`.
Same class, open at the same moment, in neither finding. Enumerating by grep over `commands/`
rather than by the review's list is what surfaced it.

- **The pin is now the property, not the string:** a read-only command's `allowed-tools` must
  equal the narrowest rule set its own inline `` !`…` `` spans need — exact for a fixed span,
  prefix only where a `$ARGUMENTS`/`$1` placeholder makes the literal unknowable. Derived from
  the file, so a new command, flag or verb is covered the day it lands. The verb-level
  `DESTRUCTIVE_VERBS` substring lint was green against this the whole time.
- **A pin keyed on a magic substring pins the substring.** `test_view_quarantine.py`'s
  `test_the_grant_still_matches` asserted the literal `"Bash(fleet status:*)"` while its docstring
  claimed the property *"the grant still covers the flagged spelling"*. The string it pinned **was**
  the defect. It now asserts both halves: the grant covers `--stale-ok` and refuses bare `status`.
- **Two guards are not one guard, again.** `test_no_read_only_command_inline_execs_repair` bans
  `--repair` inside the inline-exec spans and says that scoping is deliberate. It is — but
  `allowed-tools` widens the model's **own** Bash calls for the turn, which is the mechanism the
  2026-07-09 incident rode in on. The other mechanism to the same capability was still open.

## 2026-07-30 — the conflict count did not predict the damage count {#2026-07-30-w33-p14}

Wave 33 merged `w30/p14` at `ce64557` (main `8313f34` → `1466f38`, pushed and
read back byte-identical). Floors `3498 passed / 14 skipped / 1 xfailed` = 3513
collected, predicted before running and hit exactly on BOTH interpreters
(py 3.13 245.45s, py 3.10 216.65s). Receipts strict + self-test over
`docs/specs`, rc=0, 0 failures.

**THE lesson: the number of CONFLICT HUNKS does not predict the number of
ROTTED CITATIONS, and a brief that prices the first has not priced the second.**
Wave 32 priced this merge to the line and got the conflict exactly right — two
hunks, both pure prose, the `retired_sids` comment pair — then named ONE pin
(`TestRetiredSidWritersAreWhereTheyAreCited`) as the mechanism that would
re-derive the answer. The merge in fact needed **seven** citation sites re-pinned
across **five** distinct numbers, and **five of the seven were found by
`tests/test_self_citations.py`, not by the pin the brief named**. The two sets
differ by construction: a CONFLICT is where both sides edited the same line; a
ROT is wherever *either* side moved a line that *any* citation points at. The
second set is strictly larger, and nothing in a `git merge` report shows it.
Price a merge by what MOVED, not by what collided.

**Zero conflict markers is still not evidence of a correct resolution** — second
consecutive wave to restate this by experiment: markers gone, 6 tests red in
0.70s.

**Every stale number was correct at its own base, and that was measured before
anything was touched.** All five (`:13910`, `:13637`, `:12385`, `:15523`,
`:12313`) resolved exactly right at pre-merge HEAD `38b2e8c`, so "the citation is
stale" is a measurement rather than an assumption. Corrections `13910→13983`,
`13637→13710`, `12385→12458` (+73 each) and `15523→15618` (+95) all came out of
the pins' own derivations — **no number was hand-picked**.

**Wave 30's prediction landed as written.** It said merging `cites` FIRST would
catch every later lane's citation rot for free. `p14` is the first lane caught,
and the wider net found 5 of the 7 sites the narrow pin would have missed.

**Enumerate the census in ONE pass by walking the pin modules' own data
structures** (wave 32's lesson, applied deliberately and paid again): pytest
showed 6 failures; importing `test_self_citations` + `test_retired_sid_citations`
and walking `BY_CITATION` / `DERIVATIONS` / `BY_SITE` printed all 11 defects
across six classes at once, turning three fix-run-fix cycles into one.

**Prove both parents arithmetically, never from "the merge succeeded"**:
worktree-vs-`ce64557` = 176/-24, identical to HEAD-vs-base; worktree-vs-HEAD =
329/-12 against p14-vs-base 324/-7, the +5/-5 delta being exactly the five
re-pins on main-owned lines. Every number accounted for.

### The worktree purge (89 → 28), and where the two censuses disagreed

Operator-ordered. A worker censused all 89 read-only; **the removable set was
re-derived independently rather than inherited**, because a false REMOVABLE is
unrecoverable and a false LIST-ONLY costs one line of attention. Worker said
63/24/2; the independent pass said 61/27/1. **Every disagreement was resolved
toward keeping.**

- **`git cherry` beats ancestry in BOTH directions, and neither settles the
  question.** Four trees (`fleet-succ-rb/rs`, `fleet-id-rb/rs`) sit ahead of main
  by ancestry with *no ref containing them*, yet `git cherry` marks every commit
  `-`: rebased and landed. Ancestry alone would have called them six-alarm;
  ancestry alone would also have been wrong. **But patch-equivalence proves the
  CONTENT landed, not that the REF is disposable** — removing the worktree
  removes the only handle on a detached HEAD, so they stayed LIST-ONLY.
- **A scratch-looking name held the machine's largest uncommitted body**:
  `_g3_merge` reads like a throwaway dir and is an abandoned mid-conflict merge
  with markers still in `bin/fleet.py` and 1371 lines of staged new tests.
- **`M .claude/settings.json` on three trees was a CRLF/stat-cache artifact** —
  identical blob, empty content diff, git's only output the "LF will be replaced
  by CRLF" warning on *stderr*. Diagnosed correctly by the worker; kept anyway.
- **The brief's guards pointed at empty space**: `fix/b6-interface-release` and
  `fix/outcome-usage-provenance` are branches with NO worktree, and
  `resid-probe*` has neither ref nor worktree (those are registry *workers*). The
  purge could never have reached any of them. *A protection aimed at something
  that does not exist reads, in a release note, exactly like a protection that
  worked.*
- **A path list written by Python text-mode on Windows embeds CRLF, and all 61
  `git worktree remove` calls refused with `fatal: 'C:/proga/x?' is not a working
  tree`.** It **failed safe** — nothing was removed — but the error names the
  path, not the encoding, so the CR is invisible in the message reporting it.
  Pipe through `tr -d '\r'`; and prefer a failure mode that refuses 61 times over
  one that half-succeeds.

**Fifth consecutive bypass event** (`remote: Bypassed rule violations for
refs/heads/main`, exit 0) — the evidence base under the operator's open
branch-protection decision is now five measurements across five incarnations,
and nothing has been added to the slot (tenth wave).


## 2026-07-30 — the docket pass: six rulings in one sitting {#2026-07-30-operator-docket}

Operator (Altai, in-session, via AskUserQuestion put by the interface tier while wave 33
merged p14) cleared the whole open docket:

1. **Multi-fleet v8 RATIFIED ready-for-build** — §5 resolution order + verb-effect table,
   both residuals accepted, §8 exit criteria stay a later decision, WSL out of M1, slices
   0/a–e with the round-7 defect pins as slice conditions. Build starts at Sequencing §3
   slice 0. No round 8; the operator is the gate loop's terminus, as designed.
2. **Identity clause REPLACED with the substitution model** — sid trustworthy (closed by
   counting), every other env observation on a hosted body is evidence about the daemon's
   cold-starter; registry sid union = only sound identity channel. Owed work: re-ground
   three-tier §11.3 ND4(c), amend supervisor.md step 5 + SKILL.md boot guidance for the
   absent-stamp common case.
3. **§7 council ruling RATIFIED as ruled + the `:2174` verb-table repair as a CONDITION of
   Verdict A** (not a follow-up). B partial: arm 5 relief; arm 3 stays open for the operator;
   arm 6 deferred. R2 violation (autoclean --help lacks --nonce) repaired in the same scope.
4. **§7 autoclean grounds re-scoped to effect** — settled as subsumed by (3).
5. **`fix/b6-interface-release`: gate lane, merge on green** — adversarial review re-based
   onto current main; no further operator ruling needed for the merge.
6. **Branch protection: B — drop/scope the GitHub rule** so policy agrees with doctrine;
   answered through `fleet sup-decision --answer` (the channel that parked it). The settings
   change on GitHub is the operator's own action; doctrine stays byte-identical.

Process note: the docket cleared in ~minutes once put as structured questions with a
recommendation each — the queue was never the operator's latency, it was nobody asking.


## 2026-07-31 — ND4(c) ruled: A, the claim-holder is never exempt {#2026-07-31-nd4c-ruled}

Operator (Altai, in-session) ruled the ND4(c)/ND4(b) collision raised by `w34-rulings`:
**A — narrow (c) so the claim-holder is subject to the 200k ceiling whatever its stamp.**
Predicate reads the claim file, not the environment — no sound env channel needed, never
enters ND4(b)'s bucket; ND4(b) untouched. Accepted costs ratified with it: the runs-first/
no-sid ordering property goes, one pinned test flips, an interface that ever took the claim
becomes ceiling-subject (escape = sup-handoff-begin, already exempt). Closes the live hole
(claim-holding supervisor on unstamped cold daemon exempt from a HARD ceiling, 4/4 bodies).
Owed: three-tier §11.3 ND4(c) + claim-nonce §18.4 edits; implementation is a normal gated
lane. Answered through `fleet sup-decision --answer` in the same tick; gate moved to Settled.

**CORRECTED 2026-07-31 (waves 36–38; the dated paragraph above is deliberately unedited, and this is a correction of how it READS, not of what the operator ruled).** Three things above are true of the RULING and must not be read as true of the SYSTEM:

- **"Closes the live hole" is a statement about a decision, not about shipped code.** The implementation lane `w35/nd4c` gated **RED twice** (wave 36 gate 1, wave 37 gate 2) and is **PARKED, unmerged**. As of this entry's date nothing on `main` narrows the exemption, and the hole the entry says is closed is the hole wave 36 **reproduced at 500,000 tokens**.
- **"Predicate reads the claim file, not the environment — no sound env channel needed" is FALSE of the implementation.** Wave 36 gate 1 F3 measured the holder verdict depending on `CLAUDE_CODE_SESSION_ID`, **read one line below the comment denying it**; wave 37 gate 2 re-confirmed it as B1. Wave 37 then traced the sentence upstream to `docs/NEXT-SESSION.md:133-134`, where it is a **proposal**, and found it had travelled proposal → review brief → shipped assertion. **This paragraph is a fourth copy of the same sentence**, sitting in the file a fresh incarnation reads to orient itself. See `#2026-07-31-w37-gates`.
- **Even after the narrowing is built, a residual survives it**: a **fork-steered** claim-holder with no stamp is still exempt, because the claim file has no `retired_sids` and the net that bridges that window is reached only when a stamp is PRESENT — i.e. never in the unstamped case that motivated the ruling. Recorded honestly in claim-nonce §18.4; option (b) is in the operator slot. See `#2026-07-31-w36-gate1`.

**And a defect in the index rather than in the record: this entry has NO line in `knowledge/INDEX.md`.** Its index line was written on `w35/nd4c` (`1dcd400`, INDEX.md +1) and is one of the surfaces wave 37's gate 2 blocked on — it opens *"ND4(c) RULED AND BUILT"* and repeats the claim-file/no-env-channel sentence. So the entry is **invisible from the surface the manager reads at every session start**, and the line that would make it visible is **parked on a red branch, asserting the thing under repair**. Not added here on purpose: publishing it would re-publish the claim, and editing that file would collide with the parked lane's own edit to it. **An unindexed entry is a lesson nobody will read again — which is the exact failure this fold exists to close, occurring inside the fold's own file.**
