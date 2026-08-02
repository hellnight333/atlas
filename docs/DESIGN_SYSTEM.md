# Atlas Design System Specification

## 1. Purpose

The Atlas design system defines the visual and interaction grammar that makes complex professional workflows feel coherent, calm, and fast.

This is a behavior-and-principles specification, not implementation instructions.

## 2. Design Language Foundations

Atlas design language combines:

- editorial precision
- instrument-panel clarity
- cinematic depth cues
- low-noise information density

The system should feel premium and deliberate, with strong hierarchy and minimal ambiguity.

## 3. Typography

### 3.1 Roles

- Display: strategic headings and section anchors
- Interface: controls, labels, metadata
- Document: long-form writing surfaces and specs
- Monospace: structured data, identifiers, timeline stamps

### 3.2 Principles

- strong contrast between structural hierarchy levels
- readable body sizes for sustained sessions
- stable rhythm across multi-pane layouts
- numeric alignment support for logs/tables/timelines

### 3.3 Typographic Behavior

- heading scale is contextual, not absolute
- panel labels remain concise and scannable
- dense views favor clarity over decorative variation

## 4. Spacing System

### 4.1 Spacing Philosophy

Spacing encodes semantic grouping, not aesthetics alone.

### 4.2 Spacing Tiers

- Micro: intra-component breathing and icon-label spacing
- Standard: control grouping and list item rhythm
- Section: panel and block separation
- Structural: region boundaries and layout hierarchy

### 4.3 Rules

- adjacent controls with shared intent use tighter spacing
- unrelated groups require larger separation
- no arbitrary spacing values outside tokenized scale

## 5. Grid and Layout

### 5.1 Grid Model

- adaptive column grid in central workspace
- fixed rails for persistent navigation and inspector zones
- predictable baseline rhythm across panels

### 5.2 Layout Principles

- content should align to meaningful anchors
- primary task area receives dominant visual real estate
- compare views support side-by-side parity

## 6. Color Philosophy

### 6.1 Functional Color Roles

- Base surfaces: hierarchy of depth planes
- Text roles: primary, secondary, tertiary, disabled
- Status semantics: success, info, warning, critical
- Accent roles: interaction focus, selected state, highlights

### 6.2 Color Behavior Principles

- semantics first, branding second
- no status communicated by hue alone
- contrast compliance required in both themes
- low-saturation backgrounds to protect long-session comfort

## 7. Motion Principles

### 7.1 Motion Purpose

Motion exists to communicate:

- spatial relationship
- state transition
- causality of user action

### 7.2 Motion Types

- structural motion: pane open/close, docking transitions
- feedback motion: action confirmation and progress handoff
- attention motion: subtle cues for pending decisions

### 7.3 Motion Constraints

- short and purposeful durations
- no decorative looping distractions
- reduced-motion mode preserves information hierarchy

## 8. Iconography

### 8.1 Icon Style

- geometric clarity
- consistent stroke and corner logic
- legible at compact sizes

### 8.2 Icon Usage Rules

- icons support labels, not replace meaning in critical controls
- status icons pair with textual state labels
- icon metaphors must remain domain-stable across studios

## 9. Elevation and Depth

### 9.1 Elevation Model

Depth communicates interactivity and focus priority:

- Base plane: background and static structure
- Working plane: active panels and content surfaces
- Overlay plane: command palette, dialogs, transient overlays
- Critical plane: high-severity confirmations and blockers

### 9.2 Rules

- elevation changes only with interaction relevance
- avoid excessive layering that obscures context
- shadows and translucency should preserve readability

## 10. Accessibility Standards

### 10.1 Core Requirements

- keyboard reachability for all primary actions
- visible focus indication on all interactive controls
- non-color redundancy for status communication
- typographic readability for long sessions

### 10.2 Interaction Accessibility

- predictable focus traversal in docked and floating panels
- semantic names for assistive technologies
- clear error states with corrective guidance

## 11. Glass System

### 11.1 Purpose

The glass system introduces translucent layered surfaces for overlays and contextual panels while preserving depth and focus.

### 11.2 Usage

- command overlays
- inspector popovers
- transient contextual tools

### 11.3 Constraints

- translucency never reduces text contrast below accessibility targets
- blur radius and tint vary by theme and elevation level
- glass surfaces must maintain clear boundary edges

## 12. Theme System

### 12.1 Theme Philosophy

Themes are equal-quality modes, not primary-plus-secondary experiences.

### 12.2 Theme Components

- semantic tokens for surfaces, text, status, accents, and borders
- independent contrast calibration per theme
- motion and elevation adaptation per ambient luminance

## 13. Dark Mode

Dark mode intent:

- reduce glare and visual fatigue in long sessions
- preserve edge definition and hierarchy
- avoid crushed contrast and color clipping

Dark mode rules:

- elevation separation must remain obvious
- status hues tuned for low-luminance clarity
- bright accents used sparingly for focus anchors

## 14. Light Mode

Light mode intent:

- maximize legibility in daylight and collaborative settings
- sustain calm tone without stark contrast fatigue

Light mode rules:

- avoid flat white monoculture through subtle depth planes
- maintain distinction between interactive and static surfaces
- preserve parity of information density with dark mode

## 15. Design System Governance

### 15.1 Component Admission

New components are accepted only if:

- existing patterns cannot solve the need
- interaction model is reusable across at least two studios
- accessibility and theme behavior are fully specified

### 15.2 Change Management

- versioned tokens and behavior specs
- migration notes for component-level changes
- periodic audits for consistency drift

## 16. Quality Benchmarks

The design system succeeds when:

- users can transfer skills between studios without relearning basics
- dense workflows remain legible under pressure
- themes and accessibility modes provide equivalent capability
- visual language communicates confidence, not decoration