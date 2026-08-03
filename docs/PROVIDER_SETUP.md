# Model providers

**Read this first: Atlas cannot connect to a model provider yet.**

This is the largest gap in the Public Alpha, and it is better stated plainly on
the first line than discovered after twenty minutes of looking for a settings
screen.

## What exists today

Atlas registers exactly two provider adapters:

| Adapter | Kind | Reality |
|---|---|---|
| `local-text` | LLM | **Simulation.** Waits briefly, returns a placeholder structure |
| `local-flux` | Image | **Simulation.** Waits briefly, returns a placeholder reference |

Both exist so the orchestration pipeline can be exercised end to end. Neither
loads a model, and neither makes a network call.

There is no Anthropic adapter, no OpenAI adapter, no Google adapter, no
ComfyUI adapter and no Ollama adapter. Setting an API key anywhere will not
change that, because there is no code to use it.

## Then why did setup ask about providers?

The first-run screen records **which providers you intend to use**. It stores
names only, never keys, and it says so on the screen. That intent is useful
when adapters arrive — but it connects nothing today, and no key is requested
or stored.

## What about ComfyExecutor and CloudExecutor?

The executor layer names `LocalExecutor`, `DockerExecutor`, `RemoteExecutor`,
`ClusterExecutor`, `CloudExecutor`, `ComfyExecutor` and `OllamaExecutor`.

These are **placement categories** — they describe *where* a job would run so
the scheduler can reason about capacity and locality. They are not
integrations, and naming one does not make Atlas talk to ComfyUI.

## What works without any provider

Most of Atlas, which is the point worth making:

- Orchestration — workspaces, projects, runs, steps, jobs
- Automation — triggers, conditions, actions, dry runs
- Approvals and governance — policies, quorums, audit
- Cluster — placement, reservations, leases, recovery
- Knowledge graph — nodes, edges, lineage
- Organizations — teams, roles, permissions
- Diagnostics, backup, restore, crash recovery

The **Automation Studio** demo runs end to end on a machine with no
credentials, because automation coordinates Atlas's own subsystems rather than
calling models.

The other four demos install real projects and mark each step as running now
or needing a provider, so you can see the full shape of a pipeline and which
parts are waiting on integration.

## What is planned

Real adapters are the next priority after this release. The intended shape:

- **Cloud**: Anthropic, OpenAI, Google — your key, your account, your terms
- **Local**: Ollama for text, ComfyUI for images — no key, no cost, no network
- **Routing**: `prefer_local → fallback_cloud`, with cost and quality thresholds
- **Recipes**: versioned, benchmarked pipeline definitions in git, so a model
  is chosen by name rather than improvised

No date is promised here. Watch
[Releases](https://github.com/hellnight333/atlas/releases) and
[CHANGELOG.md](../CHANGELOG.md).

## If you want to write one

The `ProviderAdapter` interface in `packages/kernel/atlas_kernel/providers.py`
is small — one `execute(action, payload)` method — and registration happens in
the composition root. That is deliberately the whole contract.

Open an issue before building one, so the recipe design lands first and your
adapter does not have to be rewritten around it. See
[CONTRIBUTING.md](../CONTRIBUTING.md).
