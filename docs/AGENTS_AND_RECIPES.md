# Agents, tools, recipes

Infrastructure for the 300-assistant architecture. Nothing here is specific to
coding: the same four pieces carry research, discovery, media, email and
publishing, which is why none of them mention any of those.

```
fabric/agents.py     WHO does it, and the worst it can do        (declarative record)
fabric/tools.py      WHAT it may reach, and what that costs      (contract)
fabric/recipes.py    HOW one job is done, step by step           (versioned artifact)
fabric/sandbox.py    the containment those steps run inside
```

An agent is a **record**, not a process. There are no 300 daemons; there is a
registry of 300 declarations and a scheduler that dispatches against them.

## The tool contract is now enforced per step

It existed and was consulted only in aggregate — to decide whether an agent
needed the network or a sandbox. **Never per step.** So an agent declared with
`tools=("filesystem",)` could run any command at all, including one that reaches
the network, and the isolation derived from its *declaration* would be wrong
about the work it was actually doing.

That is the same shape as an agent substitution: the blast radius somebody
approved and the one that runs diverge, quietly.

`Step` now names its tool, and `Adapter.run` refuses the **whole sequence**
before the first step if any tool is undeclared. Refusing halfway would mean the
workspace had already changed and the refusal arrived too late to mean anything.

## Recipes

`CLAUDE.md` is unambiguous about why this is a primitive rather than a
convenience: *an LLM must never freestyle the steps, because it will hallucinate
them forever.* A recipe is a versioned, declarative artifact in git, and the
model's only job is choosing one **by name**.

That is the same shape as `mission/origins.py`. A model emits a string; code
decides what that string is allowed to mean. A name that resolves to nothing is
a refusal, never a default.

### What a recipe is not

- **Not a plan.** A plan is what a person approves; a recipe is how the approved
  work is carried out. It cannot authorise itself.
- **Not a workflow engine.** No conditionals, loops, jumps or variables. A
  sequence needing those is a program, and a program a model assembles at
  runtime is the thing this prevents. A domain that genuinely needs branching
  gets two recipes and something deterministic chooses between them.
- **Not runtime-configurable.** The agent is named in the declaration, because
  the agent decides the blast radius and a runtime choice is a runtime blast
  radius.

### Validated at import, not at dispatch

`_validate_all()` runs when the module loads and refuses:

| | |
|---|---|
| a tool the recipe's agent does not declare | it would be refused at dispatch anyway — at 3am, in front of nobody |
| an agent no registry entry declares | unbounded blast radius |
| a tool `fabric.tools` does not declare | a typo is not permission |
| a capability its agent does not provide | the scheduler would route work the agent cannot do |
| the same id twice | `get` returns the first and the other is invisible |

A bad declaration is a failing build in front of whoever wrote it.

### One declaration, not two

`SELF_CHECK_STEPS` was a hardcoded list in `mission/adapter.py` — the only
sequence of tool steps in the system, sitting beside the thing that runs it. It
is now **derived** from the `execution-canary` recipe. Declaring the same three
commands in both places would have been a second copy that drifts: the exact
failure the recipe primitive exists to prevent, introduced by the thing
preventing it.

## The tool-executing role

`mission/toolrunner.py`. A worker role that carries out a **declared recipe**
through the tools that recipe's agent is registered for, and satisfies the same
`CodingAgent` protocol every other role does — the worker is not modified and
does not know this is different. A non-coding agent is a **role**, not a second
worker.

It is not a model with tools. There is no prompt, no provider and no credential.
A model may eventually say `recipe = "discover-uae-dental"` — a key, which
resolves or is refused. It may not say:

| | why not |
|---|---|
| a tool | the recipe declares those, and the agent's registry entry bounds which are permitted at all |
| a URL | `permitted_urls()` is computed from the recipe; a fetch of anything else is refused before a socket opens |
| a step | recipes have no variables and are not assembled at runtime |
| an interpretation | the runner returns what the server said, and nothing about what it means |

The refusals live in the runner rather than in its caller, because a caller can
be replaced by a model and the runner cannot.

### A dispatch table, not an engine

Sixteen lines of "which adapter handles this tool". No conditionals, no retries,
no branching, no ordering beyond the recipe's own. Anything more would be a
workflow engine, and a workflow engine a model can aim is what the architecture
refuses.

### Two code-writing assumptions it exposed

Both were in the worker, both were right for coding roles, and both failed every
successful research run:

**"The agent reported success but changed no files."** The reasoning — *it is
confident and the repository is unchanged* — is about code. A research role
leaves the repository exactly as it found it, and that is its correct outcome.
`AgentOutcome.produced_nothing` now asks the outcome what its currency is;
a coding agent leaves `evidence_count` at zero and is judged on files exactly as
before.

**Committing.** `GitWorkspace.commit` refuses an unchanged tree, rightly. A role
that writes no files now returns no commit rather than failing — and this is not
a way for a coding role to skip committing, because an agent that claimed success
and produced nothing was already refused upstream.

### Proven on the server

Local runs cannot verify the guarded fetch: a controlled fixture is on loopback
and the address guard refuses loopback — correctly, and that refusal is itself
under test. The two requirements are mutually exclusive by design. This
developer machine's resolver also answers every made-up name, so the harness
reports **NOT VERIFIED** there rather than passing or failing.

On `qevik-core-01`, with honest DNS: **35/35, nothing unverified**. The real
production worker dispatched the role, fetched a real public URL through the
guard, recorded evidence, and completed with a durable report naming the recipe,
the agent, the tools invoked, and each evidence fingerprint.

That includes the whole chain in one test rather than two overlapping halves:

    rec-daily-business-discovery
      -> the ordinary recurrence tick
      -> a mission naming the recipe and the role
      -> queued with nobody asked
      -> the real worker, --agent research
      -> discover-uae-dental
      -> http-fetch through the address guard
      -> structured evidence
      -> a durable report

with an assertion that the report **claims nothing about any business**.

## Why the CLI agent is not operational

`cli-implementer` is declared, with `blocked_by=(Need.SANDBOX, Need.CREDENTIAL)`
and the reason written into its registry entry: it writes files with its own
tool loop, which needs a container rather than a worktree, and it needs a model
credential. The credential is `BLOCKED_EXTERNAL_PROVIDER` and is not a project
blocker.

Everything around it is built and tested: the registry entry, the tool contract
it would be held to, the sandbox it would run in, and the recipe format its work
would be declared in. What is missing is a provider that accepts a key.

**No stub stands in for it.** `--agent fake` exists, is not in the registry, and
a worker running it now refuses any mission whose plan named a real agent.

## Files

| Path | What |
|---|---|
| `packages/kernel/atlas_kernel/fabric/recipes.py` | the primitive |
| `packages/kernel/tests/test_recipes.py` | 22 tests |
| `packages/kernel/tests/test_tool_contract.py` | 9 tests, per-step enforcement |
| `packages/kernel/atlas_kernel/mission/adapter.py` | `Step.tool`, `undeclared_tools` |
