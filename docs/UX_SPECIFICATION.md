# Atlas UX Specification

## 1. UX Philosophy

Atlas UX is designed for sustained professional creation, not short consumer interactions.

Core philosophy:

- clarity over decoration
- momentum over friction
- judgment support over automation theater
- professional trust over persuasive nudging

The interface must feel calm, precise, and purposeful, even when the underlying workflow is complex.

## 2. Mental Model

Atlas uses a layered mental model that maps to how professionals think:

1. Intention Layer
   - what outcome am I trying to create?
2. Workflow Layer
   - what path gets me there?
3. Production Layer
   - what assets and actions are needed now?
4. Review Layer
   - is the output good, correct, and aligned?
5. Delivery Layer
   - where does this ship and what follows next?

This model is reflected structurally:

- Space contains Projects
- Project contains Studios
- Studio contains Workflows and Assets
- Workflows contain Steps, Decisions, and Deliverables

## 3. User Attention Model

Atlas recognizes three attention modes:

### 3.1 Explore Mode

- broad scanning, discovery, comparison
- UI emphasizes optionality and navigation landmarks
- interruptions allowed at low severity

### 3.2 Build Mode

- focused creation and transformation
- UI emphasizes immediate tools, status clarity, and reduced noise
- interruptions heavily filtered

### 3.3 Resolve Mode

- debugging, reviewing, publishing, and final checks
- UI emphasizes traceability, diffs, checklists, and decision logs
- interruptions only for blockers and risk alerts

The product infers mode from context, but users can always override it.

## 4. Cognitive Load Principles

1. One Dominant Task Per Surface
   - each screen has a primary job; secondary controls are visually subordinate.
2. Locality of Information
   - decisions should be made where consequences are visible.
3. Reveal on Intent
   - advanced controls appear when users request depth.
4. Chunking
   - long operations are broken into stages with explicit progress.
5. Memory Offloading
   - users should not memorize command syntax, state transitions, or dependencies.
6. Consistent Verbs
   - actions use stable terminology across studios.
7. Error Recovery First
   - error states include diagnosis, impact, and next action.

## 5. Progressive Disclosure Strategy

Atlas defines four disclosure levels:

- Level 1: Essential
  - immediate task controls and key status.
- Level 2: Context
  - dependencies, related assets, and recent decisions.
- Level 3: Advanced
  - tuning parameters, variants, and policy-level controls.
- Level 4: Diagnostic
  - logs, traces, and deep system explanations.

Rules:

- users should never be blocked by hidden essentials
- diagnostics stay discoverable but not ambient
- advanced controls remain sticky once a user opts in

## 6. Professional Workflow Philosophy

### 6.1 Workflow as a Product Primitive

Atlas treats workflows as first-class, inspectable structures instead of invisible automation.

A workflow includes:

- objective
- inputs
- transformation steps
- decision checkpoints
- outputs
- quality criteria
- publish targets

### 6.2 Momentum Preservation

Users should move fluidly between ideation and execution without re-setup overhead.

Mechanisms:

- reusable workspace layouts
- reusable workflow templates
- command palette continuity
- contextual history and smart recall

### 6.3 Trust Through Transparency

When Atlas suggests next actions, it must show:

- why this action now
- expected benefit
- possible downside
- reversible options

## 7. Beginner vs Expert UX

Atlas is intentionally dual-track.

### 7.1 Beginner Experience

Design characteristics:

- guided starts and path suggestions
- language-first affordances
- minimal visible controls at first
- explicit examples and quality checklists

Success metric:

- beginner can complete first meaningful output without external tutorial.

### 7.2 Expert Experience

Design characteristics:

- keyboard-first operation
- dense but structured information views
- composable panels and multi-window workflows
- command chaining and history-driven acceleration

Success metric:

- expert can operate at high speed with minimal pointer travel.

### 7.3 Bridge Mechanics

Mechanisms that help users evolve:

- progressive enabling of advanced controls
- "show me how this was done" transparency panels
- optional shortcuts overlays and command hints
- workflow confidence scoring that suggests next mastery step

## 8. Interaction Laws

1. Never surprise with irreversible effects.
2. Never hide system state during long operations.
3. Never break user flow for low-priority notifications.
4. Always offer a next-best action after completion or failure.
5. Always preserve context when switching studios.

## 9. Feedback and Status Architecture

Every operation communicates four levels:

- Immediate acknowledgement: action received.
- Active status: in progress, queued, waiting, blocked.
- Outcome status: success, partial success, failed, canceled.
- Remediation path: retry, revise input, choose alternative path.

Status appears in three places:

- local component feedback
- global status bar
- activity feed timeline

## 10. Accessibility and Inclusion UX

Atlas UX requires:

- full keyboard access for all primary workflows
- predictable focus order and visible focus states
- contrast targets for all critical text and status indicators
- semantic labeling for assistive technology support
- motion-reduced mode preserving meaning without disorientation

Accessibility is a quality gate, not an enhancement backlog.

## 11. Multi-Context Continuity

Users can move between:

- projects
- studios
- windows
- monitors

without losing orientation.

Continuity tools:

- persistent breadcrumb trail
- context pinning
- global activity timeline
- recoverable workspace snapshots

## 12. UX Quality Benchmarks

Atlas UX is acceptable only when:

- first-run path to value is clear within minutes
- expert throughput improves measurably over single-app workflows
- state, progress, and blockers are visible at a glance
- users trust recommendations without feeling controlled
- complex journeys remain understandable from start to finish