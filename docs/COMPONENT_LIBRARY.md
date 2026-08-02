# Atlas Component Library Specification

## 1. Scope

This document defines component behavior, states, interaction patterns, and composition rules.

No implementation details are included.

## 2. Component Behavior Framework

Every component spec includes:

- intent
- anatomy
- states
- interactions
- accessibility behavior
- composition rules

## 3. Buttons

Intent:

- trigger discrete actions with clear intent hierarchy

Anatomy:

- container
- label
- optional icon
- optional progress/status indicator

States:

- idle
- hover/focus
- active
- loading
- disabled
- success/error completion

Interactions:

- primary actions visually dominant
- destructive actions require semantic emphasis and confirmation when high-impact

Accessibility:

- clear focus ring
- label always present for critical actions

## 4. Inputs

Intent:

- capture structured or freeform user data

Types:

- single-line text
- multiline text
- search field
- token/chip input
- numeric input
- filtered selection input

States:

- default
- focused
- filled
- validating
- error
- disabled

Behavior:

- inline validation with actionable error messages
- preserve partially entered content across context transitions

## 5. Panels

Intent:

- contain grouped controls or contextual information

Variants:

- static panel
- collapsible panel
- dockable panel
- floating panel

Behavior:

- panel headers show title, state indicators, and compact actions
- panels can be pinned to preserve visibility across context changes

## 6. Inspector

Intent:

- provide object-level detail and controls for selected entities

Anatomy:

- summary section
- properties section
- related assets section
- history/diagnostics section

Behavior:

- content updates with selection changes
- supports section pinning and collapsible groups
- compare mode for side-by-side object properties

## 7. Sidebar

Intent:

- provide persistent top-level navigation

Anatomy:

- navigation groups
- destination items
- badges/indicators
- optional quick filters

Behavior:

- supports collapsed and expanded modes
- preserves recently used destinations for quick return

## 8. Lists

Intent:

- scan and manage homogeneous item collections

Behavior:

- supports sorting, filtering, grouping
- keyboard traversal across items
- multi-select for bulk actions where applicable

States:

- empty with guidance
- populated
- loading
- error

## 9. Tables

Intent:

- structured comparison and management of dense data sets

Behavior:

- column visibility controls
- sorting and filtering
- row expansion for detail
- sticky headers in long datasets

Accessibility:

- header associations and keyboard cell navigation
- alternate signals for sorted state and alerts

## 10. Timeline

Intent:

- communicate sequence, causality, and progress of events

Behavior:

- chronological and grouped views
- event severity and source indicators
- jump to related objects or screens

Use cases:

- workflow progress
- activity feed
- publish history

## 11. Canvas

Intent:

- support spatial composition of workflows, relationships, or visual plans

Behavior:

- zoom and pan
- selectable nodes/groups
- alignment aids
- minimap support for large structures

Constraints:

- spatial operations must preserve deterministic undo/redo history

## 12. Dialogs

Intent:

- request explicit decisions for high-impact actions or missing prerequisites

Types:

- confirmation dialog
- decision dialog with alternatives
- input-required dialog
- blocker dialog with remediation

Behavior:

- concise rationale
- clear consequence disclosure
- primary and safe fallback action always visible

## 13. Activity Feed

Intent:

- present recent events with actionable context

Behavior:

- grouped by project/workflow/time window
- severity and source classification
- quick drill-down to logs or related assets

## 14. Property Panel

Intent:

- edit or inspect structured attributes of the selected object

Behavior:

- segmented by categories
- inline and staged edit modes
- changed-field highlighting before commit

## 15. Asset Card

Intent:

- represent an asset in browse and selection contexts

Anatomy:

- title
- type and status metadata
- thumbnail or icon
- provenance and recency
- quick actions

Behavior:

- card expands to reveal metadata depth on demand
- supports compare and pin actions

## 16. Workflow Card

Intent:

- summarize workflow intent, status, and next action

Anatomy:

- workflow objective
- stage progress indicator
- active decision point indicator
- recommended next action

Behavior:

- direct navigation to active stage
- confidence and risk summary available in details view

## 17. Project Card

Intent:

- summarize project scope, health, and recent activity

Anatomy:

- project name and type
- priority/status
- active studios
- progress indicator
- unresolved blockers count

Behavior:

- quick-open to project workspace
- supports pinning, archiving, and handoff metadata preview

## 18. Component Composition Rules

1. One dominant action per local context.
2. Secondary actions should not visually compete with primary goals.
3. Dense components require explicit collapse and filtering mechanics.
4. Components must preserve state across temporary navigation away events.
5. All components must define keyboard behavior and focus transitions.

## 19. Component Quality Criteria

A component is production-ready when:

- its state model is complete and testable from a UX perspective
- its role in cognitive load reduction is clear
- it composes cleanly in shell, studio, and multi-window contexts
- accessibility behaviors are fully specified