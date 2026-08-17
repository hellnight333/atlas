# Qevik — Hetzner-First Execution Plan

## Objective

Stop moving the development environment between machines.

For the current phase, **Hetzner is the canonical Qevik development and execution server**. Build, test, run, and maintain the system there first. HP Z8 and Lenovo P520 can be added later as workers/rendering nodes without moving the core project.

The immediate priority is to get Qevik usable for real business work as quickly as possible.

## Architecture

```text
                 QEVIK
          Browser / Mobile UI
                    |
                    v
             Hetzner Qevik Core
             ------------------
             Git / Backend / API
             PostgreSQL
             Agents / Coding
             Web Research
             Job Orchestration
             Projects / Artifacts
             Logs / Audit
                    |
          +---------+----------+
          |         |          |
          v         v          v
       Future     Future     Future
       HP Z8      P520      Iran Worker
       GPU/AI    Video      Iran-origin
       Render    Render     Web access
```

**Current rule:** Qevik must not depend on the HP Z8 or P520. Everything required for development and the first business workflows runs on Hetzner.

Later:
- HP Z8 = heavy GPU/AI/render worker.
- Lenovo P520 = video/creative worker.
- Iran machine = geographic worker for Iran-only websites/services.
- Other machines = additional workers when useful.

## Immediate Business Goal

Move from platform-building to real deliverables.

Initial capabilities:

1. Find businesses without websites.
2. Research and qualify businesses.
3. Crawl/check websites from the correct geographic location.
4. Generate websites.
5. Generate web copy, images, branding assets, and basic SEO content.
6. Build simple web applications.
7. Build small games/prototypes.
8. Produce reports.
9. Keep project/source files organized.
10. Deploy finished websites/apps after approval.

## Geographic Execution

Geographic access is a first-class requirement.

Some websites work from outside Iran and some do not. Therefore Qevik must support geographic workers.

For an Iran-dependent task:

```text
Qevik
  -> classify task as Iran-required
  -> send request to Iran worker
  -> collect result
  -> continue analysis/build
```

Do not assume that success from Hetzner means success from Iran.

The Iran worker can be added after the Hetzner core is stable. Do not block the initial build on it.

## Coding

Coding runs continuously on Hetzner.

Claude Code and other coding agents operate against the canonical Git repository on Hetzner.

Rules:
- Git is the source of truth.
- Never rely on uncommitted local files as the only copy.
- Commit meaningful changes.
- Keep the working tree clean after milestones.
- Run tests on Hetzner.
- Database initialization/migrations must work from a clean state.

## File / Project Policy

All Qevik source code belongs in Git.

Do not create important project files in arbitrary home-directory folders.

Keep temporary files, caches, virtual environments, node_modules, coverage files, and generated binaries ignored unless explicitly required.

The repository must remain portable and cloneable onto another server/workstation.

## Qevik Core vs Workers

### Qevik Core

Qevik is the control/orchestration layer. It should:
- accept requests
- understand outcomes
- create/manage projects
- select capabilities/workers
- schedule jobs
- request approval for irreversible actions
- track execution
- maintain lineage
- store status/audit data
- return results

### Workers

Workers perform specialized execution:
- coding
- web research
- browser automation
- Iran crawling
- website building
- image generation
- video generation/rendering
- app/game builds
- deployment

A worker may run on Hetzner initially. Later the same worker interface can run on HP Z8, P520, Iran machine, or another host.

## Do Not Overbuild

Do not stop the project to build a perfect distributed system.

Priority:

1. Hetzner stable.
2. Qevik backend starts reliably.
3. PostgreSQL starts reliably.
4. Full existing test suite green.
5. Agent/coding execution works.
6. Browser/web research works.
7. Project creation works.
8. Website generation works.
9. App/game generation works.
10. Deployment workflow works.
11. Add remote GPU workers.
12. Add Iran geographic worker.
13. Improve mobile/browser control UX.

## First Production Workflow

```text
User request
    |
    v
Research business
    |
    v
Check website existence
    |
    v
If no website:
    -> create project
    -> generate site plan
    -> generate copy
    -> generate assets
    -> implement website
    -> run tests
    -> preview
    -> request approval
    -> deploy
    |
    v
Return report + project + deployment status
```

The same architecture should later support:

- Build me an app
- Build me a game
- Create a landing page
- Create a dashboard
- Research this market
- Find businesses that need websites
- Create a video
- Generate a product presentation

## Hardware Strategy

Do not configure Qevik core around GPU hardware yet.

Hetzner is the canonical execution environment.

Later:

### HP Z8
Heavy GPU workloads, local AI, rendering, video generation.

### Lenovo P520
Creative/video workstation and optional worker.

### Iran machine
Iran-local execution for Iran-only websites, crawling, verification, and services.

All connect to Qevik through a worker interface rather than becoming separate Qevik installations.

## Security

Do not expose unnecessary services publicly.

Use SSH keys.

Never commit:
- passwords
- API keys
- OAuth secrets
- private SSH keys
- secret-containing `.env` files
- tokens

Use environment variables or a proper secrets mechanism.

Because SSH is publicly reachable, harden it before production: disable password authentication when key access is confirmed and add appropriate brute-force protection.

## Claude Code Instructions

When working on this repository:

1. Read `CLAUDE.md`.
2. Read the relevant Qevik project-state and roadmap documents.
3. Inspect the current implementation before changing architecture.
4. Prefer small, testable changes.
5. Do not invent infrastructure that is not required.
6. Keep Git history clean.
7. Run relevant tests after changes.
8. Never claim a feature is complete without verifying it.
9. Update project-state/roadmap documentation when a milestone materially changes.
10. Preserve existing architectural decisions unless there is a concrete reason to change them.

## Immediate Task

Start from the current repository state and make Qevik operational on Hetzner.

### Phase A — Stabilize
- Verify Git repository and branch.
- Verify runtime/dependencies.
- Verify PostgreSQL.
- Verify database initialization from an empty database.
- Run the complete test suite.
- Fix failures.
- Ensure the application starts cleanly.
- Ensure services restart without manual repair.

### Phase B — Execution
- Verify the existing agent/coding execution path.
- Make a coding task executable from Qevik.
- Persist job/run status.
- Capture logs.
- Return artifacts/results.

### Phase C — Web
- Verify web research capability.
- Verify browser/crawl abstraction.
- Keep geographic execution as a worker capability.
- Do not hard-code Iran execution into the core.

### Phase D — Business Deliverables
Build the minimum reliable pipeline for:
- website generation
- simple app generation
- simple game generation
- report generation

The user should be able to request these from Qevik without manually opening VS Code and moving files between machines.

## Definition of Done

This stage is complete when:

- Qevik runs on Hetzner.
- PostgreSQL is reliable.
- The full test suite is green.
- Claude Code can work against the canonical repository.
- A request can create a tracked job.
- A coding/build worker can execute the job.
- Results and artifacts are persisted.
- A website project can be created and built.
- HP Z8/P520/Iran workers can later be added without rewriting the core.
- The repository is reproducible on another machine with Git.

## Important

Do not spend the next phase debating OpenClaw, workstation operating systems, or GPU placement.

Those are secondary.

**Fastest path to revenue:**

```text
Hetzner
  -> Qevik
  -> coding/research agents
  -> website/app/game generation
  -> real business deliverables
```

Get this working first. Add hardware workers afterward.
