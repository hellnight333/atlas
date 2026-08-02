# Atlas Performance Targets

## 1. Purpose

This document converts shell performance philosophy into measurable quality targets.

This is the source of truth for shell-level performance acceptance criteria.

## 2. Measurement Policy

### 2.1 Target Classes

Each metric defines:

- P50 target
- P95 target
- failure threshold

### 2.2 Environment Classes

Targets should be validated across:

- baseline hardware class
- recommended hardware class
- high-scale workspace dataset class

### 2.3 User-Perceived Priority

Metrics prioritize:

1. interaction acknowledgment
2. context switch responsiveness
3. retrieval responsiveness
4. sustained smoothness under background load

## 3. Performance Targets

### 3.1 Startup

Cold start to interactive shell:

- P50: <= 2.5 s
- P95: <= 4.5 s
- failure threshold: > 6.0 s

Warm start resume to interactive shell:

- P50: <= 1.2 s
- P95: <= 2.5 s
- failure threshold: > 3.5 s

### 3.2 Workspace Switching

Project-to-project context switch acknowledgment:

- P50: <= 120 ms
- P95: <= 250 ms
- failure threshold: > 400 ms

First meaningful workspace render after switch:

- P50: <= 700 ms
- P95: <= 1400 ms
- failure threshold: > 2000 ms

### 3.3 Universal Search

First result hint latency:

- P50: <= 80 ms
- P95: <= 180 ms
- failure threshold: > 300 ms

Top-ranked stable results ready:

- P50: <= 250 ms
- P95: <= 600 ms
- failure threshold: > 900 ms

### 3.4 Command Palette

Palette open acknowledgment:

- P50: <= 60 ms
- P95: <= 120 ms
- failure threshold: > 200 ms

Command preview and candidate list ready:

- P50: <= 120 ms
- P95: <= 300 ms
- failure threshold: > 500 ms

### 3.5 Panel Opening and Docking

Panel open/close animation and input readiness:

- P50: <= 100 ms
- P95: <= 220 ms
- failure threshold: > 350 ms

Dock snap feedback acknowledgement:

- P50: <= 50 ms
- P95: <= 120 ms
- failure threshold: > 200 ms

### 3.6 Asset Loading

Asset metadata preview visible:

- P50: <= 180 ms
- P95: <= 450 ms
- failure threshold: > 700 ms

Large asset contextual preview ready:

- P50: <= 900 ms
- P95: <= 2200 ms
- failure threshold: > 3000 ms

### 3.7 Timeline Scrolling (Activity Center)

Perceived smooth scrolling with virtualized datasets:

- P50 frame budget: <= 16.7 ms
- P95 frame budget: <= 33.3 ms
- failure threshold: > 50 ms sustained

### 3.8 Background Tasks

Task state propagation to shell surfaces:

- P50: <= 120 ms
- P95: <= 300 ms
- failure threshold: > 500 ms

Long-running task progress tick cadence:

- target interval: 1 to 3 s
- failure threshold: > 8 s without heartbeat for running task

### 3.9 UI Responsiveness

Primary input acknowledgment (click/keystroke intent feedback):

- P50: <= 50 ms
- P95: <= 100 ms
- failure threshold: > 150 ms

## 4. Degradation Strategy

Under heavy load:

1. degrade decorative animation first
2. reduce non-critical background refresh frequency
3. preserve primary interaction acknowledgment and command entry speed

## 5. Performance and Trust

If any failure threshold is crossed for user-facing interactions:

- status surfaces must expose degraded state
- Activity timeline must record impacted duration and domain
- remediation guidance should be available

## 6. Anti-Ambiguity Rules

1. No performance claim without P50 and P95 target.
2. Smoothness claims must include frame-budget thresholds.
3. Background load must not invalidate primary interaction guarantees.
4. Search and command response targets must be measured separately.
5. Performance degradation must be user-visible at critical thresholds.

## 7. Cross-References

- Shell performance philosophy: DESKTOP_SHELL_V1.md
- Activity propagation timing dependencies: ACTIVITY_MODEL.md
- Search latency and freshness behavior: UNIVERSAL_SEARCH.md
- Long-session resilience constraints: LONG_SESSION_UX.md