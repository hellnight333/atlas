# Atlas Command System Boundaries

## 1. Purpose

This document defines strict boundaries between:

- Universal Search
- Command Palette
- Quick Switcher
- Mission Control

It resolves user ambiguity about which system they are using.

This is the source of truth for command-system responsibilities.

## 2. System Definitions

### 2.1 Universal Search

Primary job:

- retrieve, rank, and preview objects and context

Interaction outcome:

- navigate to result or hand off to command execution surface

### 2.2 Command Palette

Primary job:

- invoke executable actions and workflows via keyboard-first command model

Interaction outcome:

- execute command, chain commands, or configure command intent

### 2.3 Quick Switcher

Primary job:

- jump rapidly between active contexts (projects, studios, workspaces, recent assets)

Interaction outcome:

- switch context immediately with minimal ceremony

### 2.4 Mission Control

Primary job:

- provide macro-level overview and orchestration of open windows/workspaces/sessions

Interaction outcome:

- reorient, reorganize, and route focus across the desktop environment

## 3. Responsibility Matrix

### 3.1 Universal Search Responsibilities

- find entities across domains
- display trust class and freshness
- provide preview and open routes

Not responsible for:

- running high-impact commands directly
- global workspace orchestration

### 3.2 Command Palette Responsibilities

- action execution
- action sequencing and chaining
- command history and pinning

Not responsible for:

- broad object browsing as primary mode
- cross-window macro orchestration

### 3.3 Quick Switcher Responsibilities

- immediate context jumps
- recent and pinned context transitions

Not responsible for:

- command execution
- deep retrieval and result analysis

### 3.4 Mission Control Responsibilities

- visualize all active workspaces/windows
- global workspace state management
- resolve orientation and focus drift

Not responsible for:

- object search ranking
- low-level tool commands

## 4. Interaction Model

### 4.1 Entry Cues

Each system must present unmistakable identity cues:

- name and scope label
- interaction grammar hints
- expected output type

### 4.2 User Intent Mapping

Intent classes:

- "Find something" -> Universal Search
- "Do something" -> Command Palette
- "Switch where I am" -> Quick Switcher
- "See and manage all active contexts" -> Mission Control

## 5. Keyboard Philosophy

### 5.1 Non-overlapping Primary Shortcuts

Primary entry shortcuts for the four systems must be distinct.

### 5.2 Shared Navigation Conventions

Shared key conventions allowed for:

- list traversal
- confirm/cancel
- preview toggle

Execution semantics must remain surface-specific.

### 5.3 Chaining Rules

Only Command Palette supports command chaining.

Search may hand off selected objects as command context, but cannot chain actions itself.

## 6. Decision Tree

```text
If user intent is retrieval/discovery -> Universal Search
If user intent is execute/transform/run -> Command Palette
If user intent is rapid context jump -> Quick Switcher
If user intent is macro workspace overview/re-orchestration -> Mission Control
```

If intent is ambiguous:

1. infer from current mode and focus
2. ask lightweight disambiguation
3. remember preference for repeated pattern

## 7. Cross-System Handoffs

Allowed handoffs:

- Search -> Command Palette (object as scoped context)
- Quick Switcher -> Search (within new context)
- Mission Control -> Quick Switcher (focused jump)

Disallowed handoffs:

- silent background command execution from Search
- hidden context switches from Command Palette without user-visible confirmation

## 8. Anti-Ambiguity Rules

1. Each system has one primary job and cannot absorb neighboring systems.
2. Surface identity must remain visible at all times.
3. If outcome type changes (retrieve vs execute), a handoff boundary must be explicit.
4. Quick Switcher remains context-only and action-light.
5. Mission Control remains orchestration-only and non-destructive by default.

## 9. Cross-References

- Retrieval architecture: UNIVERSAL_SEARCH.md
- Studio switching model: STUDIO_TAXONOMY.md
- Shell integration and region layering: DESKTOP_SHELL_V1.md
- Multi-window orchestration behavior: MULTI_WINDOW_MODEL.md