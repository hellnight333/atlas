# Atlas Command Palette Specification

## Status Note

This document defines Command Palette behavior.

Authoritative command-system boundaries across Command Palette, Universal Search, Quick Switcher, and Mission Control are defined in COMMAND_SYSTEM.md.

Authoritative search retrieval, ranking, freshness, and trust semantics are defined in UNIVERSAL_SEARCH.md.

## 1. Purpose

The command palette is the universal control plane for Atlas.

It enables expert-speed operation while remaining discoverable for newer users.

The palette is not only a launcher; it is a context-aware intent interpreter and workflow accelerator.

## 2. Keyboard-First Philosophy

Principles:

- every high-frequency action must be invocable from keyboard
- command execution should minimize pointer dependency
- users should remain in flow without navigating multiple panels

Keyboard-first does not mean keyboard-only. Pointer access remains fully supported.

## 3. Command System Model

Command model elements:

- verb
- object
- scope
- modifiers
- execution mode

Example structure:

- Verb: open, create, run, compare, publish
- Object: project, workflow, asset, panel, log
- Scope: global, project, studio, selection
- Modifiers: current, new window, pinned, preview

## 4. Entry and Presence

Entry points:

- global shortcut
- top bar trigger
- context menu action

Palette behavior:

- opens as overlay with focus capture
- retains last mode and recent scope by default
- supports quick close and return to origin point

## 5. Command Categories

1. Navigation Commands
   - open screens, jump to projects, switch studios
2. Creation Commands
   - create project, asset, workflow card, layout snapshot
3. Workflow Commands
   - run stage, skip optional step, mark decision resolved
4. View Commands
   - split panel, toggle inspector, switch mode
5. Quality Commands
   - run checks, open diagnostics, compare revisions
6. Publishing Commands
   - prepare package, validate checklist, publish
7. Meta Commands
   - open settings, show shortcuts, view command history

## 6. Context-Aware Commands

The palette resolves commands against current context:

- current space
- active project
- active studio
- selected object type
- current workflow stage

Behavior rules:

- context-relevant commands rank higher
- unavailable commands are shown with reason when discoverability is useful
- users can force global scope to bypass local filtering

## 7. Natural Language Support

### 7.1 Intent Parsing

Users may invoke commands using plain language prompts such as:

- "open my latest video project"
- "show assets from yesterday"
- "run publish checklist"

### 7.2 Resolution Pipeline

1. intent parse
2. scope inference
3. candidate command mapping
4. confidence scoring
5. disambiguation if needed

### 7.3 Safety and Transparency

- ambiguous commands require confirmation
- high-impact commands require explicit acknowledgement
- interpretation rationale is available on demand

## 8. Command Ranking

Ranking signals:

- contextual relevance
- personal frequency
- recency
- stage appropriateness
- team-recommended workflows (if in team space)

Ranking must remain predictable and override-able.

## 9. Command History

### 9.1 History Contents

- recently executed commands
- command outcomes
- associated context scope

### 9.2 Uses

- fast rerun
- sequence replay for repetitive workflows
- personal productivity reflection

### 9.3 Privacy and Control

- users can clear or segment history by scope
- sensitive contexts can opt out of history persistence

## 10. AI Suggestions

### 10.1 Suggestion Types

- next best command
- command sequence recommendation
- context recovery suggestion

### 10.2 Suggestion Timing

- after major stage completion
- when user appears blocked
- when repetitive pattern is detected

### 10.3 Trust Rules

- suggestions are advisory, never forced
- each suggestion includes expected outcome and confidence level
- users can dismiss and tune suggestion behavior

## 11. Multi-Step Command Sequences

The palette supports command chaining:

- users execute structured sequences without leaving command context
- each step shows pending prerequisites and effects
- users can save sequence as macro-like reusable flow

Sequence examples:

- open project -> switch studio -> run checklist
- search asset -> compare revisions -> pin inspector

## 12. Error Handling and Recovery

When a command fails, palette provides:

- reason classification (context, permission, missing dependency, transient failure)
- direct remediation command suggestions
- retry with modified scope option

## 13. Discoverability Features

- inline command hints in relevant UI contexts
- shortcut suggestions based on repeated pointer patterns
- "why this command" explanation for recommendations

## 14. Beginner and Expert Modes

### 14.1 Beginner Orientation

- descriptive command labels
- optional examples and guided phrasing
- simplified result list initially

### 14.2 Expert Acceleration

- alias support
- abbreviation-friendly matching
- command chaining and history replay
- context pinning and explicit scope shortcuts

## 15. Command Scope Hierarchy

Scope precedence:

1. selected object
2. active panel
3. active studio
4. active project
5. active space
6. global

Users can manually override inferred scope at any time.

## 16. Palette Quality Criteria

The command system is successful when users can:

- execute high-frequency actions faster than navigation-driven interaction
- understand why commands are suggested or unavailable
- recover quickly from ambiguous intent
- trust AI assistance without surrendering control