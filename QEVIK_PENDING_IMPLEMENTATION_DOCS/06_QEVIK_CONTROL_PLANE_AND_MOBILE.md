# QEVIK CONTROL PLANE + MOBILE OPERATION

## Goal

The user should be able to operate Qevik from a phone, browser, home computer or another workstation.

## Principle

The client is a control surface, not the execution environment.

## User actions

Examples:
- start task
- inspect task
- approve action
- pause
- resume
- cancel
- inspect logs
- inspect screenshots
- download artifacts
- open deployment
- inspect worker health

## Task screen

Show:
- task name
- current stage
- progress
- status
- worker
- logs
- approvals
- artifacts
- errors
- timestamps
- final result

## Mobile requirements

- responsive UI
- touch-friendly controls
- no dependency on desktop-only features
- reconnect to running jobs
- notifications/status polling or realtime updates

## Long-running jobs

The task must remain active if the client disconnects.

Use a durable server-side execution model.

## Authentication

Implement secure authentication and session management.

Never put SSH keys or provider credentials into the browser.

## Acceptance

Start a long task on desktop, close the browser, open Qevik on a phone, and resume monitoring without losing state.
