# QEVIK MASTER EXECUTION PLAN
## Authoritative implementation plan

## 0. Mission

Turn Qevik from an orchestration/control layer into an executable product that can receive a request, plan it, perform authorized work through agents/tools/browsers/workers, verify the result, publish deliverables, and report evidence.

Primary execution environment:
- Hetzner `qevik-core-01`
- 2.28.62.83
- Ubuntu 26.04 LTS
- 4 vCPU AMD EPYC Genoa
- ~8 GB RAM
- 150 GB disk

Git is the source of truth.

Do not unnecessarily rewrite existing Qevik components.

## 1. Non-negotiable execution principles

1. Inspect the existing repository before implementing.
2. Preserve working functionality.
3. Make small, testable changes.
4. Every phase ends with acceptance tests.
5. No secret values in Git.
6. Irreversible external actions require explicit authorization unless already covered by an approved policy.
7. Long-running work must survive SSH/browser disconnection.
8. Every execution must have status, logs, artifacts, and provenance.
9. Qevik Core must not depend on a local GPU workstation.
10. Workers are replaceable execution resources.

## 2. Phase order

### Phase 1 — Repository and baseline
- inspect Git status, branch, remote and uncommitted work
- establish clean baseline
- inspect current architecture and PROJECT_STATE
- run existing test/build/lint/typecheck suite
- document failures before changing them

Acceptance:
- repository state known
- baseline tests recorded
- no unexplained destructive changes

### Phase 2 — Core infrastructure
- PostgreSQL
- migrations/schema initialization
- API/runtime services
- configuration
- service supervision
- logging
- health checks
- backup/restore procedure

Acceptance:
- clean database initialization works
- restore works
- core service starts from a clean state
- health endpoint is green

### Phase 3 — Execution engine
Implement/finish:
- task intake
- task decomposition
- execution plan
- task state machine
- retries
- cancellation
- resumability
- worker dispatch
- approval gates
- artifact registration
- execution lineage

Acceptance:
A task can be submitted, executed, observed, completed/failed, resumed and audited.

### Phase 4 — Agent/coding execution
Provide an execution adapter capable of running the authorized coding agent in a controlled Qevik workspace.

Required capabilities:
- read/write repository files
- execute approved shell commands
- install dependencies
- run tests/builds
- inspect failures
- make changes
- commit changes
- push only when authorized
- return structured results

Acceptance:
A test project can be modified, tested and committed without manual copy/paste.

### Phase 5 — Browser execution
Implement browser worker/service:
- Chromium
- Playwright
- isolated browser sessions
- persistent profiles where appropriate
- navigation
- screenshots
- downloads/uploads
- forms
- authenticated sessions
- crawling
- DOM/content extraction
- console/network diagnostics
- browser-based publishing
- production verification

Acceptance:
Qevik can open a site, inspect it, perform a permitted workflow, capture evidence and report the result.

### Phase 6 — Publishing
Build deployment adapters.

Minimum:
- build
- deploy
- DNS/domain integration where authorized
- TLS/HTTPS verification
- health checks
- browser verification
- rollback capability
- deployment record

Acceptance:
A generated test website can be deployed and independently verified from its public URL.

### Phase 7 — Iran-origin worker
Create a dedicated worker contract for Iran-origin network/browser execution.

Capabilities:
- browse from Iran
- crawl from Iran
- HTTP checks from Iran
- browser checks from Iran
- screenshots/evidence
- return geographic accessibility result

Do not fake geographic results using a foreign server.

Acceptance:
Qevik can distinguish a site reachable from Europe/Hetzner from one reachable from Iran.

### Phase 8 — Worker architecture
Define workers as replaceable resources.

Future:
- HP Z8: GPU/AI/rendering
- Lenovo P520: GPU/video/creative
- Iran Worker: Iran-origin network/browser
- additional workers later

Core remains responsible for orchestration, state, policy, provenance and APIs.

Acceptance:
A worker can disconnect without corrupting task state.

### Phase 9 — Control interface
Build/finish Qevik web control surface.

Must support:
- login
- projects
- tasks
- task status
- live/progressive logs
- approvals
- artifacts
- screenshots
- deployment URLs
- execution history
- retry/resume/cancel
- worker status

Mobile browser must be usable as a control surface.

Acceptance:
A user can start and monitor a task without opening VS Code or SSH.

### Phase 10 — Qevik product website
Build Qevik public website:
- positioning
- product explanation
- demos
- use cases
- pricing/plans
- signup/login
- subscription/billing integration
- CTA
- documentation
- contact
- trust/security information

The public website must itself be deployed and verified through the publishing pipeline.

### Phase 11 — Factory workflows
Implement end-to-end workflows.

#### Website Factory
request → research → plan → code → assets → test → deploy → verify → deliver

#### App Factory
idea → specification → code → tests → build → deploy/package → verify

#### Game Factory
concept → specification → assets → implementation → build → test → package

#### Content Factory
research → script → assets → generation → assembly → quality checks → publish

#### Research Factory
question → web research → crawl → extraction → verification → report

#### Outreach Factory
research → prospect qualification → personalization → approval → sending → tracking

Acceptance:
Each workflow completes without requiring the user to manually copy/paste between tools.

### Phase 12 — Commercialization
Implement:
- plans
- subscriptions
- usage accounting
- quotas
- customer projects
- billing state
- entitlement enforcement
- execution history
- customer artifacts
- support/contact path

Do not launch billing before authorization, security and failure handling are implemented.

## 3. Definition of done

Qevik is considered operational only when all of the following are true:

- core services start reliably
- PostgreSQL initialization and restore work
- full test suite is green or every exception is explicitly documented
- coding agent can execute in a controlled workspace
- browser worker can browse/crawl
- publishing pipeline can deploy and verify
- Iran-origin worker can perform genuine Iran-origin checks
- long-running jobs survive client disconnect
- artifacts and logs are persisted
- approvals exist for risky actions
- mobile/browser control works
- at least one Website Factory E2E test passes
- at least one App Factory E2E test passes
- production verification is automated
- Git remains authoritative

## 4. Execution rule for Claude Code

For each phase:
1. inspect current implementation
2. identify missing pieces
3. implement the smallest coherent change
4. run focused tests
5. run the relevant broader suite
6. update project state
7. record remaining blockers
8. only then proceed

Do not claim completion based on code existing alone. Demonstrate the acceptance test.
