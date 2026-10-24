# Claude provider context in Fleet

This page describes Fleet’s provider-context boundary. It is a reference, not a setup recipe: it does not configure a provider or start a worker.

Fleet does not currently provide per-worker Claude provider profiles or a `fleet spawn --provider` option. The provider-profile design remains parked in [the provider design record](specs/providers.md).

Fleet selects its registry through `FLEET_HOME`, independently of Claude Code’s configuration directory. The [registry schema](SPEC.md) records a substrate label, model, and launch settings for Claude workers, but not the exact `CLAUDE_CONFIG_DIR`, upstream endpoint, or authentication identity. Multiple Claude configuration contexts can therefore share one Fleet registry when they use the same Fleet home; worker names remain unique in that registry.

`fleet result` can show the model reported for a worker’s latest outcome. That model value does not identify the upstream provider or endpoint. The source also does not preserve which Claude configuration context should be used by a later operation that launches a new turn. A Fleet record alone is not enough to reconstruct or verify provider routing.

PR7’s original guide recorded an operator observation on 2026-07-23: separate Claude configuration directories were used to run background sessions against different providers while sharing one Fleet registry. No reproducible receipt for that observation is present in the local review materials, and it is not a current Fleet compatibility guarantee. The PR’s setup and re-dispatch recipe is intentionally not carried forward here.

Provider and gateway support depends on the Claude Code version, provider, model, and enabled features. Check the current [Claude Code deployment overview](https://code.claude.com/docs/en/bedrock-vertex-proxies) and [LLM gateway documentation](https://code.claude.com/docs/en/llm-gateway) for supported configurations. Do not infer endpoint identity or feature compatibility from a model string in Fleet output.
