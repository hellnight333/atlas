# QEVIK BROWSER + AGENT EXECUTION ARCHITECTURE

## Purpose

Provide Qevik with real computer/browser execution so users do not have to copy/paste between ChatGPT, Claude, VS Code, websites and terminals.

## Target interaction

User:
"Build and publish a website for this business."

Qevik:
1. creates a task
2. plans execution
3. researches
4. uses browser/agent tools
5. writes code
6. tests
7. deploys
8. opens the deployed site
9. verifies it
10. returns URL, screenshots and evidence

## Components

### Qevik Core
Owns:
- task state
- orchestration
- policy
- approvals
- provenance
- artifacts
- worker scheduling
- APIs

### Coding Agent
Can:
- inspect repository
- edit files
- run commands
- run tests
- diagnose failures
- commit
- push when authorized

The implementation may use Claude Code or another supported coding agent. Do not hard-code Qevik's architecture around a single vendor.

### Browser Worker

Preferred stack:
- Chromium
- Playwright
- isolated sessions
- browser profiles
- session/credential references

Capabilities:
- navigation
- DOM inspection
- screenshots
- downloads
- uploads
- forms
- authentication
- crawling
- publishing
- production verification

### Agent Runtime

Agents should not receive unrestricted permanent server access.

Use:
- task-scoped workspaces
- explicit tool permissions
- environment isolation
- command allow/deny policy
- secrets references rather than plaintext
- execution timeout
- resource limits
- logs

## OpenClaw / Claude Cowork

These can be considered implementation integrations or operator tools.

They are NOT required to be Qevik's core architecture.

Qevik should own the durable task model and execution state.

If an external agent can execute browser/computer actions, wrap it behind an adapter.

## Disconnect behavior

The user interface is not the execution process.

A task must continue when:
- SSH closes
- browser closes
- laptop sleeps
- phone disconnects

The task is server-side and resumable.

## Human approval

Require approval before:
- purchases
- sending external messages
- deleting production resources
- changing critical DNS
- publishing sensitive material
- accessing protected accounts beyond configured authorization

Routine actions may be pre-approved by policy.

## Evidence

Each browser action/workflow should be able to produce:
- URL
- timestamp
- screenshot
- extracted result
- status
- relevant logs
- artifact reference

## Acceptance test

Start a browser task from the Qevik web UI, disconnect the client, reconnect later, and confirm:
- task continued
- final state is preserved
- logs exist
- screenshots/artifacts exist
- result is visible
