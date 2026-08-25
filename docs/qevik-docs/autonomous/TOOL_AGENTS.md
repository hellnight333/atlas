# Tool agents

*Status: the contract is built and enforced. No CRM, marketplace, social or
media **features** were started — the operator's instruction stands.*

Step 7 of the Munder-Difflin ordering. Section Q of the fabric architecture
lists browser, email, server, git, CRM, marketplace and social agents. What was
missing was not those features; it was the thing underneath them.

## The gap

`Agent.tools` was a tuple of free-form strings.

```python
tools=("shell", "filesystem", "git-worktree")
```

Nothing checked that a named tool existed. Nothing said what one could do.
Nothing connected a tool to the isolation the agent would run under. Two lists
kept in step by hand — which is the drift this project has been bitten by
before, and the reason the standing rule is *derive, and fail the build on a
dangling reference*.

`fabric/tools.py` makes a tool a record. Agents reference it by id, and a test
fails the build on a name nobody wrote.

## Blast radius belongs to the tool

An agent's declared `blast` must be **at least** the worst its tools can do — a
test asserts it, and a stricter one asserts *exactly*, with an explicit
(currently empty) list where deliberate caution must be justified.

An agent that says REVERSIBLE while holding a tool that sends email is routed to
**execution** approval instead of **artefact** approval. The wrong boundary,
chosen by a typo.

Writing the table down found two real errors in the registry.

### `shell` meant two different things

`cli-implementer` ran a shell in a sandboxed worktree and declared REVERSIBLE.
`administrator` ran a shell on a live host and declared IRREVERSIBLE. Both were
right about their own case, and both named the same tool.

A shell whose writes `git checkout` undoes and a shell on a production machine
are not the same tool. They are now `shell` and `host-shell`, and the blast
radius sits on each unambiguously.

### `browser` understated itself

The browser agent declared REVERSIBLE. A browser that can navigate can also
submit a form, buy something, or send a message — nothing about "browse" is
reversible once a button is clicked. It is now IRREVERSIBLE, which moves it to
artefact approval.

## A sandbox does not contain an email

`Tool.contained_by_sandbox` says whether isolation genuinely reduces the damage.
A shell writing to a worktree: yes. An email leaving the machine: no — the
effect is already elsewhere, and calling it contained because the process sat in
a namespace would be the most dangerous kind of wrong.

A test enforces the shape: anything marked contained must be local and
reversible.

## The network flag is enforced, not documented

`needs_network(agent)` is derived from its tools and feeds
`sandbox.Isolation(network=…)`. An agent whose work is entirely local — the CLI
implementer, every website builder — runs with the network **unshared**, by the
kernel, rather than by an instruction in a prompt that a model may ignore.

## Credentials stay in step

`unmet(agent)` reports credentials an agent's tools need that the agent does not
declare. A test asserts it is empty for every agent, with a negative control
that strips one and checks the function notices — otherwise "empty everywhere"
could just mean the function returns nothing.

## What this deliberately is not

No CRM agent, no marketplace agent, no social agent, no email-sending agent was
built. The operator asked for the operating fabric and named those explicitly as
not-yet. What exists is the contract each of them will have to satisfy: a record
saying what it reaches, what that costs to be wrong with, which key it needs,
and whether a container helps.

Also not built:

- **Nothing dispatches through a tool yet.** `for_agent()` resolves the records;
  no runner consumes them to build an `Isolation` and execute. That wiring is
  the same missing piece named in `SANDBOX.md`.
- **No per-tool rate limits.** Named as a gap in `SCHEDULER.md` too.
- **No per-action approval policy**, which is what `administrator` is still
  blocked on and what `host-shell` would need before anything used it.
