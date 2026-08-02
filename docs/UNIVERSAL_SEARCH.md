# Atlas Universal Search Architecture

## 1. Purpose

This document defines authoritative search behavior for Atlas across all searchable domains.

It resolves ambiguity in ranking, trust, freshness, scope, latency, and conflict handling.

This is the source of truth for Search architecture.

## 2. Search Responsibilities

Universal Search is responsible for:

- retrieval across heterogeneous domains
- ranked result presentation
- preview context for navigation confidence
- non-destructive access to objects and states

Universal Search is not the command execution authority.

## 3. Searchable Domains

Mandatory domains:

- Projects
- Assets
- Studios
- Workflows
- Memory
- Agents
- Documentation
- Settings
- History
- Commands (discoverability only, execution delegated)

## 4. Scope Model

Scopes:

- Global
- Tenant/Organization
- Space
- Project
- Studio
- Object-type filter

Scope precedence:

1. Explicit user scope
2. Active context scope
3. Global fallback

## 5. Ranking Architecture

### 5.1 Ranking Factors

Base ranking uses weighted factors:

- lexical match quality
- semantic relevance
- context proximity (active project/studio)
- recency
- frequency
- trust and verification signals
- user-pinned relevance

### 5.2 Ranking Stability

Rules:

- near-identical queries in same context should produce stable top results
- ranking drift must be explainable

### 5.3 Explainability

For high-impact or ambiguous results, expose "Why this result" with:

- matched fields
- context boost signals
- freshness state

## 6. Search Trust Model

Every result must carry a trust envelope:

- `authoritative_live`
- `authoritative_indexed`
- `derived_semantic`
- `stale_indexed`
- `restricted_visibility`

Trust envelope influences ranking and UI cues.

## 7. Fresh vs Indexed Data

### 7.1 Data Classes

- Fresh/live: directly queryable source state
- Indexed: cached searchable representation

### 7.2 Freshness Contract

Result freshness metadata includes:

- last indexed time
- divergence risk class
- live refresh availability

### 7.3 Conflict Strategy

When live and indexed disagree:

- show conflict badge
- prioritize authoritative live state for action pathways
- allow user to inspect indexed context if useful

## 8. Latency Strategy

### 8.1 Response Tiers

- Tier A: immediate local/index hints
- Tier B: enriched semantic and cross-domain joins
- Tier C: deep retrieval fallback

### 8.2 Progressive Disclosure

Search must stream results in confidence order:

1. high confidence low latency
2. medium confidence enriched
3. long-tail deep retrieval

## 9. Result Grouping

Grouping order:

1. Exact and highly relevant in-scope matches
2. Context-adjacent matches
3. Cross-domain related results
4. Historical and fallback results

Result groups must be labeled by domain and trust class.

## 10. Conflict Handling

Conflict classes:

- naming collisions
- scope collisions
- stale-vs-live divergence
- permission-restricted shadow results

For each conflict class, search must:

- indicate conflict type
- preserve safe default behavior
- provide explicit disambiguation path

## 11. AI-Enhanced Retrieval

AI enhancement can:

- expand query intent
- suggest synonyms and related concepts
- promote semantically relevant candidates

AI enhancement cannot:

- hide high-confidence lexical exact matches
- bypass permission constraints
- mutate the source-of-truth state

## 12. Search History

History stores:

- query string
- scope used
- selected result domain
- success outcome signal (optional)

User controls:

- clear history
- scoped history retention
- sensitive scope exclusion

## 13. Anti-Ambiguity Rules

1. Search retrieves and previews; it does not silently execute high-impact commands.
2. Trust class must always be available for each result.
3. Scope must always be visible and overridable.
4. No single ranking factor can dominate all contexts.
5. Permission-limited results must never leak sensitive details.

## 14. Cross-References

- Shell integration: DESKTOP_SHELL_V1.md
- Command boundary: COMMAND_SYSTEM.md
- Studio discovery and taxonomy: STUDIO_TAXONOMY.md
- Performance targets: PERFORMANCE_TARGETS.md
- Enterprise visibility and policy controls: ENTERPRISE_SHELL.md