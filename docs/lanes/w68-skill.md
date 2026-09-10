# Fleet skill operating manual
DONE means: `skills/fleet/` is a current imperative manual of at most 400 lines with generic interface-role rituals and targeted checks passing.

Docs updated: `skills/fleet/SKILL.md`; removed `skills/fleet/supervisor.md` and
`docs/operator/server-interface-profile.md`; updated direct pins in
`tests/test_doc_claims.py`, `tests/test_lane_report_durability.py`, `tests/test_self_citations.py`,
`tests/test_supervisor.py`, `tests/test_supervisor_context.py`, and `tests/test_keeper_main.py`.

Result: `SKILL.md` is 160 lines and documents all 38 top-level parser verbs plus four `index` subverbs,
the three tiers, interface role and identical become/continue rituals, home-resident interface state,
dispatch limits, permission/settings policy, mcx observer rules, wave boundary, and handoff procedure.

Checks: parser/document integrity passed on Python 3.10.21 and 3.12.14; no forbidden history markers
remain in `skills/fleet/`; the focused suite passed 593 tests on each interpreter using cached pytest
environments. The follow-up focused suite passed 611 tests on each interpreter using cached pytest
environments. The exact uv `--with pytest` form was network-blocked by PyPI DNS.

Blocker: `bin/fleet_keeper.py` still constructs the deleted default profile path; `bin/` is outside this
lane's fence and needs the owning build lane to retarget it.
