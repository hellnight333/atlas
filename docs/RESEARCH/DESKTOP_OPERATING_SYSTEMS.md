# Research: Desktop Operating Systems

## 1. Research Focus

This document extracts transferable design principles from mature desktop operating systems to inform Atlas product architecture.

Focus areas:

- window and workspace management
- navigation models
- system feedback
- consistency and trust
- customization versus coherence

## 2. Core Observations

### 2.1 Stability Builds Confidence

Desktop systems succeed when spatial and behavioral consistency are preserved across sessions.

Implication for Atlas:

- maintain stable shell landmarks (top bar, sidebar, status bar)
- preserve user workspace layout memory

### 2.2 Layered Complexity Works

OS interfaces expose simple defaults while allowing deep customization for advanced users.

Implication for Atlas:

- beginner-friendly default layouts
- expert-grade docking and multi-window control

### 2.3 Interruptions Require Governance

Effective systems classify notifications by urgency and user context.

Implication for Atlas:

- route informational updates to non-blocking channels
- reserve modal interruptions for blockers only

### 2.4 Search as a Navigation Primitive

Modern desktop usage relies on global search and command launching as a first-class flow.

Implication for Atlas:

- global search and command palette must be central, not auxiliary

### 2.5 Recoverability Is Essential

Users trust systems that make mistakes reversible and state reconstructable.

Implication for Atlas:

- restore sessions reliably
- support layout snapshots and history-based recovery

## 3. Extracted Principles for Atlas

1. Persistent orientation landmarks
2. Predictable window behavior and docking semantics
3. Progressive disclosure of advanced controls
4. Attention-aware notification policy
5. Fast global retrieval across objects and contexts
6. Session continuity with graceful fallback

## 4. Anti-Patterns to Avoid

- unstable window behavior between sessions
- hidden global state changes without user awareness
- excessive modal interruption for routine updates
- customization depth that fragments basic consistency

## 5. Atlas Application Targets

These principles should directly inform:

- DESKTOP_SHELL.md
- WORKSPACE_SYSTEM.md
- COMMAND_PALETTE.md
- UX_SPECIFICATION.md

## 6. Open Research Questions

- how should Atlas prioritize deterministic layouts versus adaptive suggestions?
- what level of default guidance best supports first-time users without reducing expert speed?
- where should workspace policy boundaries live for team environments?