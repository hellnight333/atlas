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
