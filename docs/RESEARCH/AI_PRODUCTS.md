# Research: AI Products

## 1. Research Focus

This document identifies transferable principles from high-quality AI products without copying specific implementations.

Focus areas:

- trust and explainability
- human control boundaries
- suggestion quality
- interaction ergonomics
- memory and personalization

## 2. Core Observations

### 2.1 Trust Is Built Through Legibility

Users adopt AI deeply when recommendations include rationale and confidence signals.

Implication for Atlas:

- AI suggestions must expose why, confidence, and expected tradeoffs

### 2.2 Control Boundaries Must Be Explicit

Ambiguous autonomy undermines professional trust.

Implication for Atlas:

- high-impact actions require visible decision points and confirmation pathways

### 2.3 Context Quality Determines Output Quality

AI performance improves when grounded in well-structured user/project context.

Implication for Atlas:

- memory, assets, and workflow state should be first-class context inputs

### 2.4 Mixed-Initiative Systems Work Best

The strongest AI products combine user intent with proactive suggestions, without coercion.

Implication for Atlas:

- AI participation should be advisory and transparent, never dominant

### 2.5 Personalization Requires User Governance

Personalization is powerful only when users can inspect and tune it.

Implication for Atlas:

- users need controls over history, memory influence, and suggestion modes

## 3. Extracted Principles for Atlas

1. Explain every significant recommendation.
2. Keep agency with the user at critical branches.
3. Ground assistance in project-specific context.
4. Support mixed-initiative collaboration patterns.
5. Provide clear controls for memory and personalization.

## 4. Anti-Patterns to Avoid

- opaque recommendations with no rationale
- over-automation that bypasses user review
- generic suggestions detached from project context
- manipulative urgency cues to force AI adoption

## 5. Atlas Application Targets

These principles shape:

- UX_SPECIFICATION.md
- COMMAND_PALETTE.md
- USER_FLOWS.md
- INFORMATION_ARCHITECTURE.md (Agents and Memory surfaces)

## 6. Open Research Questions

- what confidence model best communicates uncertainty to experts?
- how should Atlas calibrate proactive suggestion frequency per user mode?
- what memory visibility model best balances utility and cognitive overhead?