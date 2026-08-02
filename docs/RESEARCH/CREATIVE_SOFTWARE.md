# Research: Creative Software

## 1. Research Focus

This document distills principles from professional creative software ecosystems for application to Atlas.

Focus areas:

- canvas-centric workflows
- tool discoverability and depth
- non-destructive iteration
- asset management and versioning
- review and critique workflows

## 2. Core Observations

### 2.1 Canvas + Inspector Is a Proven Pattern

Creative professionals benefit from a strong central work surface plus contextual detail side panel.

Implication for Atlas:

- maintain workspace center-stage with adaptive inspector detail

### 2.2 Non-Destructive Work Enables Experimentation

Professional tools support branching, undo/redo, and revision comparison.

Implication for Atlas:

- preserve reversible operations and comparison surfaces across studios

### 2.3 Shortcuts Unlock Expert Throughput

Creative tools with rich keyboard systems enable deep flow states.

Implication for Atlas:

- keyboard-first command system and discoverable accelerators are mandatory

### 2.4 Asset Systems Need Metadata Depth

As project complexity grows, metadata and relationships matter as much as raw files.

Implication for Atlas:

- asset cards should surface provenance, dependencies, and usage context

### 2.5 Feedback Loops Must Be Embedded

Strong creative systems integrate review, annotation, and iteration directly in workflow.

Implication for Atlas:

- include explicit quality checkpoints and decision logs in user flows

## 3. Extracted Principles for Atlas

1. Center-stage production with contextual side intelligence
2. Iteration-safe operations and version traceability
3. Tool depth revealed through progressive disclosure
4. Rich asset metadata for retrieval and reuse
5. Integrated review checkpoints before publish actions

## 4. Anti-Patterns to Avoid

- forcing users into rigid linear paths for exploratory work
- burying revision history or making comparisons expensive
- feature explosion without hierarchy or onboarding scaffolds

## 5. Atlas Application Targets

These findings reinforce:

- COMPONENT_LIBRARY.md
- DESIGN_SYSTEM.md
- USER_FLOWS.md
- INFORMATION_ARCHITECTURE.md

## 6. Open Research Questions

- what is the optimal balance between canvas freedom and workflow scaffolding?
- when should Atlas enforce quality gates versus suggest them?
- how can visual and textual assets share consistent review semantics?