# QEVIK — AUTONOMOUS EXECUTION & BROWSER OPERATIONS ARCHITECTURE

**Document type:** Standalone implementation specification  
**Status:** Proposed / Next Architecture Track  
**Scope:** Browser automation, web research, crawling, publishing, remote execution, worker routing, approvals, and the Qevik commercial website  
**Relationship to previous documents:** This document is intentionally separate. It extends the Qevik execution model without replacing the existing project roadmap, project state, or infrastructure document.

---

## 1. Purpose

Qevik must evolve from a system that can coordinate development work into a system that can **actually perform computer and internet work on the user's behalf**.

The target experience is:

> The user gives Qevik a job. Qevik plans it, executes it, uses browsers and tools when required, builds the requested artifact, tests it, publishes it when authorized, and reports the result.

The user should not have to repeatedly copy commands, manually operate Chrome, move files between machines, or perform deployment steps that Qevik can safely automate.

Human intervention remains required for sensitive or irreversible actions such as payments, legal acceptance, destructive operations, or other actions explicitly configured to require approval.

---

## 2. Target Operating Model

The canonical control plane remains:

**Hetzner `qevik-core-01`**

Qevik Core coordinates work and delegates execution to specialized capabilities/workers.

```text
                         USER
                          │
                          ▼
                 ┌─────────────────┐
                 │   QEVIK APP/UI  │
                 │ Web / Desktop   │
                 │ Mobile Browser  │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │   QEVIK CORE    │
                 │ Hetzner         │
                 │ Control Plane   │
                 └────────┬────────┘
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
   Coding/Agent      Browser Worker    Other Workers
      Runtime            │             / Services
          │              │
          │              ▼
          │       Internet / Websites
          │
          ├───────────────┐
          │               │
          ▼               ▼
       Git/GitHub       Deployments

Future specialized workers:
  HP Z8       → GPU / AI / rendering
  Lenovo P520 → video / creative workloads
  Iran Worker → Iran-origin browsing / crawling / verification
```

The architecture must allow additional workers to be added without redesigning Qevik Core.

---

## 3. Core Principle

### Qevik is the orchestrator; tools and workers are execution capabilities.

Claude Code, browser automation, Playwright, Chromium, Git, deployment providers, GPU machines, and future tools are **capabilities available to Qevik**.

They should not become the product's architectural center.

Qevik should maintain:

- task identity;
- execution state;
- authorization;
- approvals;
- artifacts;
- provenance;
- logs;
- worker routing;
- retry state;
- deployment state;
- audit history.

---

## 4. Browser Execution Layer

Qevik needs a real browser execution capability.

### Required baseline

Use a browser automation stack capable of:

- Chromium;
- Playwright;
- persistent browser sessions where appropriate;
- multiple isolated browser profiles;
- navigation;
- clicking;
- typing;
- scrolling;
- JavaScript execution;
- screenshots;
- PDF/download handling;
- upload handling;
- DOM inspection;
- network-aware diagnostics;
- page extraction;
- authenticated sessions;
- cookie/session persistence with appropriate security controls.

The implementation must distinguish between:

### A. Research browser

Used for:

- public web search;
- website discovery;
- crawling;
- content extraction;
- competitor research;
- accessibility checks;
- website verification.

### B. Authenticated operational browser

Used for authorized actions such as:

- CMS administration;
- hosting dashboards;
- GitHub;
- deployment dashboards;
- business SaaS;
- account management;
- uploading assets;
- publishing content.

Credentials and sessions must never be exposed in task logs or model prompts unnecessarily.

---

## 5. Browser Jobs

Every browser operation should be represented as a Qevik job.

```text
BrowserJob
├── job_id
├── task_id
├── worker_id
├── browser_profile
├── target_url
├── objective
├── allowed_actions
├── approval_policy
├── artifacts
├── screenshots
├── extracted_data
├── logs
├── status
└── result
```

Suggested statuses:

```text
queued
planning
starting
running
waiting_for_approval
blocked
failed
completed
cancelled
```

---

## 6. Web Research

Qevik should be able to perform end-to-end research.

Example:

> Find 20 Dubai businesses that do not have a good website.

Qevik should be able to:

1. Search for candidate businesses.
2. Collect candidate URLs.
3. Visit their websites where available.
4. Determine whether a website exists.
5. Evaluate basic quality/availability criteria.
6. Record evidence.
7. Identify businesses with missing or poor web presence.
8. Produce a structured report.
9. Preserve sources and timestamps.

The result must contain provenance rather than merely a model-generated claim.

Example:

```text
Business
Website status
URL
HTTP status
Observed title
Observed content
Accessibility result
Last checked
Evidence
Confidence
```

---

## 7. Iran-Origin Web Worker

This is a first-class architectural requirement.

A website's accessibility from Hetzner does not establish its accessibility from Iran.

Qevik must eventually support:

```text
                   QEVIK CORE
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
       External Worker      Iran Worker
              │                 │
              ▼                 ▼
       External Internet    Iranian Internet
```

A task can specify:

```text
execution_region = iran
```

or:

```text
verification_regions = [external, iran]
```

Example:

> Check whether this website is accessible from Iran.

Qevik should execute the appropriate test from the Iran Worker and return the result with evidence.

The Iran Worker should be independently addressable and replaceable.

Do not design the core system around IP spoofing or assumptions about geography. Use a real execution point in the required region.

---

## 8. Website Factory

Qevik must be able to create websites without requiring manual copy/paste workflows.

A website task should be capable of progressing through:

```text
Idea
 ↓
Research
 ↓
Requirements
 ↓
Design
 ↓
Implementation
 ↓
Local build
 ↓
Automated tests
 ↓
Preview
 ↓
Human review if required
 ↓
Git commit
 ↓
Deployment
 ↓
Production verification
 ↓
Report
```

Example:

> Build a modern website for this Dubai restaurant.

Qevik should be capable of:

- researching the business;
- gathering permitted public information;
- generating structure/content;
- generating or requesting visual assets;
- writing the application;
- running the build;
- running tests;
- creating a Git branch/commit;
- deploying to the configured provider;
- opening the production URL;
- checking the rendered result;
- reporting the URL and deployment state.

---

## 9. Publishing Layer

Publishing must be an explicit capability.

Potential capabilities:

```text
Git
GitHub
Hosting
DNS
Domain configuration
Cloud deployment
Database migration
Environment configuration
CDN/cache invalidation
Production verification
Rollback
```

Publishing workflow:

```text
BUILD
  ↓
TEST
  ↓
PACKAGE
  ↓
APPROVAL POLICY
  ↓
DEPLOY
  ↓
VERIFY
  ↓
PUBLISH RESULT
```

A deployment should produce:

```text
deployment_id
project_id
commit_sha
environment
provider
deployment_url
status
started_at
completed_at
verification_result
rollback_reference
```

---

## 10. Safe Publishing Rules

Qevik may automate routine publishing when the project policy permits it.

The following should default to approval:

- payment;
- purchasing a domain;
- accepting legal agreements;
- deleting production resources;
- destructive database operations;
- sending consequential external communications;
- entering sensitive financial information;
- actions explicitly marked `approval_required`.

The approval system must be integrated into the execution engine rather than implemented as an ad-hoc UI prompt.

---

## 11. Coding Agent Integration

Claude Code can remain the coding engine.

Qevik should be able to create an isolated coding task:

```text
Qevik Task
   ↓
Agent Task
   ↓
Repository workspace
   ↓
Claude Code / coding agent
   ↓
Tests
   ↓
Git diff
   ↓
Review
   ↓
Commit
   ↓
Deploy
```

Qevik must know:

- which repository;
- which branch;
- which workspace;
- which task;
- which files changed;
- test results;
- commit SHA;
- deployment state.

The repository remains the source of truth for source code.

---

## 12. Long-Running Jobs

Qevik must not depend on a user's terminal remaining open.

Long-running tasks should execute on the server.

Examples:

- website generation;
- crawling;
- research;
- media generation;
- builds;
- tests;
- deployments;
- data processing.

The user should be able to close their laptop/phone and later reconnect to Qevik to inspect:

```text
Task
Progress
Logs
Artifacts
Approvals
Result
```

---

## 13. Remote User Experience

The user should be able to interact with Qevik from:

- desktop;
- laptop;
- phone;
- browser;
- future native application.

The device should primarily act as a control surface.

```text
Phone
  ↓
Qevik Web UI
  ↓
Task created
  ↓
Hetzner
  ↓
Browser / Coding / Worker
  ↓
Result
  ↓
Phone notification
```

The user should not need to SSH into the server for normal operation.

SSH remains an administrator/developer fallback.

---

## 14. Qevik Task Model

Every meaningful request should become a durable task.

```text
Task
├── id
├── user_request
├── plan
├── capabilities_required
├── worker_requirements
├── approval_policy
├── execution_steps
├── current_step
├── artifacts
├── logs
├── browser_sessions
├── git_changes
├── deployment
├── result
└── audit_record
```

This is the foundation for the "give Qevik a job and come back later" experience.

---

## 15. Capability Routing

Qevik should select the correct worker/capability based on requirements.

```text
Task: Build website
→ Qevik Core
→ Coding Agent
→ Browser Worker
→ Deployment

Task: Render 4K video
→ Qevik Core
→ GPU Worker
→ P520 / HP Z8

Task: Run AI image generation
→ Qevik Core
→ GPU Worker

Task: Verify website from Iran
→ Qevik Core
→ Iran Worker

Task: Build game
→ Qevik Core
→ Coding Agent
→ GPU/creative worker if required
```

Workers should advertise capabilities.

Example:

```text
WorkerCapabilities
- browser
- chromium
- crawl
- gpu
- cuda
- video
- image
- local_model
- deployment
- iran_origin
```

---

## 16. Artifact System

Qevik must track generated artifacts.

Examples:

- source code;
- websites;
- applications;
- game builds;
- images;
- videos;
- PDFs;
- reports;
- screenshots;
- datasets;
- deployment manifests.

Every artifact should have provenance:

```text
artifact_id
type
created_by_task
created_at
source
version
storage_location
checksum
related_commit
related_deployment
```

---

## 17. Website Testing

Qevik must not consider a website complete merely because the build succeeded.

Production verification should include, where applicable:

- HTTP response;
- page load;
- JavaScript runtime errors;
- console errors;
- major route availability;
- responsive rendering;
- screenshot capture;
- links;
- forms;
- API connectivity;
- authentication flows;
- basic performance checks;
- deployment status.

For customer websites:

```text
BUILD: PASS
TESTS: PASS
DEPLOYMENT: PASS
PRODUCTION URL: ...
SMOKE TEST: PASS
SCREENSHOT: ...
```

---

## 18. Qevik Commercial Website

Qevik should have its own public website.

This is not merely documentation.

It should eventually function as the commercial front door to the product.

### Required areas

**Landing page**
- Clear positioning around: "Give Qevik the job. Qevik does the work."
- Demonstrate actual execution.

**Product**
- autonomous execution;
- coding;
- browser operation;
- research;
- website creation;
- app creation;
- automation;
- workers;
- deployment;
- approvals.

**Demos**
- Website Factory;
- Research Agent;
- Browser Agent;
- App Factory;
- Deployment;
- Automation;
- Creative/Media workflows.

**Pricing**
- configurable subscription plans;
- possible Free/Trial, Pro, Business, Enterprise tiers;
- do not hard-code final pricing until approved.

**Subscription**
- account creation;
- authentication;
- plan selection;
- checkout;
- subscription state;
- billing portal;
- usage limits;
- invoices;
- cancellation/upgrade/downgrade.

Use an approved payment provider. Never store raw card details in Qevik.

**Customer dashboard**
- projects;
- tasks;
- usage;
- deployments;
- artifacts;
- workers;
- billing;
- settings.

**Documentation**
- getting started;
- capabilities;
- security;
- integrations;
- API;
- examples;
- deployment model;
- worker model.

---

## 19. Commercial Website Architecture

The public website should be architecturally separate from the internal control plane while integrating with the same product platform.

```text
qevik.com
   │
   ├── Marketing
   ├── Product
   ├── Demos
   ├── Pricing
   ├── Docs
   └── Login
          │
          ▼
      Qevik App
          │
          ▼
      Qevik Core
```

Do not expose Qevik Core directly to the public internet beyond required secured APIs.

Use proper authentication, authorization, TLS, secrets management, rate limiting, and network controls.

---

## 20. OpenClaw / Claude Cowork Position

OpenClaw or similar computer-use systems may be evaluated as implementation components or integrations.

They should **not automatically become the architectural foundation**.

The desired model is:

```text
Qevik
 ├── coding capability
 ├── browser capability
 ├── research capability
 ├── deployment capability
 ├── media capability
 ├── worker capability
 └── approval capability
```

A third-party agent/browser framework may implement one of these capabilities where useful.

Qevik retains orchestration, state, policy, provenance, and product identity.

---

## 21. Security Requirements

Browser automation creates a substantially larger security surface.

Minimum requirements:

- isolated browser profiles;
- encrypted credentials;
- secret redaction;
- least-privilege credentials;
- per-task authorization;
- approval gates;
- audit logs;
- no secret values in model prompts unless required;
- no secret values in screenshots/logs where avoidable;
- session expiration;
- worker authentication;
- secure transport;
- restricted service accounts;
- filesystem isolation for agent jobs;
- command execution policy;
- network egress policy where appropriate.

Never give an autonomous agent unrestricted production credentials by default.

---

## 22. Observability

Every execution should be inspectable.

```text
Task
  ↓
Plan
  ↓
Step 1 — Research      ✓
Step 2 — Browser       ✓
Step 3 — Build         ✓
Step 4 — Tests         ✓
Step 5 — Approval      waiting
Step 6 — Deploy        —
Step 7 — Verify        —
```

Logs should be searchable.

Failures should preserve:

- error;
- step;
- worker;
- command/action;
- timestamp;
- relevant artifact;
- retry state.

---

## 23. Failure Handling

Qevik should distinguish:

### Retryable
- transient network error;
- temporary provider failure;
- browser timeout;
- worker unavailable.

### User action required
- login required;
- CAPTCHA;
- payment;
- approval;
- missing credential.

### Permanent failure
- invalid configuration;
- broken code;
- unsupported operation;
- unavailable API.

The system should not blindly retry destructive operations.

---

## 24. Initial Implementation Priority

Implement in this order:

### Priority 1 — Durable task execution
Ensure Qevik can run tasks independently of the user's terminal.

### Priority 2 — Agent/coding execution
Integrate the coding agent with isolated workspaces, Git, tests, and artifacts.

### Priority 3 — Browser Worker
Deploy Chromium + Playwright and expose browser jobs to Qevik.

### Priority 4 — Research/Crawling
Implement search/crawl/extraction/provenance.

### Priority 5 — Publishing
Implement Git/deployment/provider integrations and production verification.

### Priority 6 — Approval/security hardening
Make sensitive actions safe and auditable.

### Priority 7 — Iran Worker
Implement geographically distinct browser execution and verification.

### Priority 8 — GPU Workers
Attach HP Z8 and Lenovo P520 when ready.

### Priority 9 — Qevik Commercial Website
Build the public marketing/product site and then customer account/subscription infrastructure.

---

## 25. Definition of Done

This architecture is materially implemented when the following workflow works without manual copy/paste:

> Find a local business without a good website. Build them a website, deploy it to the configured staging environment, and send me the result.

Qevik should:

1. Create task.
2. Plan execution.
3. Search web.
4. Use browser.
5. Crawl candidate sites.
6. Record evidence.
7. Select candidate.
8. Create project.
9. Use coding agent.
10. Run tests.
11. Build preview.
12. Capture screenshot.
13. Request approval if required.
14. Commit code.
15. Deploy.
16. Open deployed site.
17. Run production smoke test.
18. Store artifacts.
19. Return business, project, Git commit, deployment URL, verification, screenshots, and remaining actions.

No manual terminal copy/paste should be required for normal execution.

---

## 26. Example Future Tasks

Qevik should ultimately support requests such as:

> "Build a website for this company and show me the preview."

> "Find 50 businesses in Dubai that don't have a proper website."

> "Check this website from both the UK and Iran."

> "Build a SaaS dashboard from this specification."

> "Create a simple mobile game and prepare the build."

> "Research these competitors and produce a report."

> "Publish the website after I approve it."

> "Take this existing website, improve the design, test it, and deploy the new version."

> "Generate a promotional video for this website."

> "Run the overnight build and tell me what failed."

---

## 27. Architectural Rule

Do not optimize the system around the assumption that the user is sitting at the computer.

Optimize it around:

> **Qevik receives a job → Qevik executes the job → Qevik preserves state → Qevik asks only when human intervention is necessary → Qevik returns the result.**

The user's device is a control surface.

The Hetzner server is the current control plane.

Workers provide specialized execution capabilities.

Git remains the source of truth for source code.

The browser is a first-class execution capability.

The Iran Worker is a first-class geographic execution capability.

The HP Z8 and Lenovo P520 are future specialized workers.

The Qevik public website is the commercial front door.

---

## 28. Instruction to Implementation Agent

When implementing this document:

1. Inspect the existing Qevik architecture before introducing new abstractions.
2. Reuse existing task, approval, capability, worker, artifact, audit, and execution models where they already satisfy requirements.
3. Do not create parallel orchestration systems unnecessarily.
4. Do not replace the existing Git source-of-truth model.
5. Do not hard-code provider-specific assumptions into the core when an adapter is practical.
6. Keep browser execution isolated.
7. Treat credentials and browser sessions as secrets.
8. Make long-running execution server-side.
9. Make every meaningful execution resumable and observable.
10. Preserve provenance for research and generated artifacts.
11. Require approval for sensitive/irreversible operations.
12. Build browser and publishing layers as reusable capabilities, not one-off website scripts.
13. Design worker registration/routing so HP Z8, P520, and Iran Worker can be attached later without redesigning Qevik Core.
14. Do not assume OpenClaw or Claude Cowork is mandatory; evaluate them as optional implementation components.
15. Do not consider the feature complete until the end-to-end workflow can execute without manual copy/paste.

---

## 29. Current Infrastructure Reference

Current canonical execution server:

- Hostname: `qevik-core-01`
- Provider: Hetzner
- Public IPv4: `2.28.62.83`
- OS: Ubuntu 26.04 LTS
- Architecture: x86_64
- CPU: 4 vCPU AMD EPYC Genoa
- RAM: approximately 8 GB
- Disk: 150 GB
- Role: Qevik Core / Control Plane / Development Server

Future workers:

- HP Z8 — GPU/rendering/AI worker
- Lenovo P520 — GPU/video/creative worker
- Iran Worker — Iran-origin browsing/crawling/verification

Do not assume the user's personal computer is required for current execution.

---

## 30. Final Product Vision

Qevik should not merely be a place where AI tells the user how to perform work.

It should become the system through which the user **delegates work**.

The strategic progression is:

```text
AI suggests
     ↓
AI coordinates
     ↓
AI executes tools
     ↓
AI operates browsers
     ↓
AI builds
     ↓
AI tests
     ↓
AI publishes
     ↓
AI monitors
     ↓
AI reports
```

The end state is an execution platform where a user can issue a request from virtually any device and Qevik can perform the complete digital workflow using the appropriate agents, browsers, services, and physical/cloud workers.
