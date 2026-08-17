# QEVIK — MASTER EXECUTION SPECIFICATION
## Hetzner-First | 0→100 Operating Plan for Development, Research, Websites, Apps, Games, Content and Deployment

> **Purpose:** This document is the operational specification for Claude Code and the Qevik development team.
> 
> **Current strategic decision:** Hetzner is the canonical Qevik server and development environment. Do not block progress on HP Z8, Lenovo P520, OpenClaw, or any other workstation. Those systems become optional workers later.
>
> **Primary business objective:** Get Qevik from a development project into a system that can accept real requests and produce real business deliverables: websites, web apps, dashboards, games/prototypes, research reports, content, media, and deployments.

---

# 0. NON-NEGOTIABLE RULES

1. **Hetzner is the current source of execution.**
2. **Git is the source of truth for source code.**
3. Never depend on uncommitted files on a personal computer.
4. Never claim something works without testing it.
5. Never publish/deploy externally without the required user approval.
6. Never purchase domains, hosting, paid APIs, ads, subscriptions, or services without explicit approval.
7. Never expose API keys, passwords, OAuth secrets, SSH private keys, cookies, or session tokens.
8. Never put secrets in Git.
9. Every meaningful implementation milestone must be committed.
10. Preserve a reproducible deployment path.
11. Keep Qevik core independent of any particular GPU/workstation.
12. Geographic execution is a capability, not a hard-coded assumption.
13. For Iran-dependent websites, an Iran-based worker must eventually be used for verification/crawling.
14. A successful crawl from Hetzner/Europe does **not** prove availability from Iran.
15. Prefer automation, but require approval at irreversible or externally visible actions.
16. Do not redesign the architecture merely because a new tool is interesting.
17. Do not introduce OpenClaw unless a concrete requirement demonstrates that it is necessary.
18. Optimize for getting to revenue and real deliverables, not for building an elaborate platform before it can do useful work.

---

# 1. CURRENT TARGET ARCHITECTURE

```text
                         USER
                          |
              Browser / Mobile / Chat
                          |
                          v
                  +---------------+
                  |     QEVIK     |
                  | Control Plane |
                  +-------+-------+
                          |
          +---------------+----------------+
          |               |                |
          v               v                v
      Research         Projects         Jobs/Runs
          |               |                |
          +---------------+----------------+
                          |
                          v
                +-------------------+
                |  Hetzner Core     |
                |-------------------|
                | Backend/API       |
                | PostgreSQL        |
                | Agent Runtime     |
                | Coding Workers    |
                | Browser/Research  |
                | Artifact Storage  |
                | Logs/Audit        |
                +---------+---------+
                          |
              +-----------+------------+
              |           |            |
              v           v            v
          Web Worker   Build Worker  Deploy Worker
              |
              +-----------------------------+
                                            |
                              Future Remote Workers
                              -----------------------
                              HP Z8       GPU/AI/render
                              P520        video/creative
                              Iran        Iran-local web access
                              Other       specialized workers
```

### Principle

Qevik is the **control plane and orchestration layer**.

Workers execute tasks.

Do not turn each physical machine into a separate Qevik installation.

---

# 2. WHAT QEVIK MUST EVENTUALLY DO

A user should be able to issue requests such as:

### Business research

> Find 100 businesses in Dubai that have no proper website.

> Find businesses whose websites are outdated.

> Research this company and prepare a report.

### Website

> Build a website for this business.

> Make a landing page for this product.

> Rebuild this website with a modern design.

> Check whether the finished website works from Iran.

### App

> Build a small customer-management app.

> Build a dashboard.

> Build an internal business tool.

### Game

> Make a simple browser game.

> Create a prototype for this game idea.

### Content

> Create product descriptions.

> Create a marketing campaign.

> Create images.

> Create videos.

### Operations

> Deploy the website.

> Check whether the website is online.

> Check SSL.

> Check mobile rendering.

> Check forms.

> Check SEO basics.

> Monitor the deployed application.

---

# 3. USER REQUEST LIFECYCLE

Every request should conceptually pass through:

```text
REQUEST
  |
  v
UNDERSTAND
  |
  v
PLAN
  |
  v
SELECT CAPABILITIES
  |
  v
CREATE PROJECT/JOB
  |
  v
EXECUTE
  |
  v
VERIFY
  |
  v
PRESENT RESULT
  |
  v
APPROVAL IF NEEDED
  |
  v
PUBLISH/DEPLOY
  |
  v
POST-DEPLOY VERIFY
  |
  v
REPORT + AUDIT
```

The system should not jump directly from natural-language request to uncontrolled external action.

---

# 4. APPROVAL MODEL

Qevik can autonomously perform reversible/internal work.

Examples:

- write code
- create files
- run tests
- create drafts
- research public information
- build a local preview
- run Lighthouse-like checks
- generate assets
- create Git commits where authorized

Require explicit approval before:

- publishing a website
- changing DNS
- purchasing a domain
- paying for hosting
- subscribing to a paid service
- sending external email/messages
- sending proposals to customers
- making financial transactions
- deleting production data
- destructive database operations
- deploying to a production target when the user has not already authorized automatic deployment
- posting publicly
- making an irreversible change

Approval must be visible and auditable.

---

# 5. PROJECT MODEL

Every real customer/business task should become a project.

Minimum project metadata:

```text
project_id
name
client/business
description
type
status
repository
environment
domain
deployment_target
created_at
updated_at
owner
approval_state
```

Project types should eventually include:

- website
- web_app
- dashboard
- game
- research
- content
- media
- automation
- internal_tool

---

# 6. JOB/RUN MODEL

Every execution should have a trackable run.

Minimum:

```text
run_id
project_id
job_type
worker
status
started_at
finished_at
logs
artifacts
errors
approval_required
approval_state
```

Statuses:

```text
queued
planning
running
waiting_approval
failed
cancelled
completed
deployed
```

The user must be able to understand what Qevik is doing without opening a terminal.

---

# 7. ARTIFACT MANAGEMENT

Every generated deliverable must be stored as an artifact.

Examples:

- source code
- ZIP
- HTML
- images
- videos
- PDFs
- reports
- screenshots
- build output
- deployment logs
- test results

Artifacts need:

```text
artifact_id
project_id
run_id
type
path/storage reference
hash where useful
created_at
metadata
```

Do not lose generated work in temporary directories.

---

# 8. GIT / SOURCE CONTROL

For every code project:

1. Create or use a Git repository.
2. Keep source code under version control.
3. Configure `.gitignore`.
4. Never commit secrets.
5. Commit meaningful milestones.
6. Keep branches/worktrees organized where concurrent agents are used.
7. Push to the configured remote when authorized.
8. Verify the remote.
9. Ensure another machine can clone and reproduce the project.

Before deployment:

```text
git status
tests
build
deployment verification
```

A dirty/uncommitted production state should be treated as a warning.

---

# 9. CLAUDE CODE / CODING AGENT

Claude Code is a development executor, not the entire Qevik architecture.

Claude Code should:

- inspect repository state
- read `CLAUDE.md`
- read project-state/roadmap documentation
- plan work
- modify code
- run tests
- run builds
- inspect failures
- fix failures
- commit changes
- report exact results

Claude Code must not:

- invent missing requirements
- silently rewrite major architecture
- publish externally without authorization
- expose secrets
- claim success from an unverified assumption

---

# 10. WEBSITE FACTORY — END TO END

This is one of the highest-priority business workflows.

## 10.1 Discovery

Given a business:

- identify business name
- industry
- location
- services/products
- contact information from permitted/public sources
- current website
- social presence where relevant
- competitors
- obvious website weaknesses

## 10.2 Website Existence Check

Check:

- does a website exist?
- does the domain resolve?
- does HTTP/HTTPS work?
- is the site reachable?
- is it a parked domain?
- is it a social-profile-only presence?
- is the site clearly obsolete/broken?

Do not label a business "no website" solely because one crawler failed.

Use multiple signals where practical.

## 10.3 Geographic Verification

For relevant businesses, determine where the site needs to work.

If Iran is relevant:

```text
Hetzner check
      +
Iran worker check
      =
geographic availability result
```

Record:

- timestamp
- source location
- URL
- HTTP status
- DNS result
- TLS result
- response time where useful
- redirect chain where useful
- crawl result

## 10.4 Website Planning

Generate:

- sitemap
- page list
- information architecture
- visual direction
- typography
- content requirements
- CTA strategy
- SEO metadata plan
- mobile behavior

## 10.5 Implementation

Use the project's selected stack.

Possible stack choices:

- Next.js
- React
- static HTML/CSS/JS
- other approved framework

Do not add frameworks without need.

## 10.6 Content

Generate drafts for:

- homepage
- about
- services
- products
- contact
- FAQ
- metadata
- headings
- calls-to-action

Human/business facts must not be fabricated.

Mark assumptions.

## 10.7 Assets

Generate or collect assets legally and appropriately.

Track:

- source
- license/permission where relevant
- generated-vs-source status
- file location

## 10.8 Quality Checks

Before publication:

- build succeeds
- no obvious console errors
- links work
- images load
- mobile layout works
- desktop layout works
- forms behave correctly
- navigation works
- metadata exists
- favicon exists
- robots configuration is intentional
- sitemap exists where appropriate
- 404 behavior works
- accessibility basics checked
- performance checked
- no secrets in client bundle
- no placeholder text remains
- no broken asset paths
- no accidental debug UI

## 10.9 Preview

Produce a preview and screenshots.

User approval can occur here.

## 10.10 Publish

Only after approval or an explicit pre-authorized deployment policy:

- build production artifact
- deploy
- configure domain
- configure HTTPS
- verify DNS
- verify certificate
- verify public access

## 10.11 Post-Publish Verification

After deployment:

```text
DNS
  |
TLS
  |
HTTP/HTTPS
  |
Homepage
  |
All important routes
  |
Assets
  |
Forms
  |
Mobile
  |
Desktop
  |
SEO basics
```

Do not report "published successfully" until post-deployment verification has passed or failures are explicitly reported.

---

# 11. DOMAIN / DNS / HOSTING

Qevik should eventually support:

- domain discovery
- domain status checking
- DNS inspection
- deployment target selection
- DNS configuration assistance
- SSL verification
- hosting verification

But:

**Domain purchases and paid services require explicit user approval.**

Store domain metadata in the project, not in random notes.

Example:

```text
domain
registrar
dns_provider
hosting_provider
deployment_target
ssl_status
expires_at
```

Never store registrar passwords in the repository.

---

# 12. DEPLOYMENT ENGINE

The deployment system should support a provider abstraction.

Conceptually:

```text
DeploymentProvider
    |
    +-- Vercel-like provider
    +-- Cloudflare-like provider
    +-- VPS deployment
    +-- Docker deployment
    +-- Static hosting
```

Do not hard-code Qevik to one provider.

Every deployment should create a deployment record:

```text
deployment_id
project_id
provider
target
version/commit
status
started_at
finished_at
url
logs
verification_result
```

---

# 13. WEB RESEARCH ENGINE

Research should produce structured evidence, not just a paragraph.

For each source:

```text
URL
title
source type
retrieved_at
location/worker
relevant facts
confidence
```

Where appropriate:

- preserve citations
- preserve URLs
- distinguish facts from inference
- record failed requests
- retry safely
- respect robots/rate limits/terms where applicable

---

# 14. BROWSER AUTOMATION

Browser workers should support:

- navigation
- screenshots
- page inspection
- form interaction
- extracting visible information
- testing websites
- checking responsive behavior
- checking login flows where credentials are explicitly provided/authorized

Do not store browser session cookies or credentials in Git.

Browser automation must have clear limits around irreversible actions.

---

# 15. IRAN WORKER

This is an important future component.

Purpose:

- crawl Iran-only websites
- verify Iran accessibility
- perform Iran-origin HTTP/browser checks
- compare Iran vs foreign accessibility
- perform services that are geographically restricted

Architecture:

```text
Qevik
   |
   v
Worker Router
   |
   +--> Hetzner worker
   |
   +--> Iran worker
```

The Iran worker should report its geographic identity and health.

Do not spoof geographic location through unreliable assumptions.

---

# 16. APP FACTORY

For a new app request:

```text
request
 -> requirements
 -> architecture
 -> project
 -> repository
 -> implementation
 -> tests
 -> build
 -> preview
 -> approval
 -> deploy
 -> verification
```

Minimum app checks:

- startup
- routes
- API connectivity
- database connectivity where applicable
- authentication where applicable
- error handling
- responsive UI
- production build

---

# 17. GAME FACTORY

For a simple game:

```text
idea
 -> game design
 -> assets
 -> implementation
 -> local build
 -> playtest
 -> bug fixing
 -> packaging/deployment
```

Start with browser games where possible because deployment is simpler.

Later support:

- desktop
- mobile
- other engines/platforms

---

# 18. MEDIA / VIDEO FACTORY

The initial Hetzner system should orchestrate media jobs even if heavy rendering later moves to GPU workers.

Pipeline:

```text
brief
 -> script
 -> storyboard
 -> assets
 -> generation
 -> assembly
 -> render
 -> QC
 -> artifact
```

Later:

```text
Qevik -> HP Z8/P520 GPU worker
```

The core should not assume a local GPU exists.

---

# 19. BUSINESS LEAD FACTORY

A high-value workflow:

```text
Target geography/industry
       |
       v
Find businesses
       |
       v
Research each business
       |
       v
Website check
       |
       v
Quality score
       |
       v
Prioritize prospects
       |
       v
Generate report
       |
       v
Optional outreach draft
       |
       v
User approval
       |
       v
Send outreach
```

Never automatically send commercial outreach unless explicitly authorized.

---

# 20. REPORTING

Reports should be first-class artifacts.

A report may include:

- executive summary
- methodology
- findings
- URLs
- evidence
- screenshots
- technical checks
- recommendations
- confidence
- next actions

Formats can include:

- Markdown
- HTML
- PDF
- JSON
- CSV

---

# 21. OBSERVABILITY

Every service needs enough visibility to answer:

- Is it running?
- What is it doing?
- What failed?
- Why did it fail?
- Which worker ran it?
- Which project caused it?
- Which commit produced it?

At minimum:

- structured logs
- job/run status
- health endpoints
- error records
- audit trail

---

# 22. DATABASE

PostgreSQL is the canonical application database.

Database requirements:

- reproducible initialization
- migrations
- clean empty-database bootstrap
- backups eventually
- no manual schema edits as the normal workflow
- safe migration process
- tests against a realistic database

The current database initialization problem must remain solved and covered by tests.

---

# 23. AUTHENTICATION / ACCOUNTS

Qevik should eventually support user accounts and authenticated integrations.

Requirements:

- secure authentication
- session management
- role/permission model where needed
- OAuth integrations
- token storage outside Git
- revocation
- audit events

Integrations may eventually include:

- GitHub
- Google
- email
- cloud providers
- deployment providers
- AI providers
- browser services

Do not implement every integration before the core business workflows work.

---

# 24. EXTERNAL ACCOUNTS

For any account connection:

```text
user starts connection
 -> provider OAuth/login
 -> callback
 -> token stored securely
 -> connection health checked
 -> integration available to Qevik
```

Never ask the user to paste a private access token into a public repository.

Never write OAuth client secrets into source files.

---

# 25. EMAIL

Email automation should support:

- drafts
- templates
- approval
- sending
- delivery status
- audit

Default:

**draft first, send after approval.**

For already-authorized automated campaigns, respect the configured policy and maintain an audit trail.

---

# 26. MOBILE / BROWSER CONTROL

The user should eventually be able to control Qevik from:

- desktop browser
- mobile browser
- Qevik desktop application
- future chat interface

The mobile interface does not need to contain the development environment.

It needs to expose:

- projects
- jobs
- approvals
- reports
- artifacts
- logs/status
- worker health
- deployment status

Example:

> Build a website for this company.

The phone sends the request.

Hetzner performs the work.

The phone displays progress.

---

# 27. WORKER ROUTER

The worker router should eventually select workers based on:

```text
capability
location
GPU
CPU
RAM
availability
cost
privacy
latency
task type
```

Example:

```text
coding -> Hetzner
research -> Hetzner
Iran crawl -> Iran worker
heavy video -> HP Z8/P520 later
local AI -> GPU worker later
```

This is the mechanism that makes the architecture portable.

---

# 28. SECURITY BASELINE FOR HETZNER

Before treating Hetzner as production infrastructure:

- SSH keys only
- disable password authentication after confirming key access
- brute-force protection
- firewall
- only required ports open
- regular security updates
- non-root application user(s)
- backups
- service isolation
- secrets outside Git
- database not publicly exposed unless required
- TLS for public interfaces
- logs monitored

Do not lock down SSH in a way that removes the user's recovery path. Keep a verified administrative access path before changing SSH configuration.

---

# 29. BACKUPS

Eventually maintain:

### Database
- scheduled backups
- retention
- restore testing

### Source
- Git remote

### Artifacts
- persistent storage
- backup strategy

A backup that has never been restored is not considered verified.

---

# 30. CI/CD

The repository should eventually have:

```text
push
  -> lint
  -> typecheck
  -> unit tests
  -> integration tests
  -> build
  -> package
```

Deployment should only occur when required checks pass.

Production deployment should be observable and reversible where practical.

---

# 31. TESTING POLICY

Tests should exist at several levels:

### Unit
Individual functions/components.

### Integration
Database/API/worker interactions.

### End-to-end
User workflow.

### Deployment verification
Public deployed result.

Critical workflows should have end-to-end tests.

---

# 32. FULL-SUITE GREEN IS A GATE

Before adding large new features:

1. Run the existing suite.
2. Fix regressions.
3. Establish a green baseline.
4. Add the next feature.
5. Run targeted tests.
6. Run the full suite again.

Do not allow a growing permanent pile of ignored failures.

---

# 33. PROJECT DOCUMENTATION

Keep the existing project documentation authoritative.

Relevant files include:

- `CLAUDE.md`
- `PROJECT_MEMORY.md`
- `docs/qevik-docs/00_PROJECT_STATE.md`
- `docs/qevik-docs/62_ROADMAP.md`
- architecture documents
- deployment documents
- testing documents

Do not create competing project-state documents unless there is a clear reason.

This file is an execution specification, not a replacement for the project's existing architecture/roadmap documentation.

---

# 34. OPENCLAW

OpenClaw is **not a current blocker**.

Do not install or architect around it solely because it may be useful.

If a concrete capability gap appears:

1. identify the missing capability
2. determine whether Qevik can implement it directly
3. compare available tools
4. add the smallest appropriate component

---

# 35. HARDWARE WORKERS

Future machines:

## HP Z8
Purpose:
- GPU AI
- rendering
- video generation
- heavy local inference

## Lenovo P520
Purpose:
- video
- creative work
- GPU worker
- optional local development

## Iran machine
Purpose:
- Iran-local browser
- Iran-local crawling
- geographic verification

The Qevik core must not require any of these to remain online.

---

# 36. CURRENT DEVELOPMENT ENVIRONMENT

Current canonical development:

```text
Hetzner
  |
  +-- Git repository
  +-- Qevik
  +-- PostgreSQL
  +-- Claude Code
  +-- workers
```

Personal computers are clients/administration machines until further notice.

---

# 37. 0 → 100 IMPLEMENTATION ROADMAP

## LEVEL 0 — REPOSITORY

- [ ] Git state verified
- [ ] Remote verified
- [ ] CLAUDE.md read
- [ ] Project state read
- [ ] Roadmap read
- [ ] Working tree understood

## LEVEL 1 — SERVER

- [ ] Ubuntu/server baseline verified
- [ ] SSH access reliable
- [ ] Firewall
- [ ] Updates
- [ ] Application user
- [ ] Docker/container strategy where appropriate
- [ ] Monitoring basics

## LEVEL 2 — DATABASE

- [ ] PostgreSQL
- [ ] clean initialization
- [ ] migrations
- [ ] tests
- [ ] backup plan

## LEVEL 3 — QEVIK CORE

- [ ] backend starts
- [ ] API works
- [ ] configuration works
- [ ] health checks
- [ ] logging
- [ ] project model
- [ ] job/run model

## LEVEL 4 — AGENT EXECUTION

- [ ] agent can receive task
- [ ] agent can inspect repository
- [ ] agent can modify files
- [ ] agent can run tests
- [ ] job state persisted
- [ ] logs captured
- [ ] artifacts captured

## LEVEL 5 — WEB RESEARCH

- [ ] web search
- [ ] browser
- [ ] crawl
- [ ] extraction
- [ ] citations/evidence
- [ ] screenshots
- [ ] geographic worker interface

## LEVEL 6 — WEBSITE FACTORY

- [ ] business research
- [ ] website existence detection
- [ ] site planning
- [ ] code generation
- [ ] content
- [ ] assets
- [ ] build
- [ ] QA
- [ ] preview
- [ ] approval
- [ ] deployment
- [ ] DNS
- [ ] TLS
- [ ] post-deployment verification

## LEVEL 7 — APP FACTORY

- [ ] project generation
- [ ] implementation
- [ ] tests
- [ ] build
- [ ] preview
- [ ] deploy
- [ ] verify

## LEVEL 8 — GAME FACTORY

- [ ] prototype
- [ ] assets
- [ ] implementation
- [ ] playtest
- [ ] package
- [ ] deploy

## LEVEL 9 — CONTENT/MEDIA

- [ ] copy
- [ ] images
- [ ] video
- [ ] reports
- [ ] artifacts
- [ ] future GPU routing

## LEVEL 10 — BUSINESS FACTORY

- [ ] prospect discovery
- [ ] website qualification
- [ ] scoring
- [ ] reports
- [ ] outreach drafts
- [ ] approval
- [ ] authorized outreach

## LEVEL 11 — OPERATIONS

- [ ] worker health
- [ ] deployment status
- [ ] audit
- [ ] backups
- [ ] restore testing
- [ ] monitoring

## LEVEL 12 — REMOTE WORKERS

- [ ] worker registration
- [ ] worker authentication
- [ ] capability discovery
- [ ] health checks
- [ ] job routing
- [ ] artifact transfer
- [ ] HP Z8
- [ ] P520
- [ ] Iran worker

## LEVEL 13 — MOBILE CONTROL

- [ ] projects
- [ ] jobs
- [ ] approvals
- [ ] reports
- [ ] artifacts
- [ ] deployment status
- [ ] worker status

---

# 38. FIRST REAL BUSINESS DEMO

The first meaningful end-to-end demo should be:

```text
User:
"Find businesses in [target] that do not have a proper website."

Qevik:
  -> research
  -> website checks
  -> qualification
  -> report

User:
"Build a website for prospect #1."

Qevik:
  -> create project
  -> plan
  -> code
  -> test
  -> preview
  -> show user
  -> approval

User:
"Publish it."

Qevik:
  -> deploy
  -> DNS/SSL if authorized/configured
  -> verify from Hetzner
  -> verify from geographic worker if required
  -> report result
```

If this workflow works reliably, Qevik has crossed from "engineering project" into a useful business system.

---

# 39. DEFINITION OF DONE FOR THE CURRENT PHASE

The immediate phase is complete when:

- [ ] Hetzner is the canonical environment.
- [ ] Qevik starts reliably.
- [ ] PostgreSQL starts reliably.
- [ ] Clean database initialization works.
- [ ] Full existing test suite is green.
- [ ] Claude Code can work on the repository.
- [ ] A tracked job can be created.
- [ ] An agent can execute a coding/build task.
- [ ] Logs are persisted.
- [ ] Artifacts are persisted.
- [ ] A website project can be created.
- [ ] A website can be built.
- [ ] A preview can be produced.
- [ ] Deployment can be performed with approval.
- [ ] Post-deployment verification works.
- [ ] The architecture can later add HP Z8/P520/Iran workers without rewriting Qevik core.

---

# 40. CLAUDE CODE — START HERE

Do not merely read this document and summarize it.

**Execute the plan.**

First:

1. Inspect the current repository.
2. Read `CLAUDE.md`.
3. Read the current Qevik project state.
4. Read the current roadmap.
5. Check Git status and remote.
6. Check the current Hetzner runtime.
7. Check PostgreSQL.
8. Run the full existing test suite.
9. Record failures.
10. Fix the highest-priority blockers.
11. Run the suite again.
12. Continue through the roadmap in dependency order.

When a task is completed:

- test it
- verify it
- commit it
- update project state if materially necessary
- continue

Do not stop after analysis.

Do not ask the user to manually move files between machines unless technically unavoidable.

Do not spend time configuring the HP Z8/P520 now.

Do not spend time debating OpenClaw now.

**Build the working Hetzner-first Qevik system and get to the first real website/app/game business workflow.**
